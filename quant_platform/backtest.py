"""Event-driven backtest harness for standardized signal pipelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

import pandas as pd

from quant_platform.core import MarketSpec
from quant_platform.delivery import DeliveryResult
from quant_platform.pipeline import PipelineResult, SignalPipeline
from quant_platform.portfolio import OrderAction, OrderStatus, PortfolioOrder, Position
from quant_platform.risk import AccountState
from quant_platform.signals import Direction, Signal


@dataclass(frozen=True)
class BacktestStep:
    """One symbol/bar pipeline evaluation."""

    symbol: str
    timestamp: object
    bar_index: int
    result: PipelineResult


@dataclass(frozen=True)
class BacktestStateSnapshot:
    """Portfolio state after one event has been evaluated and filled."""

    symbol: str
    timestamp: object
    bar_index: int
    position_count: int
    submitted_order_count: int
    filled_order_count: int
    open_risk: float


@dataclass(frozen=True)
class BacktestExecutionConfig:
    """Simple execution assumptions for event-driven research backtests."""

    fee_rate: float = 0.0
    slippage_bps: float = 0.0


@dataclass(frozen=True)
class BacktestEquityPoint:
    """Account equity after one event, including unrealized PnL."""

    symbol: str
    timestamp: object
    bar_index: int
    cash: float
    unrealized_pnl: float
    equity: float


@dataclass(frozen=True)
class BacktestTrade:
    """A realized position exit from the event-driven backtest."""

    symbol: str
    layer: str
    module: str
    direction: Direction
    entry_price: float
    exit_price: float
    quantity: float
    gross_pnl: float
    entry_fee: float
    exit_fee: float
    net_pnl: float
    exit_reason: str


@dataclass(frozen=True)
class BacktestAttributionBucket:
    """Aggregated realized trade performance for one grouping key."""

    trade_count: int
    gross_pnl: float
    net_pnl: float
    fees_paid: float
    win_count: int

    @property
    def win_rate(self) -> float:
        return self.win_count / self.trade_count if self.trade_count else 0.0


@dataclass(frozen=True)
class BacktestAttribution:
    """Realized trade attribution grouped by portfolio dimensions."""

    by_symbol: dict[str, BacktestAttributionBucket]
    by_layer: dict[str, BacktestAttributionBucket]
    by_module: dict[str, BacktestAttributionBucket]


@dataclass(frozen=True)
class EventDrivenBacktestResult:
    """Collected pipeline results from an event-driven backtest run."""

    steps: list[BacktestStep]
    filled_orders: list[PortfolioOrder] = field(default_factory=list)
    state_history: list[BacktestStateSnapshot] = field(default_factory=list)
    equity_curve: list[BacktestEquityPoint] = field(default_factory=list)
    trades: list[BacktestTrade] = field(default_factory=list)
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    funding_paid: float = 0.0

    @property
    def signals(self) -> list[Signal]:
        return [signal for step in self.steps for signal in step.result.signals]

    @property
    def orders(self) -> list[PortfolioOrder]:
        return [order for step in self.steps for order in step.result.portfolio_plan.orders]

    @property
    def deliveries(self) -> list[DeliveryResult]:
        return [delivery for step in self.steps for delivery in step.result.delivery_results]

    @property
    def attribution(self) -> BacktestAttribution:
        return BacktestAttribution(
            by_symbol=self._bucket_by(lambda trade: trade.symbol),
            by_layer=self._bucket_by(lambda trade: trade.layer),
            by_module=self._bucket_by(lambda trade: trade.module),
        )

    def _bucket_by(self, key_fn) -> dict[str, BacktestAttributionBucket]:
        buckets: dict[str, list[BacktestTrade]] = {}
        for trade in self.trades:
            buckets.setdefault(key_fn(trade), []).append(trade)
        return {
            key: BacktestAttributionBucket(
                trade_count=len(items),
                gross_pnl=sum(item.gross_pnl for item in items),
                net_pnl=sum(item.net_pnl for item in items),
                fees_paid=sum(item.entry_fee + item.exit_fee for item in items),
                win_count=sum(item.net_pnl > 0 for item in items),
            )
            for key, items in buckets.items()
        }


class EventDrivenBacktest:
    """Run a SignalPipeline over one or more feature streams, bar by bar."""

    def __init__(
        self,
        *,
        pipeline: SignalPipeline,
        account: AccountState,
        execution: BacktestExecutionConfig | None = None,
        markets_by_symbol: Mapping[str, MarketSpec] | None = None,
    ):
        self.pipeline = pipeline
        self.account = account
        self.execution = execution or BacktestExecutionConfig()
        self.markets_by_symbol = dict(markets_by_symbol or {})

    def run(self, features_by_symbol: Mapping[str, pd.DataFrame]) -> EventDrivenBacktestResult:
        steps: list[BacktestStep] = []
        filled_orders: list[PortfolioOrder] = []
        state_history: list[BacktestStateSnapshot] = []
        equity_curve: list[BacktestEquityPoint] = []
        trades: list[BacktestTrade] = []
        events: list[tuple[object, str, int]] = []
        latest_prices: dict[str, float] = {}
        cash = self.account.equity
        realized_pnl = 0.0
        fees_paid = 0.0
        funding_paid = 0.0

        for symbol, features in features_by_symbol.items():
            if features.empty:
                continue
            events.extend((features.index[bar_index], symbol, bar_index) for bar_index in range(len(features)))

        for timestamp, symbol, bar_index in sorted(events, key=lambda event: (event[0], event[1])):
            features = features_by_symbol[symbol]
            window = features.iloc[: bar_index + 1]
            fill_price = float(window["Close"].iloc[-1]) if "Close" in window.columns else None
            if fill_price is not None:
                latest_prices[symbol] = fill_price
            result = self.pipeline.run(
                window,
                symbol=symbol,
                account=self.account,
                entry_price=fill_price,
                bar_index=bar_index,
            )
            steps.append(BacktestStep(symbol=symbol, timestamp=timestamp, bar_index=bar_index, result=result))
            event_fills = self._fill_submitted_orders(result.portfolio_plan.orders, fill_price)
            filled_orders.extend(event_fills)
            event_fees = sum(self._order_fee(order) for order in event_fills)
            fees_paid += event_fees
            cash -= event_fees
            event_funding = self._funding_for_symbol(symbol)
            funding_paid += event_funding
            cash -= event_funding
            event_trades = self._close_triggered_positions(symbol, fill_price, event_fills)
            trades.extend(event_trades)
            exit_fees = sum(trade.exit_fee for trade in event_trades)
            event_realized = sum(trade.gross_pnl for trade in event_trades)
            realized_pnl += event_realized
            fees_paid += exit_fees
            cash += event_realized - exit_fees
            state_history.append(self._snapshot(symbol, timestamp, bar_index))
            equity_curve.append(self._equity_point(symbol, timestamp, bar_index, cash, latest_prices))

        return EventDrivenBacktestResult(
            steps=steps,
            filled_orders=filled_orders,
            state_history=state_history,
            equity_curve=equity_curve,
            trades=trades,
            realized_pnl=realized_pnl,
            fees_paid=fees_paid,
            funding_paid=funding_paid,
        )

    def _fill_submitted_orders(
        self,
        orders: list[PortfolioOrder],
        fill_price: float | None,
    ) -> list[PortfolioOrder]:
        if fill_price is None:
            return []
        filled: list[PortfolioOrder] = []
        for order in orders:
            if order.action != OrderAction.OPEN or order.status != OrderStatus.SUBMITTED or not order.order_id:
                continue
            execution_price = self._execution_price(fill_price, order.direction)
            filled.append(
                self.pipeline.portfolio_engine.record_fill(
                    order.order_id,
                    filled_quantity=order.quantity,
                    fill_price=execution_price,
                )
            )
        return filled

    def _snapshot(self, symbol: str, timestamp: object, bar_index: int) -> BacktestStateSnapshot:
        state = self.pipeline.portfolio_engine.state
        orders = list(state.orders.values())
        submitted = sum(order.status in {OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED} for order in orders)
        filled = sum(order.status == OrderStatus.FILLED for order in orders)
        return BacktestStateSnapshot(
            symbol=symbol,
            timestamp=timestamp,
            bar_index=bar_index,
            position_count=len(state.positions),
            submitted_order_count=submitted,
            filled_order_count=filled,
            open_risk=state.open_risk(),
        )

    def _close_triggered_positions(
        self,
        symbol: str,
        close_price: float | None,
        event_fills: list[PortfolioOrder],
    ) -> list[BacktestTrade]:
        if close_price is None:
            return []
        opened_keys = {(order.symbol, order.layer) for order in event_fills if order.action == OrderAction.OPEN}
        positions = [
            position
            for position in self.pipeline.portfolio_engine.state.positions.values()
            if position.symbol == symbol and (position.symbol, position.layer) not in opened_keys
        ]
        trades: list[BacktestTrade] = []
        for position in positions:
            reason = self._exit_reason(position, close_price)
            if reason is None:
                continue
            exit_price = self._execution_price(close_price, self._exit_direction(position.direction))
            order = self.pipeline.portfolio_engine.close_position(
                position.symbol,
                position.layer,
                fill_price=exit_price,
                reason=reason,
            )
            trades.append(self._trade_from_close(order, reason))
        return trades

    @staticmethod
    def _exit_reason(position: Position, close_price: float) -> str | None:
        if position.direction == Direction.LONG:
            if position.stop_price is not None and close_price <= position.stop_price:
                return "stop"
            if position.target_price is not None and close_price >= position.target_price:
                return "target"
        elif position.direction == Direction.SHORT:
            if position.stop_price is not None and close_price >= position.stop_price:
                return "stop"
            if position.target_price is not None and close_price <= position.target_price:
                return "target"
        return None

    @staticmethod
    def _exit_direction(direction: Direction) -> Direction:
        if direction == Direction.LONG:
            return Direction.SHORT
        if direction == Direction.SHORT:
            return Direction.LONG
        return Direction.FLAT

    def _trade_from_close(self, order: PortfolioOrder, reason: str) -> BacktestTrade:
        if order.existing_position is None:
            raise ValueError("close order is missing existing_position")
        position = order.existing_position
        if position.direction == Direction.LONG:
            gross_pnl = (
                (order.average_fill_price - position.entry_price)
                * order.filled_quantity
                * self._contract_multiplier(order.symbol)
            )
        elif position.direction == Direction.SHORT:
            gross_pnl = (
                (position.entry_price - order.average_fill_price)
                * order.filled_quantity
                * self._contract_multiplier(order.symbol)
            )
        else:
            gross_pnl = 0.0
        contract_multiplier = self._contract_multiplier(order.symbol)
        entry_fee = position.entry_price * order.filled_quantity * contract_multiplier * self._fee_rate(order.symbol)
        exit_fee = self._order_fee(order)
        return BacktestTrade(
            symbol=order.symbol,
            layer=order.layer,
            module=position.module,
            direction=position.direction,
            entry_price=position.entry_price,
            exit_price=order.average_fill_price,
            quantity=order.filled_quantity,
            gross_pnl=gross_pnl,
            entry_fee=entry_fee,
            exit_fee=exit_fee,
            net_pnl=gross_pnl - entry_fee - exit_fee,
            exit_reason=reason,
        )

    def _equity_point(
        self,
        symbol: str,
        timestamp: object,
        bar_index: int,
        cash: float,
        latest_prices: dict[str, float],
    ) -> BacktestEquityPoint:
        unrealized = 0.0
        for position in self.pipeline.portfolio_engine.state.positions.values():
            current_price = latest_prices.get(position.symbol)
            if current_price is None:
                continue
            if position.direction == Direction.LONG:
                unrealized += (
                    (current_price - position.entry_price)
                    * position.quantity
                    * self._contract_multiplier(position.symbol)
                )
            elif position.direction == Direction.SHORT:
                unrealized += (
                    (position.entry_price - current_price)
                    * position.quantity
                    * self._contract_multiplier(position.symbol)
                )
        return BacktestEquityPoint(
            symbol=symbol,
            timestamp=timestamp,
            bar_index=bar_index,
            cash=cash,
            unrealized_pnl=unrealized,
            equity=cash + unrealized,
        )

    def _execution_price(self, fill_price: float, direction: Direction) -> float:
        slippage = self.execution.slippage_bps / 10_000.0
        if direction == Direction.LONG:
            return fill_price * (1.0 + slippage)
        if direction == Direction.SHORT:
            return fill_price * (1.0 - slippage)
        return fill_price

    def _fee_rate(self, symbol: str) -> float:
        market = self.markets_by_symbol.get(symbol)
        if market is not None and market.fee_rate is not None:
            return float(market.fee_rate)
        return self.execution.fee_rate

    def _contract_multiplier(self, symbol: str) -> float:
        market = self.markets_by_symbol.get(symbol)
        if market is not None:
            return float(market.contract_multiplier)
        return 1.0

    def _order_fee(self, order: PortfolioOrder) -> float:
        return (
            order.average_fill_price
            * order.filled_quantity
            * self._contract_multiplier(order.symbol)
            * self._fee_rate(order.symbol)
        )

    def _funding_for_symbol(self, symbol: str) -> float:
        market = self.markets_by_symbol.get(symbol)
        if market is None or market.funding_rate is None:
            return 0.0
        return sum(
            position.entry_price
            * position.quantity
            * self._contract_multiplier(position.symbol)
            * float(market.funding_rate)
            for position in self.pipeline.portfolio_engine.state.positions.values()
            if position.symbol == symbol
        )
