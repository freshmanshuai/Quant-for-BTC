from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from backtesting import Backtest, Strategy
from backtesting.lib import FractionalBacktest

from quant_btc.config import BacktestConfig, RiskConfig


# ═══════════════════════════ Signal feature engineering ═══════════════════════════
# These produce boolean entry columns — insensitive to price scaling.


def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False, min_periods=1).mean()


def _macd(close: pd.Series, fast: int, slow: int, signal: int):
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    return macd_line, signal_line


def _htf_ema(close: pd.Series, rule: str, length: int) -> pd.Series:
    htf_close = close.resample(rule).last().ffill()
    htf_ema = _ema(htf_close, length)
    return htf_ema.reindex(close.index, method="ffill")


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(span=period, adjust=False, min_periods=1).mean()
    avg_loss = loss.ewm(span=period, adjust=False, min_periods=1).mean()
    rs = avg_gain / avg_loss.clip(lower=1e-10)
    return 100.0 - 100.0 / (1.0 + rs)


def prepare_features(df: pd.DataFrame, cfg: BacktestConfig) -> pd.DataFrame:
    """Build signal columns.

    Two entry-signal families are produced:

    * ``long_entry`` / ``short_entry`` — original zone-crossing logic (legacy).
    * ``pullback_long`` / ``pullback_short`` — trend-pullback entries (Step 2).
      These require: (a) regime context (checked in Strategy.next),
      (b) price in EMA pullback zone, (c) momentum confirmation (RSI or MACD
      histogram), and (d) bar-level price confirmation.
    """
    out = df.copy()

    # -- EMAs --
    out["ema55"] = _ema(out["Close"], cfg.ema_fast_1)
    out["ema69"] = _ema(out["Close"], cfg.ema_fast_2)
    out["ema144"] = _ema(out["Close"], cfg.ema_slow_1)
    out["ema169"] = _ema(out["Close"], cfg.ema_slow_2)

    # -- MACD --
    out["macd"], out["macd_signal"] = _macd(
        out["Close"], fast=cfg.macd_fast, slow=cfg.macd_slow, signal=cfg.macd_signal
    )
    out["macd_hist"] = out["macd"] - out["macd_signal"]

    # -- HTF EMA --
    out["d_ema"] = _htf_ema(out["Close"], "1D", cfg.daily_ema_len)
    out["w_ema"] = _htf_ema(out["Close"], "1W", cfg.weekly_ema_len)

    # -- RSI(14) --
    out["rsi_14"] = _rsi(out["Close"], 14)

    # ═══════════ Legacy entry signals (unchanged) ═══════════
    zone_low = np.minimum(out["ema144"], out["ema169"])
    zone_high = np.maximum(out["ema144"], out["ema169"])
    in_zone = (out["Close"] >= zone_low) & (out["Close"] <= zone_high)

    ema_bear_struct = (out["ema144"] > out["ema69"]) & (out["ema169"] > out["ema55"])
    ema_bull_struct = (out["ema144"] < out["ema69"]) & (out["ema169"] < out["ema55"])

    first_enter_short = (out["Close"].shift(1) < zone_low.shift(1)) & in_zone
    first_enter_long = (out["Close"].shift(1) > zone_high.shift(1)) & in_zone

    out["ema_long_signal"] = ema_bull_struct & first_enter_long
    out["ema_short_signal"] = ema_bear_struct & first_enter_short

    out["macd_long_signal"] = (out["macd"] > out["macd_signal"]) & (
        out["macd"].shift(1) <= out["macd_signal"].shift(1)
    )
    out["macd_short_signal"] = (out["macd"] < out["macd_signal"]) & (
        out["macd"].shift(1) >= out["macd_signal"].shift(1)
    )

    out["long_score"] = (
        out["ema_long_signal"].astype(int) * cfg.ema_weight
        + out["macd_long_signal"].astype(int) * cfg.macd_weight
    )
    out["short_score"] = (
        out["ema_short_signal"].astype(int) * cfg.ema_weight
        + out["macd_short_signal"].astype(int) * cfg.macd_weight
    )

    out["major_bull"] = (out["Close"] > out["d_ema"]) & (out["Close"] > out["w_ema"])
    out["major_bear"] = (out["Close"] < out["d_ema"]) & (out["Close"] < out["w_ema"])

    out["long_entry"] = out["major_bull"] & (out["long_score"] >= cfg.signal_threshold)
    out["short_entry"] = out["major_bear"] & (out["short_score"] >= cfg.signal_threshold)

    # ═══════════ Pullback entry signals (Step 2) ═══════════

    # -- Pullback zone: price between EMA55-EMA144  OR  EMA69-EMA169 --
    in_zone_1 = (out["Close"] >= np.minimum(out["ema55"], out["ema144"])) & (
        out["Close"] <= np.maximum(out["ema55"], out["ema144"])
    )
    in_zone_2 = (out["Close"] >= np.minimum(out["ema69"], out["ema169"])) & (
        out["Close"] <= np.maximum(out["ema69"], out["ema169"])
    )
    out["in_pullback_zone"] = in_zone_1 | in_zone_2

    # -- MACD histogram rising/falling for 2 consecutive bars --
    hist = out["macd_hist"]
    out["macd_hist_rising2"] = (hist > hist.shift(1)) & (hist.shift(1) > hist.shift(2))
    out["macd_hist_falling2"] = (hist < hist.shift(1)) & (hist.shift(1) < hist.shift(2))

    # -- RSI momentum: RSI rising from 40–50 zone  /  falling from 50–60 zone --
    rsi = out["rsi_14"]
    out["rsi_bull_setup"] = (
        (rsi.shift(1) >= 40) & (rsi.shift(1) <= 50) & (rsi > rsi.shift(1))
    )
    out["rsi_bear_setup"] = (
        (rsi.shift(1) >= 50) & (rsi.shift(1) <= 60) & (rsi < rsi.shift(1))
    )

    # -- Price confirmation --
    out["break_prev_high"] = out["Close"] > out["High"].shift(1)
    out["break_prev_low"] = out["Close"] < out["Low"].shift(1)
    out["close_above_ema55"] = out["Close"] > out["ema55"]
    out["close_below_ema55"] = out["Close"] < out["ema55"]

    # -- Momentum confirmation (RSI OR MACD histogram) --
    bull_momentum = out["rsi_bull_setup"] | out["macd_hist_rising2"]
    bear_momentum = out["rsi_bear_setup"] | out["macd_hist_falling2"]

    # -- Final pullback entry signals (regime filter applied in Strategy.next) --
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

    # ═══════════ Donchian Breakout signals (Step 3) ═══════════
    out["roll_high_55"] = out["High"].rolling(55, min_periods=1).max()
    out["roll_low_55"] = out["Low"].rolling(55, min_periods=1).min()

    # Volume expansion
    out["vol_sma_50"] = out["Volume"].rolling(50, min_periods=1).mean()
    out["vol_std_50"] = out["Volume"].rolling(50, min_periods=1).std()
    out["vol_zscore"] = (out["Volume"] - out["vol_sma_50"]) / out["vol_std_50"].clip(lower=1e-10)
    vol_expand = (out["Volume"] > out["vol_sma_50"]) | (out["vol_zscore"] > 0)

    # ADX in prepare_features (scale-invariant, used for entry signals)
    out["_adx_signal"] = _build_adx(out["High"], out["Low"], out["Close"], 14)
    adx_rising = (
        (out["_adx_signal"] > out["_adx_signal"].shift(1))
        & (out["_adx_signal"].shift(1) > out["_adx_signal"].shift(2))
    )
    adx_ok = (out["_adx_signal"] > 20) | adx_rising

    # ATR & percentile (for breakout signals & scoring)
    out["_atr_signal"] = _build_atr(out["High"], out["Low"], out["Close"], 14)
    _atr_ratio = out["_atr_signal"] / out["Close"]
    _atr_pct = _rolling_pct_rank(_atr_ratio, 120)
    atr_range_ok = (_atr_pct >= 0.30) & (_atr_pct <= 0.85)

    # Breakout long
    out["breakout_long"] = (
        (out["Close"] > out["roll_high_55"].shift(1))  # Donchian breakout (no look-ahead)
        & vol_expand
        & adx_ok
        & atr_range_ok
        & (out["Close"] > out["ema55"])
    )

    # Breakout short
    out["breakout_short"] = (
        (out["Close"] < out["roll_low_55"].shift(1))
        & vol_expand
        & adx_ok
        & (out["Close"] < out["ema55"])
    )

    # ═══════════ Mean Reversion signals (Step 4) ═══════════

    # Bollinger Bands (20, 2)
    bb_mid = out["Close"].rolling(20, min_periods=1).mean()
    bb_std = out["Close"].rolling(20, min_periods=1).std()
    out["bb_upper"] = bb_mid + 2 * bb_std
    out["bb_lower"] = bb_mid - 2 * bb_std

    # Donchian 20 (for mean reversion range detection)
    out["mr_dc20_high"] = out["High"].rolling(20, min_periods=1).max()
    out["mr_dc20_low"] = out["Low"].rolling(20, min_periods=1).min()

    # Donchian 55 (for breakout detection — not broken = ranging)
    dc55_range = out["roll_high_55"] - out["roll_low_55"]
    dc55_mid = (out["roll_high_55"] + out["roll_low_55"]) / 2
    within_dc55 = (
        (out["Close"] > out["roll_low_55"] + 0.05 * dc55_range)
        & (out["Close"] < out["roll_high_55"] - 0.05 * dc55_range)
    )

    # Price near extremes
    near_bb_lower = out["Close"] <= out["bb_lower"] * 1.005
    near_bb_upper = out["Close"] >= out["bb_upper"] * 0.995
    near_dc20_low = out["Close"] <= out["mr_dc20_low"] * 1.005
    near_dc20_high = out["Close"] >= out["mr_dc20_high"] * 0.995

    # RSI zone (oversold / overbought — no cross required)
    rsi_oversold = out["rsi_14"] < 35
    rsi_overbought = out["rsi_14"] > 65

    # Candlestick: lower / upper shadow
    candle_range = (out["High"] - out["Low"]).clip(lower=1e-10)
    lower_shadow = (np.minimum(out["Open"], out["Close"]) - out["Low"]) / candle_range
    upper_shadow = (out["High"] - np.maximum(out["Open"], out["Close"])) / candle_range
    has_lower_wick = lower_shadow > 0.35
    out["_upper_shadow"] = upper_shadow
    has_upper_wick = upper_shadow > 0.35

    # Low ADX for ranging (relaxed threshold for BTC)
    low_adx = out["_adx_signal"] < 25

    # Mean reversion long
    out["meanrev_long"] = (
        low_adx
        & within_dc55
        & (near_bb_lower | near_dc20_low)
        & rsi_oversold
        & (has_lower_wick | (out["Close"] > out["Low"].shift(1)))
    )

    # Mean reversion short
    out["meanrev_short"] = (
        low_adx
        & within_dc55
        & (near_bb_upper | near_dc20_high)
        & rsi_overbought
        & (has_upper_wick | (out["Close"] < out["High"].shift(1)))
    )

    # ═══════════ Scoring System (Step 6) ═══════════
    _add_score_columns(out)

    return out.dropna().copy()


def _add_score_columns(df: pd.DataFrame):
    """Compute 0-100 quality scores for each module × direction.

    Four components: Market State (30) + Pattern (30) + Momentum (20) + Risk (20).
    """
    close = df["Close"]
    atr = df["_atr_signal"]
    adx = df["_adx_signal"]
    rsi = df["rsi_14"]
    macd_h = df["macd_hist"]
    vol_z = df["vol_zscore"]

    # HTF EMA direction
    d_ema = df["d_ema"]
    w_ema = df["w_ema"]
    d_dir = pd.Series(
        np.where(d_ema.pct_change(1).fillna(0) > 0.001, 1,
                 np.where(d_ema.pct_change(1).fillna(0) < -0.001, -1, 0)),
        index=df.index,
    )
    w_dir = pd.Series(
        np.where(w_ema.pct_change(1).fillna(0) > 0.001, 1,
                 np.where(w_ema.pct_change(1).fillna(0) < -0.001, -1, 0)),
        index=df.index,
    )

    # ── 1. Market State Score (0-30) ──
    mk_long = pd.Series(10.0, index=df.index)  # base: neutral
    mk_short = pd.Series(10.0, index=df.index)

    # Bull alignment: d_dir>0, w_dir>=0 → long favored
    bull = (d_dir > 0) & (w_dir >= 0)
    mk_long[bull] = 28.0
    mk_short[bull] = 2.0

    # Strong bull: close > d_ema too
    strong_bull = bull & (close > d_ema)
    mk_long[strong_bull] = 30.0
    mk_short[strong_bull] = 0.0

    # Bear alignment
    bear = (d_dir < 0) & (w_dir <= 0)
    mk_long[bear] = 2.0
    mk_short[bear] = 28.0

    strong_bear = bear & (close < d_ema)
    mk_long[strong_bear] = 0.0
    mk_short[strong_bear] = 30.0

    # Soft bullish (d_dir >= 0)
    soft_bull = (d_dir >= 0) & ~bull
    mk_long[soft_bull] = 20.0
    mk_short[soft_bull] = 10.0

    # Soft bearish
    soft_bear = (d_dir <= 0) & ~bear & ~soft_bull
    mk_long[soft_bear] = 10.0
    mk_short[soft_bear] = 20.0

    # ── 2. Pattern / Position Score (0-30) ──

    # -- Breakout pattern --
    dc55_range = df["roll_high_55"] - df["roll_low_55"]
    dc55_prev_high = df["roll_high_55"].shift(1)
    dc55_prev_low = df["roll_low_55"].shift(1)

    # Breakout strength
    break_strength_l = ((close - dc55_prev_high) / dc55_range.clip(1e-10)).clip(0, 0.05) * 300
    break_strength_s = ((dc55_prev_low - close) / dc55_range.clip(1e-10)).clip(0, 0.05) * 300

    # Volume contribution
    vol_score = vol_z.clip(0, 3) * 3.33  # 0-10

    # ADX contribution
    adx_score = (adx.clip(20, 45) - 20) / 25 * 5  # 0-5

    pat_breakout_l = (break_strength_l.clip(0, 15) + vol_score.clip(0, 10) + adx_score.clip(0, 5)).clip(0, 30)
    pat_breakout_s = (break_strength_s.clip(0, 15) + vol_score.clip(0, 10) + adx_score.clip(0, 5)).clip(0, 30)

    # -- Pullback pattern --
    # Quality of pullback: how close to center of EMA zone
    ema_zone_center = (df["ema55"] + df["ema144"]) / 2
    ema_zone_width = (df["ema55"] - df["ema144"]).abs().clip(1e-10)
    dist_to_center = (close - ema_zone_center).abs() / ema_zone_width
    zone_quality = (1.0 - dist_to_center.clip(0, 1)) * 15  # 0-15

    # RSI position for pullback
    rsi_pb_l = pd.Series(0.0, index=df.index)
    rsi_pb_l[(rsi >= 30) & (rsi < 55)] = 10
    rsi_pb_l[(rsi >= 35) & (rsi < 50)] = 15
    rsi_pb_s = pd.Series(0.0, index=df.index)
    rsi_pb_s[(rsi > 45) & (rsi <= 70)] = 10
    rsi_pb_s[(rsi > 50) & (rsi <= 65)] = 15

    pat_pullback_l = (zone_quality + rsi_pb_l).clip(0, 30)
    pat_pullback_s = (zone_quality + rsi_pb_s).clip(0, 30)

    # -- Mean reversion pattern --
    bb_lower = df["bb_lower"]
    bb_upper = df["bb_upper"]
    bb_range = (bb_upper - bb_lower).clip(1e-10)
    dist_lower = (close - bb_lower).clip(0, None) / bb_range * 100
    dist_upper = (bb_upper - close).clip(0, None) / bb_range * 100

    extreme_score_l = (15.0 - dist_lower * 3).clip(0, 15)  # closer to lower = better
    extreme_score_s = (15.0 - dist_upper * 3).clip(0, 15)

    # Wick score (recompute from OHLC)
    candle_rng = (df["High"] - df["Low"]).clip(1e-10)
    l_shadow = (np.minimum(df["Open"], close) - df["Low"]) / candle_rng
    u_shadow = (df["High"] - np.maximum(df["Open"], close)) / candle_rng
    wick_l_score = l_shadow.clip(0.35, 0.7) * 15 / 0.35 - 15
    wick_s_score = u_shadow.clip(0.35, 0.7) * 15 / 0.35 - 15

    pat_meanrev_l = (extreme_score_l + wick_l_score).clip(0, 30)
    pat_meanrev_s = (extreme_score_s + wick_s_score).clip(0, 30)

    # ── 3. Momentum Score (0-20) ──
    # MACD histogram: rising 2 bars = 7, rising 1 = 4, flat = 2, falling = 0
    macd_rising = (macd_h > macd_h.shift(1))
    macd_rising2 = macd_rising & macd_h.shift(1) > macd_h.shift(2)
    macd_score_l = pd.Series(2.0, index=df.index)
    macd_score_l[macd_rising] = 4.0
    macd_score_l[macd_rising2] = 7.0
    macd_score_s = pd.Series(2.0, index=df.index)
    macd_falling = ~macd_rising
    macd_falling2 = macd_falling & (macd_h.shift(1) < macd_h.shift(2))
    macd_score_s[macd_falling] = 4.0
    macd_score_s[macd_falling2] = 7.0

    # RSI momentum
    rsi_rising = rsi > rsi.shift(1)
    rsi_score_l = pd.Series(0.0, index=df.index)
    rsi_score_l[rsi_rising] = 5.0
    rsi_score_l[rsi_rising & (rsi < 50)] = 7.0
    rsi_score_s = pd.Series(0.0, index=df.index)
    rsi_score_s[~rsi_rising] = 5.0
    rsi_score_s[(~rsi_rising) & (rsi > 50)] = 7.0

    # ADX momentum
    adx_rising = (adx > adx.shift(1)) & (adx > 20)
    adx_mom_score = pd.Series(0.0, index=df.index)
    adx_mom_score[adx_rising] = 3.0

    # Volume momentum
    vol_mom_score = vol_z.clip(0, 2) / 2 * 3  # 0-3

    mom_l = (macd_score_l + rsi_score_l + adx_mom_score + vol_mom_score).clip(0, 20)
    mom_s = (macd_score_s + rsi_score_s + adx_mom_score + vol_mom_score).clip(0, 20)

    # ── 4. Risk / Reward Score (0-20) ──
    # Stop distance: 2-3% ATR → 10pts, 3-5% → 7, 5-8% → 4, >8% → 0
    atr_pct_val = atr / close
    stop_dist = atr_pct_val * 2  # approximate stop at 2× ATR
    stop_score = pd.Series(0.0, index=df.index)
    stop_score[stop_dist < 0.08] = 4.0
    stop_score[stop_dist < 0.05] = 7.0
    stop_score[stop_dist < 0.03] = 10.0

    # ATR percentile risk
    atr_pct_rank = _rolling_pct_rank(atr_pct_val, 120)
    atr_risk_score = pd.Series(0.0, index=df.index)
    atr_risk_score[(atr_pct_rank >= 0.30) & (atr_pct_rank <= 0.85)] = 5.0
    atr_risk_score[(atr_pct_rank >= 0.35) & (atr_pct_rank <= 0.70)] = 10.0

    risk_score = (stop_score + atr_risk_score).clip(0, 20)

    # ── Combine: long scores (30/30/20/20) ──
    df["score_breakout_long"] = (mk_long + pat_breakout_l + mom_l + risk_score).clip(0, 100)
    df["score_pullback_long"] = (mk_long + pat_pullback_l + mom_l + risk_score).clip(0, 100)
    df["score_meanrev_long"] = (mk_long + pat_meanrev_l + mom_l + risk_score).clip(0, 100)

    # ── Short scores: asymmetric weights (35/30/15/10) + deriv (10, added later) ──
    # Bear context dominates, momentum de-weighted, risk tighter.
    _ss = lambda mk, pat, mom, risk: (
        mk * 35 / 30 + pat + mom * 0.75 + risk * 0.5
    ).clip(0, 100)

    df["score_breakout_short"] = _ss(mk_short, pat_breakout_s, mom_s, risk_score)
    df["score_pullback_short"] = _ss(mk_short, pat_pullback_s, mom_s, risk_score)
    df["score_meanrev_short"] = _ss(mk_short, pat_meanrev_s, mom_s, risk_score)

    # ── Crash Breakdown Short (upgraded breakout short) ──
    # DMI: +DI / -DI
    _tr = pd.concat([df["High"] - df["Low"],
                     (df["High"] - df["Close"].shift(1)).abs(),
                     (df["Low"] - df["Close"].shift(1)).abs()], axis=1).max(axis=1)
    _atr_di = _tr.ewm(span=14, adjust=False, min_periods=1).mean()
    _up = df["High"].diff()
    _down = -df["Low"].diff()
    _plus_dm = pd.Series(np.where((_up > _down) & (_up > 0), _up, 0.0), index=df.index)
    _minus_dm = pd.Series(np.where((_down > _up) & (_down > 0), _down, 0.0), index=df.index)
    _plus_di = 100 * _plus_dm.ewm(span=14, adjust=False, min_periods=1).mean() / _atr_di
    _minus_di = 100 * _minus_dm.ewm(span=14, adjust=False, min_periods=1).mean() / _atr_di
    df["_plus_di"] = _plus_di
    df["_minus_di"] = _minus_di

    # Close position in bar (0=low, 1=high)
    bar_range = (df["High"] - df["Low"]).clip(1e-10)
    close_pos = (close - df["Low"]) / bar_range
    close_near_low = close_pos < 0.35

    # Late chase: RSI < 28 OR 3+ consecutive lower closes
    three_down = (close < close.shift(1)) & (close.shift(1) < close.shift(2)) & (close.shift(2) < close.shift(3))
    late_chase = (rsi < 28) | three_down

    # Crash breakdown pattern score (0-30)
    di_ratio = (_minus_di / _plus_di.clip(1e-10)).clip(0, 5)
    di_score = (di_ratio - 1.0).clip(0, 2) * 4  # -DI > +DI → up to 8 pts
    close_pos_score = (1.0 - close_pos).clip(0, 0.65) / 0.65 * 8  # closer to low = better, up to 8 pts
    vol_crash_score = vol_z.clip(0.8, 3) / 3 * 8  # high vol, up to 8 pts
    adx_crash_score = (adx.clip(22, 40) - 22) / 18 * 6  # ADX strength, up to 6 pts
    pat_crash = (di_score + close_pos_score + vol_crash_score + adx_crash_score).clip(0, 30)

    # Crash momentum (0-20): ADX rising + -DI dominance
    adx_crash_rising = adx_rising & (adx > 22)
    crash_mom = pd.Series(0.0, index=df.index)
    crash_mom[adx_crash_rising] += 10
    crash_mom[_minus_di > _plus_di] += 7
    crash_mom[vol_z > 0.8] += 3
    crash_mom = crash_mom.clip(0, 20)

    # Crash risk (0-20)
    crash_risk = risk_score.copy()
    crash_risk[late_chase] = 0  # late chase → no risk score
    crash_risk[close_pos >= 0.35] *= 0.5  # weak close → half risk score

    df["score_crash_short"] = _ss(mk_short, pat_crash, crash_mom, crash_risk)

    # Late chase flag for master filter reference
    df["_late_chase"] = late_chase

    # ── Failed Bounce Short (upgraded pullback short, Step 4) ──
    # Price rebound to resistance
    _bb_mid = (df["bb_upper"] + df["bb_lower"]) / 2
    rebound_bb = close >= _bb_mid
    rebound_ema = (close >= df["ema55"] * 0.995) & (close <= df["ema144"] * 1.01)
    rebound_zone = df["in_pullback_zone"]  # price between EMA55-144 or EMA69-169
    price_at_resistance = rebound_zone | rebound_bb | rebound_ema

    # RSI rejection: was 48-62, now falling
    rsi_reject = (
        (rsi.shift(1) >= 48) & (rsi.shift(1) <= 62) & (rsi < rsi.shift(1))
    )

    # MACD histogram turning down (was rising/stable, now falling)
    macd_turn = (macd_h < macd_h.shift(1)) & (macd_h.shift(1) >= macd_h.shift(2))

    # Upper wick
    _u_shadow = df["_upper_shadow"]
    upper_wick = _u_shadow > 0.35

    # Close breaks previous low
    break_low = close < df["Low"].shift(1)

    # Failed bounce pattern score (0-30)
    fb_pattern = pd.Series(0.0, index=df.index)
    fb_pattern[price_at_resistance] += 10  # at resistance zone
    fb_pattern[rsi_reject] += 8             # RSI rejection
    fb_pattern[macd_turn] += 5              # MACD turning
    fb_pattern[upper_wick] += 4             # wick confirmation
    fb_pattern[break_low] += 3              # breaks previous low
    fb_pattern = fb_pattern.clip(0, 30)

    # Failed bounce momentum (0-20): RSI rejection + MACD turn
    fb_mom = pd.Series(0.0, index=df.index)
    fb_mom[rsi_reject] += 10
    fb_mom[macd_turn] += 7
    fb_mom[adx_rising & (adx > 20)] += 3
    fb_mom = fb_mom.clip(0, 20)

    df["score_failed_bounce_short"] = (mk_short + fb_pattern + fb_mom + risk_score).clip(0, 100)

    # Failed bounce gate: MUST be at resistance + break low, PLUS >=1 momentum
    fb_must = price_at_resistance & break_low  # structural must-haves
    fb_momentum = (rsi_reject.astype(int) + macd_turn.astype(int) + upper_wick.astype(int)) >= 1
    df["_failed_bounce_gate"] = fb_must & fb_momentum

    # ── Bull Trap Short (Step 5) ──
    # Price breaks above significant resistance, then reverses sharply.
    # Must NOT be in Strong Bull.  Uses DC55 + BB upper as resistance.
    dc55_high_prev = df["roll_high_55"].shift(1)
    bb_upper_val = df["bb_upper"]
    trap_resistance = np.maximum(dc55_high_prev, bb_upper_val)
    # Breakout bar: high penetrated resistance
    broke_above = df["High"].shift(1) > trap_resistance.shift(1)
    # Trap bar: close back BELOW resistance by > 0.3× ATR (significant reversal)
    trap_confirmed = broke_above & ((trap_resistance - close) > 0.3 * atr)
    # Upper wick on trap bar
    trap_wick = _u_shadow > 0.35
    # Close in lower half of bar
    trap_close_low = close_pos < 0.50
    # Volume on breakout bar was above average
    trap_vol = vol_z.shift(1) > 0.5

    # Bull trap pattern score (0-30)
    trap_strength = ((df["High"].shift(1) - trap_resistance) / atr).clip(0, 2) / 2 * 10  # how far above resistance
    trap_confirm_score = ((trap_resistance - close) / atr).clip(0, 2) / 2 * 8  # how far back below
    trap_wick_score = _u_shadow.clip(0.3, 0.7) / 0.4 * 7  # rejection wick
    trap_close_score = (0.4 - close_pos).clip(0, 0.3) / 0.3 * 5  # closed near low
    trap_pattern = (trap_strength + trap_confirm_score + trap_wick_score + trap_close_score).clip(0, 30)
    trap_pattern[~trap_confirmed] = 0

    # Bull trap momentum (0-20)
    trap_mom = pd.Series(0.0, index=df.index)
    trap_mom[trap_confirmed & trap_wick] += 8
    trap_mom[trap_confirmed & trap_close_low] += 7
    trap_mom[trap_confirmed & trap_vol] += 5
    trap_mom = trap_mom.clip(0, 20)

    df["score_bull_trap_short"] = _ss(mk_short, trap_pattern, trap_mom, risk_score)
    df["_bull_trap_signal"] = trap_confirmed & trap_wick & trap_close_low & trap_vol  # strict gate

    # ── Price Action: Swing Structure + Fibonacci (Step 10) ──
    _compute_price_action_bonus(df)

    # ── Derivative Bonus placeholder ──
    df["_short_deriv_bonus"] = 0.0


def _compute_price_action_bonus(df: pd.DataFrame):
    """Add swing structure + Fibonacci columns for short quality bonus."""
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    atr = df["_atr_signal"]

    # ── Fractal Pivots (confirmed 2 bars after) ──
    pivot_high = (
        (high.shift(4) < high.shift(3)) & (high.shift(3) < high.shift(2))
        & (high.shift(2) > high.shift(1)) & (high.shift(1) > high)
    )
    pivot_low = (
        (low.shift(4) > low.shift(3)) & (low.shift(3) > low.shift(2))
        & (low.shift(2) < low.shift(1)) & (low.shift(1) < low)
    )

    # Pivot values (at the pivot bar, shifted 2 for confirmation lag)
    ph_val = pd.Series(np.where(pivot_high, high.shift(2), np.nan), index=df.index)
    pl_val = pd.Series(np.where(pivot_low, low.shift(2), np.nan), index=df.index)

    # Forward-fill to get most recent pivot
    last_ph = ph_val.ffill()
    last_pl = pl_val.ffill()

    # Previous distinct pivot: detect when ffill changes (new pivot), capture previous value
    new_ph = last_ph.diff().abs() > 1e-8
    new_pl = last_pl.diff().abs() > 1e-8
    prev_ph = last_ph.shift(1).where(new_ph).ffill()
    prev_pl = last_pl.shift(1).where(new_pl).ffill()

    # Structure detection
    lower_high = new_ph & (last_ph < prev_ph) & prev_ph.notna()
    lower_low = new_pl & (last_pl < prev_pl) & prev_pl.notna()
    # Bear structure: recent lower high AND lower low confirmed
    bear_struct_event = lower_high | lower_low
    df["_bear_structure"] = bear_struct_event.rolling(50, min_periods=1).max().astype(bool)

    # ── Fibonacci Failed Rally ──
    swing_range = last_ph - last_pl
    fib_382 = last_pl + 0.382 * swing_range
    fib_500 = last_pl + 0.500 * swing_range
    fib_618 = last_pl + 0.618 * swing_range

    in_fib_zone = (close >= fib_382) & (close <= fib_618) & (swing_range > atr * 0.5)
    _upper_shadow_col = df["_upper_shadow"]
    has_rejection = (_upper_shadow_col > 0.35) | (close < low.shift(1))
    fib_failed = in_fib_zone & has_rejection & df["_bear_structure"]
    df["_fib_failed_rally"] = fib_failed

    # ── Bonus: bear structure +5, fib failed rally +5 more ──
    bonus = pd.Series(0.0, index=df.index)
    bonus[df["_bear_structure"]] += 0
    bonus[fib_failed] += 10
    df["_price_action_bonus"] = bonus.clip(0, 10)

    # ── Double Top / Top Exhaustion Detection ──
    # Track last 3 pivot highs with their prices, RSI, MACD hist
    ph_mask = pivot_high
    ph_price = pd.Series(np.where(ph_mask, high.shift(2), np.nan), index=df.index)
    ph_rsi = pd.Series(np.where(ph_mask, df["rsi_14"].shift(2), np.nan), index=df.index)
    ph_macd = pd.Series(np.where(ph_mask, df["macd_hist"].shift(2), np.nan), index=df.index)

    # Get last 2 pivot highs (forward-filled)
    ph1_price = ph_price.ffill()  # most recent pivot high
    ph2_price = ph_price.where(ph_mask).shift(1).ffill()  # previous pivot high
    ph1_rsi = ph_rsi.ffill()
    ph2_rsi = ph_rsi.where(ph_mask).shift(1).ffill()
    ph1_macd = ph_macd.ffill()
    ph2_macd = ph_macd.where(ph_mask).shift(1).ffill()

    # Double top: two pivot highs within 3% of each other
    double_top = (
        (ph2_price > 0) & (ph1_price > 0)
        & (abs(ph1_price / ph2_price - 1) < 0.03)
        & (ph1_rsi < ph2_rsi)  # RSI divergence
        & (ph1_macd < ph2_macd)  # MACD divergence
    )
    # Neckline: lowest low between the two tops
    neckline_low = last_pl.ffill()  # most recent pivot low between the tops
    neckline_break = close < neckline_low

    # Top exhaustion score (0-100)
    top_score = pd.Series(0.0, index=df.index)
    top_score[double_top] += 25  # double/triple top structure
    top_score[double_top & (ph1_rsi < ph2_rsi - 3)] += 20  # RSI/MACD divergence
    top_score[double_top] += 15  # second top weakness (RSI already checked above)
    top_score[double_top & neckline_break] += 25  # neckline break
    top_score[double_top] += 15  # funding/OI (handled by deriv bonus separately)
    df["_top_exhaustion_score"] = top_score.clip(0, 100)
    df["_double_top_signal"] = double_top & neckline_break

    # Bull Guard: structural bull market → block shorts
    _d_ema = df["d_ema"]
    _d_ema_dir_pa = pd.Series(
        np.where(_d_ema.pct_change(1).fillna(0) > 0.001, 1,
                 np.where(_d_ema.pct_change(1).fillna(0) < -0.001, -1, 0)),
        index=df.index,
    )
    df["_bull_guard"] = (_d_ema_dir_pa > 0) & (close > _d_ema)


def compute_derivative_bonus(df: pd.DataFrame, deriv_df: pd.DataFrame | None) -> pd.Series:
    """Return derivative bonus Series (0-20) aligned to df.index.

    Call AFTER prepare_features().dropna() so NaN in derivative data
    doesn't drop valid signal rows.
    """
    bonus = pd.Series(0.0, index=df.index)

    if deriv_df is None or deriv_df.empty:
        return bonus

    # Align derivative data to feature DataFrame index
    fr = deriv_df["funding_rate"].reindex(df.index, method="ffill") if "funding_rate" in deriv_df.columns else pd.Series(0.0, index=df.index)
    oi = deriv_df["open_interest"].reindex(df.index, method="ffill") if "open_interest" in deriv_df.columns else pd.Series(0.0, index=df.index)
    close = df["Close"]

    # Funding rate z-score (90-period, min 30 bars for stability)
    fr_sma = fr.rolling(90, min_periods=30).mean()
    fr_std = fr.rolling(90, min_periods=30).std()
    funding_z = ((fr - fr_sma) / fr_std.clip(1e-10)).fillna(0)

    # 24h changes (6 × 4h bars)
    oi_change = oi.pct_change(6).fillna(0)
    price_change = close.pct_change(6).fillna(0)

    # Crowded longs: high funding + OI rising + price stalled
    crowded = (funding_z > 1.5) & (oi_change > 0.05) & (price_change < 0.02)

    # Deleveraging: price < DC20 low (shifted) + OI dropping fast
    dc20_low = close.rolling(20, min_periods=1).min()
    delever = (close < dc20_low.shift(1)) & (oi_change < -0.03)

    bonus[crowded] += 10
    bonus[delever] += 10
    return bonus.clip(0, 20)


# ═══════════════════ Risk feature helpers (called from Strategy.init) ═══════════════════


def _build_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    tr = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(span=period, adjust=False, min_periods=1).mean()


def _build_daily_prev_hl(
    high: pd.Series, low: pd.Series, index: pd.DatetimeIndex, lookback: int
) -> tuple[pd.Series, pd.Series]:
    """N-day rolling highest-high / lowest-low of completed daily candles."""
    d_high = high.resample("1D").max()
    d_low = low.resample("1D").min()
    roll_high = d_high.rolling(lookback, min_periods=1).max().shift(1)
    roll_low = d_low.rolling(lookback, min_periods=1).min().shift(1)
    return (
        roll_high.reindex(index, method="ffill"),
        roll_low.reindex(index, method="ffill"),
    )


def _build_ema_dir(close: pd.Series, rule: str, length: int) -> pd.Series:
    """+1 rising, -1 falling, 0 flat."""
    htf_close = close.resample(rule).last().ffill()
    htf_ema = _ema(htf_close, length)
    htf_ema_re = htf_ema.reindex(close.index, method="ffill")
    pct = htf_ema_re.pct_change(1).fillna(0)
    return pd.Series(
        np.where(pct > 0.001, 1, np.where(pct < -0.001, -1, 0)), index=close.index
    )


def _build_adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int
) -> pd.Series:
    """Average Directional Index (14-period default)."""
    tr = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(span=period, adjust=False, min_periods=1).mean()

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index
    )
    plus_di = 100 * plus_dm.ewm(span=period, adjust=False, min_periods=1).mean() / atr
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False, min_periods=1).mean() / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).clip(lower=1e-10)
    return dx.ewm(span=period, adjust=False, min_periods=1).mean()


def _build_bollinger_width(close: pd.Series, period: int, std_mult: float) -> pd.Series:
    """Relative BB width = (std_mult * std) / SMA."""
    sma = close.rolling(period, min_periods=1).mean()
    std = close.rolling(period, min_periods=1).std()
    return (std_mult * std) / sma


def _rolling_pct_rank(series: pd.Series, window: int) -> pd.Series:
    """Fraction of last `window` values <= current value."""
    return series.rolling(window, min_periods=1).apply(
        lambda x: (x <= x.iloc[-1]).sum() / max(len(x), 1),
        raw=False,
    )


# ════════════════════════ Base risk-managed strategy ════════════════════════


class BaseRiskStrategy(Strategy):
    """Shared risk controls: position sizing, circuit breaker, trailing stop, invalidation.

    Risk features (ATR, HTF levels) are computed in ``init()`` from ``self.data``,
    which is already price-scaled by ``FractionalBacktest`` when applicable.
    """

    risk_cfg: RiskConfig = RiskConfig()
    cooldown_bars: int = 12
    trade_size_fraction: float = 0.95

    # Subclass overridable behaviour
    _USE_FIXED_TP: bool = True   # False → breakout mode: no fixed TP, trail-only exit
    _BREAKOUT_MODE: bool = False  # True → wider trailing + Donchian exit
    _MIN_RR: float = 2.0  # minimum reward/risk ratio
    _SCORE_THRESHOLD: int = 70  # minimum score (0-100) for entry
    _RISK_PER_TRADE: float = 0.02  # overridden per module

    # Partial TP / time stop (overridden by subclasses)
    _USE_PARTIAL_TP: bool = False
    _PARTIAL_TP_R: float = 1.5
    _PARTIAL_TP_PCT: float = 0.35
    _PARTIAL_DONE: bool = False
    _USE_TIME_STOP: bool = False
    _TIME_STOP_BARS: int = 10
    _MIN_PROFIT_R: float = 0.5

    def init(self):
        # -- Compute risk & regime features from (possibly scaled) data --
        df = self.data.df
        idx = df.index
        rcfg = self.risk_cfg
        d_len = BacktestConfig().daily_ema_len
        w_len = BacktestConfig().weekly_ema_len

        # ATR
        df["_atr"] = _build_atr(df["High"], df["Low"], df["Close"], rcfg.atr_period)

        # Daily swing high / low
        df["_d_high"], df["_d_low"] = _build_daily_prev_hl(
            df["High"], df["Low"], idx, rcfg.htf_lookback_days
        )

        # HTF EMA direction
        df["_d_ema_dir"] = _build_ema_dir(df["Close"], "1D", d_len)
        df["_w_ema_dir"] = _build_ema_dir(df["Close"], "1W", w_len)

        # ---- Market Regime Classification ----
        # HTF EMAs (for trend detection & dual-layer core)
        _d_ema = _htf_ema(df["Close"], "1D", d_len)
        _w_ema = _htf_ema(df["Close"], "1W", w_len)
        df["_d_ema_169"] = _d_ema  # store for core layer access
        df["_w_ema_169"] = _w_ema

        # Bollinger Band width percentile
        bb_width = _build_bollinger_width(df["Close"], rcfg.bb_period, rcfg.bb_std_mult)
        bb_pct = _rolling_pct_rank(bb_width, rcfg.regime_lookback)

        # ATR/Close ratio percentile
        atr_ratio = df["_atr"] / df["Close"]
        atr_pct = _rolling_pct_rank(atr_ratio, rcfg.regime_lookback)

        # ADX
        adx = _build_adx(df["High"], df["Low"], df["Close"], rcfg.adx_period)

        # Large opposing candles detection
        body = (df["Close"] - df["Open"]).abs()
        large_body = body > (rcfg.high_vol_large_candle_mult * df["_atr"])
        bull_large = large_body & (df["Close"] > df["Open"])
        bear_large = large_body & (df["Close"] < df["Open"])
        opposing_large = (
            bull_large.rolling(5, min_periods=1).max().astype(bool)
            & bear_large.rolling(5, min_periods=1).max().astype(bool)
        )

        # Assign regime labels (priority: High Risk > Trend > Compression > Ranging)
        regime = pd.Series(0, index=idx, dtype=int)  # 0 = Ranging

        # 4 = High Risk
        high_vol = (atr_pct >= rcfg.high_vol_atr_pct) | opposing_large
        regime[high_vol] = 4

        # 1 = Trend Bull — price above daily EMA169, daily slope positive
        bull_cond = (
            (df["Close"] > _d_ema)
            & (df["_d_ema_dir"] > 0)
            & (regime == 0)
        )
        regime[bull_cond] = 1

        # 2 = Trend Bear — price below daily EMA169, daily slope negative
        bear_cond = (
            (df["Close"] < _d_ema)
            & (df["_d_ema_dir"] < 0)
            & (regime == 0)
        )
        regime[bear_cond] = 2

        # 3 = Compression — BB narrow + low ATR + low ADX
        compression_cond = (
            (bb_pct <= rcfg.compression_bb_pct)
            & (atr_pct <= rcfg.compression_atr_pct)
            & (adx < rcfg.adx_ranging_threshold)
            & (regime == 0)
        )
        regime[compression_cond] = 3

        df["_regime"] = regime

        # Donchian channels for trend-following exits & breakout entries
        df["_dc55_high"] = df["High"].rolling(55, min_periods=1).max()
        df["_dc55_low"] = df["Low"].rolling(55, min_periods=1).min()
        df["_dc20_high"] = df["High"].rolling(20, min_periods=1).max()
        df["_dc20_low"] = df["Low"].rolling(20, min_periods=1).min()

        # Bollinger Bands for mean reversion (scaled-price version)
        bb_sma = df["Close"].rolling(20, min_periods=1).mean()
        bb_sd = df["Close"].rolling(20, min_periods=1).std()
        df["bb_upper"] = bb_sma + 2 * bb_sd
        df["bb_lower"] = bb_sma - 2 * bb_sd

        # Daily swing low 20 (for bear core entry)
        d_low = df["Low"].resample("1D").min()
        d_swing_low_20 = d_low.rolling(20, min_periods=1).min().shift(1)
        df["_daily_swing_low_20"] = d_swing_low_20.reindex(idx, method="ffill")

        # -- State tracking --
        self._had_position = False
        self._consecutive_losses: int = 0
        self._pause_until_bar: int = -1

        self._day_start_equity: float = 100_000
        self._week_start_equity: float = 100_000
        self._current_day: int = -1
        self._current_week: int = -1
        self._daily_pnl: float = 0.0
        self._weekly_pnl: float = 0.0

        self._entry_price: float = 0.0
        self._entry_atr: float = 0.0
        self._initial_risk: float = 0.0
        self._trailing_sl: float = 0.0
        self._extreme_since_entry: float = 0.0
        self._entry_bar: int = 0

    # -- helpers --

    def _at(self, col: str) -> float:
        return float(self.data.df[col].iloc[-1])

    def _bar_index(self) -> int:
        return len(self.data.Close) - 1

    def _current_regime(self) -> int:
        return int(self._at("_regime"))

    _REGIME_NAMES = {0: "Ranging", 1: "Bull", 2: "Bear", 3: "Compression", 4: "HighRisk"}

    def _regime_name(self) -> str:
        return self._REGIME_NAMES.get(self._current_regime(), "?")

    def _is_paused(self) -> bool:
        return self._pause_until_bar >= 0 and self._bar_index() < self._pause_until_bar

    def _day_id(self) -> int:
        ts = self.data.df.index[-1]
        return ts.year * 366 + ts.dayofyear

    def _week_id(self) -> int:
        ts = self.data.df.index[-1]
        return ts.year * 53 + ts.isocalendar().week

    # -- circuit breaker --

    def _update_circuit_breaker(self):
        day = self._day_id()
        week = self._week_id()

        if day != self._current_day:
            if self._current_day >= 0:
                limit = self.risk_cfg.daily_dd_limit * self._day_start_equity
                if self._daily_pnl < -limit:
                    self._pause_until_bar = self._bar_index() + 6
            self._current_day = day
            self._day_start_equity = self.equity
            self._daily_pnl = 0.0

        if week != self._current_week:
            if self._current_week >= 0:
                limit = self.risk_cfg.weekly_dd_limit * self._week_start_equity
                if self._weekly_pnl < -limit:
                    self._pause_until_bar = self._bar_index() + 42
            self._current_week = week
            self._week_start_equity = self.equity
            self._weekly_pnl = 0.0

    def _on_trade_closed(self, pnl: float):
        self._daily_pnl += pnl
        self._weekly_pnl += pnl

        if pnl <= 0:
            self._consecutive_losses += 1
            if self._consecutive_losses >= self.risk_cfg.max_consecutive_losses:
                self._pause_until_bar = self._bar_index() + self.risk_cfg.pause_bars
        else:
            self._consecutive_losses = 0
            self._pause_until_bar = -1

    # -- position sizing --

    def _calc_position_size(self, entry: float, sl: float) -> float:
        """Risk-based position sizing: size = equity × risk% / |entry - SL|."""
        stop_pct = abs(entry - sl) / entry
        if stop_pct < 0.0001:
            return 0.0
        risk_pct = getattr(self, '_RISK_PER_TRADE', self.risk_cfg.risk_per_trade)
        raw = risk_pct / stop_pct
        size = min(raw, self.risk_cfg.max_position_frac)
        if self._consecutive_losses >= self.risk_cfg.consecutive_loss_limit:
            size *= self.risk_cfg.reduced_size_mult
        # HTF conflict: daily & weekly disagree → half size
        d_dir = self._at("_d_ema_dir")
        w_dir = self._at("_w_ema_dir")
        if d_dir * w_dir < 0:
            size *= 0.5
        # Short entry → reduce risk per bear-short rule
        is_short = sl > entry  # short has SL above entry
        if is_short:
            size *= self.risk_cfg.risk_bear_short_mult
        return min(size, 0.99)

    # -- trailing stop --

    def _update_trailing(self, is_long: bool):
        price = self._at("Close")
        atr = self._at("_atr")

        if is_long:
            self._extreme_since_entry = max(self._extreme_since_entry, self._at("High"))
            unreal_r = (price - self._entry_price) / self._initial_risk if self._initial_risk > 0 else 0
        else:
            self._extreme_since_entry = min(self._extreme_since_entry, self._at("Low"))
            unreal_r = (self._entry_price - price) / self._initial_risk if self._initial_risk > 0 else 0

        # Phase 1: breakeven
        be_r = getattr(self, '_effective_trailing_breakeven_r', self.risk_cfg.trailing_breakeven_r)
        if unreal_r >= be_r:
            if is_long and self._trailing_sl < self._entry_price:
                self._trailing_sl = self._entry_price
            elif not is_long and self._trailing_sl > self._entry_price:
                self._trailing_sl = self._entry_price

        # Phase 2: trail
        if unreal_r >= self.risk_cfg.trailing_activate_r:
            trail_mult = (
                self.risk_cfg.breakout_trail_mult if self._BREAKOUT_MODE
                else self.risk_cfg.trailing_distance_atr
            )
            dist = trail_mult * atr
            if is_long:
                new_sl = self._extreme_since_entry - dist
                if new_sl > self._trailing_sl:
                    self._trailing_sl = new_sl
            else:
                new_sl = self._extreme_since_entry + dist
                if new_sl < self._trailing_sl:
                    self._trailing_sl = new_sl

    def _check_trailing_hit(self, is_long: bool) -> bool:
        return (is_long and self._at("Low") <= self._trailing_sl) or (
            not is_long and self._at("High") >= self._trailing_sl
        )

    # -- invalidation --

    def _check_extra_exit(self, is_long: bool) -> bool:
        """Override in subclass to add extra exit conditions (e.g. Donchian reverse)."""
        return False

    def _check_partial_tp(self, is_long: bool) -> bool:
        """Check if partial take-profit level is reached."""
        if not self._USE_PARTIAL_TP or getattr(self, "_partial_done", False):
            return False
        entry = self._entry_price
        risk = self._initial_risk
        if risk <= 0:
            return False
        price = self._at("Close")
        r_multiple = (price - entry) / risk if is_long else (entry - price) / risk
        return r_multiple >= self._PARTIAL_TP_R

    def _check_time_stop(self, is_long: bool) -> bool:
        """Exit if held too long without sufficient profit."""
        if not self._USE_TIME_STOP:
            return False
        bars_held = self._bar_index() - self._entry_bar
        if bars_held < self._TIME_STOP_BARS:
            return False
        entry = self._entry_price
        risk = self._initial_risk
        if risk <= 0:
            return False
        price = self._at("Close")
        r_multiple = (price - entry) / risk if is_long else (entry - price) / risk
        return r_multiple < self._MIN_PROFIT_R

    def _regime_entry_gate(
        self, regime: int, d_dir: int, w_dir: int
    ) -> tuple[bool, bool]:
        """Return (allow_long, allow_short) based on regime + HTF context.
        Default: Pullback logic — strict regime or soft HTF alignment.
        """
        allow_long = regime == 1 or (d_dir >= 0 and w_dir >= 0)
        allow_short = regime == 2 or (d_dir <= 0 and w_dir <= 0)
        return allow_long, allow_short

    def _check_invalidation(self, is_long: bool) -> bool:
        bars_held = self._bar_index() - self._entry_bar

        if bars_held >= self.risk_cfg.max_bars_no_profit:
            unreal = (self._at("Close") - self._entry_price) * (1 if is_long else -1)
            if unreal <= 0:
                return True

        if self._entry_atr > 0 and self._at("_atr") > self.risk_cfg.volatility_spike_atr_mult * self._entry_atr:
            return True

        d_dir = self._at("_d_ema_dir")
        w_dir = self._at("_w_ema_dir")
        if is_long and d_dir < 0 and w_dir < 0:
            return True
        if not is_long and d_dir > 0 and w_dir > 0:
            return True

        return False

    # -- override in subclass --

    def _calc_sl_tp(self, is_long: bool, regime: int) -> tuple[float, float] | None:
        raise NotImplementedError

    # -- main loop --

    def next(self):
        i = self._bar_index()

        # Detect trade close
        had = self._had_position
        has = self.position and self.position.size != 0
        self._had_position = has
        if had and not has:
            # PnL via equity change since position was last open
            pnl = self.equity - getattr(self, "_eq_before_close", self.equity)
            self._on_trade_closed(pnl)

        # Cooldown / pause
        if i - getattr(self, "_last_trade_bar", -10**9) < self.cooldown_bars:
            return
        if self._is_paused():
            return

        self._update_circuit_breaker()

        # Manage open position
        if has:
            is_long = self.position.is_long

            # Partial TP (before trailing/invalidation — locks in profit)
            if self._check_partial_tp(is_long):
                self.position.close(portion=self._PARTIAL_TP_PCT)
                self._partial_done = True

            # Time stop (insufficient momentum)
            if self._check_time_stop(is_long):
                self.position.close()
                self._last_trade_bar = i
                return

            self._update_trailing(is_long)
            if self._check_invalidation(is_long):
                self.position.close()
                self._last_trade_bar = i
                return
            if self._check_trailing_hit(is_long):
                self.position.close()
                self._last_trade_bar = i
                return
            if self._check_extra_exit(is_long):
                self.position.close()
                self._last_trade_bar = i
                return
            return

        # Entry — regime-aware (Step 1 & 2 share this, gated by class attrs)
        regime = self._current_regime()
        d_dir = self._at("_d_ema_dir")
        w_dir = self._at("_w_ema_dir")

        # High Risk: never enter
        if regime == 4:
            return

        if self._USE_REGIME_GATE:
            allow_long, allow_short = self._regime_entry_gate(regime, d_dir, w_dir)
        else:
            # Step 1: Zone crossing — no direction gate (signal already directional)
            allow_long = True
            allow_short = True

        long_sig = allow_long and (
            float(self.data.df[self._LONG_COL].iloc[i]) >= self._SCORE_THRESHOLD
        )
        short_sig = allow_short and (
            float(self.data.df[self._SHORT_COL].iloc[i]) >= self._SCORE_THRESHOLD
        )

        if not long_sig and not short_sig:
            return

        # Resolution when both fire
        if long_sig and short_sig:
            if d_dir > 0 and w_dir >= 0:
                short_sig = False
            elif d_dir < 0 and w_dir <= 0:
                long_sig = False
            else:
                return

        is_long = long_sig
        result = self._calc_sl_tp(is_long, regime)
        if result is None:
            return

        sl, tp = result
        entry = self._at("Close")

        risk = abs(entry - sl)
        if risk <= 0:
            return

        if self._USE_FIXED_TP:
            # Validate RR >= 1:2
            if tp is None:
                return
            reward = abs(tp - entry)
            if reward <= 0 or reward / risk < self._MIN_RR:
                return

        size = self._calc_position_size(entry, sl)
        if size < 0.001:
            return

        self._eq_before_close = self.equity  # snapshot for PnL tracking

        if is_long:
            self.buy(size=size, sl=sl, tp=tp)
            self._trailing_sl = sl
            self._extreme_since_entry = entry
        else:
            self.sell(size=size, sl=sl, tp=tp)
            self._trailing_sl = sl
            self._extreme_since_entry = entry

        self._entry_price = entry
        self._entry_atr = self._at("_atr")
        self._initial_risk = risk
        self._entry_bar = i
        self._last_trade_bar = i
        self._partial_done = False  # reset for new trade


# ═══════════════════════ Scheme A: Pure HTF SL/TP ════════════════════════


class HTFStopStrategy(BaseRiskStrategy):
    """SL = N-day swing high/low.  TP = entry +/- 2*risk (1:2 RR)."""

    def _calc_sl_tp(self, is_long: bool, regime: int) -> tuple[float, float] | None:
        entry = self._at("Close")
        d_high = self._at("_d_high")
        d_low = self._at("_d_low")
        cap = self.risk_cfg.htf_sl_cap_pct

        if is_long:
            sl = max(d_low, entry * (1 - cap))
            if sl >= entry:
                return None
            tp = entry + 2 * (entry - sl)
        else:
            sl = min(d_high, entry * (1 + cap))
            if sl <= entry:
                return None
            tp = entry - 2 * (sl - entry)

        return sl, tp


# ═══════════════════════ Scheme B: ATR + HTF SL/TP ════════════════════════


class ATRHTFStopStrategy(BaseRiskStrategy):
    """Regime-adaptive ATR SL/TP with HTF swing-level caps (zone crossing, legacy)."""

    _LONG_COL = "long_entry"
    _SHORT_COL = "short_entry"
    _USE_REGIME_GATE = False
    _SCORE_THRESHOLD = 0  # legacy boolean columns → no score threshold

    def _calc_sl_tp(self, is_long: bool, regime: int) -> tuple[float, float] | None:
        entry = self._at("Close")
        atr = self._at("_atr")
        d_high = self._at("_d_high")
        d_low = self._at("_d_low")
        rcfg = self.risk_cfg

        # Regime-specific SL/TP multipliers
        if regime == 1:  # Trend Bull
            sl_mult = rcfg.regime_bull_sl_mult
            tp_mult = rcfg.regime_bull_tp_mult
        elif regime == 2:  # Trend Bear
            sl_mult = rcfg.regime_bear_sl_mult
            tp_mult = rcfg.regime_bear_tp_mult
        elif regime == 3:  # Compression
            sl_mult = rcfg.regime_compression_sl_mult
            tp_mult = rcfg.regime_compression_tp_mult
        else:  # Ranging (0) or fallback
            sl_mult = rcfg.regime_ranging_sl_mult
            tp_mult = rcfg.regime_ranging_tp_mult

        if is_long:
            atr_sl = entry - sl_mult * atr
            atr_tp = entry + tp_mult * atr
            sl = max(atr_sl, d_low)
            tp = atr_tp
        else:
            atr_sl = entry + sl_mult * atr
            atr_tp = entry - tp_mult * atr
            sl = min(atr_sl, d_high)
            tp = atr_tp

        if is_long and (sl >= entry or tp <= entry):
            return None
        if not is_long and (sl <= entry or tp >= entry):
            return None
        return sl, tp


# ═══════════════════════ Step 2: Pullback Entry Strategy ════════════════════


class PullbackStrategy(ATRHTFStopStrategy):
    """Trend-pullback entries with regime gating (Step 2).

    Longs only when HTF is bullish, shorts only when HTF is bearish.
    Entry requires: pullback zone + momentum confirmation + price confirmation.
    """

    _LONG_COL = "score_pullback_long"
    _SHORT_COL = "score_pullback_short"
    _USE_REGIME_GATE = True
    _SCORE_THRESHOLD = 75
    _RISK_PER_TRADE = 0.0050  # 0.50% per pullback trade
    _USE_PARTIAL_TP = True
    _PARTIAL_TP_R = 2.0
    _PARTIAL_TP_PCT = 0.40
    _USE_TIME_STOP = True
    _TIME_STOP_BARS = 10
    _MIN_PROFIT_R = 0.5

    # Override trailing BE threshold for pullback (1R instead of 1.5R)
    @property
    def _effective_trailing_breakeven_r(self) -> float:
        return self.risk_cfg.pullback_be_r  # 1.0R for pullback


# ═══════════════════════ Step 3: Donchian Breakout Strategy ════════════════════


class BreakoutStrategy(ATRHTFStopStrategy):
    """Donchian 55 breakout with trend-following exit (no fixed TP).

    Long:  Bull or Compression regime, Close > 55-bar high (shifted),
           volume expansion, ADX strong/rising, ATR in 30-85% range, Close > EMA55.
    Short: Bear regime, Close < 55-bar low, volume expansion, ADX strong,
           Close < EMA55, weekly not bullish.

    Exit:  ATR trailing stop (3× ATR, wider for trend-following)
           + Donchian 20 reverse breakout.
    """

    _LONG_COL = "score_breakout_long"
    _SHORT_COL = "score_breakout_short"
    _USE_REGIME_GATE = True
    _USE_FIXED_TP = False
    _BREAKOUT_MODE = True
    _SCORE_THRESHOLD = 55
    _RISK_PER_TRADE = 0.0065  # 0.65% per breakout trade
    _USE_PARTIAL_TP = True
    _PARTIAL_TP_R = 1.5
    _PARTIAL_TP_PCT = 0.35

    def _calc_sl_tp(self, is_long: bool, regime: int) -> tuple[float, float] | None:
        """SL-only: ATR stop with HTF cap.  No fixed TP — exit via trailing."""
        entry = self._at("Close")
        atr = self._at("_atr")
        d_high = self._at("_d_high")
        d_low = self._at("_d_low")
        sl_mult = (
            self.risk_cfg.short_sl_atr_mult if not is_long
            else self.risk_cfg.breakout_sl_atr_mult
        )

        if is_long:
            sl = max(entry - sl_mult * atr, d_low)
        else:
            sl = min(entry + sl_mult * atr, d_high)

        if is_long and sl >= entry:
            return None
        if not is_long and sl <= entry:
            return None
        return sl, None  # no fixed TP

    def _regime_entry_gate(
        self, regime: int, d_dir: int, w_dir: int
    ) -> tuple[bool, bool]:
        """Breakout gating: Bull + Compression for longs, Bear only for shorts."""
        allow_long = regime in (1, 3)  # Bull or Compression
        allow_short = regime == 2 and w_dir <= 0  # Bear, weekly not bullish
        return allow_long, allow_short

    def _check_extra_exit(self, is_long: bool) -> bool:
        """Donchian 20 reverse + EMA144/169 cross (2-bar confirm)."""
        close = self._at("Close")
        if is_long:
            # Donchian 20 low break
            if close < self._at("_dc20_low"):
                return True
            # EMA144 cross with 2-bar confirm
            ema144 = self._at("ema144")
            prev_ema144 = float(self.data.df["ema144"].iloc[-2])
            return close < ema144 and float(self.data.df["Close"].iloc[-2]) < prev_ema144
        else:
            if close > self._at("_dc20_high"):
                return True
            ema144 = self._at("ema144")
            prev_ema144 = float(self.data.df["ema144"].iloc[-2])
            return close > ema144 and float(self.data.df["Close"].iloc[-2]) > prev_ema144


# ═══════════════════════ Legacy (no risk mgmt) ═══════════════════════


# ═══════════════════════ Step 4: Mean Reversion Strategy ════════════════════


class MeanRevStrategy(BaseRiskStrategy):
    """Mean-reversion for ranging markets.  Small position, tight SL, fixed TP.

    Long:  Ranging regime, ADX<25, price near BB lower / DC20 low,
           RSI<35, wick or close-back confirmation.
    Short: Ranging regime, price near BB upper / DC20 high,
           RSI>65.

    TP = BB mid or EMA55 (range midpoint).  No trailing — fixed exit.
    Position = 40% of normal trend size.
    """

    _LONG_COL = "score_meanrev_long"
    _SHORT_COL = "score_meanrev_short"
    _USE_REGIME_GATE = True
    _USE_FIXED_TP = True
    _BREAKOUT_MODE = False
    _MIN_RR = 1.2
    _SCORE_THRESHOLD = 75
    _RISK_PER_TRADE = 0.0025  # 0.25% per mean-rev trade
    _USE_TIME_STOP = True
    _TIME_STOP_BARS = 9
    _MIN_PROFIT_R = 0.0  # any profit target counts

    def _regime_entry_gate(
        self, regime: int, d_dir: int, w_dir: int
    ) -> tuple[bool, bool]:
        """Only in Ranging regime (0)."""
        allow = regime == 0
        return allow, allow

    def _calc_sl_tp(self, is_long: bool, regime: int) -> tuple[float, float] | None:
        entry = self._at("Close")
        atr = self._at("_atr")
        rcfg = self.risk_cfg

        sl_mult = rcfg.mean_rev_sl_mult  # 1× ATR
        tp_mult = rcfg.mean_rev_tp_mult  # 2× ATR

        # TP target: BB mid or EMA55 (whichever is closer)
        bb_mid = (self._at("bb_upper") + self._at("bb_lower")) / 2
        ema55 = self._at("ema55")

        if is_long:
            sl = entry - sl_mult * atr
            tp_candidate = min(bb_mid, ema55) if bb_mid > entry else ema55
            tp = min(tp_candidate, entry + tp_mult * atr)  # cap at 2× ATR
        else:
            sl = entry + sl_mult * atr
            tp_candidate = max(bb_mid, ema55) if bb_mid < entry else ema55
            tp = max(tp_candidate, entry - tp_mult * atr)

        if is_long and (sl >= entry or tp <= entry):
            return None
        if not is_long and (sl <= entry or tp >= entry):
            return None
        return sl, tp

    def _calc_position_size(self, entry: float, sl: float) -> float:
        """Smaller position for mean reversion trades."""
        base = super()._calc_position_size(entry, sl)
        return base * self.risk_cfg.mean_rev_size_mult


# ═══════════════════════ Step 5: Dual-Layer Strategy ═══════════════════════


class DualLayerStrategy(BaseRiskStrategy):
    """Two-layer portfolio: core long (BTC beta) + tactical (4H alpha).

    Core:  Long-only.  Enters on weekly+daily bull alignment.
           Exits on weekly failure or 2 consecutive daily closes < EMA169.
           Adds on pullback signals while active.

    Tactical:  Long or short.  Uses the best signal for current regime:
           Bull → breakout_long + pullback_long
           Bear → breakout_short + pullback_short
           Ranging → meanrev_long + meanrev_short
           Compression → breakout_long

    Position: core_size + tactical_size, managed via partial closes so
    tactical exits don't disturb the core.
    """

    _USE_FIXED_TP = False
    _BREAKOUT_MODE = False
    _MIN_RR = 2.0
    _USE_TIME_STOP = True  # shorts use aggressive time stops
    _USE_PARTIAL_TP = True  # shorts use module-specific partial TP

    def init(self):
        super().init()
        df = self.data.df

        # Core tracking
        self._core_active = False
        self._core_entry_price = 0.0
        self._core_highest_close = 0.0
        self._core_size = 0.0

        # Tactical tracking
        self._tac_direction = 0  # 1=long, -1=short, 0=none
        self._tac_module = ""  # 'breakout', 'pullback', 'crash', 'bull_trap', etc.
        self._tac_entry_price = 0.0
        self._tac_sl = 0.0
        self._tac_tp = 0.0
        self._tac_size = 0.0
        self._tac_entry_bar = 0

        # Daily close tracking for core exit
        self._days_below_dema = 0
        self._last_day = -1

        # Bear core tracking
        self._bear_core_active = False
        self._bear_core_stage = 0  # 0=none, 1=probe, 2=confirm, 3=accel, 99=event_runner
        self._bear_core_size = 0.0
        self._bear_core_entry_price = 0.0
        self._bear_core_highest_daily_high = 0.0
        self._days_above_dema = 0
        self._waterfall_triggered = False
        self._waterfall_lock_r = 0.0
        # Bear group risk tracking
        self._bear_group_id = 0  # incremented per structure
        self._bear_group_exposure = 0.0
        self._bear_group_entry_bar = -10**9
        self._bear_group_peak_r = 0.0
        self._bear_group_max_exposure = 0.50
        self._bear_group_max_loss_pct = 0.006

    # ── Core helpers ──

    def _is_last_bar_of_day(self) -> bool:
        i = self._bar_index()
        df = self.data.df
        if i + 1 >= len(df):
            return True
        return df.index[i].day != df.index[i + 1].day

    def _core_entry_signal(self) -> bool:
        """Core enters only in strict Bull regime (regime == 1)."""
        return self._current_regime() == 1

    def _core_exit_signal(self) -> bool:
        """Core exits on weekly failure or 2 daily closes below EMA169."""
        w_dir = self._at("_w_ema_dir")
        if w_dir < 0:
            return True
        d_ema = self._at("_d_ema_169")

        # Track consecutive daily closes below EMA169
        day = self._day_id()
        if day != self._last_day:
            self._last_day = day
            if self._at("Close") < d_ema:
                self._days_below_dema += 1
            else:
                self._days_below_dema = 0

        return self._days_below_dema >= self.risk_cfg.core_exit_days_below_ema

    def _core_trail_stop_hit(self) -> bool:
        """Daily ATR trailing stop for core."""
        if not self._core_active:
            return False
        self._core_highest_close = max(self._core_highest_close, self._at("Close"))
        trail = self.risk_cfg.core_sl_daily_atr_mult * self._at("_atr")
        return self._at("Close") < self._core_highest_close - trail

    def _core_add_signal(self) -> bool:
        """Add to core on pullback long signal."""
        return bool(self.data.df["pullback_long"].iloc[self._bar_index()])

    # ── Bear core helpers ──

    def _bear_core_probe_signal(self) -> bool:
        """Bear core probe: daily bearish + below 20-day swing low."""
        d_dir = self._at("_d_ema_dir")
        d_ema = self._at("_d_ema_169")
        sw_low = self._at("_daily_swing_low_20")
        return (
            not self._core_active
            and not self._bear_core_active
            and self._at("Close") < d_ema
            and d_dir < 0
            and self._at("Close") < sw_low
        )

    def _bear_core_confirm_signal(self) -> bool:
        """Bear core confirm: probe active + weekly also bearish."""
        if not self._bear_core_probe:
            return False
        d_dir = self._at("_d_ema_dir")
        d_ema = self._at("_d_ema_169")
        w_ema = self._at("_w_ema_169")
        w_dir = self._at("_w_ema_dir")
        return (
            self._at("Close") < d_ema
            and d_dir < 0
            and self._at("Close") < w_ema
            and w_dir <= 0
        )

    def _check_waterfall_profit_guard(self) -> bool:
        """Detect event-driven crash: large profit in few bars without bear trend.
        Uses 4H ATR for R-computation (waterfall is a 4H event, not daily)."""
        if getattr(self, '_bear_core_stage', 0) not in (1, 2):
            return False
        entry = self._bear_core_entry_price
        bar_low = self._at("Low")
        atr_4h = self._at("_atr")
        if atr_4h <= 0 or entry <= 0:
            return False
        # Use 2.5× 4H ATR as the "R" unit for event detection
        risk_4h = 2.5 * atr_4h
        current_r = (entry - bar_low) / risk_4h
        bars = self._bar_index() - getattr(self, '_bear_core_entry_bar', -10**9)
        d_dir = self._at("_d_ema_dir")

        # Condition 1: ≤6 bars, ≥3R (4H), daily NOT bearish → event crash
        if bars <= 6 and current_r >= 1.5 and d_dir >= 0:
            self._close_portion(0.70)
            self._waterfall_lock_r = 1.5
            self._bear_core_stage = 99
            return True

        # Condition 2: ≤10 bars, ≥4R (4H) → regardless of trend
        if bars <= 10 and current_r >= 2.5:
            self._close_portion(0.80)
            self._waterfall_lock_r = 2.0
            self._bear_core_stage = 99
            return True

        return False

    def _bear_core_sl(self) -> float:
        """Bear core SL: 2.5× daily ATR above entry, capped by recent daily high."""
        daily_atr = self._at("_atr") * 1.5  # approximate daily ATR from 4H
        sl = self._bear_core_entry_price + self.risk_cfg.bear_core_sl_daily_atr * daily_atr
        return sl

    def _bear_core_exit_signal(self) -> bool:
        """Bear core exit: trend reversal or trailing stop."""
        if not self._bear_core_active:
            return False
        rcfg = self.risk_cfg
        d_dir = self._at("_d_ema_dir")
        d_ema = self._at("_d_ema_169")

        # Daily EMA direction turns positive
        if d_dir > 0:
            return True

        # 2 daily closes above daily EMA169
        day = self._day_id()
        if day != self._last_day:
            self._last_day = day
            if self._at("Close") > d_ema:
                self._days_above_dema += 1
            else:
                self._days_above_dema = 0
        if self._days_above_dema >= rcfg.bear_core_exit_days_above_ema:
            return True

        # Daily ATR trailing stop (price rises above trailing level)
        if self._bear_core_entry_price > 0:
            daily_atr = self._at("_atr") * 1.5  # approximate daily ATR
            trail_level = self._bear_core_entry_price + rcfg.bear_core_sl_daily_atr * daily_atr
            if self._at("Close") > trail_level:
                return True

        return False

    # ── Tactical helpers ──

    def _tactical_signals(self) -> tuple[bool, bool, str]:
        """Priority-ordered signal selection per market regime.

        Framework:
          Strong Bull (r=1)        → BO long + PB long + core; NO shorts
          Weak Bull / Transition   → only high-quality BO/PB; half size (via _calc_position_size)
          Ranging (r=0)            → only small mean-rev; no breakout chasing
          Compression (r=3)        → BO long allowed (breakout from compression)
          Strong Bear (r=2)        → BO short + PB short; NO longs
          High Risk (r=4)          → blocked before this method (no new positions)
        """
        regime = self._current_regime()
        i = self._bar_index()
        df = self.data.df
        d_dir = self._at("_d_ema_dir")
        w_dir = self._at("_w_ema_dir")

        strong_bull = regime == 1
        strong_bear = regime == 2
        weak_bull = not strong_bull and d_dir >= 0 and w_dir >= 0
        ranging = regime == 0
        compression = regime == 3

        score_bo_l = float(df["score_breakout_long"].iloc[i])
        score_pb_l = float(df["score_pullback_long"].iloc[i])
        # Short pullback: base score + failed-bounce bonus + derivative bonus
        score_pb_s_raw = float(df["score_pullback_short"].iloc[i])
        fb_bonus = 5 if bool(df["_failed_bounce_gate"].iloc[i]) else 0
        deriv_bonus = float(df["_short_deriv_bonus"].iloc[i]) if "_short_deriv_bonus" in df.columns else 0.0
        pa_bonus = float(df["_price_action_bonus"].iloc[i]) if "_price_action_bonus" in df.columns else 0.0
        score_pb_s = score_pb_s_raw + fb_bonus + deriv_bonus + pa_bonus
        score_mr_l = float(df["score_meanrev_long"].iloc[i])
        score_mr_s = float(df["score_meanrev_short"].iloc[i])
        score_crash_s = float(df["score_crash_short"].iloc[i]) + deriv_bonus + pa_bonus
        score_bt_s = float(df["score_bull_trap_short"].iloc[i]) + deriv_bonus + pa_bonus
        bt_gate = bool(df["_bull_trap_signal"].iloc[i])
        bo_th = self.risk_cfg.score_threshold_breakout
        pb_th = self.risk_cfg.score_threshold_pullback
        mr_th = self.risk_cfg.score_threshold_meanrev
        crash_th = 75  # ≥75 (asymmetric weights)
        pb_th_s = 999  # disabled (PF<1 in BTC)
        bt_th = 80  # ≥80
        mr_th_s = 85  # ≥85 (if enabled)
        rsi_val = float(df["rsi_14"].iloc[i])
        rsi_ok = rsi_val >= self.risk_cfg.short_rsi_floor
        late_chase_bar = bool(df["_late_chase"].iloc[i])
        late_ok = not late_chase_bar
        d_ema_val = self._at("_d_ema_169")
        close_val = self._at("Close")

        # ── Bull Guard: structural bull → block ALL shorts ──
        bull_guard = bool(df["_bull_guard"].iloc[i]) or self._core_active
        if bull_guard:
            # All short modules blocked; only allow longs
            pass  # fall through to long-only logic below

        # ── Top Exhaustion Probe ──
        top_score_val = float(df["_top_exhaustion_score"].iloc[i])
        double_top_sig = bool(df["_double_top_signal"].iloc[i])
        probe_allowed = not bull_guard and not self._bear_core_active and double_top_sig and top_score_val >= 70

        # ── Layered Short Gates ──
        short_env_ok = (
            not bull_guard and regime != 4 and rsi_ok and late_ok
        )
        short_trend_ok = short_env_ok and close_val < d_ema_val and d_dir <= 0
        short_aggressive_ok = short_trend_ok and w_dir <= 0

        # ── Ranging: mean-rev long only (short blocked by bull guard) ──
        if ranging:
            if score_mr_l >= mr_th:
                return True, False, "meanrev"
            return False, False, "none"

        # ── Strong Bear: crash(aggressive) > pullback(trend) > bull-trap(env) ──
        if strong_bear:
            if short_aggressive_ok and score_crash_s >= crash_th:
                return False, True, "crash"
            if short_trend_ok and score_pb_s >= pb_th_s:
                return False, True, "pullback"
            if short_env_ok and bt_gate and score_bt_s >= bt_th:
                return False, True, "bull_trap"
            return False, False, "none"

        # ── Weak Bear / Transition: pullback(trend) + bull-trap(env) ──
        if not strong_bull and not ranging and not compression:
            if short_trend_ok and score_pb_s >= pb_th_s:
                return False, True, "pullback"
            if short_env_ok and bt_gate and score_bt_s >= bt_th:
                return False, True, "bull_trap"
            return False, False, "none"

        # ── Strong Bull: longs ONLY, no shorts at all ──
        if strong_bull:
            if score_bo_l >= bo_th:
                return True, False, "breakout"
            if score_pb_l >= pb_th:
                return True, False, "pullback"
            if score_mr_l >= mr_th:
                return True, False, "meanrev"
            return False, False, "none"

        # ── Compression: breakout longs ──
        if compression:
            if score_bo_l >= bo_th:
                return True, False, "breakout"
            return False, False, "none"

        # ── Weak Bull / Transition: high-quality BO/PB only, both directions allowed ──
        # (half-sizing handled by _calc_position_size via HTF direction check)
        if weak_bull:
            if score_bo_l >= bo_th:
                return True, False, "breakout"
            if score_pb_l >= pb_th:
                return True, False, "pullback"
            if score_mr_l >= mr_th:
                return True, False, "meanrev"
            return False, False, "none"

        return False, False, "none"

    def _check_partial_tp(self, is_long: bool) -> bool:
        """Short-specific partial TP: crash=40%@1R+30%@2R, others=disabled."""
        if is_long:
            return super()._check_partial_tp(is_long)
        # Short: only crash breakdown uses partial TP
        mod = self._tac_module
        entry = self._tac_entry_price
        risk = abs(entry - self._tac_sl)
        if risk <= 0:
            return False
        price = self._at("Close")
        r_multiple = (entry - price) / risk
        rcfg = self.risk_cfg

        if mod == "crash":
            if not getattr(self, "_tp1_done", False) and r_multiple >= rcfg.short_crash_tp1_r:
                self._tp1_done = True; self._PARTIAL_TP_PCT = rcfg.short_crash_tp1_pct; return True
            if getattr(self, "_tp1_done", False) and not getattr(self, "_tp2_done", False) and r_multiple >= rcfg.short_crash_tp2_r:
                self._tp2_done = True; self._PARTIAL_TP_PCT = rcfg.short_crash_tp2_pct; return True
        elif mod in ("pullback", "failed_bounce"):
            if not getattr(self, "_tp1_done", False) and r_multiple >= rcfg.fb_tp1_r:
                self._tp1_done = True; self._PARTIAL_TP_PCT = rcfg.fb_tp1_pct; return True
            if getattr(self, "_tp1_done", False) and not getattr(self, "_tp2_done", False) and r_multiple >= rcfg.fb_tp2_r:
                self._tp2_done = True; self._PARTIAL_TP_PCT = rcfg.fb_tp2_pct; return True
        elif mod == "bear_core":
            if not getattr(self, "_tp1_done", False) and r_multiple >= rcfg.bear_core_tp1_r:
                self._tp1_done = True; self._PARTIAL_TP_PCT = rcfg.bear_core_tp1_pct; return True
            if getattr(self, "_tp1_done", False) and not getattr(self, "_tp2_done", False) and r_multiple >= rcfg.bear_core_tp2_r:
                self._tp2_done = True; self._PARTIAL_TP_PCT = rcfg.bear_core_tp2_pct; return True
        return False

    def _check_time_stop(self, is_long: bool) -> bool:
        """Short-specific time stops: crash=8, pullback=10, bulltrap=6 bars.
        Must reach 1R within timeout, and once reached, exit if falls below 0.5R."""
        if is_long:
            return super()._check_time_stop(is_long)
        bars_held = self._bar_index() - self._tac_entry_bar
        rcfg = self.risk_cfg
        mod = self._tac_module
        if mod == "crash":
            timeout = rcfg.short_crash_timeout
        elif mod in ("pullback", "failed_bounce"):
            timeout = rcfg.fb_timeout
        elif mod == "bear_core":
            return False  # bear core uses daily trend exit only
        elif mod == "bull_trap":
            timeout = rcfg.short_bulltrap_timeout
        else:
            return False
        risk = abs(self._tac_entry_price - self._tac_sl)
        if risk <= 0:
            return False
        r_multiple = (self._tac_entry_price - self._at("Close")) / risk
        # Track if we ever reached 1R
        if r_multiple >= 1.0:
            self._short_reached_1r = True
        # After timeout: exit if never reached 1R
        if bars_held >= timeout and not getattr(self, "_short_reached_1r", False):
            return r_multiple < 1.0
        # After reaching 1R: exit if profit evaporates below 1.0R (protect gains)
        if getattr(self, "_short_reached_1r", False) and r_multiple < 1.0:
            return True
        return False

    def _check_extra_exit(self, is_long: bool) -> bool:
        """Short: Donchian 10 high exit for crash; DC20 low as target hit for others."""
        if is_long:
            return super()._check_extra_exit(is_long)
        close = self._at("Close")
        mod = self._tac_module
        # Crash breakdown: DC10 high = exit
        dc10_high = self._at("_dc20_high")  # reuse DC20; DC10 would need new column
        dc10_high_10 = float(self.data.df["High"].rolling(10, min_periods=1).max().iloc[-1])
        if mod == "crash" and close > dc10_high_10:
            return True
        # Pullback / Bull trap: DC20 low reached = target hit → exit
        if mod in ("pullback", "failed_bounce", "bull_trap") and close <= self._at("_dc20_low"):
            return True
        return False

    def _calc_position_size(self, entry: float, sl: float) -> float:
        """Override: add weak-bull half-sizing."""
        size = super()._calc_position_size(entry, sl)
        # Weak bull / transition: half position
        regime = self._current_regime()
        d_dir = self._at("_d_ema_dir")
        w_dir = self._at("_w_ema_dir")
        weak_bull = regime != 1 and d_dir >= 0 and w_dir >= 0
        if weak_bull and regime not in (0, 2, 4):  # not ranging, bear, or high-risk
            size *= 0.5
        return size

    def _tactical_sl_tp(self, is_long: bool) -> tuple[float, float] | None:
        """Compute SL/TP for tactical trades (regime-adaptive ATR)."""
        entry = self._at("Close")
        atr = self._at("_atr")
        d_high = self._at("_d_high")
        d_low = self._at("_d_low")
        rcfg = self.risk_cfg

        regime = self._current_regime()
        if regime == 1:
            sl_m, tp_m = rcfg.regime_bull_sl_mult, rcfg.regime_bull_tp_mult
        elif regime == 2:
            sl_m, tp_m = rcfg.regime_bear_sl_mult, rcfg.regime_bear_tp_mult
        elif regime == 3:
            sl_m, tp_m = rcfg.regime_compression_sl_mult, rcfg.regime_compression_tp_mult
        else:
            sl_m, tp_m = rcfg.regime_ranging_sl_mult, rcfg.regime_ranging_tp_mult

        if is_long:
            sl = max(entry - sl_m * atr, d_low)
            tp = entry + tp_m * atr
        else:
            sl = min(entry + sl_m * atr, d_high)
            tp = entry - tp_m * atr

        if is_long and (sl >= entry or tp <= entry):
            return None
        if not is_long and (sl <= entry or tp >= entry):
            return None
        return sl, tp

    def _check_short_giveback_guard(self, entry_price: float, sl_price: float) -> bool:
        """Tiered R-level giveback protection for ALL shorts.

        Peak >= 1R & drops to <= 0.25R → exit
        Peak >= 2R & drops to <= 0.8R  → exit
        Peak >= 4R & drops to <= 2.0R  → exit
        """
        risk = abs(entry_price - sl_price)
        if risk <= 0:
            return False
        peak_r = (entry_price - self._at("Low")) / risk
        prev_peak = getattr(self, '_short_giveback_peak_r', -999.0)
        if peak_r > prev_peak:
            self._short_giveback_peak_r = peak_r
        current_r = (entry_price - self._at("Close")) / risk

        if prev_peak >= 2.0 and current_r <= 0.5:
            return True
        if prev_peak >= 3.0 and current_r <= 1.0:
            return True
        if prev_peak >= 5.0 and current_r <= 2.0:
            return True
        return False

    def _check_tactical_exit(self) -> bool:
        """Check if tactical SL/TP/trail/time-stop is hit."""
        if self._tac_direction == 0:
            return False

        is_long = self._tac_direction == 1

        # Tiered R-level giveback guard (all shorts)
        if not is_long and self._tac_entry_price > 0 and self._tac_sl > 0:
            if self._check_short_giveback_guard(self._tac_entry_price, self._tac_sl):
                return True

        # Time stop (before SL/TP — cuts losers early)
        if self._check_time_stop(is_long):
            return True

        price = self._at("Close")
        high = self._at("High")
        low = self._at("Low")

        # SL hit
        if is_long and low <= self._tac_sl:
            return True
        if not is_long and high >= self._tac_sl:
            return True

        # TP hit
        if is_long and high >= self._tac_tp:
            return True
        if not is_long and low <= self._tac_tp:
            return True

        # ATR trailing stop (same logic as base class)
        atr = self._at("_atr")
        if is_long:
            extreme = max(getattr(self, "_tac_extreme", price), high)
            self._tac_extreme = extreme
            trail_sl = extreme - self.risk_cfg.trailing_distance_atr * atr
            if trail_sl > self._tac_sl:  # trail up
                self._tac_sl = trail_sl
            if low <= self._tac_sl:
                return True
        else:
            extreme = min(getattr(self, "_tac_extreme", price), low)
            self._tac_extreme = extreme
            trail_sl = extreme + self.risk_cfg.trailing_distance_atr * atr
            if trail_sl < self._tac_sl:  # trail down
                self._tac_sl = trail_sl
            if high >= self._tac_sl:
                return True

        return False

    # ── Position helpers ──

    def _current_position_size(self) -> float:
        if self.position and self.position.size != 0:
            return float(self.position.size)
        return 0.0

    def _enter_long(self, size: float, tag: str = "", sl: float | None = None, tp: float | None = None):
        """Enter or add to long position."""
        self.buy(size=size, tag=tag, sl=sl, tp=tp)

    def _enter_short(self, size: float, tag: str = "", sl: float | None = None, tp: float | None = None):
        """Enter or add to short position with hard SL/TP."""
        self.sell(size=size, tag=tag, sl=sl, tp=tp)

    def _close_portion(self, portion: float):
        """Close a portion of the current position."""
        if self.position and portion > 0.001:
            self.position.close(portion=min(portion, 1.0))

    def _close_all(self):
        if self.position:
            self.position.close()

    # ── Main loop ──

    def next(self):
        i = self._bar_index()
        rcfg = self.risk_cfg
        max_pos = rcfg.max_position_frac

        # ── Pre-trade checks ──
        cooldown_ok = i - getattr(self, "_last_trade_bar", -10**9) >= self.cooldown_bars
        paused = self._is_paused()
        self._update_circuit_breaker()

        has_pos = self.position and abs(self.position.size) > 0.0001

        # Detect external close (e.g., library closed position fully)
        if not has_pos and (self._core_active or self._tac_direction != 0):
            pnl = self.equity - getattr(self, "_eq_snapshot", self.equity)
            self._on_trade_closed(pnl)
            self._core_active = False
            self._core_size = 0.0
            self._tac_direction = 0
            self._tac_size = 0.0

        # ── Core exit check ──
        if self._core_active and (self._core_exit_signal() or self._core_trail_stop_hit()):
            self._close_all()
            self._core_active = False
            self._core_size = 0.0
            self._tac_direction = 0
            self._tac_size = 0.0
            pnl = self.equity - getattr(self, "_eq_snapshot", self.equity)
            self._on_trade_closed(pnl)
            return

        # ── Bear core exit (V-reversal + giveback + waterfall + trend) ──
        if self._bear_core_active:
            # V-reversal: made profit then snapped back → liquidity event, not bear
            bc_sl = self._bear_core_sl()
            risk = abs(self._bear_core_entry_price - bc_sl)
            if risk > 0:
                peak_r = getattr(self, '_bear_probe_peak_r', 0.0)
                current_r = (self._bear_core_entry_price - self._at("Close")) / risk
                bars = self._bar_index() - getattr(self, '_bear_core_entry_bar', -10**9)
                if (peak_r >= 2.0 and current_r < 0.5 and bars <= 12
                        and (self._at("_d_ema_dir") >= 0 or self._current_regime() != 2)):
                    self._close_all()
                    self._bear_core_active = False
                    self._bear_core_size = 0.0
                    self._tac_direction = 0; self._tac_size = 0.0
                    self._waterfall_triggered = False; self._days_above_dema = 0
                    self._on_trade_closed(self.equity - getattr(self, "_eq_snapshot", self.equity))
                    return

            # Tiered giveback guard for bear core
            if self._check_short_giveback_guard(self._bear_core_entry_price, bc_sl):
                self._close_all()
                self._bear_core_active = False
                self._bear_core_size = 0.0
                self._tac_direction = 0; self._tac_size = 0.0
                pnl = self.equity - getattr(self, "_eq_snapshot", self.equity)
                self._on_trade_closed(pnl)
                return

            # Waterfall event runner: exit if profit drops below locked R
            if getattr(self, '_bear_core_stage', 0) == 99:
                sl = self._bear_core_sl()
                risk = abs(self._bear_core_entry_price - sl)
                if risk > 0:
                    current_r = (self._bear_core_entry_price - self._at("Close")) / risk
                    lock_r = getattr(self, '_waterfall_lock_r', 1.0)
                    if current_r < lock_r * 0.5:
                        self._close_all()
                        self._bear_core_active = False
                        self._bear_core_size = 0.0
                        self._tac_direction = 0
                        self._tac_size = 0.0
                        self._waterfall_triggered = False
                        self._days_above_dema = 0
                        pnl = self.equity - getattr(self, "_eq_snapshot", self.equity)
                        self._on_trade_closed(pnl)
                        return

        if self._bear_core_active and self._bear_core_exit_signal():
            self._close_all()
            self._bear_core_active = False
            self._bear_core_size = 0.0
            self._tac_direction = 0
            self._tac_size = 0.0
            self._days_above_dema = 0
            pnl = self.equity - getattr(self, "_eq_snapshot", self.equity)
            self._on_trade_closed(pnl)
            return

        # ── Bear core probe peak R tracker + waterfall guard ──
        if self._bear_core_active:
            sl = self._bear_core_sl()
            risk = abs(self._bear_core_entry_price - sl)
            if risk > 0:
                current_r = (self._bear_core_entry_price - self._at("Low")) / risk
                peak = getattr(self, '_bear_probe_peak_r', 0.0)
                if current_r > peak:
                    self._bear_probe_peak_r = current_r

            # Waterfall profit guard: event-driven crash, not sustainable bear
            if not getattr(self, '_waterfall_triggered', False):
                if self._check_waterfall_profit_guard():
                    self._waterfall_triggered = True
                    return  # position modified, skip rest of this bar

        # ── Tactical exit check (before entry) ──
        if self._tac_direction != 0 and self._check_tactical_exit():
            total = abs(self._current_position_size())
            if total > 0.001 and self._tac_size > 0.001:
                portion = min(self._tac_size / total, 1.0)
                self._close_portion(portion)
            else:
                self._close_all()
            self._tac_direction = 0
            self._tac_size = 0.0

        # ── Entry checks (respect cooldown & pause) ──
        if not cooldown_ok or paused:
            return

        # ── Core entry ──
        if not self._core_active and self._core_entry_signal():
            self._core_active = True
            self._core_entry_price = self._at("Close")
            self._core_highest_close = self._at("Close")
            self._core_size = rcfg.risk_core_alloc
            self._days_below_dema = 0
            self._eq_snapshot = self.equity
            self._enter_long(self._core_size, tag="core")
            self._last_trade_bar = i

        # ── Core add-on (pullback in bull) ──
        if self._core_active and not hasattr(self, "_core_fully_loaded"):
            self._core_fully_loaded = False
        if self._core_active and not getattr(self, "_core_fully_loaded", True) and self._core_add_signal():
            add_size = (rcfg.core_allocation - self._core_size) * max_pos
            if add_size > 0.001:
                self._enter_long(add_size, tag="core_add")
                self._core_size = rcfg.risk_core_alloc
                self._core_fully_loaded = True

        # ── Bear Core 3-stage entry (Probe → Confirm → Acceleration) ──
        # Stage 1: Probe (top exhaustion + neckline break) → bear group gate
        if not self._core_active and not self._bear_core_active:
            _df = self.data.df
            top_score_val = float(_df["_top_exhaustion_score"].iloc[i]) if "_top_exhaustion_score" in _df.columns else 0
            double_top_sig = bool(_df["_double_top_signal"].iloc[i]) if "_double_top_signal" in _df.columns else False
            bull_guard = bool(_df["_bull_guard"].iloc[i]) if "_bull_guard" in _df.columns else False
            # Bear group: same structure within 30 bars → one probe per structure
            same_group = (i - self._bear_group_entry_bar) <= 30
            if same_group:
                double_top_sig = False  # block re-entry
            if double_top_sig and top_score_val >= 70 and not bull_guard:
                self._bear_core_active = True
                self._bear_core_stage = 1
                self._bear_core_entry_price = self._at("Close")
                self._bear_core_entry_bar = i
                self._bear_probe_peak_r = 0.0
                self._short_giveback_peak_r = -999.0
                self._bear_core_size = rcfg.bear_core_full_pct * 0.35  # ~14% probe
                # Bear group tracking
                if not same_group:
                    self._bear_group_id += 1
                    self._bear_group_exposure = 0.0
                    self._bear_group_entry_bar = i
                    self._bear_group_peak_r = 0.0
                self._bear_group_exposure += self._bear_core_size
                self._days_above_dema = 0
                self._eq_snapshot = self.equity
                bc_sl = self._bear_core_sl()
                self._enter_short(self._bear_core_size, tag="bear_core", sl=bc_sl)
                self._last_trade_bar = i

        # Stage 2: Confirm (prove + trend + group cap)
        probe_entry_bar = getattr(self, '_bear_core_entry_bar', -10**9)
        can_confirm_add = (
            self._bear_core_active
            and getattr(self, '_bear_core_stage', 0) == 1
            and i > probe_entry_bar
            and getattr(self, '_bear_probe_peak_r', 0.0) >= 1.0
            and self._at("_d_ema_dir") < 0
            and self._bear_group_exposure < self._bear_group_max_exposure  # group cap
        )
        if can_confirm_add:
            w_dir = self._at("_w_ema_dir")
            if w_dir <= 0 and self._at("Close") < self._at("_w_ema_169"):
                add_size = rcfg.bear_core_full_pct * 0.65 - self._bear_core_size
                if add_size > 0.001:
                    bc_sl = self._bear_core_sl()
                    self._enter_short(add_size, tag="bear_core", sl=bc_sl)
                    self._bear_core_size = rcfg.bear_core_full_pct * 0.65
                    self._bear_group_exposure += add_size
                    self._bear_core_stage = 2
                    self._last_trade_bar = i

        # Stage 3: Acceleration (group cap + trend confirmed)
        if (self._bear_core_active and getattr(self, '_bear_core_stage', 0) == 2
                and i > getattr(self, '_last_trade_bar', -10**9)
                and self._at("_d_ema_dir") < 0
                and self._bear_group_exposure < self._bear_group_max_exposure):
            adx_val = float(self.data.df["_adx_signal"].iloc[i]) if "_adx_signal" in self.data.df.columns else 0
            plus_di = float(self.data.df["_plus_di"].iloc[i]) if "_plus_di" in self.data.df.columns else 0
            minus_di = float(self.data.df["_minus_di"].iloc[i]) if "_minus_di" in self.data.df.columns else 0
            if adx_val > 22 and minus_di > plus_di:
                target = min(rcfg.bear_core_full_pct, self._bear_group_max_exposure)
                add_size = target - self._bear_core_size
                if add_size > 0.001:
                    bc_sl = self._bear_core_sl()
                    self._enter_short(add_size, tag="bear_core", sl=bc_sl)
                    self._bear_core_size = target
                    self._bear_group_exposure += add_size
                    self._bear_core_stage = 3

        # ── Tactical entry ──
        regime = self._current_regime()
        if regime != 4 and self._tac_direction == 0:
            long_sig, short_sig, _module = self._tactical_signals()
            if long_sig or short_sig:
                is_long = long_sig and not short_sig
                result = self._tactical_sl_tp(is_long)
                if result:
                    sl, tp = result
                    entry = self._at("Close")
                    risk = abs(entry - sl)
                    reward = abs(tp - entry)
                    if risk > 0 and reward / risk >= 2.0:
                        self._tac_direction = 1 if is_long else -1
                        self._tac_module = _module
                        self._tp1_done = False
                        self._tp2_done = False
                        self._short_reached_1r = False
                        self._short_peak_r = 0.0
                        self._short_giveback_peak_r = -999.0
                        self._tac_entry_price = entry
                        self._tac_sl = sl
                        self._tac_tp = tp
                        # Module-specific risk: breakout 0.65%, pullback 0.50%, meanrev 0.25%
                        mod_risk = {'breakout': rcfg.risk_breakout,
                                    'crash': rcfg.risk_breakout,
                                    'pullback': rcfg.risk_pullback,
                                    'failed_bounce': rcfg.risk_pullback,
                                    'bull_trap': rcfg.risk_pullback,
                                    'meanrev': rcfg.risk_meanrev}.get(_module, rcfg.risk_per_trade)
                        self._tac_size = mod_risk / (abs(entry - sl) / entry)
                        self._tac_size = min(self._tac_size, 0.99)
                        if not is_long:
                            self._tac_size *= rcfg.risk_bear_short_mult
                        self._tac_entry_bar = i
                        self._tac_extreme = entry
                        self._last_trade_bar = i
                        if is_long:
                            self._enter_long(self._tac_size, tag=_module, sl=sl, tp=tp)
                        else:
                            self._enter_short(self._tac_size, tag=_module, sl=sl, tp=tp)


class WeightedSignalStrategy(Strategy):
    cooldown_bars = 12
    trade_size_fraction = 0.95

    def init(self):
        self.last_trade_bar = -10**9

    def next(self):
        i = len(self.data.Close) - 1
        if i - self.last_trade_bar < self.cooldown_bars:
            return

        long_entry = bool(self.data.df["long_entry"].iloc[i])
        short_entry = bool(self.data.df["short_entry"].iloc[i])

        if self.position:
            if self.position.is_long and short_entry:
                self.position.close()
                self.last_trade_bar = i
            elif self.position.is_short and long_entry:
                self.position.close()
                self.last_trade_bar = i
            return

        if long_entry:
            self.buy(size=self.trade_size_fraction)
            self.last_trade_bar = i
        elif short_entry:
            self.sell(size=self.trade_size_fraction)
            self.last_trade_bar = i


# ═════════════════════════════ Runner ═════════════════════════════


StrategyName = Literal["legacy", "htf", "atr_htf", "pullback", "breakout", "meanrev", "dual"]

STRATEGY_MAP: dict[StrategyName, type[Strategy]] = {
    "legacy": WeightedSignalStrategy,
    "htf": HTFStopStrategy,
    "atr_htf": ATRHTFStopStrategy,
    "pullback": PullbackStrategy,
    "breakout": BreakoutStrategy,
    "meanrev": MeanRevStrategy,
    "dual": DualLayerStrategy,
}


def run_backtest(
    df: pd.DataFrame,
    cfg: BacktestConfig,
    *,
    strategy_name: StrategyName = "legacy",
    risk_cfg: RiskConfig | None = None,
):
    strat_cls = STRATEGY_MAP[strategy_name]
    bt = FractionalBacktest(
        df,
        strat_cls,
        cash=cfg.initial_cash,
        commission=cfg.commission,
        exclusive_orders=True,
        hedging=False,
        finalize_trades=True,
    )

    if strategy_name == "legacy":
        return bt.run(trade_size_fraction=0.95, cooldown_bars=cfg.cooldown_bars), bt

    return bt.run(
        risk_cfg=risk_cfg or RiskConfig(),
        cooldown_bars=cfg.cooldown_bars,
        trade_size_fraction=0.95,
    ), bt
