"""Portfolio state and order planning for standardized risk decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from quant_platform.core import MarketSpec
from quant_platform.risk import RiskDecision
from quant_platform.signals import Direction


class OrderAction(str, Enum):
    OPEN = "open"
    CLOSE = "close"
    IGNORE = "ignore"


class OrderStatus(str, Enum):
    PLANNED = "planned"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


@dataclass(frozen=True)
class PositionKey:
    symbol: str
    layer: str


@dataclass(frozen=True)
class Position:
    symbol: str
    layer: str
    direction: Direction
    quantity: float
    notional: float
    risk_amount: float
    module: str
    entry_price: float
    stop_price: float | None = None
    target_price: float | None = None


@dataclass
class PortfolioState:
    positions: dict[PositionKey, Position] = field(default_factory=dict)
    orders: dict[str, "PortfolioOrder"] = field(default_factory=dict)

    def open_risk(self, symbol: str | None = None) -> float:
        positions = self.positions.values()
        if symbol is not None:
            positions = [position for position in positions if position.symbol == symbol]
        return sum(position.risk_amount for position in positions)

    def positions_for_symbol(self, symbol: str) -> list[Position]:
        return [position for position in self.positions.values() if position.symbol == symbol]

    def open_symbol_risk(self) -> dict[str, float]:
        symbol_risk: dict[str, float] = {}
        for position in self.positions.values():
            symbol_risk[position.symbol] = symbol_risk.get(position.symbol, 0.0) + position.risk_amount
        return symbol_risk

    def open_module_risk(self) -> dict[str, float]:
        module_risk: dict[str, float] = {}
        for position in self.positions.values():
            module_risk[position.module] = module_risk.get(position.module, 0.0) + position.risk_amount
        return module_risk

    def open_group_risk(self, correlation_groups: dict[str, str]) -> dict[str, float]:
        group_risk: dict[str, float] = {}
        for position in self.positions.values():
            group = correlation_groups.get(position.symbol)
            if not group:
                continue
            group_risk[group] = group_risk.get(group, 0.0) + position.risk_amount
        return group_risk


@dataclass(frozen=True)
class PortfolioOrder:
    order_id: str
    action: OrderAction
    symbol: str
    layer: str
    direction: Direction
    quantity: float
    reason: str
    status: OrderStatus = OrderStatus.PLANNED
    filled_quantity: float = 0.0
    average_fill_price: float = 0.0
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    decision: RiskDecision | None = None
    existing_position: Position | None = None


@dataclass(frozen=True)
class PortfolioPlan:
    orders: list[PortfolioOrder]


class PortfolioEngine:
    """Map risk-approved signals into multi-symbol, multi-layer position state."""

    def __init__(
        self,
        *,
        state: PortfolioState | None = None,
        layer_by_module: dict[str, str] | None = None,
        markets_by_symbol: dict[str, MarketSpec] | None = None,
        default_layer: str = "tactical",
        allow_hedging: bool = False,
        max_positions_per_symbol: int = 2,
    ):
        self.state = state or PortfolioState()
        self.layer_by_module = dict(layer_by_module or {})
        self.markets_by_symbol = dict(markets_by_symbol or {})
        self.default_layer = default_layer
        self.allow_hedging = allow_hedging
        self.max_positions_per_symbol = max_positions_per_symbol
        self._next_order_number = len(self.state.orders) + 1

    def apply(self, decisions: list[RiskDecision]) -> PortfolioPlan:
        orders: list[PortfolioOrder] = []
        ranked = sorted(enumerate(decisions), key=lambda item: (-item[1].signal.score, item[0]))
        accepted_keys: set[PositionKey] = set()

        for _, decision in ranked:
            layer = self.layer_for(decision)
            signal = decision.signal
            if not decision.allowed:
                orders.append(self._ignore(decision, layer, f"risk_blocked:{decision.reason}"))
                continue

            key = PositionKey(signal.symbol, layer)
            if key in accepted_keys:
                orders.append(self._ignore(decision, layer, "conflicting_signal_lost"))
                continue
            existing = self.state.positions.get(key)
            if existing is not None:
                orders.append(self._ignore(decision, layer, "position_exists", existing))
                continue
            if not self.allow_hedging and self._would_hedge(signal.symbol, signal.direction):
                orders.append(self._ignore(decision, layer, "hedging_disabled"))
                continue
            if len(self.state.positions_for_symbol(signal.symbol)) >= self.max_positions_per_symbol:
                orders.append(self._ignore(decision, layer, "symbol_position_limit"))
                continue

            quantity = self._quantize_quantity(signal.symbol, decision.quantity)
            entry_price = self._quantize_price(signal.symbol, decision.entry_price)
            stop_price = self._quantize_optional_price(signal.symbol, decision.stop_price)
            target_price = self._quantize_optional_price(signal.symbol, signal.preferred_target)
            notional = self._quantize_notional(signal.symbol, decision.notional, entry_price, quantity)
            position = Position(
                symbol=signal.symbol,
                layer=layer,
                direction=signal.direction,
                quantity=quantity,
                notional=notional,
                risk_amount=decision.risk_amount,
                module=signal.module,
                entry_price=entry_price,
                stop_price=stop_price,
                target_price=target_price,
            )
            self.state.positions[key] = position
            accepted_keys.add(key)
            order = PortfolioOrder(
                order_id=self._new_order_id(),
                action=OrderAction.OPEN,
                symbol=signal.symbol,
                layer=layer,
                direction=signal.direction,
                quantity=quantity,
                reason="opened",
                status=OrderStatus.SUBMITTED,
                entry_price=entry_price,
                stop_price=stop_price,
                target_price=target_price,
                decision=decision,
            )
            self.state.orders[order.order_id] = order
            orders.append(order)

        return PortfolioPlan(orders=orders)

    def layer_for(self, decision: RiskDecision) -> str:
        return self.layer_by_module.get(decision.signal.module, self.default_layer)

    def _quantize_quantity(self, symbol: str, quantity: float) -> float:
        market = self.markets_by_symbol.get(symbol)
        return market.quantize_quantity(quantity) if market is not None else quantity

    def _quantize_price(self, symbol: str, price: float) -> float:
        market = self.markets_by_symbol.get(symbol)
        return market.quantize_price(price) if market is not None else price

    def _quantize_optional_price(self, symbol: str, price: float | None) -> float | None:
        if price is None:
            return None
        return self._quantize_price(symbol, price)

    def _quantize_notional(self, symbol: str, notional: float, entry_price: float, quantity: float) -> float:
        return entry_price * quantity if symbol in self.markets_by_symbol else notional

    def record_fill(self, order_id: str, *, filled_quantity: float, fill_price: float) -> PortfolioOrder:
        order = self._get_order(order_id)
        if order.status in {OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.FILLED}:
            raise ValueError(f"order {order_id} cannot be filled from {order.status.value}")
        if filled_quantity <= 0:
            raise ValueError("filled_quantity must be positive")
        new_filled = order.filled_quantity + float(filled_quantity)
        if new_filled > order.quantity:
            raise ValueError("filled quantity exceeds order quantity")
        avg_price = (
            (order.average_fill_price * order.filled_quantity + float(fill_price) * float(filled_quantity))
            / new_filled
        )
        status = OrderStatus.FILLED if new_filled >= order.quantity else OrderStatus.PARTIALLY_FILLED
        updated = PortfolioOrder(
            order_id=order.order_id,
            action=order.action,
            symbol=order.symbol,
            layer=order.layer,
            direction=order.direction,
            quantity=order.quantity,
            reason=order.reason,
            status=status,
            filled_quantity=new_filled,
            average_fill_price=avg_price,
            entry_price=order.entry_price,
            stop_price=order.stop_price,
            target_price=order.target_price,
            decision=order.decision,
            existing_position=order.existing_position,
        )
        self.state.orders[order_id] = updated
        self._update_position_from_fill(updated)
        return updated

    def cancel_order(self, order_id: str, *, reason: str = "canceled") -> PortfolioOrder:
        return self._terminal_order(order_id, OrderStatus.CANCELED, reason)

    def reject_order(self, order_id: str, *, reason: str = "rejected") -> PortfolioOrder:
        return self._terminal_order(order_id, OrderStatus.REJECTED, reason)

    def close_position(
        self,
        symbol: str,
        layer: str,
        *,
        fill_price: float,
        quantity: float | None = None,
        reason: str = "closed",
    ) -> PortfolioOrder:
        key = PositionKey(symbol, layer)
        try:
            position = self.state.positions[key]
        except KeyError as exc:
            raise ValueError(f"no position for {symbol} {layer}") from exc

        close_quantity = position.quantity if quantity is None else float(quantity)
        if close_quantity <= 0:
            raise ValueError("quantity must be positive")
        if close_quantity > position.quantity:
            raise ValueError("close quantity exceeds position quantity")

        order = PortfolioOrder(
            order_id=self._new_order_id(),
            action=OrderAction.CLOSE,
            symbol=symbol,
            layer=layer,
            direction=position.direction,
            quantity=close_quantity,
            reason=reason,
            status=OrderStatus.FILLED,
            filled_quantity=close_quantity,
            average_fill_price=float(fill_price),
            entry_price=position.entry_price,
            stop_price=position.stop_price,
            target_price=position.target_price,
            existing_position=position,
        )
        self.state.orders[order.order_id] = order

        remaining_quantity = position.quantity - close_quantity
        if remaining_quantity <= 0:
            del self.state.positions[key]
        else:
            remaining_ratio = remaining_quantity / position.quantity
            self.state.positions[key] = Position(
                symbol=position.symbol,
                layer=position.layer,
                direction=position.direction,
                quantity=remaining_quantity,
                notional=position.entry_price * remaining_quantity,
                risk_amount=position.risk_amount * remaining_ratio,
                module=position.module,
                entry_price=position.entry_price,
                stop_price=position.stop_price,
                target_price=position.target_price,
            )
        return order

    def _would_hedge(self, symbol: str, direction: Direction) -> bool:
        if direction == Direction.FLAT:
            return False
        return any(
            position.direction != direction
            for position in self.state.positions_for_symbol(symbol)
            if position.direction != Direction.FLAT
        )

    def _new_order_id(self) -> str:
        order_id = f"ord-{self._next_order_number:06d}"
        self._next_order_number += 1
        return order_id

    def _get_order(self, order_id: str) -> PortfolioOrder:
        try:
            return self.state.orders[order_id]
        except KeyError as exc:
            raise ValueError(f"unknown order_id {order_id}") from exc

    def _terminal_order(self, order_id: str, status: OrderStatus, reason: str) -> PortfolioOrder:
        order = self._get_order(order_id)
        if order.filled_quantity > 0:
            raise ValueError(f"order {order_id} already has fills")
        if order.status in {OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.FILLED}:
            raise ValueError(f"order {order_id} is already terminal")
        updated = PortfolioOrder(
            order_id=order.order_id,
            action=order.action,
            symbol=order.symbol,
            layer=order.layer,
            direction=order.direction,
            quantity=order.quantity,
            reason=reason,
            status=status,
            filled_quantity=order.filled_quantity,
            average_fill_price=order.average_fill_price,
            entry_price=order.entry_price,
            stop_price=order.stop_price,
            target_price=order.target_price,
            decision=order.decision,
            existing_position=order.existing_position,
        )
        self.state.orders[order_id] = updated
        return updated

    def _update_position_from_fill(self, order: PortfolioOrder) -> None:
        if order.action != OrderAction.OPEN or order.filled_quantity <= 0:
            return
        key = PositionKey(order.symbol, order.layer)
        existing = self.state.positions.get(key)
        if existing is None:
            return
        fill_ratio = min(order.filled_quantity / order.quantity, 1.0) if order.quantity else 0.0
        self.state.positions[key] = Position(
            symbol=existing.symbol,
            layer=existing.layer,
            direction=existing.direction,
            quantity=order.filled_quantity,
            notional=order.average_fill_price * order.filled_quantity,
            risk_amount=existing.risk_amount * fill_ratio,
            module=existing.module,
            entry_price=order.average_fill_price,
            stop_price=existing.stop_price,
            target_price=existing.target_price,
        )

    @staticmethod
    def _ignore(
        decision: RiskDecision,
        layer: str,
        reason: str,
        existing_position: Position | None = None,
    ) -> PortfolioOrder:
        signal = decision.signal
        return PortfolioOrder(
            order_id="",
            action=OrderAction.IGNORE,
            symbol=signal.symbol,
            layer=layer,
            direction=signal.direction,
            quantity=0.0,
            reason=reason,
            status=OrderStatus.PLANNED,
            decision=decision,
            existing_position=existing_position,
        )
