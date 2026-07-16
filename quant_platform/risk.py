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
    enforce_initial_margin: bool = False
    portfolio_risk_budget: float = 0.06
    max_symbol_risk: float | None = None
    max_module_risk: float | None = None
    max_correlation_group_risk: float | None = None
    max_exchange_risk: float | None = None
    max_market_type_risk: float | None = None
    module_risk_multipliers: dict[str, float] = field(default_factory=dict)
    correlation_groups: dict[str, str] = field(default_factory=dict)
    max_drawdown_pct: float | None = None
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


@dataclass(frozen=True)
class RiskBudgetUsage:
    """Current usage for one risk budget bucket."""

    used: float
    budget: float | None = None

    @property
    def remaining(self) -> float | None:
        if self.budget is None:
            return None
        return self.budget - self.used

    @property
    def utilization(self) -> float | None:
        if self.budget is None or self.budget <= 0:
            return None
        return self.used / self.budget

    def to_dict(self) -> dict[str, float | None]:
        return {
            "used": self.used,
            "budget": self.budget,
            "remaining": self.remaining,
            "utilization": self.utilization,
        }


@dataclass(frozen=True)
class RiskBudgetDiagnostics:
    """Portfolio-level view of risk budget usage."""

    portfolio: RiskBudgetUsage
    symbols: dict[str, RiskBudgetUsage]
    modules: dict[str, RiskBudgetUsage]
    correlation_groups: dict[str, RiskBudgetUsage]
    target_risk_amount: float
    consecutive_losses: int
    paused: bool
    pause_until_bar: int
    applied_size_multiplier: float
    drawdown: dict[str, float | bool | None]
    exchanges: dict[str, RiskBudgetUsage] = field(default_factory=dict)
    market_types: dict[str, RiskBudgetUsage] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "portfolio": self.portfolio.to_dict(),
            "symbols": {key: usage.to_dict() for key, usage in self.symbols.items()},
            "modules": {key: usage.to_dict() for key, usage in self.modules.items()},
            "correlation_groups": {
                key: usage.to_dict() for key, usage in self.correlation_groups.items()
            },
            "exchanges": {key: usage.to_dict() for key, usage in self.exchanges.items()},
            "market_types": {key: usage.to_dict() for key, usage in self.market_types.items()},
            "target_risk_amount": self.target_risk_amount,
            "consecutive_losses": self.consecutive_losses,
            "paused": self.paused,
            "pause_until_bar": self.pause_until_bar,
            "applied_size_multiplier": self.applied_size_multiplier,
            "drawdown": self.drawdown,
        }


@dataclass
class RiskState:
    """Mutable rolling state for loss streak and pause handling."""

    consecutive_losses: int = 0
    pause_until_bar: int = -1
    realized_pnl: list[float] = field(default_factory=list)
    equity_peak: float | None = None

    def observe_equity(self, equity: float) -> None:
        equity = float(equity)
        if equity <= 0:
            return
        if self.equity_peak is None or equity > self.equity_peak:
            self.equity_peak = equity

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
        open_notional: float = 0.0,
        open_symbol_risk: dict[str, float] | None = None,
        open_module_risk: dict[str, float] | None = None,
        open_group_risk: dict[str, float] | None = None,
        open_exchange_risk: dict[str, float] | None = None,
        open_market_type_risk: dict[str, float] | None = None,
    ) -> RiskDecision:
        if signal.direction == Direction.FLAT:
            return self._blocked(signal, "flat_signal", entry_price=entry_price)
        if signal.preferred_stop is None:
            return self._blocked(signal, "missing_stop", entry_price=entry_price)
        if account.equity <= 0:
            return self._blocked(signal, "non_positive_equity", entry_price=entry_price)
        self.state.observe_equity(account.equity)
        if account.daily_drawdown_pct >= self.limits.daily_drawdown_limit:
            return self._blocked(signal, "daily_drawdown_limit", entry_price=entry_price)
        if account.weekly_drawdown_pct >= self.limits.weekly_drawdown_limit:
            return self._blocked(signal, "weekly_drawdown_limit", entry_price=entry_price)
        if self._max_drawdown_breached(account):
            return self._blocked(signal, "max_drawdown_limit", entry_price=entry_price)
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
        module_multiplier = float(self.limits.module_risk_multipliers.get(signal.module, 1.0))
        target_risk = account.equity * self.limits.risk_per_trade * multiplier * module_multiplier
        contract_multiplier = self._contract_multiplier(signal.symbol)
        max_loss_per_unit = stop_distance * contract_multiplier
        raw_quantity = target_risk / max_loss_per_unit
        raw_notional = raw_quantity * entry * contract_multiplier
        max_notional = account.equity * self._effective_notional_cap_multiplier(signal.symbol)
        if self.limits.enforce_initial_margin:
            portfolio_notional_cap = account.equity * self._effective_portfolio_notional_cap_multiplier(
                signal.symbol
            )
            available_notional = max(0.0, portfolio_notional_cap - float(open_notional))
        else:
            available_notional = float("inf")
        notional = min(raw_notional, max_notional, available_notional)
        quantity = notional / (entry * contract_multiplier)
        risk_amount = quantity * max_loss_per_unit

        if quantity <= 0:
            reason = "initial_margin_exhausted" if available_notional <= 0 else "zero_quantity"
            return self._blocked(signal, reason, entry_price=entry, stop_price=stop_price)

        portfolio_budget = account.equity * self.limits.portfolio_risk_budget
        if open_risk + risk_amount > portfolio_budget:
            return self._blocked(signal, "portfolio_risk_budget_exhausted", entry_price=entry, stop_price=stop_price)

        if self.limits.max_symbol_risk is not None:
            symbol_budget = account.equity * self.limits.max_symbol_risk
            current_symbol_risk = float((open_symbol_risk or {}).get(signal.symbol, 0.0))
            if current_symbol_risk + risk_amount > symbol_budget:
                return self._blocked(signal, "symbol_risk_budget_exhausted", entry_price=entry, stop_price=stop_price)

        if self.limits.max_module_risk is not None:
            module_budget = account.equity * self.limits.max_module_risk
            current_module_risk = float((open_module_risk or {}).get(signal.module, 0.0))
            if current_module_risk + risk_amount > module_budget:
                return self._blocked(signal, "module_risk_budget_exhausted", entry_price=entry, stop_price=stop_price)

        group = self.correlation_group_for_symbol(signal.symbol)
        if group and self.limits.max_correlation_group_risk is not None:
            group_budget = account.equity * self.limits.max_correlation_group_risk
            current_group_risk = float((open_group_risk or {}).get(group, 0.0))
            if current_group_risk + risk_amount > group_budget:
                return self._blocked(
                    signal,
                    "correlation_group_risk_budget_exhausted",
                    entry_price=entry,
                    stop_price=stop_price,
                )

        exchange = market.exchange if market is not None else None
        if exchange and self.limits.max_exchange_risk is not None:
            exchange_budget = account.equity * self.limits.max_exchange_risk
            current_exchange_risk = float((open_exchange_risk or {}).get(exchange, 0.0))
            if current_exchange_risk + risk_amount > exchange_budget:
                return self._blocked(
                    signal,
                    "exchange_risk_budget_exhausted",
                    entry_price=entry,
                    stop_price=stop_price,
                )

        market_type = market.market_type if market is not None else None
        if market_type and self.limits.max_market_type_risk is not None:
            market_type_budget = account.equity * self.limits.max_market_type_risk
            current_market_type_risk = float((open_market_type_risk or {}).get(market_type, 0.0))
            if current_market_type_risk + risk_amount > market_type_budget:
                return self._blocked(
                    signal,
                    "market_type_risk_budget_exhausted",
                    entry_price=entry,
                    stop_price=stop_price,
                )

        return RiskDecision(
            allowed=True,
            reason="allowed",
            signal=signal,
            quantity=quantity,
            notional=notional,
            risk_amount=risk_amount,
            entry_price=entry,
            stop_price=stop_price,
            max_loss_per_unit=max_loss_per_unit,
            applied_size_multiplier=multiplier,
        )

    def budget_diagnostics(
        self,
        account: AccountState,
        *,
        bar_index: int = 0,
        open_risk: float = 0.0,
        open_symbol_risk: dict[str, float] | None = None,
        open_module_risk: dict[str, float] | None = None,
        open_group_risk: dict[str, float] | None = None,
        open_exchange_risk: dict[str, float] | None = None,
        open_market_type_risk: dict[str, float] | None = None,
    ) -> RiskBudgetDiagnostics:
        multiplier = self.state.size_multiplier(self.limits)
        return RiskBudgetDiagnostics(
            portfolio=RiskBudgetUsage(
                used=float(open_risk),
                budget=account.equity * self.limits.portfolio_risk_budget,
            ),
            symbols=self._usage_by_key(open_symbol_risk or {}, self.limits.max_symbol_risk, account),
            modules=self._usage_by_key(open_module_risk or {}, self.limits.max_module_risk, account),
            correlation_groups=self._usage_by_key(
                open_group_risk or {},
                self.limits.max_correlation_group_risk,
                account,
            ),
            exchanges=self._usage_by_key(open_exchange_risk or {}, self.limits.max_exchange_risk, account),
            market_types=self._usage_by_key(open_market_type_risk or {}, self.limits.max_market_type_risk, account),
            target_risk_amount=account.equity * self.limits.risk_per_trade * multiplier,
            consecutive_losses=self.state.consecutive_losses,
            paused=self.state.is_paused(bar_index),
            pause_until_bar=self.state.pause_until_bar,
            applied_size_multiplier=multiplier,
            drawdown=self._drawdown_diagnostics(account),
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
            market_leverage = (
                market.max_leverage
                if market is not None and market.max_leverage is not None
                else self.limits.max_leverage
            )
            return self.limits.max_position_fraction * min(self.limits.max_leverage, market_leverage)
        return min(self.limits.max_position_fraction, self.limits.max_leverage)

    def _effective_portfolio_notional_cap_multiplier(self, symbol: str) -> float:
        market = self.markets_by_symbol.get(symbol)
        if market is not None and not market.supports_leverage:
            return 1.0
        market_leverage = (
            market.max_leverage
            if market is not None and market.max_leverage is not None
            else self.limits.max_leverage
        )
        return min(self.limits.max_leverage, market_leverage)

    def _contract_multiplier(self, symbol: str) -> float:
        market = self.markets_by_symbol.get(symbol)
        if market is None or market.contract_multiplier <= 0:
            return 1.0
        return market.contract_multiplier

    def correlation_group_for_symbol(self, symbol: str) -> str | None:
        if symbol in self.limits.correlation_groups:
            return self.limits.correlation_groups[symbol]
        market = self.markets_by_symbol.get(symbol)
        return market.correlation_group if market is not None else None

    def _max_drawdown_breached(self, account: AccountState) -> bool:
        limit = self.limits.max_drawdown_pct
        if limit is None:
            return False
        drawdown = self._current_drawdown_pct(account)
        return drawdown is not None and drawdown >= limit

    def _current_drawdown_pct(self, account: AccountState) -> float | None:
        peak = self.state.equity_peak
        if peak is None:
            return None
        peak = float(peak)
        if peak <= 0:
            return None
        return max(0.0, (peak - float(account.equity)) / peak)

    def _drawdown_diagnostics(self, account: AccountState) -> dict[str, float | bool | None]:
        current = self._current_drawdown_pct(account)
        limit = self.limits.max_drawdown_pct
        return {
            "equityPeak": self.state.equity_peak,
            "currentPct": current,
            "limitPct": limit,
            "breached": bool(limit is not None and current is not None and current >= limit),
        }

    @staticmethod
    def _usage_by_key(
        usage_by_key: dict[str, float],
        budget_fraction: float | None,
        account: AccountState,
    ) -> dict[str, RiskBudgetUsage]:
        budget = account.equity * budget_fraction if budget_fraction is not None else None
        return {
            key: RiskBudgetUsage(used=float(usage_by_key[key]), budget=budget)
            for key in sorted(usage_by_key)
        }
