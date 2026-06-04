"""BTC compatibility portfolio-layer helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BtcTacticalEntryPlan:
    should_enter: bool
    is_long: bool
    direction: int
    module: str
    order_tag: str
    entry_price: float
    stop_price: float
    target_price: float
    size: float
    entry_bar: int
    extreme: float
    tp1_done: bool
    tp2_done: bool
    short_reached_1r: bool
    short_peak_r: float
    short_giveback_peak_r: float
    last_trade_bar: int


@dataclass(frozen=True)
class BtcFlashCrashDipBuyPlan:
    should_enter: bool
    is_long: bool
    direction: int
    module: str
    order_tag: str
    entry_price: float
    stop_price: float
    target_price: float
    size: float
    entry_bar: int
    last_trade_bar: int


@dataclass(frozen=True)
class BtcCoreEntryPlan:
    should_enter: bool
    is_long: bool
    order_tag: str
    core_active: bool
    entry_price: float
    highest_close: float
    core_size: float
    days_below_dema: int
    equity_snapshot: float
    last_trade_bar: int


@dataclass(frozen=True)
class BtcCoreExitPlan:
    should_exit: bool
    layer_size: float
    core_active: bool
    core_size: float


@dataclass(frozen=True)
class BtcCoreAddStatePlan:
    should_update: bool
    core_size: float
    core_fully_loaded: bool


@dataclass(frozen=True)
class BtcExternalCloseCleanupPlan:
    should_record_trade: bool
    core_active: bool
    core_size: float
    tactical_direction: int
    tactical_size: float


@dataclass(frozen=True)
class BtcTacticalExitClosePlan:
    action: str
    portion: float


@dataclass(frozen=True)
class BtcTacticalExitCleanupPlan:
    should_cleanup: bool
    tactical_direction: int
    tactical_size: float


@dataclass(frozen=True)
class BtcShortPartialTpPlan:
    should_take_profit: bool
    tp1_done: bool
    tp2_done: bool
    portion: float


@dataclass(frozen=True)
class BtcBaseEntryPlan:
    is_long: bool
    entry_price: float
    stop_price: float
    target_price: float | None
    size: float
    initial_risk: float
    trailing_stop: float
    extreme_since_entry: float
    entry_atr: float
    entry_bar: int
    last_trade_bar: int
    partial_done: bool


@dataclass(frozen=True)
class BtcBearCoreTrendExitPlan:
    should_exit: bool
    layer_size: float
    bear_core_active: bool
    bear_core_size: float
    tactical_size: float
    days_above_dema: int


@dataclass(frozen=True)
class BtcBearCoreGivebackExitPlan:
    should_exit: bool
    layer_size: float
    bear_core_active: bool
    bear_core_size: float


@dataclass(frozen=True)
class BtcBearCoreVReversalExitPlan:
    should_exit: bool
    layer_size: float
    bear_core_active: bool
    bear_core_size: float
    waterfall_triggered: bool
    days_above_dema: int


@dataclass(frozen=True)
class BtcBearCoreWaterfallRunnerExitPlan:
    should_exit: bool
    layer_size: float
    bear_core_active: bool
    bear_core_size: float
    tactical_size: float
    waterfall_triggered: bool
    days_above_dema: int


@dataclass(frozen=True)
class BtcBearCoreProbeEntryStatePlan:
    should_enter: bool
    bear_core_active: bool
    bear_core_stage: int
    bear_core_entry_price: float
    bear_core_entry_bar: int
    bear_probe_peak_r: float
    short_giveback_peak_r: float
    bear_core_size: float
    bear_group_id: int
    bear_group_exposure: float
    bear_group_entry_bar: int
    bear_group_peak_r: float
    days_above_dema: int
    equity_snapshot: float
    last_trade_bar: int


@dataclass(frozen=True)
class BtcBearCoreConfirmAddStatePlan:
    should_update: bool
    bear_core_size: float
    bear_group_exposure: float
    bear_core_stage: int
    last_trade_bar: int


@dataclass(frozen=True)
class BtcBearCoreAccelerationAddStatePlan:
    should_update: bool
    bear_core_size: float
    bear_group_exposure: float
    bear_core_stage: int


def btc_external_close_cleanup_plan(
    *,
    has_position: bool,
    core_active: bool,
    core_size: float,
    tactical_direction: int,
    tactical_size: float,
) -> BtcExternalCloseCleanupPlan:
    """Plan legacy state cleanup after an external full close is observed."""
    if has_position or (not core_active and tactical_direction == 0):
        return BtcExternalCloseCleanupPlan(
            should_record_trade=False,
            core_active=core_active,
            core_size=core_size,
            tactical_direction=tactical_direction,
            tactical_size=tactical_size,
        )

    return BtcExternalCloseCleanupPlan(
        should_record_trade=True,
        core_active=False,
        core_size=0.0,
        tactical_direction=0,
        tactical_size=0.0,
    )


def btc_core_exit_plan(
    *,
    core_active: bool,
    exit_signal: bool,
    core_size: float,
) -> BtcCoreExitPlan:
    """Plan legacy core layer exit cleanup without applying closes."""
    if not core_active or not exit_signal:
        return BtcCoreExitPlan(
            should_exit=False,
            layer_size=0.0,
            core_active=core_active,
            core_size=core_size,
        )

    return BtcCoreExitPlan(
        should_exit=True,
        layer_size=core_size,
        core_active=False,
        core_size=0.0,
    )


def btc_tactical_exit_cleanup_plan(
    *,
    should_exit: bool,
    tactical_direction: int,
    tactical_size: float,
) -> BtcTacticalExitCleanupPlan:
    """Plan legacy tactical state cleanup after a tactical exit is executed."""
    if not should_exit:
        return BtcTacticalExitCleanupPlan(
            should_cleanup=False,
            tactical_direction=tactical_direction,
            tactical_size=tactical_size,
        )

    return BtcTacticalExitCleanupPlan(
        should_cleanup=True,
        tactical_direction=0,
        tactical_size=0.0,
    )


def btc_base_entry_plan(
    *,
    is_long: bool,
    entry_price: float,
    stop_price: float,
    target_price: float | None,
    size: float,
    use_fixed_tp: bool,
    min_reward_risk: float,
    min_size: float,
    entry_atr: float,
    entry_bar: int,
) -> BtcBaseEntryPlan | None:
    """Validate legacy base entry guards and build the state transition plan."""
    risk = abs(entry_price - stop_price)
    if risk <= 0:
        return None

    if use_fixed_tp:
        if target_price is None:
            return None
        reward = abs(target_price - entry_price)
        if reward <= 0 or reward / risk < min_reward_risk:
            return None

    if size < min_size:
        return None

    return BtcBaseEntryPlan(
        is_long=is_long,
        entry_price=entry_price,
        stop_price=stop_price,
        target_price=target_price,
        size=size,
        initial_risk=risk,
        trailing_stop=stop_price,
        extreme_since_entry=entry_price,
        entry_atr=entry_atr,
        entry_bar=entry_bar,
        last_trade_bar=entry_bar,
        partial_done=False,
    )


def btc_bear_core_waterfall_runner_exit_plan(
    *,
    bear_core_active: bool,
    runner_exit: bool,
    bear_core_size: float,
    tactical_size: float,
    waterfall_triggered: bool,
    days_above_dema: int,
) -> BtcBearCoreWaterfallRunnerExitPlan:
    """Plan legacy waterfall runner exit cleanup without applying closes."""
    if not bear_core_active or not runner_exit:
        return BtcBearCoreWaterfallRunnerExitPlan(
            should_exit=False,
            layer_size=0.0,
            bear_core_active=bear_core_active,
            bear_core_size=bear_core_size,
            tactical_size=tactical_size,
            waterfall_triggered=waterfall_triggered,
            days_above_dema=days_above_dema,
        )

    return BtcBearCoreWaterfallRunnerExitPlan(
        should_exit=True,
        layer_size=bear_core_size,
        bear_core_active=False,
        bear_core_size=0.0,
        tactical_size=0.0,
        waterfall_triggered=False,
        days_above_dema=0,
    )


def btc_bear_core_v_reversal_exit_plan(
    *,
    bear_core_active: bool,
    v_reversal_exit: bool,
    bear_core_size: float,
    waterfall_triggered: bool,
    days_above_dema: int,
) -> BtcBearCoreVReversalExitPlan:
    """Plan legacy bear-core V-reversal exit cleanup without applying closes."""
    if not bear_core_active or not v_reversal_exit:
        return BtcBearCoreVReversalExitPlan(
            should_exit=False,
            layer_size=0.0,
            bear_core_active=bear_core_active,
            bear_core_size=bear_core_size,
            waterfall_triggered=waterfall_triggered,
            days_above_dema=days_above_dema,
        )

    return BtcBearCoreVReversalExitPlan(
        should_exit=True,
        layer_size=bear_core_size,
        bear_core_active=False,
        bear_core_size=0.0,
        waterfall_triggered=False,
        days_above_dema=0,
    )


def btc_bear_core_giveback_exit_plan(
    *,
    bear_core_active: bool,
    giveback_exit: bool,
    bear_core_size: float,
) -> BtcBearCoreGivebackExitPlan:
    """Plan legacy bear-core giveback exit cleanup without applying closes."""
    if not bear_core_active or not giveback_exit:
        return BtcBearCoreGivebackExitPlan(
            should_exit=False,
            layer_size=0.0,
            bear_core_active=bear_core_active,
            bear_core_size=bear_core_size,
        )

    return BtcBearCoreGivebackExitPlan(
        should_exit=True,
        layer_size=bear_core_size,
        bear_core_active=False,
        bear_core_size=0.0,
    )


def btc_bear_core_trend_exit_plan(
    *,
    bear_core_active: bool,
    exit_signal: bool,
    bear_core_size: float,
    tactical_size: float,
    days_above_dema: int,
) -> BtcBearCoreTrendExitPlan:
    """Plan legacy bear-core trend exit state cleanup without applying closes."""
    if not bear_core_active or not exit_signal:
        return BtcBearCoreTrendExitPlan(
            should_exit=False,
            layer_size=0.0,
            bear_core_active=bear_core_active,
            bear_core_size=bear_core_size,
            tactical_size=tactical_size,
            days_above_dema=days_above_dema,
        )

    return BtcBearCoreTrendExitPlan(
        should_exit=True,
        layer_size=bear_core_size,
        bear_core_active=False,
        bear_core_size=0.0,
        tactical_size=0.0,
        days_above_dema=0,
    )


def btc_flash_crash_dip_buy_plan(
    *,
    flash_crash_active: bool,
    core_active: bool,
    tactical_direction: int,
    entry_price: float,
    bar_index: int,
) -> BtcFlashCrashDipBuyPlan:
    """Plan legacy flash-crash tactical dip-buy state without applying orders."""
    should_enter = flash_crash_active and core_active and tactical_direction == 0
    if not should_enter:
        return BtcFlashCrashDipBuyPlan(
            should_enter=False,
            is_long=True,
            direction=0,
            module="",
            order_tag="",
            entry_price=entry_price,
            stop_price=0.0,
            target_price=0.0,
            size=0.0,
            entry_bar=bar_index,
            last_trade_bar=bar_index,
        )

    return BtcFlashCrashDipBuyPlan(
        should_enter=True,
        is_long=True,
        direction=1,
        module="dip_buy",
        order_tag="dip_buy_long",
        entry_price=entry_price,
        stop_price=entry_price * 0.92,
        target_price=entry_price * 1.08,
        size=0.10,
        entry_bar=bar_index,
        last_trade_bar=bar_index,
    )


def btc_core_entry_plan(
    *,
    core_active: bool,
    entry_signal: bool,
    entry_price: float,
    core_size: float,
    equity: float,
    bar_index: int,
) -> BtcCoreEntryPlan:
    """Plan legacy core-long entry state without applying the order."""
    if core_active or not entry_signal:
        return BtcCoreEntryPlan(
            should_enter=False,
            is_long=True,
            order_tag="",
            core_active=core_active,
            entry_price=entry_price,
            highest_close=entry_price,
            core_size=core_size if core_active else 0.0,
            days_below_dema=0,
            equity_snapshot=equity,
            last_trade_bar=-10**9,
        )

    return BtcCoreEntryPlan(
        should_enter=True,
        is_long=True,
        order_tag="core_long",
        core_active=True,
        entry_price=entry_price,
        highest_close=entry_price,
        core_size=core_size,
        days_below_dema=0,
        equity_snapshot=equity,
        last_trade_bar=bar_index,
    )


def btc_base_entry_direction(
    *,
    regime: int,
    daily_ema_dir: float,
    weekly_ema_dir: float,
    allow_long: bool,
    allow_short: bool,
    long_score: float,
    short_score: float,
    score_threshold: float,
) -> bool | None:
    """Resolve legacy base strategy entry direction without planning orders."""
    if regime == 4:
        return None

    long_signal = allow_long and long_score >= score_threshold
    short_signal = allow_short and short_score >= score_threshold
    if not long_signal and not short_signal:
        return None

    if long_signal and short_signal:
        if daily_ema_dir > 0 and weekly_ema_dir >= 0:
            return True
        if daily_ema_dir < 0 and weekly_ema_dir <= 0:
            return False
        return None

    return True if long_signal else False


def btc_base_partial_tp(
    *,
    enabled: bool,
    partial_done: bool,
    is_long: bool,
    entry_price: float,
    initial_risk: float,
    close: float,
    partial_tp_r: float,
) -> bool:
    """Evaluate legacy base partial take-profit trigger."""
    if not enabled or partial_done:
        return False
    if initial_risk <= 0:
        return False
    r_multiple = (close - entry_price) / initial_risk if is_long else (entry_price - close) / initial_risk
    return r_multiple >= partial_tp_r


def btc_base_time_stop(
    *,
    enabled: bool,
    is_long: bool,
    bars_held: int,
    time_stop_bars: int,
    entry_price: float,
    initial_risk: float,
    close: float,
    min_profit_r: float,
) -> bool:
    """Evaluate legacy base time-stop trigger."""
    if not enabled:
        return False
    if bars_held < time_stop_bars:
        return False
    if initial_risk <= 0:
        return False
    r_multiple = (close - entry_price) / initial_risk if is_long else (entry_price - close) / initial_risk
    return r_multiple < min_profit_r


def btc_base_invalidation(
    *,
    is_long: bool,
    bars_held: int,
    max_bars_no_profit: int,
    close: float,
    entry_price: float,
    entry_atr: float,
    current_atr: float,
    volatility_spike_atr_mult: float,
    daily_ema_dir: float,
    weekly_ema_dir: float,
) -> bool:
    """Evaluate legacy base invalidation exits without applying the close."""
    if bars_held >= max_bars_no_profit:
        unreal = (close - entry_price) * (1 if is_long else -1)
        if unreal <= 0:
            return True

    if entry_atr > 0 and current_atr > volatility_spike_atr_mult * entry_atr:
        return True

    if is_long and daily_ema_dir < 0 and weekly_ema_dir < 0:
        return True
    if not is_long and daily_ema_dir > 0 and weekly_ema_dir > 0:
        return True
    return False


def btc_base_trailing_stop_update(
    *,
    is_long: bool,
    close: float,
    high: float,
    low: float,
    atr: float,
    entry_price: float,
    initial_risk: float,
    previous_extreme: float,
    trailing_stop: float,
    breakout_mode: bool,
    effective_breakeven_r: float,
    risk_cfg,
) -> tuple[float, float]:
    """Update legacy base trailing-stop state without applying an exit."""
    if is_long:
        new_extreme = max(previous_extreme, high)
        unreal_r = (close - entry_price) / initial_risk if initial_risk > 0 else 0
    else:
        new_extreme = min(previous_extreme, low)
        unreal_r = (entry_price - close) / initial_risk if initial_risk > 0 else 0

    new_stop = trailing_stop
    if unreal_r >= effective_breakeven_r:
        if is_long and new_stop < entry_price:
            new_stop = entry_price
        elif not is_long and new_stop > entry_price:
            new_stop = entry_price

    if unreal_r >= risk_cfg.trailing_activate_r:
        trail_mult = risk_cfg.breakout_trail_mult if breakout_mode else risk_cfg.trailing_distance_atr
        trail_stop = new_extreme - trail_mult * atr if is_long else new_extreme + trail_mult * atr
        if is_long and trail_stop > new_stop:
            new_stop = trail_stop
        elif not is_long and trail_stop < new_stop:
            new_stop = trail_stop

    return new_extreme, new_stop


def btc_base_trailing_stop_hit(
    *,
    is_long: bool,
    low: float,
    high: float,
    trailing_stop: float,
) -> bool:
    """Evaluate legacy base trailing-stop hit without applying the close."""
    return (is_long and low <= trailing_stop) or (not is_long and high >= trailing_stop)


def btc_htf_stop_target(
    *,
    is_long: bool,
    entry: float,
    daily_high: float,
    daily_low: float,
    risk_cfg,
) -> tuple[float, float] | None:
    """Compute legacy HTF swing stop and fixed 1:2 target."""
    cap = risk_cfg.htf_sl_cap_pct
    if is_long:
        stop = max(daily_low, entry * (1 - cap))
        if stop >= entry:
            return None
        target = entry + 2 * (entry - stop)
    else:
        stop = min(daily_high, entry * (1 + cap))
        if stop <= entry:
            return None
        target = entry - 2 * (stop - entry)
    return stop, target


def btc_atr_htf_stop_target(
    *,
    is_long: bool,
    entry: float,
    atr: float,
    daily_high: float,
    daily_low: float,
    regime: int,
    risk_cfg,
) -> tuple[float, float] | None:
    """Compute legacy regime-adaptive ATR stop/target with HTF swing caps."""
    if regime == 1:
        stop_mult, target_mult = risk_cfg.regime_bull_sl_mult, risk_cfg.regime_bull_tp_mult
    elif regime == 2:
        stop_mult, target_mult = risk_cfg.regime_bear_sl_mult, risk_cfg.regime_bear_tp_mult
    elif regime == 3:
        stop_mult, target_mult = risk_cfg.regime_compression_sl_mult, risk_cfg.regime_compression_tp_mult
    else:
        stop_mult, target_mult = risk_cfg.regime_ranging_sl_mult, risk_cfg.regime_ranging_tp_mult

    if is_long:
        stop = max(entry - stop_mult * atr, daily_low)
        target = entry + target_mult * atr
    else:
        stop = min(entry + stop_mult * atr, daily_high)
        target = entry - target_mult * atr

    if is_long and (stop >= entry or target <= entry):
        return None
    if not is_long and (stop <= entry or target >= entry):
        return None
    return stop, target


def btc_breakout_stop_target(
    *,
    is_long: bool,
    entry: float,
    atr: float,
    daily_high: float,
    daily_low: float,
    risk_cfg,
) -> tuple[float, None] | None:
    """Compute legacy breakout initial stop with no fixed take-profit."""
    stop_mult = risk_cfg.breakout_sl_atr_mult if is_long else risk_cfg.short_sl_atr_mult
    if is_long:
        stop = max(entry - stop_mult * atr, daily_low)
        if stop >= entry:
            return None
    else:
        stop = min(entry + stop_mult * atr, daily_high)
        if stop <= entry:
            return None
    return stop, None


def btc_meanrev_stop_target(
    *,
    is_long: bool,
    entry: float,
    atr: float,
    bb_upper: float,
    bb_lower: float,
    ema55: float,
    risk_cfg,
) -> tuple[float, float] | None:
    """Compute legacy mean-reversion stop and midpoint/EMA target."""
    stop_mult = risk_cfg.mean_rev_sl_mult
    target_mult = risk_cfg.mean_rev_tp_mult
    bb_mid = (bb_upper + bb_lower) / 2

    if is_long:
        stop = entry - stop_mult * atr
        target_candidate = min(bb_mid, ema55) if bb_mid > entry else ema55
        target = min(target_candidate, entry + target_mult * atr)
    else:
        stop = entry + stop_mult * atr
        target_candidate = max(bb_mid, ema55) if bb_mid < entry else ema55
        target = max(target_candidate, entry - target_mult * atr)

    if is_long and (stop >= entry or target <= entry):
        return None
    if not is_long and (stop <= entry or target >= entry):
        return None
    return stop, target


def btc_tactical_entry_plan(
    *,
    long_signal: bool,
    short_signal: bool,
    module: str,
    entry: float,
    stop: float,
    target: float,
    position_size: float,
    bar_index: int,
    min_reward_risk: float = 2.0,
) -> BtcTacticalEntryPlan:
    """Plan legacy BTC tactical entry state without applying the order."""
    is_long = bool(long_signal and not short_signal)
    direction = 1 if is_long else -1
    empty = BtcTacticalEntryPlan(
        should_enter=False,
        is_long=is_long,
        direction=direction,
        module=module,
        order_tag="",
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        size=0.0,
        entry_bar=bar_index,
        extreme=entry,
        tp1_done=False,
        tp2_done=False,
        short_reached_1r=False,
        short_peak_r=0.0,
        short_giveback_peak_r=-999.0,
        last_trade_bar=bar_index,
    )
    if not (long_signal or short_signal):
        return empty
    risk = abs(entry - stop)
    reward = abs(target - entry)
    if risk <= 0 or reward / risk < min_reward_risk:
        return empty
    return BtcTacticalEntryPlan(
        should_enter=True,
        is_long=is_long,
        direction=direction,
        module=module,
        order_tag=f"{module}_{'long' if is_long else 'short'}",
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        size=position_size,
        entry_bar=bar_index,
        extreme=entry,
        tp1_done=False,
        tp2_done=False,
        short_reached_1r=False,
        short_peak_r=0.0,
        short_giveback_peak_r=-999.0,
        last_trade_bar=bar_index,
    )


def btc_layer_close_portion(*, layer_size: float, total_position_size: float) -> float:
    """Return legacy close portion for a layer within an aggregate position."""
    if layer_size <= 0:
        return 0.0
    total = abs(total_position_size)
    if total < 0.0001:
        return 0.0
    return min(layer_size / total, 1.0)


def btc_tactical_exit_close_plan(
    *,
    total_position_size: float,
    tactical_size: float,
) -> BtcTacticalExitClosePlan:
    """Plan legacy tactical exit close action without applying the close."""
    if abs(total_position_size) > 0.001 and tactical_size > 0.001:
        return BtcTacticalExitClosePlan(
            action="portion",
            portion=btc_layer_close_portion(
                layer_size=tactical_size,
                total_position_size=total_position_size,
            ),
        )
    return BtcTacticalExitClosePlan(action="all", portion=0.0)


def btc_tactical_sl_tp(
    *,
    is_long: bool,
    entry: float,
    atr: float,
    daily_high: float,
    daily_low: float,
    regime: int,
    risk_cfg,
) -> tuple[float, float] | None:
    """Compute legacy BTC tactical stop/target from regime-specific ATR rules."""
    if regime == 1:
        sl_m, tp_m = risk_cfg.regime_bull_sl_mult, risk_cfg.regime_bull_tp_mult
    elif regime == 2:
        sl_m, tp_m = risk_cfg.regime_bear_sl_mult, risk_cfg.regime_bear_tp_mult
    elif regime == 3:
        sl_m, tp_m = risk_cfg.regime_compression_sl_mult, risk_cfg.regime_compression_tp_mult
    else:
        sl_m, tp_m = risk_cfg.regime_ranging_sl_mult, risk_cfg.regime_ranging_tp_mult

    if is_long:
        stop = max(entry - sl_m * atr, daily_low)
        target = entry + tp_m * atr
    else:
        stop = min(entry + sl_m * atr, daily_high)
        target = entry - tp_m * atr

    if is_long and (stop >= entry or target <= entry):
        return None
    if not is_long and (stop <= entry or target >= entry):
        return None
    return stop, target


def btc_short_partial_tp_plan(
    *,
    module: str,
    entry_price: float,
    stop_price: float,
    close: float,
    tp1_done: bool,
    tp2_done: bool,
    risk_cfg,
) -> BtcShortPartialTpPlan:
    """Plan legacy short partial take-profit state without applying the close."""
    empty = BtcShortPartialTpPlan(
        should_take_profit=False,
        tp1_done=tp1_done,
        tp2_done=tp2_done,
        portion=0.0,
    )
    risk = abs(entry_price - stop_price)
    if risk <= 0:
        return empty

    if module == "crash":
        tp1_r, tp1_pct = risk_cfg.short_crash_tp1_r, risk_cfg.short_crash_tp1_pct
        tp2_r, tp2_pct = risk_cfg.short_crash_tp2_r, risk_cfg.short_crash_tp2_pct
    elif module in ("pullback", "failed_bounce"):
        tp1_r, tp1_pct = risk_cfg.fb_tp1_r, risk_cfg.fb_tp1_pct
        tp2_r, tp2_pct = risk_cfg.fb_tp2_r, risk_cfg.fb_tp2_pct
    elif module == "bear_core":
        tp1_r, tp1_pct = risk_cfg.bear_core_tp1_r, risk_cfg.bear_core_tp1_pct
        tp2_r, tp2_pct = risk_cfg.bear_core_tp2_r, risk_cfg.bear_core_tp2_pct
    else:
        return empty

    r_multiple = (entry_price - close) / risk
    if not tp1_done and r_multiple >= tp1_r:
        return BtcShortPartialTpPlan(True, True, tp2_done, tp1_pct)
    if tp1_done and not tp2_done and r_multiple >= tp2_r:
        return BtcShortPartialTpPlan(True, tp1_done, True, tp2_pct)
    return empty


def btc_short_extra_exit(
    *,
    module: str,
    close: float,
    dc10_high: float,
    dc20_low: float,
) -> bool:
    """Evaluate legacy short extra-exit rules without applying the exit."""
    if module == "crash" and close > dc10_high:
        return True
    if module in ("pullback", "failed_bounce", "bull_trap") and close <= dc20_low:
        return True
    return False


def btc_breakout_extra_exit(
    *,
    is_long: bool,
    close: float,
    dc20_low: float,
    dc20_high: float,
    ema144: float,
    prev_close: float,
    prev_ema144: float,
) -> bool:
    """Evaluate legacy breakout extra-exit rules without applying the exit."""
    if is_long:
        if close < dc20_low:
            return True
        return close < ema144 and prev_close < prev_ema144
    if close > dc20_high:
        return True
    return close > ema144 and prev_close > prev_ema144


def btc_flash_crash_state(
    *,
    bar_index: int,
    close: float,
    high_lookback: float,
    atr_now: float,
    atr_sma20: float,
    flash_crash_active: bool,
    flash_crash_bar: int,
) -> tuple[bool, int]:
    """Update legacy BTC flash-crash dip-buy state without applying orders."""
    active = flash_crash_active
    active_bar = flash_crash_bar
    flash_crash = (close / high_lookback - 1) < -0.05 and atr_now > 1.8 * atr_sma20
    if flash_crash and not active:
        active = True
        active_bar = bar_index

    if active:
        recovery = close > high_lookback * 0.97
        timeout = bar_index - active_bar > 12
        if recovery or timeout:
            active = False
    return active, active_bar


def btc_bear_core_v_reversal_exit(
    *,
    entry_price: float,
    stop_price: float,
    close: float,
    peak_r: float,
    bars_held: int,
    daily_ema_dir: float,
    regime: int,
) -> bool:
    """Evaluate legacy bear-core V-reversal snapback exit without applying closes."""
    risk = abs(entry_price - stop_price)
    if risk <= 0:
        return False

    current_r = (entry_price - close) / risk
    return (
        peak_r >= 2.0
        and current_r < 0.5
        and bars_held <= 12
        and (daily_ema_dir >= 0 or regime != 2)
    )


def btc_bear_core_probe_signal(
    *,
    core_active: bool,
    bear_core_active: bool,
    close: float,
    daily_ema_dir: float,
    daily_ema: float,
    daily_swing_low_20: float,
) -> bool:
    """Return legacy BTC bear-core stage-1 probe permission."""
    return (
        not core_active
        and not bear_core_active
        and close < daily_ema
        and daily_ema_dir < 0
        and close < daily_swing_low_20
    )


def btc_bear_core_confirm_signal(
    *,
    probe_active: bool,
    close: float,
    daily_ema_dir: float,
    daily_ema: float,
    weekly_ema: float,
    weekly_ema_dir: float,
) -> bool:
    """Return legacy BTC bear-core stage-2 confirmation permission."""
    return (
        probe_active
        and close < daily_ema
        and daily_ema_dir < 0
        and close < weekly_ema
        and weekly_ema_dir <= 0
    )


def btc_bear_core_probe_plan(
    *,
    bar_index: int,
    core_active: bool,
    bear_core_active: bool,
    top_score: float,
    double_top_signal: bool,
    bull_guard: bool,
    group_entry_bar: int,
    group_id: int,
    group_exposure: float,
    risk_cfg,
) -> tuple[bool, bool, float, int, float, int, float]:
    """Plan legacy bear-core stage-1 probe and group tracking updates."""
    same_group = (bar_index - group_entry_bar) <= 30
    if same_group:
        double_top_signal = False
    should_probe = (
        not core_active
        and not bear_core_active
        and double_top_signal
        and top_score >= 70
        and not bull_guard
    )
    if not should_probe:
        return False, same_group, 0.0, group_id, group_exposure, group_entry_bar, 0.0

    probe_size = risk_cfg.bear_core_full_pct * 0.35
    if same_group:
        new_group_id = group_id
        new_group_exposure = group_exposure + probe_size
        new_group_entry_bar = group_entry_bar
    else:
        new_group_id = group_id + 1
        new_group_exposure = probe_size
        new_group_entry_bar = bar_index
    return True, same_group, probe_size, new_group_id, new_group_exposure, new_group_entry_bar, 0.0


def btc_bear_core_probe_entry_state_plan(
    *,
    should_probe: bool,
    entry_price: float,
    bar_index: int,
    equity: float,
    probe_size: float,
    group_id: int,
    group_exposure: float,
    group_entry_bar: int,
    group_peak_r: float,
    bear_core_active: bool,
    bear_core_stage: int,
    bear_core_entry_price: float,
    bear_core_entry_bar: int,
    bear_core_size: float,
    bear_group_id: int,
    bear_group_exposure: float,
    bear_group_entry_bar: int,
    bear_group_peak_r: float,
    days_above_dema: int,
    equity_snapshot: float,
) -> BtcBearCoreProbeEntryStatePlan:
    """Plan legacy bear-core probe entry state updates without applying orders."""
    if not should_probe:
        return BtcBearCoreProbeEntryStatePlan(
            should_enter=False,
            bear_core_active=bear_core_active,
            bear_core_stage=bear_core_stage,
            bear_core_entry_price=bear_core_entry_price,
            bear_core_entry_bar=bear_core_entry_bar,
            bear_probe_peak_r=0.0,
            short_giveback_peak_r=-999.0,
            bear_core_size=bear_core_size,
            bear_group_id=bear_group_id,
            bear_group_exposure=bear_group_exposure,
            bear_group_entry_bar=bear_group_entry_bar,
            bear_group_peak_r=bear_group_peak_r,
            days_above_dema=days_above_dema,
            equity_snapshot=equity_snapshot,
            last_trade_bar=-10**9,
        )

    return BtcBearCoreProbeEntryStatePlan(
        should_enter=True,
        bear_core_active=True,
        bear_core_stage=1,
        bear_core_entry_price=entry_price,
        bear_core_entry_bar=bar_index,
        bear_probe_peak_r=0.0,
        short_giveback_peak_r=-999.0,
        bear_core_size=probe_size,
        bear_group_id=group_id,
        bear_group_exposure=group_exposure,
        bear_group_entry_bar=group_entry_bar,
        bear_group_peak_r=group_peak_r,
        days_above_dema=0,
        equity_snapshot=equity,
        last_trade_bar=bar_index,
    )


def btc_bear_core_confirm_add_plan(
    *,
    bar_index: int,
    entry_bar: int,
    active: bool,
    stage: int,
    probe_peak_r: float,
    daily_ema_dir: float,
    weekly_ema_dir: float,
    close: float,
    weekly_ema: float,
    current_size: float,
    group_exposure: float,
    group_max_exposure: float,
    risk_cfg,
) -> tuple[bool, float, float, float, int]:
    """Plan legacy bear-core stage-2 confirm add."""
    can_confirm = (
        active
        and stage == 1
        and bar_index > entry_bar
        and probe_peak_r >= 1.0
        and daily_ema_dir < 0
        and group_exposure < group_max_exposure
        and weekly_ema_dir <= 0
        and close < weekly_ema
    )
    if not can_confirm:
        return False, 0.0, current_size, group_exposure, stage

    target_size = risk_cfg.bear_core_full_pct * 0.65
    add_size = target_size - current_size
    if add_size <= 0.001:
        return False, 0.0, current_size, group_exposure, stage
    return True, add_size, target_size, group_exposure + add_size, 2


def btc_bear_core_confirm_add_state_plan(
    *,
    should_confirm_add: bool,
    bar_index: int,
    target_size: float,
    group_exposure: float,
    stage: int,
    bear_core_size: float,
    bear_group_exposure: float,
    bear_core_stage: int,
    last_trade_bar: int,
) -> BtcBearCoreConfirmAddStatePlan:
    """Plan legacy bear-core confirm-add state updates without applying orders."""
    if not should_confirm_add:
        return BtcBearCoreConfirmAddStatePlan(
            should_update=False,
            bear_core_size=bear_core_size,
            bear_group_exposure=bear_group_exposure,
            bear_core_stage=bear_core_stage,
            last_trade_bar=last_trade_bar,
        )

    return BtcBearCoreConfirmAddStatePlan(
        should_update=True,
        bear_core_size=target_size,
        bear_group_exposure=group_exposure,
        bear_core_stage=stage,
        last_trade_bar=bar_index,
    )


def btc_bear_core_acceleration_add_plan(
    *,
    bar_index: int,
    last_trade_bar: int,
    active: bool,
    stage: int,
    daily_ema_dir: float,
    adx: float,
    plus_di: float,
    minus_di: float,
    current_size: float,
    group_exposure: float,
    group_max_exposure: float,
    risk_cfg,
) -> tuple[bool, float, float, float, int]:
    """Plan legacy bear-core stage-3 acceleration add."""
    can_accelerate = (
        active
        and stage == 2
        and bar_index > last_trade_bar
        and daily_ema_dir < 0
        and group_exposure < group_max_exposure
        and adx > 22
        and minus_di > plus_di
    )
    if not can_accelerate:
        return False, 0.0, current_size, group_exposure, stage

    target_size = min(risk_cfg.bear_core_full_pct, group_max_exposure)
    add_size = target_size - current_size
    if add_size <= 0.001:
        return False, 0.0, current_size, group_exposure, stage
    return True, add_size, target_size, group_exposure + add_size, 3


def btc_bear_core_acceleration_add_state_plan(
    *,
    should_accel_add: bool,
    target_size: float,
    group_exposure: float,
    stage: int,
    bear_core_size: float,
    bear_group_exposure: float,
    bear_core_stage: int,
) -> BtcBearCoreAccelerationAddStatePlan:
    """Plan legacy bear-core acceleration-add state updates without applying orders."""
    if not should_accel_add:
        return BtcBearCoreAccelerationAddStatePlan(
            should_update=False,
            bear_core_size=bear_core_size,
            bear_group_exposure=bear_group_exposure,
            bear_core_stage=bear_core_stage,
        )

    return BtcBearCoreAccelerationAddStatePlan(
        should_update=True,
        bear_core_size=target_size,
        bear_group_exposure=group_exposure,
        bear_core_stage=stage,
    )


def btc_bear_probe_peak_r(
    *,
    entry_price: float,
    stop_price: float,
    low: float,
    previous_peak_r: float,
) -> float:
    """Track legacy bear-core probe max favorable R without applying exits."""
    risk = abs(entry_price - stop_price)
    if risk <= 0:
        return previous_peak_r
    current_r = (entry_price - low) / risk
    return current_r if current_r > previous_peak_r else previous_peak_r


def btc_core_entry_signal(*, regime: int) -> bool:
    """Return whether the BTC core long layer may enter."""
    return regime == 1


def btc_core_exit_signal(
    *,
    weekly_ema_dir: float,
    close: float,
    daily_ema: float,
    day_id: int,
    last_day: int,
    days_below_dema: int,
    risk_cfg,
) -> tuple[bool, int, int]:
    """Evaluate BTC core long trend-failure exit and return updated day state."""
    if weekly_ema_dir < 0:
        return True, last_day, days_below_dema
    new_last_day = last_day
    new_days_below = days_below_dema
    if day_id != last_day:
        new_last_day = day_id
        if close < daily_ema:
            new_days_below += 1
        else:
            new_days_below = 0
    return new_days_below >= risk_cfg.core_exit_days_below_ema, new_last_day, new_days_below


def btc_core_trail_stop_hit(
    *,
    core_active: bool,
    highest_close: float,
    close: float,
    atr: float,
    risk_cfg,
) -> tuple[bool, float]:
    """Evaluate BTC core long ATR trail and return updated highest close."""
    if not core_active:
        return False, highest_close
    new_highest_close = max(highest_close, close)
    trail = risk_cfg.core_sl_daily_atr_mult * atr
    return close < new_highest_close - trail, new_highest_close


def btc_core_add_signal(*, pullback_long: bool) -> bool:
    """Return whether the BTC core long layer may add exposure."""
    return bool(pullback_long)


def btc_core_add_plan(
    *,
    core_active: bool,
    core_fully_loaded: bool,
    core_add_signal: bool,
    core_size: float,
    max_position_frac: float,
    risk_cfg,
) -> tuple[bool, float, float, bool]:
    """Plan legacy BTC core pullback add without applying the order."""
    if not core_active or core_fully_loaded or not core_add_signal:
        return False, 0.0, core_size, core_fully_loaded

    add_size = (risk_cfg.core_allocation - core_size) * max_position_frac
    if add_size <= 0.001:
        return False, 0.0, core_size, core_fully_loaded
    return True, add_size, risk_cfg.risk_core_alloc, True


def btc_core_add_state_plan(
    *,
    should_core_add: bool,
    new_core_size: float,
    new_core_fully_loaded: bool,
    core_size: float,
    core_fully_loaded: bool,
) -> BtcCoreAddStatePlan:
    """Plan legacy core-add state updates without applying the order."""
    if not should_core_add:
        return BtcCoreAddStatePlan(
            should_update=False,
            core_size=core_size,
            core_fully_loaded=core_fully_loaded,
        )

    return BtcCoreAddStatePlan(
        should_update=True,
        core_size=new_core_size,
        core_fully_loaded=new_core_fully_loaded,
    )


def btc_bear_core_stop(*, entry_price: float, atr_4h: float, risk_cfg) -> float:
    """Return BTC bear core stop using the legacy daily-ATR approximation."""
    daily_atr = atr_4h * 1.5
    return entry_price + risk_cfg.bear_core_sl_daily_atr * daily_atr


def btc_bear_core_exit_signal(
    *,
    bear_core_active: bool,
    entry_price: float,
    close: float,
    atr_4h: float,
    daily_ema_dir: float,
    daily_ema: float,
    day_id: int,
    last_day: int,
    days_above_dema: int,
    risk_cfg,
) -> tuple[bool, int, int]:
    """Evaluate BTC bear core trend and ATR-trail exits with updated day state."""
    if not bear_core_active:
        return False, last_day, days_above_dema
    if daily_ema_dir > 0:
        return True, last_day, days_above_dema

    new_last_day = last_day
    new_days_above = days_above_dema
    if day_id != last_day:
        new_last_day = day_id
        if close > daily_ema:
            new_days_above += 1
        else:
            new_days_above = 0
    if new_days_above >= risk_cfg.bear_core_exit_days_above_ema:
        return True, new_last_day, new_days_above

    if entry_price > 0 and close > btc_bear_core_stop(
        entry_price=entry_price,
        atr_4h=atr_4h,
        risk_cfg=risk_cfg,
    ):
        return True, new_last_day, new_days_above
    return False, new_last_day, new_days_above


def btc_short_giveback_guard(
    *,
    entry_price: float,
    stop_price: float,
    low: float,
    close: float,
    previous_peak_r: float,
) -> tuple[bool, float]:
    """Evaluate legacy tiered short giveback guard and return updated peak R."""
    risk = abs(entry_price - stop_price)
    if risk <= 0:
        return False, previous_peak_r
    peak_r = (entry_price - low) / risk
    updated_peak = peak_r if peak_r > previous_peak_r else previous_peak_r
    current_r = (entry_price - close) / risk

    if previous_peak_r >= 2.0 and current_r <= 0.5:
        return True, updated_peak
    if previous_peak_r >= 3.0 and current_r <= 1.0:
        return True, updated_peak
    if previous_peak_r >= 5.0 and current_r <= 2.0:
        return True, updated_peak
    return False, updated_peak


def btc_short_time_stop(
    *,
    module: str,
    bars_held: int,
    entry_price: float,
    stop_price: float,
    close: float,
    short_reached_1r: bool,
    risk_cfg,
) -> tuple[bool, bool]:
    """Evaluate legacy short tactical time-stop and return updated 1R state."""
    if module == "crash":
        timeout = risk_cfg.short_crash_timeout
    elif module in ("pullback", "failed_bounce"):
        timeout = risk_cfg.fb_timeout
    elif module == "bear_core":
        return False, short_reached_1r
    elif module == "bull_trap":
        timeout = risk_cfg.short_bulltrap_timeout
    else:
        return False, short_reached_1r

    risk = abs(entry_price - stop_price)
    if risk <= 0:
        return False, short_reached_1r

    r_multiple = (entry_price - close) / risk
    new_reached_1r = short_reached_1r or r_multiple >= 1.0
    if bars_held >= timeout and not new_reached_1r:
        return r_multiple < 1.0, new_reached_1r
    if new_reached_1r and r_multiple < 1.0:
        return True, new_reached_1r
    return False, new_reached_1r


def btc_tactical_hard_exit(
    *,
    is_long: bool,
    high: float,
    low: float,
    stop_price: float,
    target_price: float,
) -> bool:
    """Evaluate legacy tactical hard stop/target hit without applying the exit."""
    if is_long:
        return low <= stop_price or high >= target_price
    return high >= stop_price or low <= target_price


def btc_tactical_trailing_stop(
    *,
    is_long: bool,
    price: float,
    high: float,
    low: float,
    atr: float,
    previous_extreme: float,
    stop_price: float,
    risk_cfg,
) -> tuple[bool, float, float]:
    """Update legacy tactical ATR trailing stop without applying the exit."""
    if is_long:
        new_extreme = max(previous_extreme, high)
        trail_stop = new_extreme - risk_cfg.trailing_distance_atr * atr
        new_stop = trail_stop if trail_stop > stop_price else stop_price
        return low <= new_stop, new_extreme, new_stop

    new_extreme = min(previous_extreme, low)
    trail_stop = new_extreme + risk_cfg.trailing_distance_atr * atr
    new_stop = trail_stop if trail_stop < stop_price else stop_price
    return high >= new_stop, new_extreme, new_stop


def btc_bear_core_waterfall_guard(
    *,
    stage: int,
    entry_price: float,
    low: float,
    atr_4h: float,
    bars_since_entry: int,
    daily_ema_dir: float,
) -> tuple[bool, float, float, int]:
    """Evaluate legacy bear-core waterfall profit guard without applying orders."""
    if stage not in (1, 2):
        return False, 0.0, 0.0, stage
    if atr_4h <= 0 or entry_price <= 0:
        return False, 0.0, 0.0, stage

    risk_4h = 2.5 * atr_4h
    current_r = (entry_price - low) / risk_4h
    if bars_since_entry <= 6 and current_r >= 1.5 and daily_ema_dir >= 0:
        return True, 0.70, 1.5, 99
    if bars_since_entry <= 10 and current_r >= 2.5:
        return True, 0.80, 2.0, 99
    return False, 0.0, 0.0, stage


def btc_bear_core_waterfall_runner_exit(
    *,
    stage: int,
    entry_price: float,
    stop_price: float,
    close: float,
    lock_r: float,
) -> bool:
    """Evaluate legacy waterfall runner giveback exit without applying closes."""
    if stage != 99:
        return False

    risk = abs(entry_price - stop_price)
    if risk <= 0:
        return False

    current_r = (entry_price - close) / risk
    return current_r < lock_r * 0.5
