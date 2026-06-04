"""Generic risk decisions for standardized platform signals."""

from __future__ import annotations

from dataclasses import dataclass, field

from quant_platform.core import MarketSpec
from quant_platform.signals import Direction, Signal


@dataclass(frozen=True)
class AccountState:
    """Current account-level risk context passed into the risk engine."""

    equity: float
    daily_drawdown_pct: float = 0.0
    weekly_drawdown_pct: float = 0.0


@dataclass(frozen=True)
class RiskLimits:
    """Risk limits shared by signal, portfolio, and delivery layers."""

    risk_per_trade: float = 0.02
    max_position_fraction: float = 1.0
    max_leverage: float = 1.0
    portfolio_risk_budget: float = 0.06
    max_symbol_risk: float | None = None
    max_module_risk: float | None = None
    max_correlation_group_risk: float | None = None
    correlation_groups: dict[str, str] = field(default_factory=dict)
    daily_drawdown_limit: float = 0.075
    weekly_drawdown_limit: float = 0.075
    consecutive_loss_limit: int = 3
    reduced_size_multiplier: float = 0.5
    max_consecutive_losses: int = 5
    pause_bars: int = 18


@dataclass(frozen=True)
class RiskDecision:
    """Position sizing and gate result for one candidate signal."""

    allowed: bool
    reason: str
    signal: Signal
    quantity: float = 0.0
    notional: float = 0.0
    risk_amount: float = 0.0
    entry_price: float = 0.0
    stop_price: float | None = None
    max_loss_per_unit: float = 0.0
    applied_size_multiplier: float = 1.0


@dataclass
class RiskState:
    """Mutable rolling state for loss streak and pause handling."""

    consecutive_losses: int = 0
    pause_until_bar: int = -1
    realized_pnl: list[float] = field(default_factory=list)

    def record_trade(self, pnl: float, bar_index: int, limits: RiskLimits) -> None:
        self.realized_pnl.append(float(pnl))
        if pnl <= 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= limits.max_consecutive_losses:
                self.pause_until_bar = int(bar_index) + limits.pause_bars
        else:
            self.consecutive_losses = 0
            self.pause_until_bar = -1

    def is_paused(self, bar_index: int) -> bool:
        return self.pause_until_bar >= 0 and int(bar_index) < self.pause_until_bar

    def size_multiplier(self, limits: RiskLimits) -> float:
        if self.consecutive_losses >= limits.consecutive_loss_limit:
            return limits.reduced_size_multiplier
        return 1.0


class RiskEngine:
    """Evaluate standardized signals against account and portfolio limits."""

    def __init__(
        self,
        limits: RiskLimits | None = None,
        state: RiskState | None = None,
        markets_by_symbol: dict[str, MarketSpec] | None = None,
    ):
        self.limits = limits or RiskLimits()
        self.state = state or RiskState()
        self.markets_by_symbol = dict(markets_by_symbol or {})

    def evaluate(
        self,
        signal: Signal,
        account: AccountState,
        *,
        entry_price: float,
        bar_index: int = 0,
        open_risk: float = 0.0,
        open_symbol_risk: dict[str, float] | None = None,
        open_module_risk: dict[str, float] | None = None,
        open_group_risk: dict[str, float] | None = None,
    ) -> RiskDecision:
        if signal.direction == Direction.FLAT:
            return self._blocked(signal, "flat_signal", entry_price=entry_price)
        if signal.preferred_stop is None:
            return self._blocked(signal, "missing_stop", entry_price=entry_price)
        if account.equity <= 0:
            return self._blocked(signal, "non_positive_equity", entry_price=entry_price)
        if account.daily_drawdown_pct >= self.limits.daily_drawdown_limit:
            return self._blocked(signal, "daily_drawdown_limit", entry_price=entry_price)
        if account.weekly_drawdown_pct >= self.limits.weekly_drawdown_limit:
            return self._blocked(signal, "weekly_drawdown_limit", entry_price=entry_price)
        if self.state.is_paused(bar_index):
            return self._blocked(signal, "paused_after_consecutive_losses", entry_price=entry_price)
        market = self.markets_by_symbol.get(signal.symbol)
        if market is not None and signal.direction == Direction.SHORT and not market.supports_short:
            return self._blocked(signal, "short_not_supported", entry_price=entry_price)

        stop_price = float(signal.preferred_stop)
        entry = float(entry_price)
        stop_distance = abs(entry - stop_price)
        if entry <= 0 or stop_distance <= 0:
            return self._blocked(signal, "invalid_stop_distance", entry_price=entry_price, stop_price=stop_price)

        multiplier = self.state.size_multiplier(self.limits)
        target_risk = account.equity * self.limits.risk_per_trade * multiplier
        portfolio_budget = account.equity * self.limits.portfolio_risk_budget
        if open_risk + target_risk > portfolio_budget:
            return self._blocked(signal, "portfolio_risk_budget_exhausted", entry_price=entry, stop_price=stop_price)

        if self.limits.max_symbol_risk is not None:
            symbol_budget = account.equity * self.limits.max_symbol_risk
            current_symbol_risk = float((open_symbol_risk or {}).get(signal.symbol, 0.0))
            if current_symbol_risk + target_risk > symbol_budget:
                return self._blocked(signal, "symbol_risk_budget_exhausted", entry_price=entry, stop_price=stop_price)

        if self.limits.max_module_risk is not None:
            module_budget = account.equity * self.limits.max_module_risk
            current_module_risk = float((open_module_risk or {}).get(signal.module, 0.0))
            if current_module_risk + target_risk > module_budget:
                return self._blocked(signal, "module_risk_budget_exhausted", entry_price=entry, stop_price=stop_price)

        group = self.limits.correlation_groups.get(signal.symbol)
        if group and self.limits.max_correlation_group_risk is not None:
            group_budget = account.equity * self.limits.max_correlation_group_risk
            current_group_risk = float((open_group_risk or {}).get(group, 0.0))
            if current_group_risk + target_risk > group_budget:
                return self._blocked(
                    signal,
                    "correlation_group_risk_budget_exhausted",
                    entry_price=entry,
                    stop_price=stop_price,
                )

        raw_quantity = target_risk / stop_distance
        raw_notional = raw_quantity * entry
        max_notional = account.equity * self._effective_notional_cap_multiplier(signal.symbol)
        notional = min(raw_notional, max_notional)
        quantity = notional / entry
        risk_amount = quantity * stop_distance

        if quantity <= 0:
            return self._blocked(signal, "zero_quantity", entry_price=entry, stop_price=stop_price)

        return RiskDecision(
            allowed=True,
            reason="allowed",
            signal=signal,
            quantity=quantity,
            notional=notional,
            risk_amount=risk_amount,
            entry_price=entry,
            stop_price=stop_price,
            max_loss_per_unit=stop_distance,
            applied_size_multiplier=multiplier,
        )

    @staticmethod
    def _blocked(
        signal: Signal,
        reason: str,
        *,
        entry_price: float,
        stop_price: float | None = None,
    ) -> RiskDecision:
        return RiskDecision(
            allowed=False,
            reason=reason,
            signal=signal,
            entry_price=float(entry_price),
            stop_price=stop_price,
        )

    def _effective_notional_cap_multiplier(self, symbol: str) -> float:
        market = self.markets_by_symbol.get(symbol)
        if market is not None and not market.supports_leverage:
            return min(self.limits.max_position_fraction, 1.0)
        if symbol in self.markets_by_symbol:
            return self.limits.max_position_fraction * self.limits.max_leverage
        return min(self.limits.max_position_fraction, self.limits.max_leverage)
