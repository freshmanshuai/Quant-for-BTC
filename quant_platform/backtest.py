"""Event-driven backtest harness for standardized signal pipelines."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Mapping

import pandas as pd

from quant_platform.core import MarketSpec
from quant_platform.delivery import DeliveryResult
from quant_platform.pipeline import PipelineResult, SignalPipeline
from quant_platform.portfolio import OrderAction, OrderStatus, PortfolioOrder, Position, PositionKey
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
    intrabar_stop_target: bool = False
    intrabar_entry_limit: bool = False
    max_entry_fill_fraction_per_bar: float | None = None
    max_entry_volume_fraction_per_bar: float | None = None
    max_exit_fill_fraction_per_bar: float | None = None
    max_exit_volume_fraction_per_bar: float | None = None
    max_entry_order_age_bars: int | None = None
    max_exit_order_age_bars: int | None = None
    entry_spread_feature: str | None = None
    exit_spread_feature: str | None = None


@dataclass(frozen=True)
class BacktestEquityPoint:
    """Account equity after one event, including unrealized PnL."""

    symbol: str
    timestamp: object
    bar_index: int
    cash: float
    unrealized_pnl: float
    equity: float
    return_pct: float = 0.0
    equity_peak: float = 0.0
    drawdown_amount: float = 0.0
    drawdown_pct: float = 0.0
    drawdown_duration_bars: int = 0


@dataclass(frozen=True)
class BacktestPerformanceSummary:
    """Run-level performance metrics derived from the event equity curve."""

    initial_equity: float
    final_equity: float
    total_return_pct: float
    final_unrealized_pnl: float
    realized_pnl: float
    fees_paid: float
    funding_paid: float
    max_equity: float
    min_equity: float
    max_drawdown_amount: float
    max_drawdown_pct: float
    return_to_max_drawdown: float | None = None
    max_drawdown_duration_bars: int = 0
    drawdown_point_count: int = 0
    time_in_drawdown_pct: float = 0.0
    event_return_count: int = 0
    average_event_return_pct: float = 0.0
    best_event_return_pct: float = 0.0
    worst_event_return_pct: float = 0.0
    positive_event_return_count: int = 0
    negative_event_return_count: int = 0
    event_return_win_rate: float = 0.0
    max_consecutive_positive_event_returns: int = 0
    max_consecutive_negative_event_returns: int = 0
    average_positive_event_return_pct: float = 0.0
    average_negative_event_return_pct: float = 0.0
    event_return_payoff_ratio: float | None = None
    event_return_profit_factor: float | None = None
    event_return_volatility_pct: float = 0.0
    event_return_risk_ratio: float | None = None
    event_return_downside_volatility_pct: float = 0.0
    event_return_sortino_ratio: float | None = None
    trade_count: int = 0
    win_rate: float = 0.0
    average_trade_net_pnl: float = 0.0
    average_holding_bars: float | None = None
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float | None = None
    average_win_net_pnl: float | None = None
    average_loss_net_pnl: float | None = None
    payoff_ratio: float | None = None
    realized_trade_notional: float = 0.0
    realized_turnover_ratio: float = 0.0


@dataclass(frozen=True)
class BacktestExposureBucket:
    """Exposure aggregated for one portfolio grouping key."""

    position_count: int
    long_notional: float
    short_notional: float
    gross_notional: float
    net_notional: float
    open_risk: float


@dataclass(frozen=True)
class BacktestExposurePoint:
    """Portfolio exposure after one event, marked with latest known prices."""

    symbol: str
    timestamp: object
    bar_index: int
    position_count: int
    long_notional: float
    short_notional: float
    gross_notional: float
    net_notional: float
    open_risk: float
    symbol_exposure: dict[str, BacktestExposureBucket] = field(default_factory=dict)
    layer_exposure: dict[str, BacktestExposureBucket] = field(default_factory=dict)
    module_exposure: dict[str, BacktestExposureBucket] = field(default_factory=dict)
    group_exposure: dict[str, BacktestExposureBucket] = field(default_factory=dict)
    exchange_exposure: dict[str, BacktestExposureBucket] = field(default_factory=dict)
    market_type_exposure: dict[str, BacktestExposureBucket] = field(default_factory=dict)


@dataclass(frozen=True)
class BacktestExposureSummary:
    """Peak portfolio exposure observed over an event-driven run."""

    max_position_count: int
    max_gross_notional: float
    max_abs_net_notional: float
    max_open_risk: float
    max_symbol_gross_notional: float
    max_symbol_open_risk: float
    max_layer_gross_notional: float
    max_layer_open_risk: float
    max_module_gross_notional: float
    max_module_open_risk: float
    max_group_gross_notional: float
    max_group_open_risk: float
    max_exchange_gross_notional: float = 0.0
    max_exchange_open_risk: float = 0.0
    max_market_type_gross_notional: float = 0.0
    max_market_type_open_risk: float = 0.0
    max_symbol_gross_notional_symbol: str | None = None
    max_symbol_open_risk_symbol: str | None = None
    max_layer_gross_notional_layer: str | None = None
    max_layer_open_risk_layer: str | None = None
    max_module_gross_notional_module: str | None = None
    max_module_open_risk_module: str | None = None
    max_group_gross_notional_group: str | None = None
    max_group_open_risk_group: str | None = None
    max_exchange_gross_notional_exchange: str | None = None
    max_exchange_open_risk_exchange: str | None = None
    max_market_type_gross_notional_market_type: str | None = None
    max_market_type_open_risk_market_type: str | None = None


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
    entry_timestamp: object | None = None
    exit_timestamp: object | None = None
    entry_bar_index: int | None = None
    exit_bar_index: int | None = None
    holding_bars: int | None = None


@dataclass(frozen=True)
class BacktestAttributionBucket:
    """Aggregated realized trade performance for one grouping key."""

    trade_count: int
    gross_pnl: float
    net_pnl: float
    fees_paid: float
    win_count: int
    realized_trade_notional: float = 0.0
    average_holding_bars: float | None = None
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float | None = None
    average_win_net_pnl: float | None = None
    average_loss_net_pnl: float | None = None
    payoff_ratio: float | None = None

    @property
    def win_rate(self) -> float:
        return self.win_count / self.trade_count if self.trade_count else 0.0


@dataclass(frozen=True)
class BacktestAttribution:
    """Realized trade attribution grouped by portfolio dimensions."""

    by_symbol: dict[str, BacktestAttributionBucket]
    by_layer: dict[str, BacktestAttributionBucket]
    by_module: dict[str, BacktestAttributionBucket]
    by_direction: dict[str, BacktestAttributionBucket]
    by_exit_reason: dict[str, BacktestAttributionBucket]
    by_exchange: dict[str, BacktestAttributionBucket] = field(default_factory=dict)
    by_market_type: dict[str, BacktestAttributionBucket] = field(default_factory=dict)
    by_correlation_group: dict[str, BacktestAttributionBucket] = field(default_factory=dict)


@dataclass(frozen=True)
class BacktestOrderLatency:
    """Bars an order waited between first submission and terminal resolution."""

    order_id: str
    action: OrderAction
    status: OrderStatus
    symbol: str
    layer: str
    module: str
    submitted_bar_index: int
    resolved_bar_index: int
    wait_bars: int


@dataclass(frozen=True)
class BacktestOrderLatencySummary:
    """Run-level order wait-time summary for resolved submitted orders."""

    resolved_count: int
    average_wait_bars: float | None
    max_wait_bars: int | None
    filled_count: int = 0
    canceled_count: int = 0
    rejected_count: int = 0


@dataclass(frozen=True)
class BacktestOpenOrderAge:
    """Bars an unresolved submitted order has remained open by run end."""

    order_id: str
    action: OrderAction
    status: OrderStatus
    symbol: str
    layer: str
    module: str
    submitted_bar_index: int
    current_bar_index: int
    age_bars: int


@dataclass(frozen=True)
class BacktestOpenOrderAgeSummary:
    """Run-level age summary for unresolved submitted orders."""

    open_count: int
    average_age_bars: float | None
    max_age_bars: int | None
    submitted_count: int = 0
    partially_filled_count: int = 0


@dataclass(frozen=True)
class BacktestOrderLifecycleSummary:
    """Run-level order resolution mix for event-driven execution simulation."""

    total_order_count: int
    submitted_count: int
    partially_filled_count: int
    filled_count: int
    canceled_count: int
    rejected_count: int
    resolved_count: int
    open_count: int
    terminal_count: int
    fill_rate: float
    open_rate: float
    terminal_rate: float


@dataclass(frozen=True)
class EventDrivenBacktestResult:
    """Collected pipeline results from an event-driven backtest run."""

    steps: list[BacktestStep]
    initial_equity: float = 0.0
    filled_orders: list[PortfolioOrder] = field(default_factory=list)
    state_history: list[BacktestStateSnapshot] = field(default_factory=list)
    equity_curve: list[BacktestEquityPoint] = field(default_factory=list)
    exposure_curve: list[BacktestExposurePoint] = field(default_factory=list)
    trades: list[BacktestTrade] = field(default_factory=list)
    terminal_orders: list[PortfolioOrder] = field(default_factory=list)
    order_latency: list[BacktestOrderLatency] = field(default_factory=list)
    open_order_ages: list[BacktestOpenOrderAge] = field(default_factory=list)
    markets_by_symbol: Mapping[str, MarketSpec] = field(default_factory=dict)
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

    def _effective_orders(self) -> list[PortfolioOrder]:
        effective_orders: dict[str, PortfolioOrder] = {}
        unkeyed_orders: list[PortfolioOrder] = []
        for order in self.orders:
            if order.order_id:
                effective_orders[order.order_id] = order
            else:
                unkeyed_orders.append(order)
        for order in self.filled_orders:
            if order.order_id:
                effective_orders[order.order_id] = order
            else:
                unkeyed_orders.append(order)
        for order in self.terminal_orders:
            if order.order_id:
                effective_orders[order.order_id] = order
            else:
                unkeyed_orders.append(order)
        return list(effective_orders.values()) + unkeyed_orders

    @property
    def order_status_counts(self) -> dict[OrderStatus, int]:
        counts = {status: 0 for status in OrderStatus}
        for order in self._effective_orders():
            counts[order.status] += 1
        return counts

    @property
    def order_action_counts(self) -> dict[OrderAction, int]:
        counts = {action: 0 for action in OrderAction}
        for order in self._effective_orders():
            counts[order.action] += 1
        return counts

    @property
    def order_module_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for order in self._effective_orders():
            module = self._order_module(order)
            counts[module] = counts.get(module, 0) + 1
        return counts

    @property
    def order_symbol_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for order in self._effective_orders():
            counts[order.symbol] = counts.get(order.symbol, 0) + 1
        return counts

    @property
    def order_layer_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for order in self._effective_orders():
            counts[order.layer] = counts.get(order.layer, 0) + 1
        return counts

    @staticmethod
    def _order_module(order: PortfolioOrder) -> str:
        if order.decision is None:
            return "unknown"
        return order.decision.signal.module or "unknown"

    @property
    def terminal_order_reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for order in self.terminal_orders:
            reason = order.reason or "unknown"
            counts[reason] = counts.get(reason, 0) + 1
        return counts

    @property
    def order_latency_summary(self) -> BacktestOrderLatencySummary:
        if not self.order_latency:
            return BacktestOrderLatencySummary(
                resolved_count=0,
                average_wait_bars=None,
                max_wait_bars=None,
            )
        wait_bars = [item.wait_bars for item in self.order_latency]
        return BacktestOrderLatencySummary(
            resolved_count=len(self.order_latency),
            average_wait_bars=sum(wait_bars) / len(wait_bars),
            max_wait_bars=max(wait_bars),
            filled_count=sum(item.status == OrderStatus.FILLED for item in self.order_latency),
            canceled_count=sum(item.status == OrderStatus.CANCELED for item in self.order_latency),
            rejected_count=sum(item.status == OrderStatus.REJECTED for item in self.order_latency),
        )

    @property
    def open_order_age_summary(self) -> BacktestOpenOrderAgeSummary:
        if not self.open_order_ages:
            return BacktestOpenOrderAgeSummary(
                open_count=0,
                average_age_bars=None,
                max_age_bars=None,
            )
        age_bars = [item.age_bars for item in self.open_order_ages]
        return BacktestOpenOrderAgeSummary(
            open_count=len(self.open_order_ages),
            average_age_bars=sum(age_bars) / len(age_bars),
            max_age_bars=max(age_bars),
            submitted_count=sum(item.status == OrderStatus.SUBMITTED for item in self.open_order_ages),
            partially_filled_count=sum(
                item.status == OrderStatus.PARTIALLY_FILLED for item in self.open_order_ages
            ),
        )

    @property
    def order_lifecycle_summary(self) -> BacktestOrderLifecycleSummary:
        return self._order_lifecycle_summary_for_orders(self._effective_orders())

    @property
    def order_lifecycle_by_action(self) -> dict[OrderAction, BacktestOrderLifecycleSummary]:
        orders = self._effective_orders()
        return {
            action: self._order_lifecycle_summary_for_orders(
                [order for order in orders if order.action == action]
            )
            for action in OrderAction
        }

    @property
    def order_lifecycle_by_module(self) -> dict[str, BacktestOrderLifecycleSummary]:
        groups: dict[str, list[PortfolioOrder]] = {}
        for order in self._effective_orders():
            module = self._order_module(order)
            groups.setdefault(module, []).append(order)
        return {
            module: self._order_lifecycle_summary_for_orders(orders)
            for module, orders in groups.items()
        }

    @property
    def order_lifecycle_by_symbol(self) -> dict[str, BacktestOrderLifecycleSummary]:
        groups: dict[str, list[PortfolioOrder]] = {}
        for order in self._effective_orders():
            groups.setdefault(order.symbol, []).append(order)
        return {
            symbol: self._order_lifecycle_summary_for_orders(orders)
            for symbol, orders in groups.items()
        }

    @property
    def order_lifecycle_by_layer(self) -> dict[str, BacktestOrderLifecycleSummary]:
        groups: dict[str, list[PortfolioOrder]] = {}
        for order in self._effective_orders():
            groups.setdefault(order.layer, []).append(order)
        return {
            layer: self._order_lifecycle_summary_for_orders(orders)
            for layer, orders in groups.items()
        }

    @property
    def order_lifecycle_by_direction(self) -> dict[str, BacktestOrderLifecycleSummary]:
        groups: dict[str, list[PortfolioOrder]] = {}
        for order in self._effective_orders():
            groups.setdefault(order.direction.value, []).append(order)
        return {
            direction: self._order_lifecycle_summary_for_orders(orders)
            for direction, orders in groups.items()
        }

    @property
    def order_lifecycle_by_correlation_group(self) -> dict[str, BacktestOrderLifecycleSummary]:
        groups: dict[str, list[PortfolioOrder]] = {}
        for order in self._effective_orders():
            market = self.markets_by_symbol.get(order.symbol)
            group = market.correlation_group if market is not None else None
            if group:
                groups.setdefault(group, []).append(order)
        return {
            group: self._order_lifecycle_summary_for_orders(orders)
            for group, orders in groups.items()
        }

    @property
    def order_lifecycle_by_exchange(self) -> dict[str, BacktestOrderLifecycleSummary]:
        groups: dict[str, list[PortfolioOrder]] = {}
        for order in self._effective_orders():
            market = self.markets_by_symbol.get(order.symbol)
            if market is not None and market.exchange:
                groups.setdefault(market.exchange, []).append(order)
        return {
            exchange: self._order_lifecycle_summary_for_orders(orders)
            for exchange, orders in groups.items()
        }

    @property
    def order_lifecycle_by_market_type(self) -> dict[str, BacktestOrderLifecycleSummary]:
        groups: dict[str, list[PortfolioOrder]] = {}
        for order in self._effective_orders():
            market = self.markets_by_symbol.get(order.symbol)
            if market is not None and market.market_type:
                groups.setdefault(market.market_type, []).append(order)
        return {
            market_type: self._order_lifecycle_summary_for_orders(orders)
            for market_type, orders in groups.items()
        }

    @staticmethod
    def _order_lifecycle_summary_for_orders(orders: list[PortfolioOrder]) -> BacktestOrderLifecycleSummary:
        counts = {status: 0 for status in OrderStatus}
        for order in orders:
            counts[order.status] += 1
        submitted_count = counts[OrderStatus.SUBMITTED]
        partially_filled_count = counts[OrderStatus.PARTIALLY_FILLED]
        filled_count = counts[OrderStatus.FILLED]
        canceled_count = counts[OrderStatus.CANCELED]
        rejected_count = counts[OrderStatus.REJECTED]
        open_count = submitted_count + partially_filled_count
        terminal_count = canceled_count + rejected_count
        resolved_count = filled_count + terminal_count
        total_order_count = sum(counts.values())
        return BacktestOrderLifecycleSummary(
            total_order_count=total_order_count,
            submitted_count=submitted_count,
            partially_filled_count=partially_filled_count,
            filled_count=filled_count,
            canceled_count=canceled_count,
            rejected_count=rejected_count,
            resolved_count=resolved_count,
            open_count=open_count,
            terminal_count=terminal_count,
            fill_rate=filled_count / total_order_count if total_order_count else 0.0,
            open_rate=open_count / total_order_count if total_order_count else 0.0,
            terminal_rate=terminal_count / total_order_count if total_order_count else 0.0,
        )

    @property
    def attribution(self) -> BacktestAttribution:
        return BacktestAttribution(
            by_symbol=self._bucket_by(lambda trade: trade.symbol),
            by_layer=self._bucket_by(lambda trade: trade.layer),
            by_module=self._bucket_by(lambda trade: trade.module),
            by_direction=self._bucket_by(lambda trade: trade.direction.value),
            by_exit_reason=self._bucket_by(lambda trade: trade.exit_reason),
            by_exchange=self._bucket_by_market_field(lambda market: market.exchange),
            by_market_type=self._bucket_by_market_field(lambda market: market.market_type),
            by_correlation_group=self._bucket_by_market_field(lambda market: market.correlation_group),
        )

    @property
    def performance_summary(self) -> BacktestPerformanceSummary:
        initial_equity = float(self.initial_equity)
        trade_count = len(self.trades)
        win_rate = (
            sum(trade.net_pnl > 0 for trade in self.trades) / trade_count
            if trade_count
            else 0.0
        )
        average_trade_net_pnl = (
            sum(trade.net_pnl for trade in self.trades) / trade_count
            if trade_count
            else 0.0
        )
        average_holding_bars = self._average_holding_bars(self.trades)
        wins = [trade.net_pnl for trade in self.trades if trade.net_pnl > 0]
        losses = [abs(trade.net_pnl) for trade in self.trades if trade.net_pnl < 0]
        gross_profit = sum(wins)
        gross_loss = sum(losses)
        profit_factor = gross_profit / gross_loss if gross_loss else None
        average_win_net_pnl = sum(wins) / len(wins) if wins else None
        average_loss_net_pnl = sum(losses) / len(losses) if losses else None
        payoff_ratio = (
            average_win_net_pnl / average_loss_net_pnl
            if average_win_net_pnl is not None and average_loss_net_pnl
            else None
        )
        realized_trade_notional = sum(
            (abs(trade.entry_price) + abs(trade.exit_price)) * trade.quantity
            for trade in self.trades
        )
        realized_turnover_ratio = (
            realized_trade_notional / initial_equity
            if initial_equity
            else 0.0
        )
        if not self.equity_curve:
            return BacktestPerformanceSummary(
                initial_equity=initial_equity,
                final_equity=initial_equity,
                total_return_pct=0.0,
                final_unrealized_pnl=0.0,
                realized_pnl=self.realized_pnl,
                fees_paid=self.fees_paid,
                funding_paid=self.funding_paid,
                max_equity=initial_equity,
                min_equity=initial_equity,
                max_drawdown_amount=0.0,
                max_drawdown_pct=0.0,
                return_to_max_drawdown=None,
                max_drawdown_duration_bars=0,
                drawdown_point_count=0,
                time_in_drawdown_pct=0.0,
                event_return_count=0,
                average_event_return_pct=0.0,
                best_event_return_pct=0.0,
                worst_event_return_pct=0.0,
                positive_event_return_count=0,
                negative_event_return_count=0,
                event_return_win_rate=0.0,
                max_consecutive_positive_event_returns=0,
                max_consecutive_negative_event_returns=0,
                average_positive_event_return_pct=0.0,
                average_negative_event_return_pct=0.0,
                event_return_payoff_ratio=None,
                event_return_profit_factor=None,
                event_return_volatility_pct=0.0,
                event_return_risk_ratio=None,
                event_return_downside_volatility_pct=0.0,
                event_return_sortino_ratio=None,
                trade_count=trade_count,
                win_rate=win_rate,
                average_trade_net_pnl=average_trade_net_pnl,
                average_holding_bars=average_holding_bars,
                gross_profit=gross_profit,
                gross_loss=gross_loss,
                profit_factor=profit_factor,
                average_win_net_pnl=average_win_net_pnl,
                average_loss_net_pnl=average_loss_net_pnl,
                payoff_ratio=payoff_ratio,
                realized_trade_notional=realized_trade_notional,
                realized_turnover_ratio=realized_turnover_ratio,
            )

        equity_values = [initial_equity] + [float(point.equity) for point in self.equity_curve]
        peak = equity_values[0]
        max_drawdown_amount = 0.0
        max_drawdown_pct = 0.0
        max_drawdown_duration_bars = 0
        current_drawdown_duration_bars = 0
        for equity in equity_values:
            if equity >= peak:
                peak = equity
                current_drawdown_duration_bars = 0
            else:
                current_drawdown_duration_bars += 1
            drawdown_amount = peak - equity
            drawdown_pct = drawdown_amount / peak if peak else 0.0
            if drawdown_amount > max_drawdown_amount:
                max_drawdown_amount = drawdown_amount
                max_drawdown_pct = drawdown_pct
            max_drawdown_duration_bars = max(
                max_drawdown_duration_bars,
                current_drawdown_duration_bars,
            )

        event_peak = initial_equity
        drawdown_point_count = 0
        for point in self.equity_curve:
            equity = float(point.equity)
            if equity >= event_peak:
                event_peak = equity
            else:
                drawdown_point_count += 1

        event_returns = [
            (current - previous) / previous if previous else 0.0
            for previous, current in zip(equity_values, equity_values[1:])
        ]
        positive_event_return_count = sum(return_pct > 0 for return_pct in event_returns)
        negative_event_return_count = sum(return_pct < 0 for return_pct in event_returns)
        max_consecutive_positive_event_returns = 0
        max_consecutive_negative_event_returns = 0
        current_positive_event_returns = 0
        current_negative_event_returns = 0
        for return_pct in event_returns:
            if return_pct > 0:
                current_positive_event_returns += 1
                current_negative_event_returns = 0
            elif return_pct < 0:
                current_negative_event_returns += 1
                current_positive_event_returns = 0
            else:
                current_positive_event_returns = 0
                current_negative_event_returns = 0
            max_consecutive_positive_event_returns = max(
                max_consecutive_positive_event_returns,
                current_positive_event_returns,
            )
            max_consecutive_negative_event_returns = max(
                max_consecutive_negative_event_returns,
                current_negative_event_returns,
            )
        positive_event_returns = [return_pct for return_pct in event_returns if return_pct > 0]
        negative_event_returns = [abs(return_pct) for return_pct in event_returns if return_pct < 0]
        positive_event_return_sum = sum(positive_event_returns)
        negative_event_return_sum = sum(negative_event_returns)
        average_positive_event_return_pct = (
            positive_event_return_sum / len(positive_event_returns)
            if positive_event_returns
            else 0.0
        )
        average_negative_event_return_pct = (
            negative_event_return_sum / len(negative_event_returns)
            if negative_event_returns
            else 0.0
        )
        average_event_return_pct = sum(event_returns) / len(event_returns)
        event_return_volatility_pct = math.sqrt(
            sum((return_pct - average_event_return_pct) ** 2 for return_pct in event_returns)
            / len(event_returns)
        )
        event_return_downside_volatility_pct = math.sqrt(
            sum((min(return_pct, 0.0)) ** 2 for return_pct in event_returns)
            / len(event_returns)
        )

        final_equity = equity_values[-1]
        total_return_pct = (final_equity - initial_equity) / initial_equity if initial_equity else 0.0
        return BacktestPerformanceSummary(
            initial_equity=initial_equity,
            final_equity=final_equity,
            total_return_pct=total_return_pct,
            final_unrealized_pnl=float(self.equity_curve[-1].unrealized_pnl),
            realized_pnl=self.realized_pnl,
            fees_paid=self.fees_paid,
            funding_paid=self.funding_paid,
            max_equity=max(equity_values),
            min_equity=min(equity_values),
            max_drawdown_amount=max_drawdown_amount,
            max_drawdown_pct=max_drawdown_pct,
            return_to_max_drawdown=total_return_pct / max_drawdown_pct if max_drawdown_pct else None,
            max_drawdown_duration_bars=max_drawdown_duration_bars,
            drawdown_point_count=drawdown_point_count,
            time_in_drawdown_pct=drawdown_point_count / len(self.equity_curve),
            event_return_count=len(event_returns),
            average_event_return_pct=average_event_return_pct,
            best_event_return_pct=max(event_returns),
            worst_event_return_pct=min(event_returns),
            positive_event_return_count=positive_event_return_count,
            negative_event_return_count=negative_event_return_count,
            event_return_win_rate=positive_event_return_count / len(event_returns),
            max_consecutive_positive_event_returns=max_consecutive_positive_event_returns,
            max_consecutive_negative_event_returns=max_consecutive_negative_event_returns,
            average_positive_event_return_pct=average_positive_event_return_pct,
            average_negative_event_return_pct=average_negative_event_return_pct,
            event_return_payoff_ratio=(
                average_positive_event_return_pct / average_negative_event_return_pct
                if average_positive_event_return_pct and average_negative_event_return_pct
                else None
            ),
            event_return_profit_factor=(
                positive_event_return_sum / negative_event_return_sum
                if positive_event_return_sum and negative_event_return_sum
                else None
            ),
            event_return_volatility_pct=event_return_volatility_pct,
            event_return_risk_ratio=(
                average_event_return_pct / event_return_volatility_pct
                if event_return_volatility_pct
                else None
            ),
            event_return_downside_volatility_pct=event_return_downside_volatility_pct,
            event_return_sortino_ratio=(
                average_event_return_pct / event_return_downside_volatility_pct
                if event_return_downside_volatility_pct
                else None
            ),
            trade_count=trade_count,
            win_rate=win_rate,
            average_trade_net_pnl=average_trade_net_pnl,
            average_holding_bars=average_holding_bars,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            profit_factor=profit_factor,
            average_win_net_pnl=average_win_net_pnl,
            average_loss_net_pnl=average_loss_net_pnl,
            payoff_ratio=payoff_ratio,
            realized_trade_notional=realized_trade_notional,
            realized_turnover_ratio=realized_turnover_ratio,
        )

    @property
    def exposure_summary(self) -> BacktestExposureSummary:
        symbol_buckets = [
            (symbol, bucket)
            for point in self.exposure_curve
            for symbol, bucket in point.symbol_exposure.items()
        ]
        layer_buckets = [
            (layer, bucket)
            for point in self.exposure_curve
            for layer, bucket in point.layer_exposure.items()
        ]
        module_buckets = [
            (module, bucket)
            for point in self.exposure_curve
            for module, bucket in point.module_exposure.items()
        ]
        group_buckets = [
            (group, bucket)
            for point in self.exposure_curve
            for group, bucket in point.group_exposure.items()
        ]
        exchange_buckets = [
            (exchange, bucket)
            for point in self.exposure_curve
            for exchange, bucket in point.exchange_exposure.items()
        ]
        market_type_buckets = [
            (market_type, bucket)
            for point in self.exposure_curve
            for market_type, bucket in point.market_type_exposure.items()
        ]
        max_gross_symbol = max(symbol_buckets, key=lambda item: item[1].gross_notional, default=None)
        max_open_risk_symbol = max(symbol_buckets, key=lambda item: item[1].open_risk, default=None)
        max_gross_layer = max(layer_buckets, key=lambda item: item[1].gross_notional, default=None)
        max_open_risk_layer = max(layer_buckets, key=lambda item: item[1].open_risk, default=None)
        max_gross_module = max(module_buckets, key=lambda item: item[1].gross_notional, default=None)
        max_open_risk_module = max(module_buckets, key=lambda item: item[1].open_risk, default=None)
        max_gross_group = max(group_buckets, key=lambda item: item[1].gross_notional, default=None)
        max_open_risk_group = max(group_buckets, key=lambda item: item[1].open_risk, default=None)
        max_gross_exchange = max(exchange_buckets, key=lambda item: item[1].gross_notional, default=None)
        max_open_risk_exchange = max(exchange_buckets, key=lambda item: item[1].open_risk, default=None)
        max_gross_market_type = max(market_type_buckets, key=lambda item: item[1].gross_notional, default=None)
        max_open_risk_market_type = max(market_type_buckets, key=lambda item: item[1].open_risk, default=None)
        return BacktestExposureSummary(
            max_position_count=max((point.position_count for point in self.exposure_curve), default=0),
            max_gross_notional=max((point.gross_notional for point in self.exposure_curve), default=0.0),
            max_abs_net_notional=max((abs(point.net_notional) for point in self.exposure_curve), default=0.0),
            max_open_risk=max((point.open_risk for point in self.exposure_curve), default=0.0),
            max_symbol_gross_notional=max_gross_symbol[1].gross_notional if max_gross_symbol else 0.0,
            max_symbol_open_risk=max_open_risk_symbol[1].open_risk if max_open_risk_symbol else 0.0,
            max_layer_gross_notional=max_gross_layer[1].gross_notional if max_gross_layer else 0.0,
            max_layer_open_risk=max_open_risk_layer[1].open_risk if max_open_risk_layer else 0.0,
            max_module_gross_notional=max_gross_module[1].gross_notional if max_gross_module else 0.0,
            max_module_open_risk=max_open_risk_module[1].open_risk if max_open_risk_module else 0.0,
            max_group_gross_notional=max_gross_group[1].gross_notional if max_gross_group else 0.0,
            max_group_open_risk=max_open_risk_group[1].open_risk if max_open_risk_group else 0.0,
            max_exchange_gross_notional=max_gross_exchange[1].gross_notional if max_gross_exchange else 0.0,
            max_exchange_open_risk=max_open_risk_exchange[1].open_risk if max_open_risk_exchange else 0.0,
            max_market_type_gross_notional=max_gross_market_type[1].gross_notional if max_gross_market_type else 0.0,
            max_market_type_open_risk=max_open_risk_market_type[1].open_risk if max_open_risk_market_type else 0.0,
            max_symbol_gross_notional_symbol=max_gross_symbol[0] if max_gross_symbol else None,
            max_symbol_open_risk_symbol=max_open_risk_symbol[0] if max_open_risk_symbol else None,
            max_layer_gross_notional_layer=max_gross_layer[0] if max_gross_layer else None,
            max_layer_open_risk_layer=max_open_risk_layer[0] if max_open_risk_layer else None,
            max_module_gross_notional_module=max_gross_module[0] if max_gross_module else None,
            max_module_open_risk_module=max_open_risk_module[0] if max_open_risk_module else None,
            max_group_gross_notional_group=max_gross_group[0] if max_gross_group else None,
            max_group_open_risk_group=max_open_risk_group[0] if max_open_risk_group else None,
            max_exchange_gross_notional_exchange=max_gross_exchange[0] if max_gross_exchange else None,
            max_exchange_open_risk_exchange=max_open_risk_exchange[0] if max_open_risk_exchange else None,
            max_market_type_gross_notional_market_type=max_gross_market_type[0] if max_gross_market_type else None,
            max_market_type_open_risk_market_type=max_open_risk_market_type[0] if max_open_risk_market_type else None,
        )

    def _bucket_by(self, key_fn) -> dict[str, BacktestAttributionBucket]:
        buckets: dict[str, list[BacktestTrade]] = {}
        for trade in self.trades:
            buckets.setdefault(key_fn(trade), []).append(trade)
        return {key: self._attribution_bucket(items) for key, items in buckets.items()}

    def _bucket_by_market_field(self, key_fn) -> dict[str, BacktestAttributionBucket]:
        buckets: dict[str, list[BacktestTrade]] = {}
        for trade in self.trades:
            market = self.markets_by_symbol.get(trade.symbol)
            key = key_fn(market) if market is not None else None
            if key:
                buckets.setdefault(key, []).append(trade)
        return {key: self._attribution_bucket(items) for key, items in buckets.items()}

    def _attribution_bucket(self, trades: list[BacktestTrade]) -> BacktestAttributionBucket:
        wins = [trade.net_pnl for trade in trades if trade.net_pnl > 0]
        losses = [abs(trade.net_pnl) for trade in trades if trade.net_pnl < 0]
        gross_profit = sum(wins)
        gross_loss = sum(losses)
        average_win_net_pnl = sum(wins) / len(wins) if wins else None
        average_loss_net_pnl = sum(losses) / len(losses) if losses else None
        return BacktestAttributionBucket(
            trade_count=len(trades),
            gross_pnl=sum(item.gross_pnl for item in trades),
            net_pnl=sum(item.net_pnl for item in trades),
            fees_paid=sum(item.entry_fee + item.exit_fee for item in trades),
            win_count=sum(item.net_pnl > 0 for item in trades),
            realized_trade_notional=sum(
                (abs(item.entry_price) + abs(item.exit_price)) * item.quantity
                for item in trades
            ),
            average_holding_bars=self._average_holding_bars(trades),
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            profit_factor=gross_profit / gross_loss if gross_loss else None,
            average_win_net_pnl=average_win_net_pnl,
            average_loss_net_pnl=average_loss_net_pnl,
            payoff_ratio=(
                average_win_net_pnl / average_loss_net_pnl
                if average_win_net_pnl is not None and average_loss_net_pnl
                else None
            ),
        )

    @staticmethod
    def _average_holding_bars(trades: list[BacktestTrade]) -> float | None:
        holding_bars = [trade.holding_bars for trade in trades if trade.holding_bars is not None]
        return sum(holding_bars) / len(holding_bars) if holding_bars else None


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
        self._triggered_exit_order_quantities: dict[tuple[str, str], float] = {}
        self._position_entries: dict[PositionKey, tuple[object, int]] = {}

    def run(self, features_by_symbol: Mapping[str, pd.DataFrame]) -> EventDrivenBacktestResult:
        self._triggered_exit_order_quantities = {}
        self._position_entries = {}
        steps: list[BacktestStep] = []
        filled_orders: list[PortfolioOrder] = []
        state_history: list[BacktestStateSnapshot] = []
        equity_curve: list[BacktestEquityPoint] = []
        exposure_curve: list[BacktestExposurePoint] = []
        trades: list[BacktestTrade] = []
        terminal_orders: list[PortfolioOrder] = []
        order_latency: list[BacktestOrderLatency] = []
        equity_peak = float(self.account.equity)
        previous_equity = float(self.account.equity)
        equity_drawdown_duration_bars = 0
        events: list[tuple[object, str, int]] = []
        order_first_seen_bar: dict[str, int] = {}
        latency_recorded_order_ids: set[str] = set()
        last_bar_by_symbol: dict[str, int] = {}
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
            last_bar_by_symbol[symbol] = bar_index
            features = features_by_symbol[symbol]
            window = features.iloc[: bar_index + 1]
            fill_price = float(window["Close"].iloc[-1]) if "Close" in window.columns else None
            if fill_price is not None:
                latest_prices[symbol] = fill_price
            account = self._account_with_equity(
                self._equity_point(symbol, timestamp, bar_index, cash, latest_prices).equity
            )
            result = self.pipeline.run(
                window,
                symbol=symbol,
                account=account,
                entry_price=fill_price,
                bar_index=bar_index,
            )
            steps.append(BacktestStep(symbol=symbol, timestamp=timestamp, bar_index=bar_index, result=result))
            event_fills = self._already_filled_internal_orders(result.portfolio_plan.orders)
            event_orders = self._event_submitted_orders(symbol, result.portfolio_plan.orders)
            self._track_submitted_order_first_seen(order_first_seen_bar, event_orders, bar_index)
            submitted_fills, submitted_entry_fees = self._fill_submitted_orders(
                event_orders,
                fill_price,
                window.iloc[-1],
            )
            event_fills.extend(submitted_fills)
            filled_orders.extend(event_fills)
            expired_orders = self._cancel_expired_orders(event_orders, order_first_seen_bar, bar_index)
            terminal_orders.extend(expired_orders)
            self._record_order_latency(
                order_latency,
                latency_recorded_order_ids,
                event_fills + expired_orders,
                order_first_seen_bar,
                bar_index,
            )
            event_fees = submitted_entry_fees
            fees_paid += event_fees
            cash -= event_fees
            event_funding = self._funding_for_symbol(symbol)
            funding_paid += event_funding
            cash -= event_funding
            event_trades = self._trades_from_event_fills(event_fills, timestamp, bar_index)
            event_trades.extend(
                self._close_triggered_positions(
                    symbol,
                    window.iloc[-1],
                    fill_price,
                    event_fills,
                    timestamp,
                    bar_index,
                )
            )
            trades.extend(event_trades)
            self._record_risk_trade_feedback(event_trades, bar_index)
            exit_fees = sum(trade.exit_fee for trade in event_trades)
            event_realized = sum(trade.gross_pnl for trade in event_trades)
            realized_pnl += event_realized
            fees_paid += exit_fees
            cash += event_realized - exit_fees
            state_history.append(self._snapshot(symbol, timestamp, bar_index))
            equity_point = self._equity_point(symbol, timestamp, bar_index, cash, latest_prices)
            if equity_point.equity >= equity_peak:
                equity_peak = equity_point.equity
                equity_drawdown_duration_bars = 0
            else:
                equity_drawdown_duration_bars += 1
            drawdown_amount = equity_peak - equity_point.equity
            equity_curve.append(
                replace(
                    equity_point,
                    return_pct=(equity_point.equity - previous_equity) / previous_equity if previous_equity else 0.0,
                    equity_peak=equity_peak,
                    drawdown_amount=drawdown_amount,
                    drawdown_pct=drawdown_amount / equity_peak if equity_peak else 0.0,
                    drawdown_duration_bars=equity_drawdown_duration_bars,
                )
            )
            previous_equity = equity_point.equity
            exposure_curve.append(self._exposure_point(symbol, timestamp, bar_index, latest_prices))

        open_order_ages = self._open_order_ages(order_first_seen_bar, last_bar_by_symbol)

        return EventDrivenBacktestResult(
            steps=steps,
            initial_equity=self.account.equity,
            filled_orders=filled_orders,
            state_history=state_history,
            equity_curve=equity_curve,
            exposure_curve=exposure_curve,
            trades=trades,
            terminal_orders=terminal_orders,
            order_latency=order_latency,
            open_order_ages=open_order_ages,
            markets_by_symbol=self.markets_by_symbol,
            realized_pnl=realized_pnl,
            fees_paid=fees_paid,
            funding_paid=funding_paid,
        )

    def _event_submitted_orders(self, symbol: str, current_orders: list[PortfolioOrder]) -> list[PortfolioOrder]:
        current_ids = {order.order_id for order in current_orders if order.order_id}
        orders = list(current_orders)
        orders.extend(
            order
            for order in self.pipeline.portfolio_engine.state.orders.values()
            if (
                order.order_id
                and order.order_id not in current_ids
                and order.symbol == symbol
                and order.status in {OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED}
            )
        )
        return orders

    @staticmethod
    def _track_submitted_order_first_seen(
        order_first_seen_bar: dict[str, int],
        orders: list[PortfolioOrder],
        bar_index: int,
    ) -> None:
        for order in orders:
            if order.order_id and order.status in {OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED}:
                order_first_seen_bar.setdefault(order.order_id, bar_index)

    @staticmethod
    def _record_order_latency(
        order_latency: list[BacktestOrderLatency],
        recorded_order_ids: set[str],
        orders: list[PortfolioOrder],
        order_first_seen_bar: dict[str, int],
        bar_index: int,
    ) -> None:
        terminal_statuses = {OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED}
        for order in orders:
            if not order.order_id or order.order_id in recorded_order_ids:
                continue
            if order.status not in terminal_statuses:
                continue
            if order.order_id not in order_first_seen_bar:
                continue
            submitted_bar_index = order_first_seen_bar[order.order_id]
            order_latency.append(
                BacktestOrderLatency(
                    order_id=order.order_id,
                    action=order.action,
                    status=order.status,
                    symbol=order.symbol,
                    layer=order.layer,
                    module=EventDrivenBacktestResult._order_module(order),
                    submitted_bar_index=submitted_bar_index,
                    resolved_bar_index=bar_index,
                    wait_bars=bar_index - submitted_bar_index,
                )
            )
            recorded_order_ids.add(order.order_id)

    def _open_order_ages(
        self,
        order_first_seen_bar: dict[str, int],
        last_bar_by_symbol: dict[str, int],
    ) -> list[BacktestOpenOrderAge]:
        open_statuses = {OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED}
        rows: list[BacktestOpenOrderAge] = []
        for order in self.pipeline.portfolio_engine.state.orders.values():
            if not order.order_id or order.status not in open_statuses:
                continue
            submitted_bar_index = order_first_seen_bar.get(order.order_id)
            current_bar_index = last_bar_by_symbol.get(order.symbol)
            if submitted_bar_index is None or current_bar_index is None:
                continue
            rows.append(
                BacktestOpenOrderAge(
                    order_id=order.order_id,
                    action=order.action,
                    status=order.status,
                    symbol=order.symbol,
                    layer=order.layer,
                    module=EventDrivenBacktestResult._order_module(order),
                    submitted_bar_index=submitted_bar_index,
                    current_bar_index=current_bar_index,
                    age_bars=current_bar_index - submitted_bar_index,
                )
            )
        return rows

    def _fill_submitted_orders(
        self,
        orders: list[PortfolioOrder],
        fill_price: float | None,
        current_bar: pd.Series,
    ) -> tuple[list[PortfolioOrder], float]:
        if fill_price is None:
            return [], 0.0
        filled: list[PortfolioOrder] = []
        entry_fees = 0.0
        for order in orders:
            if order.action not in {OrderAction.OPEN, OrderAction.CLOSE, OrderAction.REBALANCE}:
                continue
            if order.status not in {OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED} or not order.order_id:
                continue
            execution_price = self._submitted_order_execution_price(order, fill_price, current_bar)
            if execution_price is None:
                self._discard_precreated_open_position(order)
                continue
            fill_quantity = self._submitted_order_fill_quantity(order, current_bar)
            if fill_quantity <= 0:
                continue
            filled_order = self.pipeline.portfolio_engine.record_fill(
                order.order_id,
                filled_quantity=fill_quantity,
                fill_price=execution_price,
            )
            filled.append(self._event_fill_order(filled_order, fill_quantity, execution_price))
            if self._is_entry_like_fill(order):
                entry_fees += self._fill_fee(order.symbol, execution_price, fill_quantity)
        return filled, entry_fees

    def _cancel_expired_orders(
        self,
        orders: list[PortfolioOrder],
        order_first_seen_bar: dict[str, int],
        bar_index: int,
    ) -> list[PortfolioOrder]:
        return self._cancel_expired_entry_orders(
            orders,
            order_first_seen_bar,
            bar_index,
        ) + self._cancel_expired_exit_orders(
            orders,
            order_first_seen_bar,
            bar_index,
        )

    def _cancel_expired_entry_orders(
        self,
        orders: list[PortfolioOrder],
        order_first_seen_bar: dict[str, int],
        bar_index: int,
    ) -> list[PortfolioOrder]:
        max_age = self.execution.max_entry_order_age_bars
        if max_age is None:
            return []
        canceled: list[PortfolioOrder] = []
        for order in orders:
            if not order.order_id or not self._is_entry_like_fill(order):
                continue
            current_order = self.pipeline.portfolio_engine.state.orders.get(order.order_id)
            if current_order is None:
                continue
            if current_order.status not in {OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED}:
                continue
            first_seen = order_first_seen_bar.get(order.order_id, bar_index)
            if bar_index - first_seen <= max_age:
                continue
            self._discard_precreated_open_position(current_order)
            canceled.append(
                self.pipeline.portfolio_engine.cancel_order(
                    current_order.order_id,
                    reason="entry_order_expired",
                )
            )
        return canceled

    def _cancel_expired_exit_orders(
        self,
        orders: list[PortfolioOrder],
        order_first_seen_bar: dict[str, int],
        bar_index: int,
    ) -> list[PortfolioOrder]:
        max_age = self.execution.max_exit_order_age_bars
        if max_age is None:
            return []
        canceled: list[PortfolioOrder] = []
        for order in orders:
            if not order.order_id or not self._is_exit_like_fill(order):
                continue
            current_order = self.pipeline.portfolio_engine.state.orders.get(order.order_id)
            if current_order is None:
                continue
            if current_order.status not in {OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED}:
                continue
            first_seen = order_first_seen_bar.get(order.order_id, bar_index)
            if bar_index - first_seen <= max_age:
                continue
            canceled.append(
                self.pipeline.portfolio_engine.cancel_order(
                    current_order.order_id,
                    reason="exit_order_expired",
                )
            )
        return canceled

    def _submitted_order_fill_quantity(self, order: PortfolioOrder, current_bar: pd.Series) -> float:
        remaining = order.quantity - order.filled_quantity
        if remaining <= 0:
            return 0.0
        if self._is_entry_like_fill(order):
            return self._capped_fill_quantity(
                current_bar,
                order_quantity=order.quantity,
                remaining=remaining,
                max_fill_fraction_per_bar=self.execution.max_entry_fill_fraction_per_bar,
                max_volume_fraction_per_bar=self.execution.max_entry_volume_fraction_per_bar,
            )
        if self._is_exit_like_fill(order):
            return self._capped_fill_quantity(
                current_bar,
                order_quantity=order.quantity,
                remaining=remaining,
                max_fill_fraction_per_bar=self.execution.max_exit_fill_fraction_per_bar,
                max_volume_fraction_per_bar=self.execution.max_exit_volume_fraction_per_bar,
            )
        return remaining

    def _capped_fill_quantity(
        self,
        current_bar: pd.Series,
        *,
        order_quantity: float,
        remaining: float,
        max_fill_fraction_per_bar: float | None,
        max_volume_fraction_per_bar: float | None,
    ) -> float:
        max_quantity = remaining
        if max_fill_fraction_per_bar is not None:
            max_quantity = min(max_quantity, order_quantity * max_fill_fraction_per_bar)
        if max_volume_fraction_per_bar is not None:
            volume = self._bar_volume(current_bar)
            if volume is not None:
                max_quantity = min(max_quantity, volume * max_volume_fraction_per_bar)
        return min(remaining, max_quantity)

    def _event_fill_order(
        self,
        order: PortfolioOrder,
        fill_quantity: float,
        fill_price: float,
    ) -> PortfolioOrder:
        if not self._is_exit_like_fill(order):
            return order
        return replace(order, filled_quantity=fill_quantity, average_fill_price=fill_price)

    def _submitted_order_execution_price(
        self,
        order: PortfolioOrder,
        fill_price: float,
        current_bar: pd.Series,
    ) -> float | None:
        if self.execution.intrabar_entry_limit and self._is_entry_like_fill(order):
            entry_price = order.entry_price if order.entry_price is not None else fill_price
            if not self._bar_touches_price(current_bar, entry_price):
                return None
            return self._execution_price(
                self._entry_spread_adjusted_price(order, entry_price, current_bar),
                order.direction,
            )
        if self._is_exit_like_fill(order):
            exit_direction = self._order_exit_direction(order)
            return self._execution_price(
                self._exit_spread_adjusted_price(exit_direction, fill_price, current_bar),
                exit_direction,
            )
        return self._execution_price(
            self._entry_spread_adjusted_price(order, fill_price, current_bar),
            order.direction,
        )

    def _entry_spread_adjusted_price(
        self,
        order: PortfolioOrder,
        fill_price: float,
        current_bar: pd.Series,
    ) -> float:
        feature_name = self.execution.entry_spread_feature
        if not feature_name or not self._is_entry_like_fill(order) or feature_name not in current_bar.index:
            return fill_price
        return self._spread_adjusted_price(feature_name, order.direction, fill_price, current_bar)

    def _exit_spread_adjusted_price(
        self,
        direction: Direction,
        fill_price: float,
        current_bar: pd.Series,
    ) -> float:
        feature_name = self.execution.exit_spread_feature
        if not feature_name or feature_name not in current_bar.index:
            return fill_price
        return self._spread_adjusted_price(feature_name, direction, fill_price, current_bar)

    @staticmethod
    def _spread_adjusted_price(
        feature_name: str,
        direction: Direction,
        fill_price: float,
        current_bar: pd.Series,
    ) -> float:
        spread = current_bar[feature_name]
        if pd.isna(spread):
            return fill_price
        half_spread = max(float(spread), 0.0) / 2.0
        if direction == Direction.LONG:
            return fill_price + half_spread
        if direction == Direction.SHORT:
            return fill_price - half_spread
        return fill_price

    def _discard_precreated_open_position(self, order: PortfolioOrder) -> None:
        if order.action != OrderAction.OPEN:
            return
        key = PositionKey(order.symbol, order.layer)
        position = self.pipeline.portfolio_engine.state.positions.get(key)
        if position is None:
            return
        if (
            position.direction == order.direction
            and position.quantity == order.quantity
            and position.entry_price == order.entry_price
        ):
            del self.pipeline.portfolio_engine.state.positions[key]

    @staticmethod
    def _already_filled_internal_orders(orders: list[PortfolioOrder]) -> list[PortfolioOrder]:
        return [
            order
            for order in orders
            if order.status == OrderStatus.FILLED and order.action == OrderAction.TRANSFER
        ]

    def _trades_from_event_fills(
        self,
        event_fills: list[PortfolioOrder],
        timestamp: object,
        bar_index: int,
    ) -> list[BacktestTrade]:
        trades: list[BacktestTrade] = []
        for order in event_fills:
            if order.action == OrderAction.OPEN:
                self._record_entry_metadata(order, timestamp, bar_index)
                continue
            if order.action == OrderAction.CLOSE or self._is_rebalance_reduce(order):
                trades.append(self._trade_from_close(order, order.reason, timestamp, bar_index))
                self._clear_entry_metadata_if_closed(order)
        return trades

    def _record_entry_metadata(self, order: PortfolioOrder, timestamp: object, bar_index: int) -> None:
        if order.filled_quantity <= 0:
            return
        self._position_entries.setdefault(PositionKey(order.symbol, order.layer), (timestamp, bar_index))

    def _clear_entry_metadata_if_closed(self, order: PortfolioOrder) -> None:
        position = order.existing_position
        if position is None:
            return
        if order.filled_quantity < position.quantity:
            return
        self._position_entries.pop(PositionKey(order.symbol, order.layer), None)

    def _record_risk_trade_feedback(self, event_trades: list[BacktestTrade], bar_index: int) -> None:
        for trade in event_trades:
            self.pipeline.risk_engine.state.record_trade(
                trade.net_pnl,
                bar_index=bar_index,
                limits=self.pipeline.risk_engine.limits,
            )

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
        current_bar: pd.Series,
        close_price: float | None,
        event_fills: list[PortfolioOrder],
        timestamp: object,
        bar_index: int,
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
            trigger = self._exit_trigger(position, close_price, current_bar)
            if trigger is None:
                continue
            reason, trigger_price = trigger
            exit_direction = self._exit_direction(position.direction)
            exit_price = self._execution_price(
                self._exit_spread_adjusted_price(exit_direction, trigger_price, current_bar),
                exit_direction,
            )
            close_quantity = self._triggered_exit_fill_quantity(position, current_bar)
            if close_quantity <= 0:
                continue
            order = self.pipeline.portfolio_engine.close_position(
                position.symbol,
                position.layer,
                fill_price=exit_price,
                quantity=close_quantity,
                reason=reason,
            )
            if close_quantity >= position.quantity:
                self._triggered_exit_order_quantities.pop((position.symbol, position.layer), None)
            trades.append(self._trade_from_close(order, reason, timestamp, bar_index))
            self._clear_entry_metadata_if_closed(order)
        return trades

    def _triggered_exit_fill_quantity(self, position: Position, current_bar: pd.Series) -> float:
        key = (position.symbol, position.layer)
        order_quantity = self._triggered_exit_order_quantities.setdefault(key, position.quantity)
        return self._capped_fill_quantity(
            current_bar,
            order_quantity=order_quantity,
            remaining=position.quantity,
            max_fill_fraction_per_bar=self.execution.max_exit_fill_fraction_per_bar,
            max_volume_fraction_per_bar=self.execution.max_exit_volume_fraction_per_bar,
        )

    def _exit_trigger(
        self,
        position: Position,
        close_price: float,
        current_bar: pd.Series,
    ) -> tuple[str, float] | None:
        if self.execution.intrabar_stop_target:
            intrabar_trigger = self._intrabar_exit_trigger(position, current_bar)
            if intrabar_trigger is not None:
                return intrabar_trigger
        reason = self._exit_reason(position, close_price)
        if reason is None:
            return None
        return reason, close_price

    def _intrabar_exit_trigger(self, position: Position, current_bar: pd.Series) -> tuple[str, float] | None:
        high_price = self._bar_price(current_bar, "High")
        low_price = self._bar_price(current_bar, "Low")
        if high_price is None or low_price is None:
            return None
        if position.direction == Direction.LONG:
            if position.stop_price is not None and low_price <= position.stop_price:
                return "stop", position.stop_price
            if position.target_price is not None and high_price >= position.target_price:
                return "target", position.target_price
        elif position.direction == Direction.SHORT:
            if position.stop_price is not None and high_price >= position.stop_price:
                return "stop", position.stop_price
            if position.target_price is not None and low_price <= position.target_price:
                return "target", position.target_price
        return None

    def _bar_touches_price(self, current_bar: pd.Series, price: float) -> bool:
        high_price = self._bar_price(current_bar, "High")
        low_price = self._bar_price(current_bar, "Low")
        if high_price is None or low_price is None:
            return True
        return low_price <= price <= high_price

    @staticmethod
    def _bar_price(current_bar: pd.Series, column: str) -> float | None:
        if column not in current_bar.index:
            return None
        value = current_bar[column]
        if pd.isna(value):
            return None
        return float(value)

    @staticmethod
    def _bar_volume(current_bar: pd.Series) -> float | None:
        if "Volume" not in current_bar.index:
            return None
        value = current_bar["Volume"]
        if pd.isna(value):
            return None
        return float(value)

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

    def _trade_from_close(
        self,
        order: PortfolioOrder,
        reason: str,
        exit_timestamp: object,
        exit_bar_index: int,
    ) -> BacktestTrade:
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
        entry_timestamp, entry_bar_index = self._position_entries.get(
            PositionKey(order.symbol, order.layer),
            (None, None),
        )
        holding_bars = exit_bar_index - entry_bar_index if entry_bar_index is not None else None
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
            entry_timestamp=entry_timestamp,
            exit_timestamp=exit_timestamp,
            entry_bar_index=entry_bar_index,
            exit_bar_index=exit_bar_index,
            holding_bars=holding_bars,
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

    def _account_with_equity(self, equity: float) -> AccountState:
        return AccountState(
            equity=equity,
            daily_drawdown_pct=self.account.daily_drawdown_pct,
            weekly_drawdown_pct=self.account.weekly_drawdown_pct,
        )

    def _exposure_point(
        self,
        symbol: str,
        timestamp: object,
        bar_index: int,
        latest_prices: dict[str, float],
    ) -> BacktestExposurePoint:
        long_notional = 0.0
        short_notional = 0.0
        symbol_stats: dict[str, dict[str, float]] = {}
        layer_stats: dict[str, dict[str, float]] = {}
        module_stats: dict[str, dict[str, float]] = {}
        group_stats: dict[str, dict[str, float]] = {}
        exchange_stats: dict[str, dict[str, float]] = {}
        market_type_stats: dict[str, dict[str, float]] = {}
        positions = list(self.pipeline.portfolio_engine.state.positions.values())

        def add_stats(stats_by_key: dict[str, dict[str, float]], key: str | None, position: Position, notional: float):
            if not key:
                return
            stats = stats_by_key.setdefault(
                key,
                {
                    "position_count": 0.0,
                    "long_notional": 0.0,
                    "short_notional": 0.0,
                    "open_risk": 0.0,
                },
            )
            stats["position_count"] += 1.0
            stats["open_risk"] += position.risk_amount
            if position.direction == Direction.LONG:
                stats["long_notional"] += notional
            elif position.direction == Direction.SHORT:
                stats["short_notional"] += notional

        for position in positions:
            current_price = latest_prices.get(position.symbol, position.entry_price)
            notional = current_price * position.quantity * self._contract_multiplier(position.symbol)
            if position.direction == Direction.LONG:
                long_notional += notional
            elif position.direction == Direction.SHORT:
                short_notional += notional
            stats = symbol_stats.setdefault(
                position.symbol,
                {
                    "position_count": 0.0,
                    "long_notional": 0.0,
                    "short_notional": 0.0,
                    "open_risk": 0.0,
                },
            )
            stats["position_count"] += 1.0
            stats["open_risk"] += position.risk_amount
            if position.direction == Direction.LONG:
                stats["long_notional"] += notional
            elif position.direction == Direction.SHORT:
                stats["short_notional"] += notional
            stats = layer_stats.setdefault(
                position.layer,
                {
                    "position_count": 0.0,
                    "long_notional": 0.0,
                    "short_notional": 0.0,
                    "open_risk": 0.0,
                },
            )
            stats["position_count"] += 1.0
            stats["open_risk"] += position.risk_amount
            if position.direction == Direction.LONG:
                stats["long_notional"] += notional
            elif position.direction == Direction.SHORT:
                stats["short_notional"] += notional
            stats = module_stats.setdefault(
                position.module,
                {
                    "position_count": 0.0,
                    "long_notional": 0.0,
                    "short_notional": 0.0,
                    "open_risk": 0.0,
                },
            )
            stats["position_count"] += 1.0
            stats["open_risk"] += position.risk_amount
            if position.direction == Direction.LONG:
                stats["long_notional"] += notional
            elif position.direction == Direction.SHORT:
                stats["short_notional"] += notional
            group = self._correlation_group(position.symbol)
            if group:
                add_stats(group_stats, group, position, notional)
            market = self.markets_by_symbol.get(position.symbol)
            if market is not None:
                add_stats(exchange_stats, market.exchange, position, notional)
                add_stats(market_type_stats, market.market_type, position, notional)
        return BacktestExposurePoint(
            symbol=symbol,
            timestamp=timestamp,
            bar_index=bar_index,
            position_count=len(positions),
            long_notional=long_notional,
            short_notional=short_notional,
            gross_notional=long_notional + short_notional,
            net_notional=long_notional - short_notional,
            open_risk=self.pipeline.portfolio_engine.state.open_risk(),
            symbol_exposure=self._exposure_buckets(symbol_stats),
            layer_exposure=self._exposure_buckets(layer_stats),
            module_exposure=self._exposure_buckets(module_stats),
            group_exposure=self._exposure_buckets(group_stats),
            exchange_exposure=self._exposure_buckets(exchange_stats),
            market_type_exposure=self._exposure_buckets(market_type_stats),
        )

    def _exposure_buckets(self, stats_by_key: dict[str, dict[str, float]]) -> dict[str, BacktestExposureBucket]:
        return {
            key: BacktestExposureBucket(
                position_count=int(stats["position_count"]),
                long_notional=stats["long_notional"],
                short_notional=stats["short_notional"],
                gross_notional=stats["long_notional"] + stats["short_notional"],
                net_notional=stats["long_notional"] - stats["short_notional"],
                open_risk=stats["open_risk"],
            )
            for key, stats in stats_by_key.items()
        }

    def _correlation_group(self, symbol: str) -> str | None:
        market = self.markets_by_symbol.get(symbol)
        return market.correlation_group if market is not None else None

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
        return self._fill_fee(order.symbol, order.average_fill_price, order.filled_quantity)

    def _fill_fee(self, symbol: str, fill_price: float, filled_quantity: float) -> float:
        return fill_price * filled_quantity * self._contract_multiplier(symbol) * self._fee_rate(symbol)

    @staticmethod
    def _is_entry_like_fill(order: PortfolioOrder) -> bool:
        if order.action == OrderAction.OPEN:
            return True
        if order.action == OrderAction.REBALANCE and order.reason != "decrease_position":
            return True
        return False

    @staticmethod
    def _is_rebalance_reduce(order: PortfolioOrder) -> bool:
        return order.action == OrderAction.REBALANCE and order.reason == "decrease_position"

    @staticmethod
    def _is_exit_like_fill(order: PortfolioOrder) -> bool:
        return order.action == OrderAction.CLOSE or EventDrivenBacktest._is_rebalance_reduce(order)

    def _order_exit_direction(self, order: PortfolioOrder) -> Direction:
        if order.existing_position is not None:
            return self._exit_direction(order.existing_position.direction)
        return order.direction

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
