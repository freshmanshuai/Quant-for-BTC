"""Portfolio state and order planning for standardized risk decisions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from quant_platform.core import MarketSpec
from quant_platform.risk import RiskDecision
from quant_platform.signals import Direction


class OrderAction(str, Enum):
    OPEN = "open"
    CLOSE = "close"
    REBALANCE = "rebalance"
    TRANSFER = "transfer"
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

    def open_notional(self) -> float:
        """Gross entry notional currently consuming initial margin."""
        return sum(abs(position.notional) for position in self.positions.values())

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

    def open_group_risk(
        self,
        correlation_groups: dict[str, str] | None = None,
        group_resolver: Callable[[str], str | None] | None = None,
    ) -> dict[str, float]:
        group_risk: dict[str, float] = {}
        for position in self.positions.values():
            if group_resolver is not None:
                group = group_resolver(position.symbol)
            else:
                group = (correlation_groups or {}).get(position.symbol)
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
        rebalance_existing: bool = False,
        close_on_opposite_signal: bool = False,
        reverse_on_opposite_signal: bool = False,
        transfer_existing_layer: bool = False,
        precreate_positions: bool = True,
    ):
        self.state = state or PortfolioState()
        self.layer_by_module = dict(layer_by_module or {})
        self.markets_by_symbol = dict(markets_by_symbol or {})
        self.default_layer = default_layer
        self.allow_hedging = allow_hedging
        self.max_positions_per_symbol = max_positions_per_symbol
        self.rebalance_existing = rebalance_existing
        self.close_on_opposite_signal = close_on_opposite_signal
        self.reverse_on_opposite_signal = reverse_on_opposite_signal
        self.transfer_existing_layer = transfer_existing_layer
        self.precreate_positions = precreate_positions
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
            if existing is None and self._has_pending_entry(key):
                orders.append(self._ignore(decision, layer, "entry_order_pending"))
                continue
            if existing is not None:
                if self._has_pending_exit(key):
                    orders.append(self._ignore(decision, layer, "exit_order_pending", existing))
                    continue
                if self.rebalance_existing and existing.direction == signal.direction:
                    orders.append(self._rebalance(decision, layer, existing))
                    accepted_keys.add(key)
                    continue
                if self.reverse_on_opposite_signal and self._is_opposite_direction(existing.direction, signal.direction):
                    orders.extend(self._reverse_for_opposite_signal(decision, layer, existing))
                    accepted_keys.add(key)
                    continue
                if self.close_on_opposite_signal and self._is_opposite_direction(existing.direction, signal.direction):
                    orders.append(self._close_for_opposite_signal(decision, layer, existing))
                    accepted_keys.add(key)
                    continue
                orders.append(self._ignore(decision, layer, "position_exists", existing))
                continue
            if self.transfer_existing_layer:
                transfer_order = self._transfer_existing_layer(decision, layer)
                if transfer_order is not None:
                    orders.append(transfer_order)
                    accepted_keys.add(key)
                    continue
            if not self.allow_hedging and self._would_hedge(signal.symbol, signal.direction):
                orders.append(self._ignore(decision, layer, "hedging_disabled"))
                continue
            if len(self.state.positions_for_symbol(signal.symbol)) >= self.max_positions_per_symbol:
                orders.append(self._ignore(decision, layer, "symbol_position_limit"))
                continue

            order = self._open_for_decision(
                decision,
                layer,
                precreate_position=self.precreate_positions,
            )
            accepted_keys.add(key)
            orders.append(order)

        return PortfolioPlan(orders=orders)

    def _has_pending_entry(self, key: PositionKey) -> bool:
        return any(
            order.symbol == key.symbol
            and order.layer == key.layer
            and order.action == OrderAction.OPEN
            and order.status in {OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED}
            for order in self.state.orders.values()
        )

    def _has_pending_exit(self, key: PositionKey) -> bool:
        return any(
            order.symbol == key.symbol
            and order.layer == key.layer
            and order.action in {OrderAction.CLOSE, OrderAction.REBALANCE}
            and order.status in {OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED}
            for order in self.state.orders.values()
        )

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
        if symbol not in self.markets_by_symbol:
            return notional
        return self._position_notional(symbol, entry_price, quantity)

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
        return self._terminal_order(order_id, OrderStatus.CANCELED, reason, allow_partial_fill=True)

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
        decision: RiskDecision | None = None,
    ) -> PortfolioOrder:
        key = PositionKey(symbol, layer)
        try:
            position = self.state.positions[key]
        except KeyError as exc:
            raise ValueError(f"no position for {symbol} {layer}") from exc

        close_quantity = position.quantity if quantity is None else self._quantize_quantity(symbol, float(quantity))
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
            decision=decision,
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
                notional=self._position_notional(position.symbol, position.entry_price, remaining_quantity),
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

    @staticmethod
    def _is_opposite_direction(existing: Direction, incoming: Direction) -> bool:
        return existing != Direction.FLAT and incoming != Direction.FLAT and existing != incoming

    def _close_for_opposite_signal(
        self,
        decision: RiskDecision,
        layer: str,
        existing: Position,
    ) -> PortfolioOrder:
        order = PortfolioOrder(
            order_id=self._new_order_id(),
            action=OrderAction.CLOSE,
            symbol=existing.symbol,
            layer=layer,
            direction=existing.direction,
            quantity=existing.quantity,
            reason="opposite_signal_close",
            status=OrderStatus.SUBMITTED,
            entry_price=existing.entry_price,
            stop_price=existing.stop_price,
            target_price=existing.target_price,
            decision=decision,
            existing_position=existing,
        )
        self.state.orders[order.order_id] = order
        return order

    def _reverse_for_opposite_signal(
        self,
        decision: RiskDecision,
        layer: str,
        existing: Position,
    ) -> list[PortfolioOrder]:
        close_order = self._close_for_opposite_signal(decision, layer, existing)
        open_order = self._open_for_decision(
            decision,
            layer,
            reason="opposite_signal_open",
            precreate_position=False,
        )
        return [close_order, open_order]

    def _open_for_decision(
        self,
        decision: RiskDecision,
        layer: str,
        *,
        reason: str = "opened",
        precreate_position: bool = True,
    ) -> PortfolioOrder:
        signal = decision.signal
        quantity = self._quantize_quantity(signal.symbol, decision.quantity)
        entry_price = self._quantize_price(signal.symbol, decision.entry_price)
        stop_price = self._quantize_optional_price(signal.symbol, decision.stop_price)
        target_price = self._quantize_optional_price(signal.symbol, signal.preferred_target)
        notional = self._quantize_notional(signal.symbol, decision.notional, entry_price, quantity)
        if precreate_position:
            self.state.positions[PositionKey(signal.symbol, layer)] = Position(
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
        order = PortfolioOrder(
            order_id=self._new_order_id(),
            action=OrderAction.OPEN,
            symbol=signal.symbol,
            layer=layer,
            direction=signal.direction,
            quantity=quantity,
            reason=reason,
            status=OrderStatus.SUBMITTED,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            decision=decision,
        )
        self.state.orders[order.order_id] = order
        return order

    def _rebalance(
        self,
        decision: RiskDecision,
        layer: str,
        existing: Position,
    ) -> PortfolioOrder:
        quantity = self._quantize_quantity(decision.signal.symbol, decision.quantity)
        delta = quantity - existing.quantity
        if delta == 0:
            return self._ignore(decision, layer, "rebalance_not_required", existing)
        reason = "increase_position" if delta > 0 else "decrease_position"
        order = PortfolioOrder(
            order_id=self._new_order_id(),
            action=OrderAction.REBALANCE,
            symbol=decision.signal.symbol,
            layer=layer,
            direction=decision.signal.direction,
            quantity=abs(delta),
            reason=reason,
            status=OrderStatus.SUBMITTED,
            entry_price=self._quantize_price(decision.signal.symbol, decision.entry_price),
            stop_price=self._quantize_optional_price(decision.signal.symbol, decision.stop_price),
            target_price=self._quantize_optional_price(
                decision.signal.symbol,
                decision.signal.preferred_target,
            ),
            decision=decision,
            existing_position=existing,
        )
        self.state.orders[order.order_id] = order
        return order

    def _transfer_existing_layer(
        self,
        decision: RiskDecision,
        target_layer: str,
    ) -> PortfolioOrder | None:
        signal = decision.signal
        candidates = [
            (key, position)
            for key, position in self.state.positions.items()
            if (
                key.symbol == signal.symbol
                and key.layer != target_layer
                and position.direction == signal.direction
            )
        ]
        if len(candidates) != 1:
            return None

        source_key, source = candidates[0]
        target_key = PositionKey(signal.symbol, target_layer)
        if target_key in self.state.positions:
            return None

        transferred = Position(
            symbol=source.symbol,
            layer=target_layer,
            direction=source.direction,
            quantity=source.quantity,
            notional=source.notional,
            risk_amount=source.risk_amount,
            module=signal.module,
            entry_price=source.entry_price,
            stop_price=source.stop_price,
            target_price=source.target_price,
        )
        del self.state.positions[source_key]
        self.state.positions[target_key] = transferred
        order = PortfolioOrder(
            order_id=self._new_order_id(),
            action=OrderAction.TRANSFER,
            symbol=signal.symbol,
            layer=target_layer,
            direction=signal.direction,
            quantity=transferred.quantity,
            reason="layer_transfer",
            status=OrderStatus.FILLED,
            filled_quantity=transferred.quantity,
            average_fill_price=transferred.entry_price,
            entry_price=transferred.entry_price,
            stop_price=transferred.stop_price,
            target_price=transferred.target_price,
            decision=decision,
            existing_position=transferred,
        )
        self.state.orders[order.order_id] = order
        return order

    def _new_order_id(self) -> str:
        order_id = f"ord-{self._next_order_number:06d}"
        self._next_order_number += 1
        return order_id

    def _get_order(self, order_id: str) -> PortfolioOrder:
        try:
            return self.state.orders[order_id]
        except KeyError as exc:
            raise ValueError(f"unknown order_id {order_id}") from exc

    def _terminal_order(
        self,
        order_id: str,
        status: OrderStatus,
        reason: str,
        *,
        allow_partial_fill: bool = False,
    ) -> PortfolioOrder:
        order = self._get_order(order_id)
        if order.filled_quantity > 0 and not allow_partial_fill:
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
        if order.filled_quantity <= 0:
            return
        if order.action == OrderAction.REBALANCE:
            self._update_position_from_rebalance_fill(order)
            return
        if order.action == OrderAction.CLOSE:
            self._update_position_from_close_fill(order)
            return
        if order.action != OrderAction.OPEN:
            return
        key = PositionKey(order.symbol, order.layer)
        existing = self.state.positions.get(key)
        if existing is None:
            self.state.positions[key] = self._position_from_open_fill(order)
            return
        fill_ratio = min(order.filled_quantity / order.quantity, 1.0) if order.quantity else 0.0
        self.state.positions[key] = Position(
            symbol=existing.symbol,
            layer=existing.layer,
            direction=existing.direction,
            quantity=order.filled_quantity,
            notional=self._position_notional(order.symbol, order.average_fill_price, order.filled_quantity),
            risk_amount=existing.risk_amount * fill_ratio,
            module=existing.module,
            entry_price=order.average_fill_price,
            stop_price=existing.stop_price,
            target_price=existing.target_price,
        )

    def _position_from_open_fill(self, order: PortfolioOrder) -> Position:
        fill_ratio = min(order.filled_quantity / order.quantity, 1.0) if order.quantity else 0.0
        decision = order.decision
        risk_amount = decision.risk_amount * fill_ratio if decision is not None else 0.0
        module = decision.signal.module if decision is not None else ""
        return Position(
            symbol=order.symbol,
            layer=order.layer,
            direction=order.direction,
            quantity=order.filled_quantity,
            notional=self._position_notional(order.symbol, order.average_fill_price, order.filled_quantity),
            risk_amount=risk_amount,
            module=module,
            entry_price=order.average_fill_price,
            stop_price=order.stop_price,
            target_price=order.target_price,
        )

    def _update_position_from_rebalance_fill(self, order: PortfolioOrder) -> None:
        key = PositionKey(order.symbol, order.layer)
        original = order.existing_position
        if original is None or key not in self.state.positions:
            return

        fill_ratio = min(order.filled_quantity / order.quantity, 1.0) if order.quantity else 0.0
        target_risk = order.decision.risk_amount if order.decision is not None else original.risk_amount
        risk_amount = original.risk_amount + (target_risk - original.risk_amount) * fill_ratio
        module = order.decision.signal.module if order.decision is not None else original.module

        if order.reason == "decrease_position":
            quantity = original.quantity - order.filled_quantity
            if quantity <= 0:
                del self.state.positions[key]
                return
            remaining_ratio = quantity / original.quantity if original.quantity else 0.0
            notional = original.notional * remaining_ratio
            entry_price = original.entry_price
        else:
            quantity = original.quantity + order.filled_quantity
            notional = original.notional + self._position_notional(
                order.symbol,
                order.average_fill_price,
                order.filled_quantity,
            )
            entry_price = self._entry_price_from_notional(order.symbol, notional, quantity, original.entry_price)

        self.state.positions[key] = Position(
            symbol=original.symbol,
            layer=original.layer,
            direction=original.direction,
            quantity=quantity,
            notional=notional,
            risk_amount=risk_amount,
            module=module,
            entry_price=entry_price,
            stop_price=order.stop_price if order.stop_price is not None else original.stop_price,
            target_price=order.target_price if order.target_price is not None else original.target_price,
        )

    def _update_position_from_close_fill(self, order: PortfolioOrder) -> None:
        key = PositionKey(order.symbol, order.layer)
        original = order.existing_position
        if original is None or key not in self.state.positions:
            return

        quantity = original.quantity - order.filled_quantity
        if quantity <= 0:
            del self.state.positions[key]
            return

        remaining_ratio = quantity / original.quantity if original.quantity else 0.0
        self.state.positions[key] = Position(
            symbol=original.symbol,
            layer=original.layer,
            direction=original.direction,
            quantity=quantity,
            notional=original.notional * remaining_ratio,
            risk_amount=original.risk_amount * remaining_ratio,
            module=original.module,
            entry_price=original.entry_price,
            stop_price=original.stop_price,
            target_price=original.target_price,
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

    def _position_notional(self, symbol: str, price: float, quantity: float) -> float:
        market = self.markets_by_symbol.get(symbol)
        multiplier = market.contract_multiplier if market is not None and market.contract_multiplier > 0 else 1.0
        return float(price) * float(quantity) * multiplier

    def _entry_price_from_notional(
        self,
        symbol: str,
        notional: float,
        quantity: float,
        fallback: float,
    ) -> float:
        market = self.markets_by_symbol.get(symbol)
        multiplier = market.contract_multiplier if market is not None and market.contract_multiplier > 0 else 1.0
        denominator = float(quantity) * multiplier
        return float(notional) / denominator if denominator else fallback
