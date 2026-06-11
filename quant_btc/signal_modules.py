"""BTC compatibility signal module mappings."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant_platform.signal_modules import ColumnSignalConfig, ColumnSignalModule, SignalModuleRunner
from quant_platform.signals import Direction, Signal


def btc_mtf_sweep_reclaim(
    bars: pd.DataFrame | None,
    *,
    is_long: bool,
    key_level: float,
) -> bool:
    """Return legacy 15m sweep/reclaim confirmation for a 4H BTC signal."""
    if bars is None or len(bars) < 3:
        return False
    if is_long:
        swept = (bars["Low"] < key_level).any()
        if not swept:
            return False
        return bool((bars.iloc[-2:]["Close"] > key_level).all())

    swept = (bars["High"] > key_level).any()
    if not swept:
        return False
    return bool((bars.iloc[-2:]["Close"] < key_level).all())


def btc_mtf_no_new_extreme(bars: pd.DataFrame | None, *, is_long: bool) -> bool:
    """Return legacy 15m no-new-low/no-new-high confirmation."""
    if bars is None or len(bars) < 4:
        return False
    mid = len(bars) // 2
    first_half = bars.iloc[:mid]
    second_half = bars.iloc[mid:]
    if is_long:
        return bool(second_half["Low"].min() >= first_half["Low"].min())
    return bool(second_half["High"].max() <= first_half["High"].max())


def btc_mtf_higher_low_formed(bars: pd.DataFrame | None) -> bool:
    """Return legacy 15m higher-low confirmation for retest/pullback signals."""
    if bars is None or len(bars) < 6:
        return False
    lows = bars["Low"].values
    for i in range(2, len(lows) - 2):
        if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and lows[i] < lows[i + 1] and lows[i] < lows[i + 2]:
            prev_lows = lows[:i]
            if len(prev_lows) > 3:
                prev_swing = min(prev_lows[1:-1])
                if lows[i] > prev_swing:
                    return True
    return False


def select_btc_base_entry_signal(
    row: pd.Series,
    *,
    symbol: str,
    module: str,
    long_column: str,
    short_column: str,
    regime: int,
    daily_ema_dir: float,
    weekly_ema_dir: float,
    allow_long: bool,
    allow_short: bool,
    score_threshold: float,
    long_score_column: str | None = None,
    short_score_column: str | None = None,
    long_stop_column: str | None = None,
    short_stop_column: str | None = None,
    long_target_column: str | None = None,
    short_target_column: str | None = None,
) -> Signal | None:
    """Select the BTC base-strategy entry as a standardized compatibility signal."""
    long_score = _row_float(row, long_score_column or long_column)
    short_score = _row_float(row, short_score_column or short_column)
    is_long = _btc_base_entry_direction(
        regime=regime,
        daily_ema_dir=daily_ema_dir,
        weekly_ema_dir=weekly_ema_dir,
        allow_long=allow_long,
        allow_short=allow_short,
        long_score=long_score,
        short_score=short_score,
        score_threshold=score_threshold,
    )
    if is_long is None:
        return None

    if is_long:
        direction = Direction.LONG
        score = long_score
        stop = _optional_row_float(row, long_stop_column)
        target = _optional_row_float(row, long_target_column)
    else:
        direction = Direction.SHORT
        score = short_score
        stop = _optional_row_float(row, short_stop_column)
        target = _optional_row_float(row, short_target_column)

    return Signal(
        module=module,
        symbol=symbol,
        direction=direction,
        score=score,
        entry_reason=f"{module} BTC compatibility entry",
        invalidation="BTC compatibility exit and risk rules",
        preferred_stop=stop,
        preferred_target=target,
        confidence=max(0.0, min(1.0, score / 100.0)),
        required_data=("ohlcv:4h", "features:btc_compat"),
    )


def select_btc_weighted_legacy_signal(
    row: pd.Series,
    *,
    symbol: str,
    long_column: str = "long_entry",
    short_column: str = "short_entry",
) -> Signal | None:
    """Select the simple weighted legacy entry as a standardized compatibility signal."""
    if _row_bool(row, long_column):
        direction = Direction.LONG
    elif _row_bool(row, short_column):
        direction = Direction.SHORT
    else:
        return None
    return _btc_compat_signal(
        symbol,
        "legacy_weighted",
        direction,
        100.0,
        entry_reason="legacy_weighted BTC compatibility entry",
        invalidation="BTC weighted legacy opposite-signal exit",
    )


def select_btc_core_entry_signal(*, symbol: str, regime: int) -> Signal | None:
    """Select the BTC core-long entry as a standardized compatibility signal."""
    if regime != 1:
        return None
    return _btc_compat_signal(
        symbol,
        "core_long",
        Direction.LONG,
        100.0,
        invalidation="BTC core compatibility exit and risk rules",
        required_data=("ohlcv:4h", "regime:btc_compat"),
    )


def select_btc_flash_crash_dip_buy_signal(*, symbol: str, should_enter: bool) -> Signal | None:
    """Select the BTC flash-crash dip-buy as a standardized compatibility signal."""
    if not should_enter:
        return None
    return _btc_compat_signal(
        symbol,
        "dip_buy",
        Direction.LONG,
        80.0,
        entry_reason="dip_buy BTC tactical compatibility entry",
        invalidation="BTC tactical compatibility exit and risk rules",
        required_data=("ohlcv:4h", "regime:btc_compat"),
    )


def select_btc_core_add_signal(
    row: pd.Series,
    *,
    symbol: str,
    pullback_column: str = "pullback_long",
    score_column: str = "score_pullback_long",
) -> Signal | None:
    """Select the BTC core pullback add-on as a standardized compatibility signal."""
    if not _row_bool(row, pullback_column):
        return None
    score = _optional_row_float(row, score_column)
    if score is None:
        score = 100.0
    return _btc_compat_signal(
        symbol,
        "core_add",
        Direction.LONG,
        score,
        invalidation="BTC core add compatibility exit and risk rules",
    )


def select_btc_bear_core_probe_signal(
    row: pd.Series,
    *,
    symbol: str,
    core_active: bool,
    bear_core_active: bool,
    score_threshold: float = 70.0,
    top_score_column: str = "_top_exhaustion_score",
    double_top_column: str = "_double_top_signal",
    bull_guard_column: str = "_bull_guard",
) -> Signal | None:
    """Select the BTC bear-core stage-1 probe as a standardized compatibility signal."""
    top_score = _row_float(row, top_score_column)
    if (
        core_active
        or bear_core_active
        or not _row_bool(row, double_top_column)
        or top_score < score_threshold
        or _row_bool(row, bull_guard_column)
    ):
        return None
    return _btc_compat_signal(
        symbol,
        "bear_core_probe",
        Direction.SHORT,
        top_score,
        invalidation="BTC bear-core compatibility exit and risk rules",
    )


def select_btc_bear_core_confirm_add_signal(
    row: pd.Series,
    *,
    symbol: str,
    bar_index: int,
    entry_bar: int,
    active: bool,
    stage: int,
    probe_peak_r: float,
) -> Signal | None:
    """Select the BTC bear-core stage-2 confirmation add as a standardized signal."""
    if (
        not active
        or stage != 1
        or bar_index <= entry_bar
        or probe_peak_r < 1.0
        or _row_float(row, "_d_ema_dir") >= 0
        or _row_float(row, "_w_ema_dir") > 0
        or _row_float(row, "Close") >= _row_float(row, "_w_ema_169")
    ):
        return None
    return _btc_compat_signal(
        symbol,
        "bear_core_confirm",
        Direction.SHORT,
        80.0,
        invalidation="BTC bear-core compatibility exit and risk rules",
    )


def select_btc_bear_core_acceleration_add_signal(
    row: pd.Series,
    *,
    symbol: str,
    bar_index: int,
    last_trade_bar: int,
    active: bool,
    stage: int,
) -> Signal | None:
    """Select the BTC bear-core stage-3 acceleration add as a standardized signal."""
    if (
        not active
        or stage != 2
        or bar_index <= last_trade_bar
        or _row_float(row, "_d_ema_dir") >= 0
        or _row_float(row, "_adx_signal") <= 22
        or _row_float(row, "_minus_di") <= _row_float(row, "_plus_di")
    ):
        return None
    return _btc_compat_signal(
        symbol,
        "bear_core_acceleration",
        Direction.SHORT,
        85.0,
        invalidation="BTC bear-core compatibility exit and risk rules",
    )


def select_btc_tactical_signal(
    row: pd.Series,
    *,
    symbol: str,
    regime: int,
    daily_ema_dir: float,
    weekly_ema_dir: float,
    core_active: bool,
    bear_core_active: bool,
    short_rsi_floor: float,
    mtf_no_new_extreme_long: bool = False,
    mtf_no_new_extreme_short: bool = False,
    mtf_higher_low: bool = False,
) -> Signal | None:
    """Select the BTC dual-layer tactical entry as a standardized compatibility signal."""
    strong_bull = regime == 1
    strong_bear = regime == 2
    weak_bull = not strong_bull and daily_ema_dir >= 0 and weekly_ema_dir >= 0
    ranging = regime == 0
    compression = regime == 3

    score_bo_retest_l = _row_float(row, "score_breakout_retest_long")
    score_pb_struct_l = _row_float(row, "score_pullback_struct_long")
    score_pb_struct_s = _row_float(row, "score_pullback_struct_short")
    score_mr_range_l = _row_float(row, "score_meanrev_range_long")
    score_sweep_l = _row_float(row, "score_sweep_reversal_long")
    score_sweep_s = _row_float(row, "score_sweep_reversal_short")

    deriv_bonus = _row_float(row, "_short_deriv_bonus")
    pa_bonus = _row_float(row, "_price_action_bonus")
    fb_bonus = 5.0 if _row_bool(row, "_failed_bounce_gate") else 0.0
    perp_long_bonus = _row_float(row, "_perp_crowding_long_bonus")
    score_pb_s = score_pb_struct_s + fb_bonus + deriv_bonus + pa_bonus
    score_crash_s = _row_float(row, "score_crash_short") + deriv_bonus + pa_bonus
    score_bt_s = _row_float(row, "score_bull_trap_short") + deriv_bonus + pa_bonus
    bt_gate = _row_bool(row, "_bull_trap_signal")

    bo_retest_th = 70.0
    pb_struct_th = 70.0
    mr_range_th = 75.0
    sweep_th = 65.0
    crash_th = 75.0
    pb_th_s = 999.0
    bt_th = 80.0

    sweep_gate_l = _row_bool(row, "_sweep_signal_long")
    sweep_gate_s = _row_bool(row, "_sweep_signal_short")
    sweep_score_l = score_sweep_l + (10.0 if mtf_no_new_extreme_long else 0.0)
    sweep_score_s = score_sweep_s + (10.0 if mtf_no_new_extreme_short else 0.0)
    retest_score_l = score_bo_retest_l + (5.0 if mtf_higher_low else 0.0)
    struct_score_l = score_pb_struct_l + (5.0 if mtf_higher_low else 0.0)

    rsi_ok = _row_float(row, "rsi_14") >= short_rsi_floor
    late_ok = not _row_bool(row, "_late_chase")
    close_val = _row_float(row, "Close")
    daily_ema = _row_float(row, "_d_ema_169")
    bull_guard = _row_bool(row, "_bull_guard") or core_active
    short_env_ok = not bull_guard and regime != 4 and rsi_ok and late_ok
    short_trend_ok = short_env_ok and close_val < daily_ema and daily_ema_dir <= 0
    short_aggressive_ok = short_trend_ok and weekly_ema_dir <= 0

    if ranging:
        if score_mr_range_l >= mr_range_th:
            return _btc_tactical_signal(symbol, "meanrev_range", Direction.LONG, score_mr_range_l)
        if sweep_gate_l and sweep_score_l + perp_long_bonus >= sweep_th:
            return _btc_tactical_signal(symbol, "sweep_reversal", Direction.LONG, sweep_score_l + perp_long_bonus)
        if sweep_gate_s and sweep_score_s >= sweep_th:
            return _btc_tactical_signal(symbol, "sweep_reversal", Direction.SHORT, sweep_score_s)
        return None

    if strong_bear:
        if short_aggressive_ok and score_crash_s >= crash_th:
            return _btc_tactical_signal(symbol, "crash", Direction.SHORT, score_crash_s)
        if short_trend_ok and score_pb_s >= pb_th_s:
            return _btc_tactical_signal(symbol, "pullback_struct", Direction.SHORT, score_pb_s)
        if sweep_gate_s and sweep_score_s >= sweep_th:
            return _btc_tactical_signal(symbol, "sweep_reversal", Direction.SHORT, sweep_score_s)
        if short_env_ok and bt_gate and score_bt_s >= bt_th:
            return _btc_tactical_signal(symbol, "bull_trap", Direction.SHORT, score_bt_s)
        return None

    if not strong_bull and not ranging and not compression:
        if short_trend_ok and score_pb_s >= pb_th_s:
            return _btc_tactical_signal(symbol, "pullback_struct", Direction.SHORT, score_pb_s)
        if sweep_gate_s and sweep_score_s >= sweep_th:
            return _btc_tactical_signal(symbol, "sweep_reversal", Direction.SHORT, sweep_score_s)
        if short_env_ok and bt_gate and score_bt_s >= bt_th:
            return _btc_tactical_signal(symbol, "bull_trap", Direction.SHORT, score_bt_s)
        return None

    if strong_bull:
        if retest_score_l >= bo_retest_th:
            return _btc_tactical_signal(symbol, "breakout_retest", Direction.LONG, retest_score_l)
        if struct_score_l + perp_long_bonus >= pb_struct_th:
            return _btc_tactical_signal(symbol, "pullback_struct", Direction.LONG, struct_score_l + perp_long_bonus)
        if sweep_gate_l and sweep_score_l + perp_long_bonus >= sweep_th:
            return _btc_tactical_signal(symbol, "sweep_reversal", Direction.LONG, sweep_score_l + perp_long_bonus)
        if score_mr_range_l >= mr_range_th:
            return _btc_tactical_signal(symbol, "meanrev_range", Direction.LONG, score_mr_range_l)
        return None

    if compression:
        if retest_score_l >= bo_retest_th:
            return _btc_tactical_signal(symbol, "breakout_retest", Direction.LONG, retest_score_l)
        if sweep_gate_l and sweep_score_l >= sweep_th:
            return _btc_tactical_signal(symbol, "sweep_reversal", Direction.LONG, sweep_score_l)
        return None

    if weak_bull:
        if retest_score_l >= bo_retest_th:
            return _btc_tactical_signal(symbol, "breakout_retest", Direction.LONG, retest_score_l)
        if struct_score_l + perp_long_bonus >= pb_struct_th:
            return _btc_tactical_signal(symbol, "pullback_struct", Direction.LONG, struct_score_l + perp_long_bonus)
        if sweep_gate_l and sweep_score_l + perp_long_bonus >= sweep_th:
            return _btc_tactical_signal(symbol, "sweep_reversal", Direction.LONG, sweep_score_l + perp_long_bonus)
        if score_mr_range_l >= mr_range_th:
            return _btc_tactical_signal(symbol, "meanrev_range", Direction.LONG, score_mr_range_l)
        return None

    return None


def _btc_tactical_signal(symbol: str, module: str, direction: Direction, score: float) -> Signal:
    return _btc_compat_signal(
        symbol,
        module,
        direction,
        score,
        entry_reason=f"{module} BTC tactical compatibility entry",
        invalidation="BTC tactical compatibility exit and risk rules",
    )


def _btc_compat_signal(
    symbol: str,
    module: str,
    direction: Direction,
    score: float,
    *,
    entry_reason: str | None = None,
    invalidation: str = "BTC compatibility exit and risk rules",
    required_data: tuple[str, ...] = ("ohlcv:4h", "features:btc_compat"),
) -> Signal:
    return Signal(
        module=module,
        symbol=symbol,
        direction=direction,
        score=score,
        entry_reason=entry_reason or f"{module} BTC compatibility entry",
        invalidation=invalidation,
        confidence=max(0.0, min(1.0, score / 100.0)),
        required_data=required_data,
    )


def _btc_base_entry_direction(
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


def _row_float(row: pd.Series, column: str) -> float:
    value = row.get(column, 0.0)
    if pd.isna(value):
        return 0.0
    return float(value)


def _row_bool(row: pd.Series, column: str) -> bool:
    value = row.get(column, False)
    if pd.isna(value):
        return False
    return bool(value)


def _optional_row_float(row: pd.Series, column: str | None) -> float | None:
    if not column:
        return None
    value = row.get(column)
    if pd.isna(value):
        return None
    return float(value)


def add_btc_signal_predicate_columns(features: pd.DataFrame) -> pd.DataFrame:
    """Add legacy BTC module boolean columns from precomputed feature columns."""
    out = features.copy()

    in_zone_1 = (out["Close"] >= np.minimum(out["ema55"], out["ema144"])) & (
        out["Close"] <= np.maximum(out["ema55"], out["ema144"])
    )
    in_zone_2 = (out["Close"] >= np.minimum(out["ema69"], out["ema169"])) & (
        out["Close"] <= np.maximum(out["ema69"], out["ema169"])
    )
    out["in_pullback_zone"] = in_zone_1 | in_zone_2

    hist = out["macd_hist"]
    out["macd_hist_rising2"] = (hist > hist.shift(1)) & (hist.shift(1) > hist.shift(2))
    out["macd_hist_falling2"] = (hist < hist.shift(1)) & (hist.shift(1) < hist.shift(2))

    rsi = out["rsi_14"]
    out["rsi_bull_setup"] = (
        (rsi.shift(1) >= 40) & (rsi.shift(1) <= 50) & (rsi > rsi.shift(1))
    )
    out["rsi_bear_setup"] = (
        (rsi.shift(1) >= 50) & (rsi.shift(1) <= 60) & (rsi < rsi.shift(1))
    )

    out["break_prev_high"] = out["Close"] > out["High"].shift(1)
    out["break_prev_low"] = out["Close"] < out["Low"].shift(1)
    out["close_above_ema55"] = out["Close"] > out["ema55"]
    out["close_below_ema55"] = out["Close"] < out["ema55"]

    bull_momentum = out["rsi_bull_setup"] | out["macd_hist_rising2"]
    bear_momentum = out["rsi_bear_setup"] | out["macd_hist_falling2"]
    out["pullback_long"] = (
        out["in_pullback_zone"]
        & bull_momentum
        & out["break_prev_high"]
        & out["close_above_ema55"]
    )
    out["pullback_short"] = (
        out["in_pullback_zone"]
        & bear_momentum
        & out["break_prev_low"]
        & out["close_below_ema55"]
    )

    vol_expand = (out["Volume"] > out["vol_sma_50"]) | (out["vol_zscore"] > 0)
    adx_rising = (
        (out["_adx_signal"] > out["_adx_signal"].shift(1))
        & (out["_adx_signal"].shift(1) > out["_adx_signal"].shift(2))
    )
    adx_ok = (out["_adx_signal"] > 20) | adx_rising
    atr_range_ok = (out["_atr_pct_signal"] >= 0.30) & (out["_atr_pct_signal"] <= 0.85)
    out["breakout_long"] = (
        (out["Close"] > out["roll_high_55"].shift(1))
        & vol_expand
        & adx_ok
        & atr_range_ok
        & (out["Close"] > out["ema55"])
    )
    out["breakout_short"] = (
        (out["Close"] < out["roll_low_55"].shift(1))
        & vol_expand
        & adx_ok
        & (out["Close"] < out["ema55"])
    )

    dc55_range = out["roll_high_55"] - out["roll_low_55"]
    within_dc55 = (
        (out["Close"] > out["roll_low_55"] + 0.05 * dc55_range)
        & (out["Close"] < out["roll_high_55"] - 0.05 * dc55_range)
    )
    near_bb_lower = out["Close"] <= out["bb_lower"] * 1.005
    near_bb_upper = out["Close"] >= out["bb_upper"] * 0.995
    near_dc20_low = out["Close"] <= out["mr_dc20_low"] * 1.005
    near_dc20_high = out["Close"] >= out["mr_dc20_high"] * 0.995
    rsi_oversold = out["rsi_14"] < 35
    rsi_overbought = out["rsi_14"] > 65
    has_lower_wick = out["_lower_shadow"] > 0.35
    has_upper_wick = out["_upper_shadow"] > 0.35
    low_adx = out["_adx_signal"] < 25
    out["meanrev_long"] = (
        low_adx
        & within_dc55
        & (near_bb_lower | near_dc20_low)
        & rsi_oversold
        & (has_lower_wick | (out["Close"] > out["Low"].shift(1)))
    )
    out["meanrev_short"] = (
        low_adx
        & within_dc55
        & (near_bb_upper | near_dc20_high)
        & rsi_overbought
        & (has_upper_wick | (out["Close"] < out["High"].shift(1)))
    )
    return out


def add_btc_score_signal_columns(features: pd.DataFrame) -> pd.DataFrame:
    """Add standardized signal gates that depend on score columns."""
    out = features.copy()
    out["_crash_short_signal"] = (out["score_crash_short"] >= 75) & (~out["_late_chase"])
    return out


def add_btc_module_score_columns(features: pd.DataFrame) -> pd.DataFrame:
    """Compute BTC compatibility module score columns from prepared features."""
    out = features.copy()
    close = out["Close"]
    atr = out["_atr_signal"]
    adx = out["_adx_signal"]
    rsi = out["rsi_14"]
    macd_h = out["macd_hist"]
    vol_z = out["vol_zscore"]

    d_ema = out["d_ema"]
    w_ema = out["w_ema"]
    d_dir = pd.Series(
        np.where(d_ema.pct_change(1).fillna(0) > 0.001, 1, np.where(d_ema.pct_change(1).fillna(0) < -0.001, -1, 0)),
        index=out.index,
    )
    w_dir = pd.Series(
        np.where(w_ema.pct_change(1).fillna(0) > 0.001, 1, np.where(w_ema.pct_change(1).fillna(0) < -0.001, -1, 0)),
        index=out.index,
    )

    market_long_score = pd.Series(10.0, index=out.index)
    market_short_score = pd.Series(10.0, index=out.index)
    bull = (d_dir > 0) & (w_dir >= 0)
    market_long_score[bull] = 28.0
    market_short_score[bull] = 2.0
    strong_bull = bull & (close > d_ema)
    market_long_score[strong_bull] = 30.0
    market_short_score[strong_bull] = 0.0
    bear = (d_dir < 0) & (w_dir <= 0)
    market_long_score[bear] = 2.0
    market_short_score[bear] = 28.0
    strong_bear = bear & (close < d_ema)
    market_long_score[strong_bear] = 0.0
    market_short_score[strong_bear] = 30.0
    soft_bull = (d_dir >= 0) & ~bull
    market_long_score[soft_bull] = 20.0
    market_short_score[soft_bull] = 10.0
    soft_bear = (d_dir <= 0) & ~bear & ~soft_bull
    market_long_score[soft_bear] = 10.0
    market_short_score[soft_bear] = 20.0

    dc55_range = out["roll_high_55"] - out["roll_low_55"]
    dc55_prev_high = out["roll_high_55"].shift(1)
    dc55_prev_low = out["roll_low_55"].shift(1)
    break_strength_l = ((close - dc55_prev_high) / dc55_range.clip(1e-10)).clip(0, 0.05) * 300
    break_strength_s = ((dc55_prev_low - close) / dc55_range.clip(1e-10)).clip(0, 0.05) * 300
    vol_score = vol_z.clip(0, 3) * 3.33
    adx_score = (adx.clip(20, 45) - 20) / 25 * 5
    pat_breakout_l = (break_strength_l.clip(0, 15) + vol_score.clip(0, 10) + adx_score.clip(0, 5)).clip(0, 30)
    pat_breakout_s = (break_strength_s.clip(0, 15) + vol_score.clip(0, 10) + adx_score.clip(0, 5)).clip(0, 30)

    ema_zone_center = (out["ema55"] + out["ema144"]) / 2
    ema_zone_width = (out["ema55"] - out["ema144"]).abs().clip(1e-10)
    dist_to_center = (close - ema_zone_center).abs() / ema_zone_width
    zone_quality = (1.0 - dist_to_center.clip(0, 1)) * 15
    rsi_pb_l = pd.Series(0.0, index=out.index)
    rsi_pb_l[(rsi >= 30) & (rsi < 55)] = 10
    rsi_pb_l[(rsi >= 35) & (rsi < 50)] = 15
    rsi_pb_s = pd.Series(0.0, index=out.index)
    rsi_pb_s[(rsi > 45) & (rsi <= 70)] = 10
    rsi_pb_s[(rsi > 50) & (rsi <= 65)] = 15
    pat_pullback_l = (zone_quality + rsi_pb_l).clip(0, 30)
    pat_pullback_s = (zone_quality + rsi_pb_s).clip(0, 30)

    bb_lower = out["bb_lower"]
    bb_upper = out["bb_upper"]
    bb_range = (bb_upper - bb_lower).clip(1e-10)
    dist_lower = (close - bb_lower).clip(0, None) / bb_range * 100
    dist_upper = (bb_upper - close).clip(0, None) / bb_range * 100
    extreme_score_l = (15.0 - dist_lower * 3).clip(0, 15)
    extreme_score_s = (15.0 - dist_upper * 3).clip(0, 15)
    candle_rng = (out["High"] - out["Low"]).clip(1e-10)
    l_shadow = (np.minimum(out["Open"], close) - out["Low"]) / candle_rng
    u_shadow = (out["High"] - np.maximum(out["Open"], close)) / candle_rng
    wick_l_score = l_shadow.clip(0.35, 0.7) * 15 / 0.35 - 15
    wick_s_score = u_shadow.clip(0.35, 0.7) * 15 / 0.35 - 15
    pat_meanrev_l = (extreme_score_l + wick_l_score).clip(0, 30)
    pat_meanrev_s = (extreme_score_s + wick_s_score).clip(0, 30)

    macd_rising = macd_h > macd_h.shift(1)
    macd_rising2 = macd_rising & (macd_h.shift(1) > macd_h.shift(2))
    macd_score_l = pd.Series(2.0, index=out.index)
    macd_score_l[macd_rising] = 4.0
    macd_score_l[macd_rising2] = 7.0
    macd_score_s = pd.Series(2.0, index=out.index)
    macd_falling = ~macd_rising
    macd_falling2 = macd_falling & (macd_h.shift(1) < macd_h.shift(2))
    macd_score_s[macd_falling] = 4.0
    macd_score_s[macd_falling2] = 7.0
    rsi_rising = rsi > rsi.shift(1)
    rsi_score_l = pd.Series(0.0, index=out.index)
    rsi_score_l[rsi_rising] = 5.0
    rsi_score_l[rsi_rising & (rsi < 50)] = 7.0
    rsi_score_s = pd.Series(0.0, index=out.index)
    rsi_score_s[~rsi_rising] = 5.0
    rsi_score_s[(~rsi_rising) & (rsi > 50)] = 7.0
    adx_rising = (adx > adx.shift(1)) & (adx > 20)
    adx_mom_score = pd.Series(0.0, index=out.index)
    adx_mom_score[adx_rising] = 3.0
    vol_mom_score = vol_z.clip(0, 2) / 2 * 3
    momentum_long_score = (macd_score_l + rsi_score_l + adx_mom_score + vol_mom_score).clip(0, 20)
    momentum_short_score = (macd_score_s + rsi_score_s + adx_mom_score + vol_mom_score).clip(0, 20)

    atr_pct_val = atr / close
    stop_dist = atr_pct_val * 2
    stop_score = pd.Series(0.0, index=out.index)
    stop_score[stop_dist < 0.08] = 4.0
    stop_score[stop_dist < 0.05] = 7.0
    stop_score[stop_dist < 0.03] = 10.0
    atr_pct_rank = _rolling_pct_rank(atr_pct_val, 120)
    atr_risk_score = pd.Series(0.0, index=out.index)
    atr_risk_score[(atr_pct_rank >= 0.30) & (atr_pct_rank <= 0.85)] = 5.0
    atr_risk_score[(atr_pct_rank >= 0.35) & (atr_pct_rank <= 0.70)] = 10.0
    risk_score = (stop_score + atr_risk_score).clip(0, 20)

    out["score_breakout_long"] = (market_long_score + pat_breakout_l + momentum_long_score + risk_score).clip(0, 100)
    out["score_pullback_long"] = (market_long_score + pat_pullback_l + momentum_long_score + risk_score).clip(0, 100)
    out["score_meanrev_long"] = (market_long_score + pat_meanrev_l + momentum_long_score + risk_score).clip(0, 100)

    sweep_scores = add_btc_sweep_score_columns(
        out,
        market_long_score,
        market_short_score,
        momentum_long_score,
        momentum_short_score,
        risk_score,
    )
    for col in ["score_sweep_reversal_long", "score_sweep_reversal_short", "_sweep_signal_long", "_sweep_signal_short"]:
        out[col] = sweep_scores[col]

    out["_perp_crowding_long_bonus"] = 0.0

    dc55_high_prev_v2 = out["roll_high_55"].shift(1)
    dc55_low_prev_v2 = out["roll_low_55"].shift(1)
    breakout_level_l = dc55_high_prev_v2
    breakout_level_s = dc55_low_prev_v2
    broke_out_l = close > dc55_high_prev_v2
    broke_out_s = close < dc55_low_prev_v2
    in_retest_zone_l = (close / breakout_level_l - 1).abs() < 0.015
    in_retest_zone_s = (close / breakout_level_s - 1).abs() < 0.015
    retest_bar_l = broke_out_l.shift(1) & in_retest_zone_l
    retest_bar_s = broke_out_s.shift(1) & in_retest_zone_s
    retest_hold_l = retest_bar_l & (out["Low"] > breakout_level_l * 0.995)
    retest_hold_s = retest_bar_s & (out["High"] < breakout_level_s * 1.005)
    retest_break_l = (close > out["High"].shift(1)) & retest_hold_l.shift(1)
    retest_break_s = (close < out["Low"].shift(1)) & retest_hold_s.shift(1)
    bo_strength_l = ((close - breakout_level_l) / atr).clip(0, 3) / 3 * 10
    bo_strength_s = ((breakout_level_s - close) / atr).clip(0, 3) / 3 * 10
    retest_quality_l = pd.Series(0.0, index=out.index)
    retest_quality_l[retest_hold_l] = 10
    retest_quality_l[retest_break_l] = 10
    retest_quality_s = pd.Series(0.0, index=out.index)
    retest_quality_s[retest_hold_s] = 10
    retest_quality_s[retest_break_s] = 10
    pat_retest_l = (bo_strength_l + retest_quality_l).clip(0, 30)
    pat_retest_s = (bo_strength_s + retest_quality_s).clip(0, 30)
    out["score_breakout_retest_long"] = (market_long_score + pat_retest_l + momentum_long_score + risk_score).clip(0, 100)

    ema55_val = out["ema55"]
    ema144_val = out["ema144"]
    pullback_zone_l = (close >= ema55_val * 0.98) & (close <= ema144_val * 1.02)
    pullback_zone_s = (close <= ema55_val * 1.02) & (close >= ema144_val * 0.98)
    pivot_high_pb = (
        (out["High"].shift(4) < out["High"].shift(3))
        & (out["High"].shift(3) < out["High"].shift(2))
        & (out["High"].shift(2) > out["High"].shift(1))
        & (out["High"].shift(1) > out["High"])
    )
    pivot_low_pb = (
        (out["Low"].shift(4) > out["Low"].shift(3))
        & (out["Low"].shift(3) > out["Low"].shift(2))
        & (out["Low"].shift(2) < out["Low"].shift(1))
        & (out["Low"].shift(1) < out["Low"])
    )
    pl_val_pb = pd.Series(np.where(pivot_low_pb, out["Low"].shift(2), np.nan), index=out.index).ffill()
    pl_prev_pb = pl_val_pb.where(pl_val_pb.diff().abs() > 1e-8).shift(1).ffill()
    higher_low = pivot_low_pb & (pl_val_pb > pl_prev_pb) & pl_prev_pb.notna()
    ph_val_pb = pd.Series(np.where(pivot_high_pb, out["High"].shift(2), np.nan), index=out.index).ffill()
    ph_prev_pb = ph_val_pb.where(ph_val_pb.diff().abs() > 1e-8).shift(1).ffill()
    lower_high = pivot_high_pb & (ph_val_pb < ph_prev_pb) & ph_prev_pb.notna()
    has_higher_low = higher_low.rolling(50, min_periods=1).max().astype(bool)
    has_lower_high = lower_high.rolling(50, min_periods=1).max().astype(bool)
    breaks_pb_high = close > out["High"].shift(1)
    breaks_pb_low = close < out["Low"].shift(1)
    pat_struct_l = pd.Series(0.0, index=out.index)
    pat_struct_l[pullback_zone_l] = 8
    pat_struct_l[has_higher_low] = 12
    pat_struct_l[breaks_pb_high] = 10
    pat_struct_s = pd.Series(0.0, index=out.index)
    pat_struct_s[pullback_zone_s] = 8
    pat_struct_s[has_lower_high] = 12
    pat_struct_s[breaks_pb_low] = 10
    out["score_pullback_struct_long"] = (market_long_score + pat_struct_l.clip(0, 30) + momentum_long_score + risk_score).clip(0, 100)
    out["score_pullback_struct_short"] = (market_short_score + pat_struct_s.clip(0, 30) + momentum_short_score + risk_score).clip(0, 100)

    bb_mid_v2 = (out["bb_upper"] + out["bb_lower"]) / 2
    bb_width_v2 = (out["bb_upper"] - out["bb_lower"]) / bb_mid_v2.clip(1e-10)
    bb_width_expanding = bb_width_v2 > bb_width_v2.shift(5)
    dc55_range_v2 = out["roll_high_55"] - out["roll_low_55"]
    within_dc55_v2 = (close > out["roll_low_55"] + 0.05 * dc55_range_v2) & (close < out["roll_high_55"] - 0.05 * dc55_range_v2)
    strict_ranging = (adx < 20) & ~bb_width_expanding & within_dc55_v2
    reclaimed_lower = (out["Low"].shift(1) < out["bb_lower"].shift(1)) & (close > out["bb_lower"])
    reclaimed_upper = (out["High"].shift(1) > out["bb_upper"].shift(1)) & (close < out["bb_upper"])
    lower_wick = (np.minimum(out["Open"], close) - out["Low"]) / (out["High"] - out["Low"]).clip(1e-10)
    upper_wick = (out["High"] - np.maximum(out["Open"], close)) / (out["High"] - out["Low"]).clip(1e-10)
    pat_range_l = pd.Series(0.0, index=out.index)
    pat_range_l[strict_ranging] = 10
    pat_range_l[reclaimed_lower] = 12
    pat_range_l[lower_wick > 0.35] = 8
    pat_range_s = pd.Series(0.0, index=out.index)
    pat_range_s[strict_ranging] = 10
    pat_range_s[reclaimed_upper] = 12
    pat_range_s[upper_wick > 0.35] = 8
    out["score_meanrev_range_long"] = (market_long_score + pat_range_l.clip(0, 30) + momentum_long_score + risk_score).clip(0, 100)
    out["score_meanrev_range_short"] = (market_short_score + pat_range_s.clip(0, 30) + momentum_short_score + risk_score).clip(0, 100)

    short_score = lambda mk, pat, mom, risk: (mk * 35 / 30 + pat + mom * 0.75 + risk * 0.5).clip(0, 100)
    out["score_breakout_short"] = short_score(market_short_score, pat_breakout_s, momentum_short_score, risk_score)
    out["score_pullback_short"] = short_score(market_short_score, pat_pullback_s, momentum_short_score, risk_score)
    out["score_meanrev_short"] = short_score(market_short_score, pat_meanrev_s, momentum_short_score, risk_score)

    crash_scores = add_btc_crash_score_columns(out, market_short_score, risk_score, adx_rising)
    for col in ["_plus_di", "_minus_di", "_late_chase", "score_crash_short", "_crash_short_signal"]:
        out[col] = crash_scores[col]

    short_extension_scores = add_btc_short_extension_score_columns(out, market_short_score, risk_score, adx_rising)
    for col in ["score_failed_bounce_short", "score_bull_trap_short", "_failed_bounce_gate", "_bull_trap_signal"]:
        out[col] = short_extension_scores[col]

    _add_btc_price_action_bonus(out)
    out["_short_deriv_bonus"] = 0.0
    return out


def add_btc_preferred_exit_columns(
    features: pd.DataFrame,
    *,
    stop_atr_multiple: float = 2.0,
    target_atr_multiple: float = 4.0,
) -> pd.DataFrame:
    """Add preview-only ATR stop/target columns for standardized BTC signals."""
    out = features.copy()
    stop_distance = stop_atr_multiple * out["_atr_signal"]
    target_distance = target_atr_multiple * out["_atr_signal"]
    out["_btc_long_stop"] = out["Close"] - stop_distance
    out["_btc_long_target"] = out["Close"] + target_distance
    out["_btc_short_stop"] = out["Close"] + stop_distance
    out["_btc_short_target"] = out["Close"] - target_distance
    return out


def add_btc_crash_score_columns(
    features: pd.DataFrame,
    market_short_score: pd.Series,
    risk_score: pd.Series,
    adx_rising: pd.Series,
) -> pd.DataFrame:
    """Add Crash Short score, DMI helper columns, and standardized gate."""
    out = features.copy()
    close = out["Close"]
    adx = out["_adx_signal"]
    vol_z = out["vol_zscore"]

    true_range = pd.concat([
        out["High"] - out["Low"],
        (out["High"] - out["Close"].shift(1)).abs(),
        (out["Low"] - out["Close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr_di = true_range.ewm(span=14, adjust=False, min_periods=1).mean()
    up_move = out["High"].diff()
    down_move = -out["Low"].diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=out.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=out.index)
    plus_di = 100 * plus_dm.ewm(span=14, adjust=False, min_periods=1).mean() / atr_di
    minus_di = 100 * minus_dm.ewm(span=14, adjust=False, min_periods=1).mean() / atr_di

    close_pos = (close - out["Low"]) / (out["High"] - out["Low"]).clip(1e-10)
    three_down = (close < close.shift(1)) & (close.shift(1) < close.shift(2)) & (close.shift(2) < close.shift(3))
    late_chase = (out["rsi_14"] < 28) | three_down

    di_ratio = (minus_di / plus_di.clip(1e-10)).clip(0, 5)
    di_score = (di_ratio - 1.0).clip(0, 2) * 4
    close_pos_score = (1.0 - close_pos).clip(0, 0.65) / 0.65 * 8
    vol_crash_score = vol_z.clip(0.8, 3) / 3 * 8
    adx_crash_score = (adx.clip(22, 40) - 22) / 18 * 6
    pat_crash = (di_score + close_pos_score + vol_crash_score + adx_crash_score).clip(0, 30)

    crash_mom = pd.Series(0.0, index=out.index)
    crash_mom[adx_rising & (adx > 22)] += 10
    crash_mom[minus_di > plus_di] += 7
    crash_mom[vol_z > 0.8] += 3
    crash_mom = crash_mom.clip(0, 20)

    crash_risk = risk_score.copy()
    crash_risk[late_chase] = 0
    crash_risk[close_pos >= 0.35] *= 0.5

    out["_plus_di"] = plus_di
    out["_minus_di"] = minus_di
    out["_late_chase"] = late_chase
    out["score_crash_short"] = (market_short_score + pat_crash + crash_mom + crash_risk).clip(0, 100)
    return add_btc_score_signal_columns(out)


def add_btc_sweep_signal_columns(features: pd.DataFrame) -> pd.DataFrame:
    """Add liquidity sweep reclaim gates from existing support/resistance features."""
    out = features.copy()
    components = _sweep_components(out)
    out["_sweep_signal_long"] = components["reclaim_long"]
    out["_sweep_signal_short"] = components["reclaim_short"]
    return out


def add_btc_sweep_score_columns(
    features: pd.DataFrame,
    market_long_score: pd.Series,
    market_short_score: pd.Series,
    momentum_long_score: pd.Series,
    momentum_short_score: pd.Series,
    risk_score: pd.Series,
) -> pd.DataFrame:
    """Add Sweep Reversal scores plus standardized reclaim gates."""
    out = features.copy()
    components = _sweep_components(out)
    atr = out["_atr_signal"]
    close = out["Close"]

    lower_wick = (np.minimum(out["Open"], close) - out["Low"]) / (out["High"] - out["Low"]).clip(1e-10)
    upper_wick = (out["High"] - np.maximum(out["Open"], close)) / (out["High"] - out["Low"]).clip(1e-10)
    sweep_depth_l = ((components["key_low"] - out["Low"]) / atr).clip(0, 1.5) / 1.5 * 8
    reclaim_strength_l = ((close - components["key_low"]) / atr).clip(0, 1.5) / 1.5 * 8
    sweep_depth_s = ((out["High"] - components["key_high"]) / atr).clip(0, 1.5) / 1.5 * 8
    reclaim_strength_s = ((components["key_high"] - close) / atr).clip(0, 1.5) / 1.5 * 8
    wick_sweep_l = lower_wick.clip(0.35, 0.7) / 0.35 * 7
    wick_sweep_s = upper_wick.clip(0.35, 0.7) / 0.35 * 7

    pat_sweep_l = pd.Series(0.0, index=out.index)
    pat_sweep_l[components["sweep_low_bar"]] = sweep_depth_l + wick_sweep_l + 7
    pat_sweep_l[components["reclaim_long"]] = reclaim_strength_l + 7
    pat_sweep_l = pat_sweep_l.clip(0, 30)

    pat_sweep_s = pd.Series(0.0, index=out.index)
    pat_sweep_s[components["sweep_high_bar"]] = sweep_depth_s + wick_sweep_s + 7
    pat_sweep_s[components["reclaim_short"]] = reclaim_strength_s + 7
    pat_sweep_s = pat_sweep_s.clip(0, 30)

    out["score_sweep_reversal_long"] = (market_long_score + pat_sweep_l + momentum_long_score + risk_score).clip(0, 100)
    out["score_sweep_reversal_short"] = (market_short_score + pat_sweep_s + momentum_short_score + risk_score).clip(0, 100)
    out["_sweep_signal_long"] = components["reclaim_long"]
    out["_sweep_signal_short"] = components["reclaim_short"]
    return out


def _sweep_components(features: pd.DataFrame) -> dict[str, pd.Series]:
    key_low = np.minimum(features["mr_dc20_low"].shift(1), features["bb_lower"].shift(1))
    key_high = np.maximum(features["mr_dc20_high"].shift(1), features["bb_upper"].shift(1))
    sweep_low_bar = features["Low"] < key_low
    sweep_high_bar = features["High"] > key_high
    return {
        "key_low": key_low,
        "key_high": key_high,
        "sweep_low_bar": sweep_low_bar,
        "sweep_high_bar": sweep_high_bar,
        "reclaim_long": sweep_low_bar & (features["Close"] > key_low),
        "reclaim_short": sweep_high_bar & (features["Close"] < key_high),
    }


def add_btc_short_extension_signal_columns(features: pd.DataFrame) -> pd.DataFrame:
    """Add BTC failed-bounce and bull-trap short gates from existing features."""
    out = features.copy()
    components = _short_extension_components(out)
    out["_failed_bounce_gate"] = components["failed_bounce_gate"]
    out["_bull_trap_signal"] = components["bull_trap_signal"]
    return out


def add_btc_short_extension_score_columns(
    features: pd.DataFrame,
    market_short_score: pd.Series,
    risk_score: pd.Series,
    adx_rising: pd.Series,
) -> pd.DataFrame:
    """Add Failed Bounce and Bull Trap scores plus their standardized gates."""
    out = features.copy()
    components = _short_extension_components(out)

    fb_pattern = pd.Series(0.0, index=out.index)
    fb_pattern[components["price_at_resistance"]] += 10
    fb_pattern[components["rsi_reject"]] += 8
    fb_pattern[components["macd_turn"]] += 5
    fb_pattern[components["upper_wick"]] += 4
    fb_pattern[components["break_low"]] += 3
    fb_pattern = fb_pattern.clip(0, 30)

    fb_mom = pd.Series(0.0, index=out.index)
    fb_mom[components["rsi_reject"]] += 10
    fb_mom[components["macd_turn"]] += 7
    fb_mom[adx_rising & (out["_adx_signal"] > 20)] += 3
    fb_mom = fb_mom.clip(0, 20)

    close_pos = components["close_pos"]
    trap_strength = ((out["High"].shift(1) - components["trap_resistance"]) / out["_atr_signal"]).clip(0, 2) / 2 * 10
    trap_confirm_score = ((components["trap_resistance"] - out["Close"]) / out["_atr_signal"]).clip(0, 2) / 2 * 8
    trap_wick_score = out["_upper_shadow"].clip(0.3, 0.7) / 0.4 * 7
    trap_close_score = (0.4 - close_pos).clip(0, 0.3) / 0.3 * 5
    trap_pattern = (trap_strength + trap_confirm_score + trap_wick_score + trap_close_score).clip(0, 30)
    trap_pattern[~components["trap_confirmed"]] = 0

    trap_mom = pd.Series(0.0, index=out.index)
    trap_mom[components["trap_confirmed"] & components["upper_wick"]] += 8
    trap_mom[components["trap_confirmed"] & components["trap_close_low"]] += 7
    trap_mom[components["trap_confirmed"] & components["trap_vol"]] += 5
    trap_mom = trap_mom.clip(0, 20)

    out["score_failed_bounce_short"] = (market_short_score + fb_pattern + fb_mom + risk_score).clip(0, 100)
    out["score_bull_trap_short"] = (market_short_score + trap_pattern + trap_mom + risk_score).clip(0, 100)
    out["_failed_bounce_gate"] = components["failed_bounce_gate"]
    out["_bull_trap_signal"] = components["bull_trap_signal"]
    return out


def _short_extension_components(features: pd.DataFrame) -> dict[str, pd.Series]:
    close = features["Close"]
    bb_mid = (features["bb_upper"] + features["bb_lower"]) / 2
    rebound_bb = close >= bb_mid
    rebound_ema = (close >= features["ema55"] * 0.995) & (close <= features["ema144"] * 1.01)
    if "in_pullback_zone" in features.columns:
        rebound_zone = features["in_pullback_zone"]
    else:
        in_zone_1 = (close >= np.minimum(features["ema55"], features["ema144"])) & (
            close <= np.maximum(features["ema55"], features["ema144"])
        )
        in_zone_2 = (close >= np.minimum(features["ema69"], features["ema169"])) & (
            close <= np.maximum(features["ema69"], features["ema169"])
        )
        rebound_zone = in_zone_1 | in_zone_2
    price_at_resistance = rebound_zone | rebound_bb | rebound_ema

    rsi = features["rsi_14"]
    rsi_reject = (rsi.shift(1) >= 48) & (rsi.shift(1) <= 62) & (rsi < rsi.shift(1))
    macd_h = features["macd_hist"]
    macd_turn = (macd_h < macd_h.shift(1)) & (macd_h.shift(1) >= macd_h.shift(2))
    upper_wick = features["_upper_shadow"] > 0.35
    break_low = close < features["Low"].shift(1)
    failed_bounce_gate = price_at_resistance & break_low & (
        (rsi_reject.astype(int) + macd_turn.astype(int) + upper_wick.astype(int)) >= 1
    )

    trap_resistance = np.maximum(features["roll_high_55"].shift(1), features["bb_upper"])
    broke_above = features["High"].shift(1) > trap_resistance.shift(1)
    trap_confirmed = broke_above & ((trap_resistance - close) > 0.3 * features["_atr_signal"])
    close_pos = (close - features["Low"]) / (features["High"] - features["Low"]).clip(1e-10)
    trap_close_low = close_pos < 0.50
    trap_vol = features["vol_zscore"].shift(1) > 0.5
    bull_trap_signal = trap_confirmed & upper_wick & trap_close_low & trap_vol

    return {
        "price_at_resistance": price_at_resistance,
        "rsi_reject": rsi_reject,
        "macd_turn": macd_turn,
        "upper_wick": upper_wick,
        "break_low": break_low,
        "failed_bounce_gate": failed_bounce_gate,
        "trap_resistance": trap_resistance,
        "trap_confirmed": trap_confirmed,
        "close_pos": close_pos,
        "trap_close_low": trap_close_low,
        "trap_vol": trap_vol,
        "bull_trap_signal": bull_trap_signal,
    }


def _add_btc_price_action_bonus(features: pd.DataFrame) -> None:
    close = features["Close"]
    high = features["High"]
    low = features["Low"]
    atr = features["_atr_signal"]

    pivot_high = (
        (high.shift(4) < high.shift(3))
        & (high.shift(3) < high.shift(2))
        & (high.shift(2) > high.shift(1))
        & (high.shift(1) > high)
    )
    pivot_low = (
        (low.shift(4) > low.shift(3))
        & (low.shift(3) > low.shift(2))
        & (low.shift(2) < low.shift(1))
        & (low.shift(1) < low)
    )

    ph_val = pd.Series(np.where(pivot_high, high.shift(2), np.nan), index=features.index)
    pl_val = pd.Series(np.where(pivot_low, low.shift(2), np.nan), index=features.index)
    last_ph = ph_val.ffill()
    last_pl = pl_val.ffill()
    new_ph = last_ph.diff().abs() > 1e-8
    new_pl = last_pl.diff().abs() > 1e-8
    prev_ph = last_ph.shift(1).where(new_ph).ffill()
    prev_pl = last_pl.shift(1).where(new_pl).ffill()

    lower_high = new_ph & (last_ph < prev_ph) & prev_ph.notna()
    lower_low = new_pl & (last_pl < prev_pl) & prev_pl.notna()
    features["_bear_structure"] = (lower_high | lower_low).rolling(50, min_periods=1).max().astype(bool)

    swing_range = last_ph - last_pl
    fib_382 = last_pl + 0.382 * swing_range
    fib_618 = last_pl + 0.618 * swing_range
    in_fib_zone = (close >= fib_382) & (close <= fib_618) & (swing_range > atr * 0.5)
    has_rejection = (features["_upper_shadow"] > 0.35) | (close < low.shift(1))
    fib_failed = in_fib_zone & has_rejection & features["_bear_structure"]
    features["_fib_failed_rally"] = fib_failed
    bonus = pd.Series(0.0, index=features.index)
    bonus[fib_failed] += 10
    features["_price_action_bonus"] = bonus.clip(0, 10)

    ph_price = pd.Series(np.where(pivot_high, high.shift(2), np.nan), index=features.index)
    ph_rsi = pd.Series(np.where(pivot_high, features["rsi_14"].shift(2), np.nan), index=features.index)
    ph_macd = pd.Series(np.where(pivot_high, features["macd_hist"].shift(2), np.nan), index=features.index)
    ph1_price = ph_price.ffill()
    ph2_price = ph_price.where(pivot_high).shift(1).ffill()
    ph1_rsi = ph_rsi.ffill()
    ph2_rsi = ph_rsi.where(pivot_high).shift(1).ffill()
    ph1_macd = ph_macd.ffill()
    ph2_macd = ph_macd.where(pivot_high).shift(1).ffill()

    double_top = (
        (ph2_price > 0)
        & (ph1_price > 0)
        & (abs(ph1_price / ph2_price - 1) < 0.03)
        & (ph1_rsi < ph2_rsi)
        & (ph1_macd < ph2_macd)
    )
    neckline_low = last_pl.ffill()
    neckline_break = close < neckline_low
    top_score = pd.Series(0.0, index=features.index)
    top_score[double_top] += 25
    top_score[double_top & (ph1_rsi < ph2_rsi - 3)] += 20
    top_score[double_top] += 15
    top_score[double_top & neckline_break] += 25
    top_score[double_top] += 15
    features["_top_exhaustion_score"] = top_score.clip(0, 100)
    features["_double_top_signal"] = double_top & neckline_break

    d_ema = features["d_ema"]
    d_ema_dir = pd.Series(
        np.where(d_ema.pct_change(1).fillna(0) > 0.001, 1, np.where(d_ema.pct_change(1).fillna(0) < -0.001, -1, 0)),
        index=features.index,
    )
    features["_bull_guard"] = (d_ema_dir > 0) & (close > d_ema)


def _rolling_pct_rank(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=1).apply(
        lambda x: (x <= x.iloc[-1]).sum() / max(len(x), 1),
        raw=False,
    )


def build_btc_signal_modules() -> list[ColumnSignalModule]:
    """Build compatibility signal modules from existing BTC feature columns."""
    return [
        ColumnSignalModule(
            ColumnSignalConfig(
                module="breakout",
                long_column="breakout_long",
                short_column="breakout_short",
                long_score_column="score_breakout_long",
                short_score_column="score_breakout_short",
                long_stop_column="_btc_long_stop",
                short_stop_column="_btc_short_stop",
                long_target_column="_btc_long_target",
                short_target_column="_btc_short_target",
                entry_reason="Donchian breakout",
                invalidation="Close back inside the Donchian channel",
                required_data=("ohlcv:4h", "features:donchian", "features:volatility"),
            )
        ),
        ColumnSignalModule(
            ColumnSignalConfig(
                module="pullback",
                long_column="pullback_long",
                short_column="pullback_short",
                long_score_column="score_pullback_long",
                short_score_column="score_pullback_short",
                long_stop_column="_btc_long_stop",
                short_stop_column="_btc_short_stop",
                long_target_column="_btc_long_target",
                short_target_column="_btc_short_target",
                entry_reason="EMA-zone pullback with momentum confirmation",
                invalidation="Momentum fails or price loses EMA confirmation",
                required_data=("ohlcv:4h", "features:ema", "features:momentum"),
            )
        ),
        ColumnSignalModule(
            ColumnSignalConfig(
                module="meanrev",
                long_column="meanrev_long",
                short_column="meanrev_short",
                long_score_column="score_meanrev_long",
                short_score_column="score_meanrev_short",
                long_stop_column="_btc_long_stop",
                short_stop_column="_btc_short_stop",
                long_target_column="_btc_long_target",
                short_target_column="_btc_short_target",
                entry_reason="Range mean reversion at Bollinger or Donchian extreme",
                invalidation="Range boundary breaks without reclaim",
                required_data=("ohlcv:4h", "features:bollinger", "features:donchian"),
            )
        ),
        ColumnSignalModule(
            ColumnSignalConfig(
                module="sweep_reversal",
                long_column="_sweep_signal_long",
                short_column="_sweep_signal_short",
                long_score_column="score_sweep_reversal_long",
                short_score_column="score_sweep_reversal_short",
                long_stop_column="_btc_long_stop",
                short_stop_column="_btc_short_stop",
                long_target_column="_btc_long_target",
                short_target_column="_btc_short_target",
                entry_reason="Liquidity sweep and reclaim",
                invalidation="Sweep level fails to hold after reclaim",
                required_data=("ohlcv:4h", "features:donchian", "features:price_action"),
            )
        ),
        ColumnSignalModule(
            ColumnSignalConfig(
                module="crash_short",
                short_column="_crash_short_signal",
                short_score_column="score_crash_short",
                short_stop_column="_btc_short_stop",
                short_target_column="_btc_short_target",
                entry_reason="Crash breakdown short",
                invalidation="Breakdown loses downside momentum",
                required_data=("ohlcv:4h", "features:adx", "features:volume", "features:price_action"),
            )
        ),
        ColumnSignalModule(
            ColumnSignalConfig(
                module="failed_bounce",
                short_column="_failed_bounce_gate",
                short_score_column="score_failed_bounce_short",
                short_stop_column="_btc_short_stop",
                short_target_column="_btc_short_target",
                entry_reason="Failed bounce into resistance",
                invalidation="Price reclaims resistance after the failed bounce",
                required_data=("ohlcv:4h", "features:ema", "features:momentum", "features:price_action"),
            )
        ),
        ColumnSignalModule(
            ColumnSignalConfig(
                module="bull_trap",
                short_column="_bull_trap_signal",
                short_score_column="score_bull_trap_short",
                short_stop_column="_btc_short_stop",
                short_target_column="_btc_short_target",
                entry_reason="Bull trap reversal below resistance",
                invalidation="Price reclaims the trap resistance",
                required_data=("ohlcv:4h", "features:donchian", "features:bollinger", "features:volume"),
            )
        ),
    ]


def generate_btc_standard_signals(
    features: pd.DataFrame,
    *,
    symbol: str = "BTC/USDT",
    limit: int | None = None,
) -> list[Signal]:
    """Generate standardized BTC signals from prepared compatibility feature columns."""
    frame = features.tail(limit).copy() if limit is not None and limit > 0 else features
    if {"Close", "_atr_signal"}.issubset(frame.columns) and "_btc_long_stop" not in frame.columns:
        frame = add_btc_preferred_exit_columns(frame)
    return SignalModuleRunner(build_btc_signal_modules()).generate(frame, symbol=symbol)
