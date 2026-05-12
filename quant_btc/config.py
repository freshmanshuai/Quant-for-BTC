from dataclasses import dataclass


@dataclass(frozen=True)
class RiskConfig:
    """Risk management & position sizing parameters for leveraged futures trading."""

    # --- Leverage ---
    leverage: int = 5

    # --- Per-module risk allocation ---
    risk_per_trade: float = 0.02  # fallback (2%)
    max_position_frac: float = 1.50  # allow >1 when stop is very tight (leverage effect)
    # Module-specific (used by strategy class attrs)
    risk_breakout: float = 0.0065  # 0.5–0.8% per breakout trade
    risk_pullback: float = 0.0050  # 0.4–0.6% per pullback trade
    risk_meanrev: float = 0.0025  # 0.2–0.3% per mean-rev trade
    risk_bear_short_mult: float = 0.40  # short risk = long risk × 40% (tighter)

    # --- Short-specific constraints ---
    short_score_boost: int = 0  # base boost (module-specific overrides below)
    short_breakout_boost: int = 0  # now controlled by crash_th directly in strategy
    short_pullback_boost: int = 5   # pullback shorts: moderate boost (75+5=80)
    short_meanrev_enabled: bool = True  # range-gated: only in regime=0 with d_dir<=0
    short_require_weekly_bear: bool = True  # must have w_ema_dir <= 0
    short_no_partial_tp: bool = True  # no partial TP for shorts (take full profit)
    short_sl_atr_mult: float = 1.8  # tighter SL for shorts (vs 2.5 for longs)
    short_rsi_floor: float = 30.0  # don't short when RSI < 30 (oversold bounce risk)

    # --- Bear Core Short (long-term bear layer) ---
    bear_core_probe_pct: float = 0.25  # probe at 25% of core allocation
    bear_core_full_pct: float = 0.40  # full bear core = 40% equity
    bear_core_sl_daily_atr: float = 3.0  # stop at 3× daily ATR
    bear_core_exit_days_above_ema: int = 2  # exit after 2 daily closes > EMA169

    # --- Module-specific short exits ---
    # Bear Core (daily-level, no 4H timeout)
    bear_core_tp1_r: float = 2.0  # partial TP at 2R
    bear_core_tp1_pct: float = 0.25  # close 25%
    bear_core_tp2_r: float = 4.0  # second partial at 4R
    bear_core_tp2_pct: float = 0.25  # close 25%

    # Failed Bounce (relaxed from pullback)
    fb_tp1_r: float = 1.0  # 1R partial
    fb_tp1_pct: float = 0.35  # close 35%
    fb_tp2_r: float = 2.0  # 2R partial
    fb_tp2_pct: float = 0.30  # close 30%
    fb_timeout: int = 15  # relaxed from 10

    # Crash Breakdown (aggressive, existing)
    short_crash_tp1_r: float = 1.0
    short_crash_tp1_pct: float = 0.40
    short_crash_tp2_r: float = 2.0
    short_crash_tp2_pct: float = 0.30
    short_crash_timeout: int = 8
    short_crash_trail_atr: float = 2.0

    # Bull Trap (fast)
    short_bulltrap_timeout: int = 6
    risk_core_alloc: float = 0.40  # core long: 40% of equity (spot-like)

    # --- ATR-based SL/TP (Scheme B: ATR + HTF) ---
    atr_period: int = 14
    atr_sl_mult: float = 2.0  # SL = entry ± 2× ATR
    atr_tp_mult: float = 4.0  # TP = entry ± 4× ATR  → RR = 1:2

    # --- HTF SL cap ---
    htf_lookback_days: int = 5  # N-day rolling high/low for swing points
    htf_sl_cap_pct: float = 0.10  # cap SL distance at 10% of entry

    # --- Trailing stop ---
    trailing_breakeven_r: float = 1.5  # move SL to BE after 1.5× initial risk
    trailing_activate_r: float = 3.0  # start trailing after 3× initial risk
    trailing_distance_atr: float = 1.5  # trail SL at 1.5× ATR from extreme

    # --- Circuit breaker ---
    daily_dd_limit: float = 0.075  # 7.5% intraday drawdown → halt
    weekly_dd_limit: float = 0.075  # 7.5% intraweek drawdown → halt
    consecutive_loss_limit: int = 3  # reduce size after N consecutive losses
    reduced_size_mult: float = 0.5  # trade at 50% of normal size
    max_consecutive_losses: int = 5  # pause trading after N consecutive losses
    pause_bars: int = 18  # pause for ~3 days (18 × 4h bars)

    # --- Invalidation exits ---
    max_bars_no_profit: int = 84  # exit if position not profitable after 2 weeks
    volatility_spike_atr_mult: float = 3.0  # exit if ATR spikes 3× above entry ATR

    # --- Donchian Breakout (Step 3) ---
    donchian_period: int = 55
    donchian_exit_period: int = 20  # reverse breakout for trend exit
    breakout_sl_mult: float = 2.0  # SL for breakout entries (ATR multiplier)
    breakout_trail_mult: float = 3.0  # wider trailing for trend-following
    breakout_vol_lookback: int = 50
    breakout_adx_min: float = 20.0
    breakout_atr_pct_low: float = 0.30
    breakout_atr_pct_high: float = 0.85

    # --- Mean Reversion (Step 4) ---
    mean_rev_size_mult: float = 0.40  # 40% of normal trend position size
    mean_rev_sl_mult: float = 1.0  # tight SL: 1× ATR
    mean_rev_tp_mult: float = 2.0  # TP: 2× ATR or BB mid (whichever closer)
    mean_rev_rsi_oversold: float = 35.0
    mean_rev_rsi_overbought: float = 65.0

    # --- Dual-Layer (Step 5) ---
    core_allocation: float = 0.55  # 55% of max position for core long
    tactical_allocation: float = 0.25  # 25% for tactical (20% buffer to cap)
    core_exit_days_below_ema: int = 2  # consecutive daily closes below EMA169 → exit core
    core_sl_daily_atr_mult: float = 3.0  # daily ATR trailing stop for core

    # --- Module-Specific Exits (Step 7) ---
    # Breakout
    breakout_sl_atr_mult: float = 2.5  # 2.2–2.8 ATR initial SL
    breakout_partial_r: float = 1.5  # partial TP at 1.5R
    breakout_partial_pct: float = 0.35  # close 35%
    breakout_ema_exit_len: int = 144  # exit when Close < EMA144 (2 bars confirm)

    # Pullback
    pullback_sl_atr_mult: float = 2.0  # 1.8–2.2 ATR
    pullback_be_r: float = 1.0  # move SL to BE at 1R
    pullback_partial_r: float = 2.0  # partial TP at 2R
    pullback_partial_pct: float = 0.40  # close 40%
    pullback_timeout_bars: int = 10  # exit if no 0.5R in 8-12 bars
    pullback_min_r: float = 0.5

    # Mean Reversion
    meanrev_timeout_bars: int = 9  # exit if target not reached in 8-10 bars
    meanrev_sl_boundary_atr: float = 1.0  # SL outside range boundary by 0.8-1.2 ATR

    # Core layer
    core_weekly_exit: bool = True  # exit core on weekly close < w_ema169
    core_daily_confirm_bars: int = 2  # consecutive daily closes < d_ema169

    # --- Scoring System (Step 6) ---
    score_threshold_breakout: int = 55
    score_threshold_pullback: int = 75
    score_threshold_meanrev: int = 75

    # Score weights (total = 30 + 30 + 20 + 20 = 100)
    score_weight_market: int = 30
    score_weight_pattern: int = 30
    score_weight_momentum: int = 20
    score_weight_risk: int = 20

    # --- Funding rate ---
    funding_rate_deduction: bool = True  # deduct funding cost for positions > 24h
    funding_rate_annual: float = 0.10  # approximate annualised funding cost (10%)

    # --- Market regime classification ---
    adx_period: int = 14
    adx_ranging_threshold: float = 20.0  # ADX below this → ranging/choppy
    bb_period: int = 20
    bb_std_mult: float = 2.0
    regime_lookback: int = 120  # bars for rolling percentile (120 × 4h = 20 days)
    compression_bb_pct: float = 0.25  # BB width below 25th percentile → compression
    compression_atr_pct: float = 0.30  # ATR/Close below 30th percentile → compression
    high_vol_atr_pct: float = 0.90  # ATR/Close above 90th percentile → high vol
    high_vol_large_candle_mult: float = 2.0  # body > 2× ATR → large candle

    # --- Regime-specific SL/TP adjustments (multipliers on base ATR) ---
    regime_bull_sl_mult: float = 2.5
    regime_bull_tp_mult: float = 5.0
    regime_bear_sl_mult: float = 2.5
    regime_bear_tp_mult: float = 5.0
    regime_ranging_sl_mult: float = 2.0
    regime_ranging_tp_mult: float = 4.0
    regime_compression_sl_mult: float = 1.5
    regime_compression_tp_mult: float = 3.0


@dataclass(frozen=True)
class BacktestConfig:
    symbol: str = "BTC/USDT"
    timeframe: str = "4h"
    limit: int = 50000
    initial_cash: float = 100_000
    commission: float = 0.0004  # 4 bps — typical futures taker fee

    # Data source
    market_type: str = "swap"  # "swap" (perpetual futures) or "spot"
    exchange_id: str = "binance"  # binance / bybit / okx for swap
    proxy_url: str = "http://127.0.0.1:7897"

    # Signal model
    ema_weight: int = 75
    macd_weight: int = 25
    signal_threshold: int = 75

    # EMA settings
    ema_fast_1: int = 55
    ema_fast_2: int = 69
    ema_slow_1: int = 144
    ema_slow_2: int = 169

    # MACD settings
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    # HTF filters
    daily_ema_len: int = 169
    weekly_ema_len: int = 169

    # Cooldown
    cooldown_bars: int = 12
