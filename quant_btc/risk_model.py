"""BTC compatibility risk helpers."""

from __future__ import annotations


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
