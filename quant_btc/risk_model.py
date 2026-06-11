"""BTC compatibility risk helpers."""

from __future__ import annotations

from dataclasses import dataclass, replace

from quant_platform.risk import AccountState, RiskDecision, RiskEngine, RiskLimits
from quant_platform.signals import Signal


@dataclass(frozen=True)
class BtcLegacyRiskAudit:
    """Serializable parity snapshot for a legacy entry and platform RiskEngine decision."""

    legacy_decision: RiskDecision
    engine_decision: RiskDecision
    enforcement_enabled: bool = False
    bar_index: int | None = None
    tolerance: float = 1e-9

    @property
    def allowed_match(self) -> bool:
        return self.legacy_decision.allowed == self.engine_decision.allowed

    @property
    def quantity_delta(self) -> float:
        return self.engine_decision.quantity - self.legacy_decision.quantity

    @property
    def notional_delta(self) -> float:
        return self.engine_decision.notional - self.legacy_decision.notional

    @property
    def risk_amount_delta(self) -> float:
        return self.engine_decision.risk_amount - self.legacy_decision.risk_amount

    @property
    def entry_price_delta(self) -> float:
        return self.engine_decision.entry_price - self.legacy_decision.entry_price

    @property
    def stop_price_delta(self) -> float | None:
        if self.engine_decision.stop_price is None or self.legacy_decision.stop_price is None:
            return None
        return self.engine_decision.stop_price - self.legacy_decision.stop_price

    @property
    def quantity_match(self) -> bool:
        return abs(self.quantity_delta) <= self.tolerance

    @property
    def notional_match(self) -> bool:
        return abs(self.notional_delta) <= self.tolerance

    @property
    def risk_amount_match(self) -> bool:
        return abs(self.risk_amount_delta) <= self.tolerance

    @property
    def parity_status(self) -> str:
        if self.legacy_decision.allowed and not self.engine_decision.allowed:
            return "engine_blocked"
        if not self.legacy_decision.allowed and self.engine_decision.allowed:
            return "engine_allowed"
        if not self.legacy_decision.allowed and not self.engine_decision.allowed:
            return "both_blocked"
        if self.quantity_match and self.notional_match and self.risk_amount_match:
            return "matched"
        return "sizing_mismatch"

    @property
    def would_block(self) -> bool:
        return self.enforcement_enabled and not self.engine_decision.allowed

    @property
    def would_block_if_enforced(self) -> bool:
        return not self.engine_decision.allowed

    def to_dict(self) -> dict[str, object]:
        signal = self.legacy_decision.signal
        return {
            "bar_index": self.bar_index,
            "module": signal.module,
            "symbol": signal.symbol,
            "direction": signal.direction.value,
            "parity_status": self.parity_status,
            "enforcement_enabled": self.enforcement_enabled,
            "would_block": self.would_block,
            "would_block_if_enforced": self.would_block_if_enforced,
            "allowed_match": self.allowed_match,
            "quantity_match": self.quantity_match,
            "notional_match": self.notional_match,
            "risk_amount_match": self.risk_amount_match,
            "legacy_allowed": self.legacy_decision.allowed,
            "engine_allowed": self.engine_decision.allowed,
            "legacy_reason": self.legacy_decision.reason,
            "engine_reason": self.engine_decision.reason,
            "legacy_quantity": self.legacy_decision.quantity,
            "engine_quantity": self.engine_decision.quantity,
            "quantity_delta": self.quantity_delta,
            "legacy_notional": self.legacy_decision.notional,
            "engine_notional": self.engine_decision.notional,
            "notional_delta": self.notional_delta,
            "legacy_risk_amount": self.legacy_decision.risk_amount,
            "engine_risk_amount": self.engine_decision.risk_amount,
            "risk_amount_delta": self.risk_amount_delta,
            "legacy_entry_price": self.legacy_decision.entry_price,
            "engine_entry_price": self.engine_decision.entry_price,
            "entry_price_delta": self.entry_price_delta,
            "legacy_stop_price": self.legacy_decision.stop_price,
            "engine_stop_price": self.engine_decision.stop_price,
            "stop_price_delta": self.stop_price_delta,
        }


def build_btc_legacy_entry_risk_audit(
    *,
    legacy_decision: RiskDecision,
    engine_decision: RiskDecision,
    enforcement_enabled: bool = False,
    bar_index: int | None = None,
) -> BtcLegacyRiskAudit:
    """Build a serializable parity snapshot before platform enforcement is enabled."""
    return BtcLegacyRiskAudit(
        legacy_decision=legacy_decision,
        engine_decision=engine_decision,
        enforcement_enabled=enforcement_enabled,
        bar_index=bar_index,
    )


def btc_dual_layer_regime_size_multiplier(
    *,
    regime: int,
    daily_ema_dir: float,
    weekly_ema_dir: float,
) -> float:
    """Return legacy dual-layer regime size adjustment."""
    weak_bull = regime != 1 and daily_ema_dir >= 0 and weekly_ema_dir >= 0
    if weak_bull and regime not in (0, 2, 4):
        return 0.5
    return 1.0


def calculate_btc_base_position_size(
    *,
    entry: float,
    stop: float,
    risk_per_trade: float,
    consecutive_losses: int,
    daily_ema_dir: float,
    weekly_ema_dir: float,
    risk_cfg,
) -> float:
    """Calculate legacy BTC single-module position fraction from stop distance."""
    if entry <= 0:
        return 0.0
    stop_pct = abs(entry - stop) / entry
    if stop_pct < 0.0001:
        return 0.0
    size = min(risk_per_trade / stop_pct, risk_cfg.max_position_frac)
    if consecutive_losses >= risk_cfg.consecutive_loss_limit:
        size *= risk_cfg.reduced_size_mult
    if daily_ema_dir * weekly_ema_dir < 0:
        size *= 0.5
    if stop > entry:
        size *= risk_cfg.risk_bear_short_mult
    return min(size, 0.99)


def btc_tactical_module_risk(module: str, is_long: bool, risk_cfg) -> float:
    """Return BTC compatibility risk percentage for a tactical signal module."""
    tag = f"{module}_long" if is_long else f"{module}_short"
    return {
        "breakout_retest_long": risk_cfg.risk_breakout,
        "breakout_retest_short": risk_cfg.risk_breakout,
        "crash_short": risk_cfg.risk_breakout,
        "pullback_struct_long": risk_cfg.risk_pullback,
        "pullback_struct_short": risk_cfg.risk_pullback,
        "failed_bounce_short": risk_cfg.risk_pullback,
        "bull_trap_short": risk_cfg.risk_pullback,
        "meanrev_range_long": risk_cfg.risk_meanrev,
        "meanrev_range_short": risk_cfg.risk_meanrev,
        "sweep_reversal_long": risk_cfg.risk_meanrev,
        "sweep_reversal_short": risk_cfg.risk_meanrev,
    }.get(tag, risk_cfg.risk_per_trade)


def calculate_btc_tactical_position_size(
    *,
    module: str,
    is_long: bool,
    entry: float,
    stop: float,
    risk_cfg,
) -> float:
    """Calculate legacy BTC tactical position fraction from module risk and stop distance."""
    if entry <= 0:
        return 0.0
    stop_pct = abs(entry - stop) / entry
    if stop_pct <= 0:
        return 0.0
    size = btc_tactical_module_risk(module, is_long, risk_cfg) / stop_pct
    size = min(size, 0.99)
    if not is_long:
        size *= risk_cfg.risk_bear_short_mult
    return size


def build_btc_legacy_entry_risk_decision(
    *,
    signal: Signal,
    equity: float,
    entry_price: float,
    size_fraction: float,
    stop_price: float | None = None,
    target_price: float | None = None,
    reason: str = "legacy_compat_audit",
) -> RiskDecision:
    """Represent a legacy BTC fractional entry as a platform risk decision for audit."""
    entry = float(entry_price)
    size = abs(float(size_fraction))
    account_equity = float(equity)
    enriched_signal = replace(
        signal,
        preferred_stop=stop_price if stop_price is not None else signal.preferred_stop,
        preferred_target=target_price if target_price is not None else signal.preferred_target,
    )
    if account_equity <= 0 or entry <= 0 or size <= 0:
        return RiskDecision(
            allowed=False,
            reason="invalid_legacy_entry_audit",
            signal=enriched_signal,
            entry_price=entry,
            stop_price=stop_price,
        )

    notional = account_equity * size
    quantity = notional / entry
    max_loss_per_unit = abs(entry - float(stop_price)) if stop_price is not None else 0.0
    return RiskDecision(
        allowed=True,
        reason=reason,
        signal=enriched_signal,
        quantity=quantity,
        notional=notional,
        risk_amount=quantity * max_loss_per_unit,
        entry_price=entry,
        stop_price=stop_price,
        max_loss_per_unit=max_loss_per_unit,
    )


def build_btc_legacy_entry_risk_engine_decision(
    *,
    signal: Signal,
    equity: float,
    entry_price: float,
    size_fraction: float,
    stop_price: float | None = None,
    target_price: float | None = None,
    risk_engine: RiskEngine | None = None,
) -> RiskDecision:
    """Run a legacy BTC fractional entry through the generic RiskEngine for audit."""
    legacy_decision = build_btc_legacy_entry_risk_decision(
        signal=signal,
        equity=equity,
        entry_price=entry_price,
        size_fraction=size_fraction,
        stop_price=stop_price,
        target_price=target_price,
    )
    account_equity = float(equity)
    risk_fraction = legacy_decision.risk_amount / account_equity if account_equity > 0 else 0.0
    notional_fraction = legacy_decision.notional / account_equity if account_equity > 0 else 0.0
    max_position_fraction = max(abs(float(size_fraction)), notional_fraction, 0.0)
    default_limits = RiskLimits()
    limits = RiskLimits(
        risk_per_trade=risk_fraction,
        max_position_fraction=max_position_fraction,
        max_leverage=1.0,
        portfolio_risk_budget=max(risk_fraction, default_limits.portfolio_risk_budget),
    )
    engine = risk_engine or RiskEngine(limits)
    return engine.evaluate(
        legacy_decision.signal,
        AccountState(equity=account_equity),
        entry_price=float(entry_price),
    )
