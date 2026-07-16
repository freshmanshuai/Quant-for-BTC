from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
try:
    from backtesting import Backtest, Strategy
    from backtesting.lib import FractionalBacktest
except ImportError:
    Backtest = None
    FractionalBacktest = None

    class Strategy:
        """Import-time fallback so pure feature helpers remain testable without backtesting."""

from quant_btc.config import BacktestConfig, RiskConfig
from quant_btc.feature_engine import build_btc_feature_engine
from quant_btc.portfolio_model import (
    btc_atr_htf_stop_target,
    btc_bear_core_acceleration_add_plan,
    btc_bear_core_acceleration_add_state_plan,
    btc_bear_core_confirm_add_state_plan,
    btc_bear_core_confirm_signal,
    btc_bear_core_confirm_add_plan,
    btc_bear_core_giveback_exit_plan,
    btc_bear_core_probe_entry_state_plan,
    btc_bear_core_probe_plan,
    btc_bear_core_exit_signal,
    btc_bear_core_stop,
    btc_bear_core_trend_exit_plan,
    btc_bear_core_v_reversal_exit,
    btc_bear_core_v_reversal_exit_plan,
    btc_bear_core_waterfall_guard,
    btc_bear_core_waterfall_runner_exit,
    btc_bear_core_waterfall_runner_exit_plan,
    btc_bear_probe_peak_r,
    btc_base_entry_plan,
    btc_base_invalidation,
    btc_base_partial_tp,
    btc_base_trailing_stop_hit,
    btc_base_trailing_stop_update,
    btc_base_time_stop,
    btc_breakout_extra_exit,
    btc_breakout_stop_target,
    btc_core_add_plan,
    btc_core_add_state_plan,
    btc_core_entry_plan,
    btc_core_exit_plan,
    btc_core_exit_signal,
    btc_core_trail_stop_hit,
    btc_external_close_cleanup_plan,
    btc_flash_crash_dip_buy_plan,
    btc_flash_crash_state,
    btc_htf_stop_target,
    btc_layer_close_portion,
    btc_meanrev_stop_target,
    btc_short_extra_exit,
    btc_short_partial_tp_plan,
    btc_short_giveback_guard,
    btc_short_time_stop,
    btc_tactical_exit_cleanup_plan,
    btc_tactical_entry_plan,
    btc_tactical_exit_close_plan,
    btc_tactical_hard_exit,
    btc_tactical_sl_tp,
    btc_tactical_trailing_stop,
)
from quant_btc.regime_model import btc_regime_entry_gate, build_btc_regime_model
from quant_btc.risk_model import (
    btc_dual_layer_regime_size_multiplier,
    build_btc_legacy_entry_risk_audit,
    build_btc_legacy_entry_risk_decision,
    build_btc_legacy_entry_risk_engine_decision,
    calculate_btc_base_position_size,
    calculate_btc_tactical_position_size,
)
from quant_btc.signal_modules import (
    add_btc_module_score_columns,
    add_btc_score_signal_columns,
    add_btc_signal_predicate_columns,
    btc_mtf_higher_low_formed,
    btc_mtf_no_new_extreme,
    btc_mtf_sweep_reclaim,
    select_btc_base_entry_signal,
    select_btc_bear_core_acceleration_add_signal,
    select_btc_bear_core_confirm_add_signal,
    select_btc_bear_core_probe_signal,
    select_btc_core_add_signal,
    select_btc_core_entry_signal,
    select_btc_flash_crash_dip_buy_signal,
    select_btc_tactical_signal,
    select_btc_weighted_legacy_signal,
)
from quant_platform.features import (
    DerivativesFeatureConfig,
    DerivativesFeatureModule,
    ema as platform_ema,
    htf_ema as platform_htf_ema,
)
from quant_platform.pipeline import PipelineResult, SignalPipeline
from quant_platform.portfolio import (
    PortfolioEngine,
    PortfolioPlan,
    PortfolioState,
    Position,
    PositionKey,
)
from quant_platform.risk import AccountState, RiskEngine, RiskLimits
from quant_platform.signal_modules import SignalModuleRunner
from quant_platform.signals import Direction, Signal


_BTC_PLATFORM_LAYER_BY_MODULE = {
    "legacy_zone": "tactical",
    "legacy_weighted": "tactical",
    "breakout": "tactical",
    "breakout_retest": "tactical",
    "pullback": "tactical",
    "pullback_struct": "tactical",
    "meanrev": "tactical",
    "meanrev_range": "tactical",
    "sweep_reversal": "tactical",
    "crash": "tactical",
    "crash_short": "tactical",
    "failed_bounce": "tactical",
    "bull_trap": "tactical",
    "dip_buy": "tactical",
    "core_long": "core",
    "core_add": "core",
    "core_pullback_add": "core",
    "bear_core_probe": "bear_core",
    "bear_core_confirm": "bear_core",
    "bear_core_confirm_add": "bear_core",
    "bear_core_acceleration": "bear_core",
    "bear_core_acceleration_add": "bear_core",
}


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?Signal feature engineering 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?
# These produce boolean entry columns 鈥?insensitive to price scaling.


def _ema(series: pd.Series, length: int) -> pd.Series:
    return platform_ema(series, length)


def _macd(close: pd.Series, fast: int, slow: int, signal: int):
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    return macd_line, signal_line


def _htf_ema(close: pd.Series, rule: str, length: int) -> pd.Series:
    return platform_htf_ema(close, rule, length)


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

    * ``long_entry`` / ``short_entry`` 鈥?original zone-crossing logic (legacy).
    * ``pullback_long`` / ``pullback_short`` 鈥?trend-pullback entries (Step 2).
      These require: (a) regime context (checked in Strategy.next),
      (b) price in EMA pullback zone, (c) momentum confirmation (RSI or MACD
      histogram), and (d) bar-level price confirmation.
    """
    out = build_btc_feature_engine(cfg).run(df)

    # 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?Legacy entry signals (unchanged) 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?
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
    out = add_btc_signal_predicate_columns(out)

    # 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?Pullback entry signals (Step 2) 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?

    # 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?Donchian Breakout signals (Step 3) 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?    vol_expand = (out["Volume"] > out["vol_sma_50"]) | (out["vol_zscore"] > 0)

    # 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?Mean Reversion signals (Step 4) 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?

    # Scoring system.
    out = add_btc_module_score_columns(out)
    out = add_btc_score_signal_columns(out)

    return out.dropna().copy()


def compute_derivative_bonus(df: pd.DataFrame, deriv_df: pd.DataFrame | None) -> pd.Series:
    """Return derivative bonus Series (0-20) aligned to df.index.

    Call AFTER prepare_features().dropna() so NaN in derivative data
    doesn't drop valid signal rows.
    """
    bonus = pd.Series(0.0, index=df.index)

    if deriv_df is None or deriv_df.empty:
        return bonus

    # Align derivative data to feature DataFrame index
    derivative_features = DerivativesFeatureModule(
        deriv_df,
        DerivativesFeatureConfig(
            funding_zscore_lookback=90,
            funding_min_periods=30,
            open_interest_change_periods=6,
            price_change_periods=6,
        ),
    ).apply(df)
    close = df["Close"]

    funding_z = derivative_features["funding_zscore_90"].fillna(0)

    # 24h changes (6 脳 4h bars)
    oi_change = derivative_features["open_interest_change_6"].fillna(0)
    price_change = derivative_features["derivative_price_change_6"].fillna(0)

    # Crowded longs: high funding + OI rising + price stalled
    crowded = (funding_z > 1.5) & (oi_change > 0.05) & (price_change < 0.02)

    # Deleveraging: price < DC20 low (shifted) + OI dropping fast
    dc20_low = close.rolling(20, min_periods=1).min()
    delever = (close < dc20_low.shift(1)) & (oi_change < -0.03)

    # 鈹€鈹€ Short bonus 鈹€鈹€
    bonus_short = pd.Series(0.0, index=df.index)
    bonus_short[crowded] += 10
    bonus_short[delever] += 10
    bonus_short = bonus_short.clip(0, 20)

    # 鈹€鈹€ Long bonus: crowded shorts 鈫?short squeeze risk 鈹€鈹€
    # Extreme negative funding + OI rising + price not falling
    crowded_shorts = (funding_z < -1.5) & (oi_change > 0.05) & (price_change > -0.02)
    # Deleveraging shorts: price breaks above resistance + OI dropping = shorts covering
    dc20_high_val = close.rolling(20, min_periods=1).max()
    short_cover = (close > dc20_high_val.shift(1)) & (oi_change < -0.03)
    bonus_long = pd.Series(0.0, index=df.index)
    bonus_long[crowded_shorts] += 10
    bonus_long[short_cover] += 10
    bonus_long = bonus_long.clip(0, 20)

    # Store both in DataFrame
    df["_short_deriv_bonus"] = bonus_short
    df["_perp_crowding_long_bonus"] = bonus_long
    return bonus_short


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?Risk feature helpers (called from Strategy.init) 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?


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


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲 Base risk-managed strategy 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲


class BaseRiskStrategy(Strategy):
    """Shared risk controls: position sizing, circuit breaker, trailing stop, invalidation.

    Risk features (ATR, HTF levels) are computed in ``init()`` from ``self.data``,
    which is already price-scaled by ``FractionalBacktest`` when applicable.
    """

    risk_cfg: RiskConfig = RiskConfig()
    cooldown_bars: int = 12
    trade_size_fraction: float = 0.95
    _ENFORCE_PLATFORM_RISK_ENGINE: bool = False

    # Subclass overridable behaviour
    _USE_FIXED_TP: bool = True   # False 鈫?breakout mode: no fixed TP, trail-only exit
    _BREAKOUT_MODE: bool = False  # True 鈫?wider trailing + Donchian exit
    _MIN_RR: float = 2.0  # minimum reward/risk ratio
    _SCORE_THRESHOLD: int = 70  # minimum score (0-100) for entry
    _RISK_PER_TRADE: float = 0.02  # overridden per module
    _SIGNAL_MODULE: str = "legacy_zone"

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

        # Daily swing high / low
        df["_d_high"], df["_d_low"] = _build_daily_prev_hl(
            df["High"], df["Low"], idx, rcfg.htf_lookback_days
        )

        regime_df = build_btc_regime_model(rcfg).classify(df)
        for col in ["_atr", "_d_ema_dir", "_w_ema_dir", "_d_ema_169", "_w_ema_169", "_bb_width_pct", "_atr_pct", "_adx", "_regime"]:
            df[col] = regime_df[col]

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
        self._last_platform_risk_decision = None
        self._last_platform_risk_engine_decision = None
        self._last_platform_pipeline_result = None
        self._last_platform_entry_order = None
        self._platform_pipeline_results = []
        self._last_platform_risk_audit = None
        self._platform_risk_audits = []

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

    def _record_legacy_entry_risk_decision(
        self,
        *,
        signal: Signal,
        entry_price: float,
        size_fraction: float,
        stop_price: float | None,
        target_price: float | None,
    ):
        self._last_platform_risk_decision = build_btc_legacy_entry_risk_decision(
            signal=signal,
            equity=self.equity,
            entry_price=entry_price,
            size_fraction=size_fraction,
            stop_price=stop_price,
            target_price=target_price,
        )
        self._last_platform_risk_engine_decision = build_btc_legacy_entry_risk_engine_decision(
            signal=signal,
            equity=self.equity,
            entry_price=entry_price,
            size_fraction=size_fraction,
            stop_price=stop_price,
            target_price=target_price,
            risk_engine=getattr(self, "_platform_risk_engine", None),
        )
        self._last_platform_risk_audit = build_btc_legacy_entry_risk_audit(
            legacy_decision=self._last_platform_risk_decision,
            engine_decision=self._last_platform_risk_engine_decision,
            enforcement_enabled=getattr(self, "_ENFORCE_PLATFORM_RISK_ENGINE", False),
            bar_index=self._bar_index(),
        )
        self._last_platform_pipeline_result = SignalPipeline(
            signal_runner=SignalModuleRunner([]),
            risk_engine=RiskEngine(RiskLimits()),
            portfolio_engine=PortfolioEngine(layer_by_module=_BTC_PLATFORM_LAYER_BY_MODULE),
        ).run_decisions(
            [self._last_platform_risk_decision],
            account=AccountState(equity=float(self.equity)),
            bar_index=self._bar_index(),
        )
        if not hasattr(self, "_platform_pipeline_results"):
            self._platform_pipeline_results = []
        self._platform_pipeline_results.append(self._last_platform_pipeline_result)
        self._last_platform_entry_order = self._platform_open_entry_order(
            self._last_platform_pipeline_result
        )
        if not hasattr(self, "_platform_risk_audits"):
            self._platform_risk_audits = []
        self._platform_risk_audits.append(self._last_platform_risk_audit)
        return self._last_platform_risk_decision

    def _platform_open_entry_order(self, pipeline_result):
        for order in getattr(pipeline_result.portfolio_plan, "orders", []):
            action = getattr(order.action, "value", order.action)
            if action == "open":
                return order
        return None

    def _entry_order_parameters(
        self,
        *,
        is_long: bool,
        stop_price: float | None,
        target_price: float | None,
    ) -> tuple[bool, float | None, float | None]:
        platform_order = getattr(self, "_last_platform_entry_order", None)
        if platform_order is None:
            return is_long, stop_price, target_price
        order_is_long = platform_order.direction == Direction.LONG
        order_stop = (
            platform_order.stop_price
            if platform_order.stop_price is not None
            else stop_price
        )
        return order_is_long, order_stop, platform_order.target_price

    def _platform_risk_engine_blocks_entry(self) -> bool:
        if not getattr(self, "_ENFORCE_PLATFORM_RISK_ENGINE", False):
            return False
        decision = getattr(self, "_last_platform_risk_engine_decision", None)
        return decision is not None and not decision.allowed

    def _record_platform_close_pipeline(self, *, reason: str, portion: float | None = None):
        position = getattr(self, "position", None)
        if not position:
            return None
        entry_price = self._at("Close")
        direction = Direction.LONG if position.is_long else Direction.SHORT
        module = self._SIGNAL_MODULE
        layer = _BTC_PLATFORM_LAYER_BY_MODULE.get(module, "tactical")
        size_fraction = abs(float(getattr(position, "size", 0.0)))
        decision_signal = Signal(
            module=module,
            symbol="BTC/USDT",
            direction=direction,
            score=0.0,
            entry_reason=reason,
            invalidation=reason,
        )
        decision = build_btc_legacy_entry_risk_decision(
            signal=decision_signal,
            equity=self.equity,
            entry_price=entry_price,
            size_fraction=size_fraction,
            stop_price=getattr(self, "_trailing_sl", None),
            target_price=None,
            reason=f"{reason}_audit",
        )
        state = PortfolioState(positions={
            PositionKey("BTC/USDT", layer): Position(
                symbol="BTC/USDT",
                layer=layer,
                direction=direction,
                quantity=decision.quantity,
                notional=decision.notional,
                risk_amount=decision.risk_amount,
                module=module,
                entry_price=entry_price,
                stop_price=decision.stop_price,
            )
        })
        risk_engine = RiskEngine(RiskLimits())
        portfolio_engine = PortfolioEngine(
            state=state,
            layer_by_module=_BTC_PLATFORM_LAYER_BY_MODULE,
        )
        order = portfolio_engine.close_position(
            "BTC/USDT",
            layer,
            fill_price=entry_price,
            quantity=decision.quantity * float(portion) if portion is not None else decision.quantity,
            reason=reason,
            decision=decision,
        )
        self._last_platform_pipeline_result = PipelineResult(
            signals=[decision_signal],
            risk_decisions=[decision],
            portfolio_plan=PortfolioPlan(orders=[order]),
            delivery_results=[],
            risk_diagnostics=risk_engine.budget_diagnostics(
                AccountState(equity=float(self.equity)),
                bar_index=self._bar_index(),
            ),
        )
        if not hasattr(self, "_platform_pipeline_results"):
            self._platform_pipeline_results = []
        self._platform_pipeline_results.append(self._last_platform_pipeline_result)
        return self._last_platform_pipeline_result

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
        """Risk-based position sizing: size = equity 脳 risk% / |entry - SL|."""
        risk_pct = getattr(self, '_RISK_PER_TRADE', self.risk_cfg.risk_per_trade)
        return calculate_btc_base_position_size(
            entry=entry,
            stop=sl,
            risk_per_trade=risk_pct,
            consecutive_losses=self._consecutive_losses,
            daily_ema_dir=self._at("_d_ema_dir"),
            weekly_ema_dir=self._at("_w_ema_dir"),
            risk_cfg=self.risk_cfg,
        )

    # -- trailing stop --

    def _update_trailing(self, is_long: bool):
        self._extreme_since_entry, self._trailing_sl = btc_base_trailing_stop_update(
            is_long=is_long,
            close=self._at("Close"),
            high=self._at("High"),
            low=self._at("Low"),
            atr=self._at("_atr"),
            entry_price=self._entry_price,
            initial_risk=self._initial_risk,
            previous_extreme=self._extreme_since_entry,
            trailing_stop=self._trailing_sl,
            breakout_mode=self._BREAKOUT_MODE,
            effective_breakeven_r=getattr(self, '_effective_trailing_breakeven_r', self.risk_cfg.trailing_breakeven_r),
            risk_cfg=self.risk_cfg,
        )

    def _check_trailing_hit(self, is_long: bool) -> bool:
        return btc_base_trailing_stop_hit(
            is_long=is_long,
            low=self._at("Low"),
            high=self._at("High"),
            trailing_stop=self._trailing_sl,
        )

    # -- invalidation --

    def _check_extra_exit(self, is_long: bool) -> bool:
        """Override in subclass to add extra exit conditions (e.g. Donchian reverse)."""
        return False

    def _check_partial_tp(self, is_long: bool) -> bool:
        """Check if partial take-profit level is reached."""
        return btc_base_partial_tp(
            enabled=self._USE_PARTIAL_TP,
            partial_done=getattr(self, "_partial_done", False),
            is_long=is_long,
            entry_price=self._entry_price,
            initial_risk=self._initial_risk,
            close=self._at("Close"),
            partial_tp_r=self._PARTIAL_TP_R,
        )

    def _check_time_stop(self, is_long: bool) -> bool:
        """Exit if held too long without sufficient profit."""
        return btc_base_time_stop(
            enabled=self._USE_TIME_STOP,
            is_long=is_long,
            bars_held=self._bar_index() - self._entry_bar,
            time_stop_bars=self._TIME_STOP_BARS,
            entry_price=self._entry_price,
            initial_risk=self._initial_risk,
            close=self._at("Close"),
            min_profit_r=self._MIN_PROFIT_R,
        )

    def _regime_entry_gate(
        self, regime: int, d_dir: int, w_dir: int
    ) -> tuple[bool, bool]:
        """Return (allow_long, allow_short) based on regime + HTF context.
        Default: Pullback logic - strict regime or soft HTF alignment.
        """
        return btc_regime_entry_gate(regime=regime, d_dir=d_dir, w_dir=w_dir, mode="default")

    def _check_invalidation(self, is_long: bool) -> bool:
        return btc_base_invalidation(
            is_long=is_long,
            bars_held=self._bar_index() - self._entry_bar,
            max_bars_no_profit=self.risk_cfg.max_bars_no_profit,
            close=self._at("Close"),
            entry_price=self._entry_price,
            entry_atr=self._entry_atr,
            current_atr=self._at("_atr"),
            volatility_spike_atr_mult=self.risk_cfg.volatility_spike_atr_mult,
            daily_ema_dir=self._at("_d_ema_dir"),
            weekly_ema_dir=self._at("_w_ema_dir"),
        )

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

            # Partial TP (before trailing/invalidation 鈥?locks in profit)
            if self._check_partial_tp(is_long):
                self._record_platform_close_pipeline(
                    reason="partial_take_profit",
                    portion=self._PARTIAL_TP_PCT,
                )
                self.position.close(portion=self._PARTIAL_TP_PCT)
                self._partial_done = True

            # Time stop (insufficient momentum)
            if self._check_time_stop(is_long):
                self._record_platform_close_pipeline(reason="time_stop")
                self.position.close()
                self._last_trade_bar = i
                return

            self._update_trailing(is_long)
            if self._check_invalidation(is_long):
                self._record_platform_close_pipeline(reason="invalidation")
                self.position.close()
                self._last_trade_bar = i
                return
            if self._check_trailing_hit(is_long):
                self._record_platform_close_pipeline(reason="trailing_stop")
                self.position.close()
                self._last_trade_bar = i
                return
            if self._check_extra_exit(is_long):
                self._record_platform_close_pipeline(reason="extra_exit")
                self.position.close()
                self._last_trade_bar = i
                return
            return

        # Entry 鈥?regime-aware (Step 1 & 2 share this, gated by class attrs)
        regime = self._current_regime()
        d_dir = self._at("_d_ema_dir")
        w_dir = self._at("_w_ema_dir")

        if self._USE_REGIME_GATE and regime != 4:
            allow_long, allow_short = self._regime_entry_gate(regime, d_dir, w_dir)
        else:
            # Step 1: Zone crossing 鈥?no direction gate (signal already directional)
            allow_long = True
            allow_short = True

        entry_signal = select_btc_base_entry_signal(
            self.data.df.iloc[i],
            symbol="BTC/USDT",
            module=self._SIGNAL_MODULE,
            long_column=self._LONG_COL,
            short_column=self._SHORT_COL,
            regime=regime,
            daily_ema_dir=d_dir,
            weekly_ema_dir=w_dir,
            allow_long=allow_long,
            allow_short=allow_short,
            score_threshold=self._SCORE_THRESHOLD,
        )
        if entry_signal is None:
            return
        is_long = entry_signal.direction == Direction.LONG

        result = self._calc_sl_tp(is_long, regime)
        if result is None:
            return

        sl, tp = result
        entry = self._at("Close")
        size = self._calc_position_size(entry, sl)

        plan = btc_base_entry_plan(
            is_long=is_long,
            entry_price=entry,
            stop_price=sl,
            target_price=tp,
            size=size,
            use_fixed_tp=self._USE_FIXED_TP,
            min_reward_risk=self._MIN_RR,
            min_size=0.001,
            entry_atr=self._at("_atr"),
            entry_bar=i,
        )
        if plan is None:
            return

        self._record_legacy_entry_risk_decision(
            signal=entry_signal,
            entry_price=plan.entry_price,
            size_fraction=plan.size,
            stop_price=plan.stop_price,
            target_price=plan.target_price,
        )
        if self._platform_risk_engine_blocks_entry():
            return

        self._eq_before_close = self.equity  # snapshot for PnL tracking

        order_is_long, order_stop, order_target = self._entry_order_parameters(
            is_long=plan.is_long,
            stop_price=plan.stop_price,
            target_price=plan.target_price,
        )

        if order_is_long:
            self.buy(size=plan.size, sl=order_stop, tp=order_target)
        else:
            self.sell(size=plan.size, sl=order_stop, tp=order_target)

        self._trailing_sl = plan.trailing_stop
        self._extreme_since_entry = plan.extreme_since_entry
        self._entry_price = plan.entry_price
        self._entry_atr = plan.entry_atr
        self._initial_risk = plan.initial_risk
        self._entry_bar = plan.entry_bar
        self._last_trade_bar = plan.last_trade_bar
        self._partial_done = plan.partial_done


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?Scheme A: Pure HTF SL/TP 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲


class HTFStopStrategy(BaseRiskStrategy):
    """SL = N-day swing high/low.  TP = entry +/- 2*risk (1:2 RR)."""

    def _calc_sl_tp(self, is_long: bool, regime: int) -> tuple[float, float] | None:
        return btc_htf_stop_target(
            is_long=is_long,
            entry=self._at("Close"),
            daily_high=self._at("_d_high"),
            daily_low=self._at("_d_low"),
            risk_cfg=self.risk_cfg,
        )


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?Scheme B: ATR + HTF SL/TP 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲


class ATRHTFStopStrategy(BaseRiskStrategy):
    """Regime-adaptive ATR SL/TP with HTF swing-level caps (zone crossing, legacy)."""

    _LONG_COL = "long_entry"
    _SHORT_COL = "short_entry"
    _USE_REGIME_GATE = False
    _SCORE_THRESHOLD = 0  # legacy boolean columns 鈫?no score threshold

    def _calc_sl_tp(self, is_long: bool, regime: int) -> tuple[float, float] | None:
        return btc_atr_htf_stop_target(
            is_long=is_long,
            entry=self._at("Close"),
            atr=self._at("_atr"),
            daily_high=self._at("_d_high"),
            daily_low=self._at("_d_low"),
            regime=regime,
            risk_cfg=self.risk_cfg,
        )


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?Step 2: Pullback Entry Strategy 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲


class PullbackStrategy(ATRHTFStopStrategy):
    """Trend-pullback entries with regime gating (Step 2).

    Longs only when HTF is bullish, shorts only when HTF is bearish.
    Entry requires: pullback zone + momentum confirmation + price confirmation.
    """

    _LONG_COL = "score_pullback_long"
    _SHORT_COL = "score_pullback_short"
    _SIGNAL_MODULE = "pullback"
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


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?Step 3: Donchian Breakout Strategy 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲


class BreakoutStrategy(ATRHTFStopStrategy):
    """Donchian 55 breakout with trend-following exit (no fixed TP).

    Long:  Bull or Compression regime, Close > 55-bar high (shifted),
           volume expansion, ADX strong/rising, ATR in 30-85% range, Close > EMA55.
    Short: Bear regime, Close < 55-bar low, volume expansion, ADX strong,
           Close < EMA55, weekly not bullish.

    Exit:  ATR trailing stop (3脳 ATR, wider for trend-following)
           + Donchian 20 reverse breakout.
    """

    _LONG_COL = "score_breakout_long"
    _SHORT_COL = "score_breakout_short"
    _SIGNAL_MODULE = "breakout"
    _USE_REGIME_GATE = True
    _USE_FIXED_TP = False
    _BREAKOUT_MODE = True
    _SCORE_THRESHOLD = 55
    _RISK_PER_TRADE = 0.0065  # 0.65% per breakout trade
    _USE_PARTIAL_TP = True
    _PARTIAL_TP_R = 1.5
    _PARTIAL_TP_PCT = 0.35

    def _calc_sl_tp(self, is_long: bool, regime: int) -> tuple[float, float] | None:
        """SL-only: ATR stop with HTF cap.  No fixed TP 鈥?exit via trailing."""
        return btc_breakout_stop_target(
            is_long=is_long,
            entry=self._at("Close"),
            atr=self._at("_atr"),
            daily_high=self._at("_d_high"),
            daily_low=self._at("_d_low"),
            risk_cfg=self.risk_cfg,
        )

    def _regime_entry_gate(
        self, regime: int, d_dir: int, w_dir: int
    ) -> tuple[bool, bool]:
        """Breakout gating: Bull + Compression for longs, Bear only for shorts."""
        return btc_regime_entry_gate(regime=regime, d_dir=d_dir, w_dir=w_dir, mode="breakout")

    def _check_extra_exit(self, is_long: bool) -> bool:
        """Donchian 20 reverse + EMA144/169 cross (2-bar confirm)."""
        close = self._at("Close")
        return btc_breakout_extra_exit(
            is_long=is_long,
            close=close,
            dc20_low=self._at("_dc20_low"),
            dc20_high=self._at("_dc20_high"),
            ema144=self._at("ema144"),
            prev_close=float(self.data.df["Close"].iloc[-2]),
            prev_ema144=float(self.data.df["ema144"].iloc[-2]),
        )


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?Legacy (no risk mgmt) 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?Step 4: Mean Reversion Strategy 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲


class MeanRevStrategy(BaseRiskStrategy):
    """Mean-reversion for ranging markets.  Small position, tight SL, fixed TP.

    Long:  Ranging regime, ADX<25, price near BB lower / DC20 low,
           RSI<35, wick or close-back confirmation.
    Short: Ranging regime, price near BB upper / DC20 high,
           RSI>65.

    TP = BB mid or EMA55 (range midpoint).  No trailing 鈥?fixed exit.
    Position = 40% of normal trend size.
    """

    _LONG_COL = "score_meanrev_long"
    _SHORT_COL = "score_meanrev_short"
    _SIGNAL_MODULE = "meanrev"
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
        return btc_regime_entry_gate(regime=regime, d_dir=d_dir, w_dir=w_dir, mode="meanrev")

    def _calc_sl_tp(self, is_long: bool, regime: int) -> tuple[float, float] | None:
        return btc_meanrev_stop_target(
            is_long=is_long,
            entry=self._at("Close"),
            atr=self._at("_atr"),
            bb_upper=self._at("bb_upper"),
            bb_lower=self._at("bb_lower"),
            ema55=self._at("ema55"),
            risk_cfg=self.risk_cfg,
        )

    def _calc_position_size(self, entry: float, sl: float) -> float:
        """Smaller position for mean reversion trades."""
        base = super()._calc_position_size(entry, sl)
        return base * self.risk_cfg.mean_rev_size_mult


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?Step 5: Dual-Layer Strategy 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?


class DualLayerStrategy(BaseRiskStrategy):
    """Two-layer portfolio: core long (BTC beta) + tactical (4H alpha).

    Core:  Long-only.  Enters on weekly+daily bull alignment.
           Exits on weekly failure or 2 consecutive daily closes < EMA169.
           Adds on pullback signals while active.

    Tactical:  Long or short.  Uses the best signal for current regime:
           Bull 鈫?breakout_long + pullback_long
           Bear 鈫?breakout_short + pullback_short
           Ranging 鈫?meanrev_long + meanrev_short
           Compression 鈫?breakout_long

    Position: core_size + tactical_size, managed via partial closes so
    tactical exits don't disturb the core.
    """

    _USE_FIXED_TP = False
    _BREAKOUT_MODE = False
    _MIN_RR = 2.0
    _USE_TIME_STOP = True
    _USE_PARTIAL_TP = True

    # MTF (multi-timeframe) data 鈥?set by run_backtest.py before backtest
    _mtf_15m: pd.DataFrame | None = None

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
        self._flash_crash_active = False
        self._flash_crash_bar = -10**9
        # Bear group risk tracking
        self._bear_group_id = 0  # incremented per structure
        self._bear_group_exposure = 0.0
        self._bear_group_entry_bar = -10**9
        self._bear_group_peak_r = 0.0
        self._bear_group_max_exposure = 0.50
        self._bear_group_max_loss_pct = 0.006

    # 鈹€鈹€ Core helpers 鈹€鈹€

    def _is_last_bar_of_day(self) -> bool:
        i = self._bar_index()
        df = self.data.df
        if i + 1 >= len(df):
            return True
        return df.index[i].day != df.index[i + 1].day

    def _core_entry_standard_signal(self) -> Signal | None:
        """Core enters only in strict Bull regime (regime == 1)."""
        return select_btc_core_entry_signal(symbol="BTC/USDT", regime=self._current_regime())

    def _core_entry_signal(self) -> bool:
        return self._core_entry_standard_signal() is not None

    def _core_exit_signal(self) -> bool:
        """Core exits on weekly failure or 2 daily closes below EMA169."""
        should_exit, self._last_day, self._days_below_dema = btc_core_exit_signal(
            weekly_ema_dir=self._at("_w_ema_dir"),
            close=self._at("Close"),
            daily_ema=self._at("_d_ema_169"),
            day_id=self._day_id(),
            last_day=self._last_day,
            days_below_dema=self._days_below_dema,
            risk_cfg=self.risk_cfg,
        )
        return should_exit

    def _core_trail_stop_hit(self) -> bool:
        """Daily ATR trailing stop for core."""
        stop_hit, self._core_highest_close = btc_core_trail_stop_hit(
            core_active=self._core_active,
            highest_close=self._core_highest_close,
            close=self._at("Close"),
            atr=self._at("_atr"),
            risk_cfg=self.risk_cfg,
        )
        return stop_hit

    def _core_add_standard_signal(self) -> Signal | None:
        """Add to core on pullback long signal."""
        return select_btc_core_add_signal(
            self.data.df.iloc[self._bar_index()],
            symbol="BTC/USDT",
        )

    def _core_add_signal(self) -> bool:
        return self._core_add_standard_signal() is not None

    # 鈹€鈹€ Bear core helpers 鈹€鈹€

    def _bear_core_probe_standard_signal(self) -> Signal | None:
        """Bear core probe: top exhaustion and neckline-break permission."""
        return select_btc_bear_core_probe_signal(
            self.data.df.iloc[self._bar_index()],
            symbol="BTC/USDT",
            core_active=self._core_active,
            bear_core_active=self._bear_core_active,
        )

    def _bear_core_probe_signal(self) -> bool:
        return self._bear_core_probe_standard_signal() is not None

    def _bear_core_confirm_add_standard_signal(self) -> Signal | None:
        """Bear core stage-2 add after the probe has proven itself."""
        return select_btc_bear_core_confirm_add_signal(
            self.data.df.iloc[self._bar_index()],
            symbol="BTC/USDT",
            bar_index=self._bar_index(),
            entry_bar=getattr(self, '_bear_core_entry_bar', -10**9),
            active=self._bear_core_active,
            stage=getattr(self, '_bear_core_stage', 0),
            probe_peak_r=getattr(self, '_bear_probe_peak_r', 0.0),
        )

    def _bear_core_acceleration_add_standard_signal(self) -> Signal | None:
        """Bear core stage-3 add when trend and DMI confirm acceleration."""
        return select_btc_bear_core_acceleration_add_signal(
            self.data.df.iloc[self._bar_index()],
            symbol="BTC/USDT",
            bar_index=self._bar_index(),
            last_trade_bar=getattr(self, '_last_trade_bar', -10**9),
            active=self._bear_core_active,
            stage=getattr(self, '_bear_core_stage', 0),
        )

    def _bear_core_confirm_signal(self) -> bool:
        """Bear core confirm: probe active + weekly also bearish."""
        return btc_bear_core_confirm_signal(
            probe_active=self._bear_core_probe,
            close=self._at("Close"),
            daily_ema_dir=self._at("_d_ema_dir"),
            daily_ema=self._at("_d_ema_169"),
            weekly_ema=self._at("_w_ema_169"),
            weekly_ema_dir=self._at("_w_ema_dir"),
        )

    def _check_waterfall_profit_guard(self) -> bool:
        """Detect event-driven crash: large profit in few bars without bear trend.
        Uses 4H ATR for R-computation (waterfall is a 4H event, not daily)."""
        triggered, close_fraction, lock_r, next_stage = btc_bear_core_waterfall_guard(
            stage=getattr(self, '_bear_core_stage', 0),
            entry_price=self._bear_core_entry_price,
            low=self._at("Low"),
            atr_4h=self._at("_atr"),
            bars_since_entry=self._bar_index() - getattr(self, '_bear_core_entry_bar', -10**9),
            daily_ema_dir=self._at("_d_ema_dir"),
        )
        if not triggered:
            return False
        self._record_layer_close_pipeline(
            layer="bear_core",
            module=self._bear_core_close_module(),
            direction=Direction.SHORT,
            layer_size=self._bear_core_size,
            reason="bear_core_waterfall_guard",
            portion=close_fraction,
        )
        self._close_portion(close_fraction)
        self._waterfall_lock_r = lock_r
        self._bear_core_stage = next_stage
        return True

    def _bear_core_sl(self) -> float:
        """Bear core SL: 2.5脳 daily ATR above entry, capped by recent daily high."""
        return btc_bear_core_stop(
            entry_price=self._bear_core_entry_price,
            atr_4h=self._at("_atr"),
            risk_cfg=self.risk_cfg,
        )

    def _bear_core_exit_signal(self) -> bool:
        """Bear core exit: trend reversal or trailing stop."""
        should_exit, self._last_day, self._days_above_dema = btc_bear_core_exit_signal(
            bear_core_active=self._bear_core_active,
            entry_price=self._bear_core_entry_price,
            close=self._at("Close"),
            atr_4h=self._at("_atr"),
            daily_ema_dir=self._at("_d_ema_dir"),
            daily_ema=self._at("_d_ema_169"),
            day_id=self._day_id(),
            last_day=self._last_day,
            days_above_dema=self._days_above_dema,
            risk_cfg=self.risk_cfg,
        )
        return should_exit

    # 鈹€鈹€ MTF (15m) confirmation helpers 鈹€鈹€

    def _mtf_15m_bars(self) -> pd.DataFrame | None:
        """Return 15m bars within the current 4H bar window."""
        mtf = DualLayerStrategy._mtf_15m
        if mtf is None or mtf.empty:
            return None
        ts = self.data.df.index[-1]
        end = ts + pd.Timedelta(hours=4)
        return mtf[(mtf.index >= ts) & (mtf.index < end)]

    def _mtf_sweep_reclaim(self, is_long: bool, key_level: float) -> bool:
        """Check 15m bars: sweep below key level then reclaim above it."""
        return btc_mtf_sweep_reclaim(
            self._mtf_15m_bars(),
            is_long=is_long,
            key_level=key_level,
        )

    def _mtf_no_new_extreme(self, is_long: bool) -> bool:
        """Check 15m: last 2 bars didn't make new low (long) or new high (short)."""
        return btc_mtf_no_new_extreme(self._mtf_15m_bars(), is_long=is_long)

    def _mtf_higher_low_formed(self) -> bool:
        """15m: a higher low formed within this 4H bar."""
        return btc_mtf_higher_low_formed(self._mtf_15m_bars())

    # 鈹€鈹€ Tactical helpers 鈹€鈹€

    def _tactical_signal(self) -> Signal | None:
        """Return the priority-ordered tactical signal for the current bar.

        Framework:
          Strong Bull (r=1)        鈫?BO long + PB long + core; NO shorts
          Weak Bull / Transition   鈫?only high-quality BO/PB; half size (via _calc_position_size)
          Ranging (r=0)            鈫?only small mean-rev; no breakout chasing
          Compression (r=3)        鈫?BO long allowed (breakout from compression)
          Strong Bear (r=2)        鈫?BO short + PB short; NO longs
          High Risk (r=4)          鈫?blocked before this method (no new positions)
        """
        regime = self._current_regime()
        i = self._bar_index()
        row = self.data.df.iloc[i]
        sweep_gate_l = bool(row.get("_sweep_signal_long", False))
        sweep_gate_s = bool(row.get("_sweep_signal_short", False))
        # MTF (15m) confirmation bonuses
        mtf_confirm_l = self._mtf_no_new_extreme(True) if sweep_gate_l else False
        mtf_confirm_s = self._mtf_no_new_extreme(False) if sweep_gate_s else False
        mtf_hl = self._mtf_higher_low_formed()  # higher low for retest/pullback
        return select_btc_tactical_signal(
            row,
            symbol="BTC/USDT",
            regime=regime,
            daily_ema_dir=self._at("_d_ema_dir"),
            weekly_ema_dir=self._at("_w_ema_dir"),
            core_active=self._core_active,
            bear_core_active=self._bear_core_active,
            short_rsi_floor=self.risk_cfg.short_rsi_floor,
            mtf_no_new_extreme_long=mtf_confirm_l,
            mtf_no_new_extreme_short=mtf_confirm_s,
            mtf_higher_low=mtf_hl,
        )

    def _tactical_signals(self) -> tuple[bool, bool, str]:
        signal = self._tactical_signal()
        if signal is None:
            return False, False, "none"
        return signal.direction == Direction.LONG, signal.direction == Direction.SHORT, signal.module

    def _check_partial_tp(self, is_long: bool) -> bool:
        """Short-specific partial TP: crash=40%@1R+30%@2R, others=disabled."""
        if is_long:
            return super()._check_partial_tp(is_long)
        # Short: only crash breakdown uses partial TP
        plan = btc_short_partial_tp_plan(
            module=self._tac_module,
            entry_price=self._tac_entry_price,
            stop_price=self._tac_sl,
            close=self._at("Close"),
            tp1_done=getattr(self, "_tp1_done", False),
            tp2_done=getattr(self, "_tp2_done", False),
            risk_cfg=self.risk_cfg,
        )
        if not plan.should_take_profit:
            return False
        self._tp1_done = plan.tp1_done
        self._tp2_done = plan.tp2_done
        self._PARTIAL_TP_PCT = plan.portion
        return True

    def _check_time_stop(self, is_long: bool) -> bool:
        """Short-specific time stops: crash=8, pullback=10, bulltrap=6 bars.
        Must reach 1R within timeout, and once reached, exit if falls below 0.5R."""
        if is_long:
            return super()._check_time_stop(is_long)
        should_exit, self._short_reached_1r = btc_short_time_stop(
            module=self._tac_module,
            bars_held=self._bar_index() - self._tac_entry_bar,
            entry_price=self._tac_entry_price,
            stop_price=self._tac_sl,
            close=self._at("Close"),
            short_reached_1r=getattr(self, "_short_reached_1r", False),
            risk_cfg=self.risk_cfg,
        )
        return should_exit

    def _check_extra_exit(self, is_long: bool) -> bool:
        """Short: Donchian 10 high exit for crash; DC20 low as target hit for others."""
        if is_long:
            return super()._check_extra_exit(is_long)
        close = self._at("Close")
        dc10_high = float(self.data.df["High"].rolling(10, min_periods=1).max().iloc[-1])
        return btc_short_extra_exit(
            module=self._tac_module,
            close=close,
            dc10_high=dc10_high,
            dc20_low=self._at("_dc20_low"),
        )

    def _calc_position_size(self, entry: float, sl: float) -> float:
        """Override: add weak-bull half-sizing."""
        size = super()._calc_position_size(entry, sl)
        return size * btc_dual_layer_regime_size_multiplier(
            regime=self._current_regime(),
            daily_ema_dir=self._at("_d_ema_dir"),
            weekly_ema_dir=self._at("_w_ema_dir"),
        )

    def _tactical_sl_tp(self, is_long: bool) -> tuple[float, float] | None:
        """Compute SL/TP for tactical trades (regime-adaptive ATR)."""
        return btc_tactical_sl_tp(
            is_long=is_long,
            entry=self._at("Close"),
            atr=self._at("_atr"),
            daily_high=self._at("_d_high"),
            daily_low=self._at("_d_low"),
            regime=self._current_regime(),
            risk_cfg=self.risk_cfg,
        )

    def _check_short_giveback_guard(self, entry_price: float, sl_price: float) -> bool:
        """Tiered R-level giveback protection for ALL shorts.

        Peak >= 1R & drops to <= 0.25R 鈫?exit
        Peak >= 2R & drops to <= 0.8R  鈫?exit
        Peak >= 4R & drops to <= 2.0R  鈫?exit
        """
        should_exit, self._short_giveback_peak_r = btc_short_giveback_guard(
            entry_price=entry_price,
            stop_price=sl_price,
            low=self._at("Low"),
            close=self._at("Close"),
            previous_peak_r=getattr(self, '_short_giveback_peak_r', -999.0),
        )
        return should_exit

    def _check_tactical_exit(self) -> bool:
        """Check if tactical SL/TP/trail/time-stop is hit."""
        if self._tac_direction == 0:
            return False

        is_long = self._tac_direction == 1

        # Tiered R-level giveback guard (all shorts)
        if not is_long and self._tac_entry_price > 0 and self._tac_sl > 0:
            if self._check_short_giveback_guard(self._tac_entry_price, self._tac_sl):
                return True

        # Time stop (before SL/TP 鈥?cuts losers early)
        if self._check_time_stop(is_long):
            return True

        price = self._at("Close")
        high = self._at("High")
        low = self._at("Low")

        if btc_tactical_hard_exit(
            is_long=is_long,
            high=high,
            low=low,
            stop_price=self._tac_sl,
            target_price=self._tac_tp,
        ):
            return True

        # ATR trailing stop (same logic as base class)
        should_exit, self._tac_extreme, self._tac_sl = btc_tactical_trailing_stop(
            is_long=is_long,
            price=price,
            high=high,
            low=low,
            atr=self._at("_atr"),
            previous_extreme=getattr(self, "_tac_extreme", price),
            stop_price=self._tac_sl,
            risk_cfg=self.risk_cfg,
        )
        if should_exit:
            return True

        return False

    # 鈹€鈹€ Position helpers 鈹€鈹€

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

    def _close_layer(self, layer_size: float):
        """Close only a specific layer, leaving other layers intact."""
        if not self.position:
            return
        portion = btc_layer_close_portion(layer_size=layer_size, total_position_size=float(self.position.size))
        if portion > 0:
            self.position.close(portion=portion)

    def _bear_core_close_module(self) -> str:
        stage = getattr(self, "_bear_core_stage", 0)
        if stage >= 3:
            return "bear_core_acceleration"
        if stage >= 2:
            return "bear_core_confirm"
        return "bear_core_probe"

    def _record_layer_close_pipeline(
        self,
        *,
        layer: str,
        module: str,
        direction: Direction,
        layer_size: float,
        reason: str,
        portion: float | None = None,
    ):
        entry_price = self._at("Close")
        decision_signal = Signal(
            module=module,
            symbol="BTC/USDT",
            direction=direction,
            score=0.0,
            entry_reason=reason,
            invalidation=reason,
        )
        decision = build_btc_legacy_entry_risk_decision(
            signal=decision_signal,
            equity=self.equity,
            entry_price=entry_price,
            size_fraction=abs(float(layer_size)),
            stop_price=None,
            target_price=None,
            reason=f"{reason}_audit",
        )
        state = PortfolioState(positions={
            PositionKey("BTC/USDT", layer): Position(
                symbol="BTC/USDT",
                layer=layer,
                direction=direction,
                quantity=decision.quantity,
                notional=decision.notional,
                risk_amount=decision.risk_amount,
                module=module,
                entry_price=entry_price,
            )
        })
        risk_engine = RiskEngine(RiskLimits())
        portfolio_engine = PortfolioEngine(
            state=state,
            layer_by_module=_BTC_PLATFORM_LAYER_BY_MODULE,
        )
        order = portfolio_engine.close_position(
            "BTC/USDT",
            layer,
            fill_price=entry_price,
            quantity=decision.quantity * float(portion) if portion is not None else decision.quantity,
            reason=reason,
            decision=decision,
        )
        self._last_platform_pipeline_result = PipelineResult(
            signals=[decision_signal],
            risk_decisions=[decision],
            portfolio_plan=PortfolioPlan(orders=[order]),
            delivery_results=[],
            risk_diagnostics=risk_engine.budget_diagnostics(
                AccountState(equity=float(self.equity)),
                bar_index=self._bar_index(),
            ),
        )
        if not hasattr(self, "_platform_pipeline_results"):
            self._platform_pipeline_results = []
        self._platform_pipeline_results.append(self._last_platform_pipeline_result)
        return self._last_platform_pipeline_result

    # 鈹€鈹€ Main loop 鈹€鈹€

    def next(self):
        i = self._bar_index()
        rcfg = self.risk_cfg
        max_pos = rcfg.max_position_frac

        # 鈹€鈹€ Pre-trade checks 鈹€鈹€
        cooldown_ok = i - getattr(self, "_last_trade_bar", -10**9) >= self.cooldown_bars
        paused = self._is_paused()
        self._update_circuit_breaker()

        has_pos = self.position and abs(self.position.size) > 0.0001

        # Detect external close (e.g., library closed position fully)
        external_close_plan = btc_external_close_cleanup_plan(
            has_position=bool(has_pos),
            core_active=self._core_active,
            core_size=self._core_size,
            tactical_direction=self._tac_direction,
            tactical_size=self._tac_size,
        )
        if external_close_plan.should_record_trade:
            pnl = self.equity - getattr(self, "_eq_snapshot", self.equity)
            self._on_trade_closed(pnl)
            self._core_active = external_close_plan.core_active
            self._core_size = external_close_plan.core_size
            self._tac_direction = external_close_plan.tactical_direction
            self._tac_size = external_close_plan.tactical_size

        # 鈹€鈹€ Core exit (close core layer only) 鈹€鈹€
        core_exit_plan = btc_core_exit_plan(
            core_active=self._core_active,
            exit_signal=(self._core_exit_signal() or self._core_trail_stop_hit()) if self._core_active else False,
            core_size=self._core_size,
        )
        if core_exit_plan.should_exit:
            self._record_layer_close_pipeline(
                layer="core",
                module="core_long",
                direction=Direction.LONG,
                layer_size=core_exit_plan.layer_size,
                reason="core_exit",
            )
            self._close_layer(core_exit_plan.layer_size)
            self._core_active = core_exit_plan.core_active
            self._core_size = core_exit_plan.core_size
            return

        # 鈹€鈹€ Bear core exit (V-reversal + giveback + waterfall + trend) 鈹€鈹€
        if self._bear_core_active:
            # V-reversal: made profit then snapped back 鈫?liquidity event, not bear
            bc_sl = self._bear_core_sl()
            v_reversal_exit_plan = btc_bear_core_v_reversal_exit_plan(
                bear_core_active=self._bear_core_active,
                v_reversal_exit=btc_bear_core_v_reversal_exit(
                    entry_price=self._bear_core_entry_price,
                    stop_price=bc_sl,
                    close=self._at("Close"),
                    peak_r=getattr(self, '_bear_probe_peak_r', 0.0),
                    bars_held=self._bar_index() - getattr(self, '_bear_core_entry_bar', -10**9),
                    daily_ema_dir=self._at("_d_ema_dir"),
                    regime=self._current_regime(),
                ),
                bear_core_size=self._bear_core_size,
                waterfall_triggered=getattr(self, '_waterfall_triggered', False),
                days_above_dema=self._days_above_dema,
            )
            if v_reversal_exit_plan.should_exit:
                self._record_layer_close_pipeline(
                    layer="bear_core",
                    module=self._bear_core_close_module(),
                    direction=Direction.SHORT,
                    layer_size=v_reversal_exit_plan.layer_size,
                    reason="bear_core_v_reversal_exit",
                )
                self._close_layer(v_reversal_exit_plan.layer_size)
                self._bear_core_active = v_reversal_exit_plan.bear_core_active
                self._bear_core_size = v_reversal_exit_plan.bear_core_size
                self._waterfall_triggered = v_reversal_exit_plan.waterfall_triggered
                self._days_above_dema = v_reversal_exit_plan.days_above_dema
                self._on_trade_closed(self.equity - getattr(self, "_eq_snapshot", self.equity))
                return

            # Tiered giveback guard for bear core
            giveback_exit_plan = btc_bear_core_giveback_exit_plan(
                bear_core_active=self._bear_core_active,
                giveback_exit=self._check_short_giveback_guard(self._bear_core_entry_price, bc_sl),
                bear_core_size=self._bear_core_size,
            )
            if giveback_exit_plan.should_exit:
                self._record_layer_close_pipeline(
                    layer="bear_core",
                    module=self._bear_core_close_module(),
                    direction=Direction.SHORT,
                    layer_size=giveback_exit_plan.layer_size,
                    reason="bear_core_giveback_exit",
                )
                self._close_layer(giveback_exit_plan.layer_size)
                self._bear_core_active = giveback_exit_plan.bear_core_active
                self._bear_core_size = giveback_exit_plan.bear_core_size
                pnl = self.equity - getattr(self, "_eq_snapshot", self.equity)
                self._on_trade_closed(pnl)
                return

            # Waterfall event runner: exit if profit drops below locked R
            runner_exit_plan = btc_bear_core_waterfall_runner_exit_plan(
                bear_core_active=self._bear_core_active,
                runner_exit=btc_bear_core_waterfall_runner_exit(
                    stage=getattr(self, '_bear_core_stage', 0),
                    entry_price=self._bear_core_entry_price,
                    stop_price=self._bear_core_sl(),
                    close=self._at("Close"),
                    lock_r=getattr(self, '_waterfall_lock_r', 1.0),
                ),
                bear_core_size=self._bear_core_size,
                tactical_size=self._tac_size,
                waterfall_triggered=getattr(self, '_waterfall_triggered', False),
                days_above_dema=self._days_above_dema,
            )
            if runner_exit_plan.should_exit:
                self._record_layer_close_pipeline(
                    layer="bear_core",
                    module=self._bear_core_close_module(),
                    direction=Direction.SHORT,
                    layer_size=runner_exit_plan.layer_size,
                    reason="bear_core_waterfall_runner_exit",
                )
                self._close_layer(runner_exit_plan.layer_size)
                self._bear_core_active = runner_exit_plan.bear_core_active
                self._bear_core_size = runner_exit_plan.bear_core_size
                self._tac_size = runner_exit_plan.tactical_size
                self._waterfall_triggered = runner_exit_plan.waterfall_triggered
                self._days_above_dema = runner_exit_plan.days_above_dema
                pnl = self.equity - getattr(self, "_eq_snapshot", self.equity)
                self._on_trade_closed(pnl)
                return

        bear_trend_exit_plan = btc_bear_core_trend_exit_plan(
            bear_core_active=self._bear_core_active,
            exit_signal=self._bear_core_exit_signal() if self._bear_core_active else False,
            bear_core_size=self._bear_core_size,
            tactical_size=self._tac_size,
            days_above_dema=self._days_above_dema,
        )
        if bear_trend_exit_plan.should_exit:
            self._record_layer_close_pipeline(
                layer="bear_core",
                module=self._bear_core_close_module(),
                direction=Direction.SHORT,
                layer_size=bear_trend_exit_plan.layer_size,
                reason="bear_core_trend_exit",
            )
            self._close_layer(bear_trend_exit_plan.layer_size)
            self._bear_core_active = bear_trend_exit_plan.bear_core_active
            self._bear_core_size = bear_trend_exit_plan.bear_core_size
            self._tac_size = bear_trend_exit_plan.tactical_size
            self._days_above_dema = bear_trend_exit_plan.days_above_dema
            pnl = self.equity - getattr(self, "_eq_snapshot", self.equity)
            self._on_trade_closed(pnl)
            return

        # 鈹€鈹€ Flash crash detection (rapid >5% drop = liquidity grab) 鈹€鈹€
        _df = self.data.df
        high_6 = float(_df["High"].iloc[max(0,i-5):i+1].max())
        atr_now = self._at("_atr")
        atr_sma20 = float(_df["_atr"].iloc[max(0,i-19):i+1].mean()) if i >= 5 else atr_now
        self._flash_crash_active, self._flash_crash_bar = btc_flash_crash_state(
            bar_index=i,
            close=self._at("Close"),
            high_lookback=high_6,
            atr_now=atr_now,
            atr_sma20=atr_sma20,
            flash_crash_active=getattr(self, '_flash_crash_active', False),
            flash_crash_bar=getattr(self, '_flash_crash_bar', i),
        )

        # 鈹€鈹€ Bear core probe peak R tracker + waterfall guard 鈹€鈹€
        if self._bear_core_active:
            sl = self._bear_core_sl()
            self._bear_probe_peak_r = btc_bear_probe_peak_r(
                entry_price=self._bear_core_entry_price,
                stop_price=sl,
                low=self._at("Low"),
                previous_peak_r=getattr(self, '_bear_probe_peak_r', 0.0),
            )

            # Waterfall profit guard: event-driven crash, not sustainable bear
            if not getattr(self, '_waterfall_triggered', False):
                if self._check_waterfall_profit_guard():
                    self._waterfall_triggered = True
                    return  # position modified, skip rest of this bar

        # 鈹€鈹€ Tactical exit check (before entry) 鈹€鈹€
        if self._tac_direction != 0 and self._check_tactical_exit():
            self._record_layer_close_pipeline(
                layer="tactical",
                module=getattr(self, "_tac_module", "tactical"),
                direction=Direction.LONG if self._tac_direction == 1 else Direction.SHORT,
                layer_size=self._tac_size,
                reason="tactical_exit",
            )
            close_plan = btc_tactical_exit_close_plan(
                total_position_size=self._current_position_size(),
                tactical_size=self._tac_size,
            )
            if close_plan.action == "portion":
                self._close_portion(close_plan.portion)
            else:
                self._close_all()
            cleanup_plan = btc_tactical_exit_cleanup_plan(
                should_exit=True,
                tactical_direction=self._tac_direction,
                tactical_size=self._tac_size,
            )
            self._tac_direction = cleanup_plan.tactical_direction
            self._tac_size = cleanup_plan.tactical_size

        # 鈹€鈹€ Entry checks (respect cooldown & pause) 鈹€鈹€
        if not cooldown_ok or paused:
            return

        # 鈹€鈹€ Core entry 鈹€鈹€
        core_entry_signal = self._core_entry_standard_signal() if not self._core_active else None
        core_entry_plan = btc_core_entry_plan(
            core_active=self._core_active,
            entry_signal=core_entry_signal is not None,
            entry_price=self._at("Close"),
            core_size=rcfg.risk_core_alloc,
            equity=self.equity,
            bar_index=i,
        )
        if core_entry_plan.should_enter:
            if core_entry_signal is not None:
                self._record_legacy_entry_risk_decision(
                    signal=core_entry_signal,
                    entry_price=core_entry_plan.entry_price,
                    size_fraction=core_entry_plan.core_size,
                    stop_price=None,
                    target_price=None,
                )
                if self._platform_risk_engine_blocks_entry():
                    return
            self._core_active = core_entry_plan.core_active
            self._core_entry_price = core_entry_plan.entry_price
            self._core_highest_close = core_entry_plan.highest_close
            self._core_size = core_entry_plan.core_size
            self._days_below_dema = core_entry_plan.days_below_dema
            self._eq_snapshot = core_entry_plan.equity_snapshot
            # Core long: NO hard SL 鈥?uses manual trend-failure exit only.
            # Flash crashes (liquidity grabs) must not shake out strategic longs.
            order_is_long, order_stop, order_target = self._entry_order_parameters(
                is_long=True,
                stop_price=None,
                target_price=None,
            )
            if order_is_long:
                self._enter_long(
                    self._core_size,
                    tag=core_entry_plan.order_tag,
                    sl=order_stop,
                    tp=order_target,
                )
            else:
                self._enter_short(
                    self._core_size,
                    tag=core_entry_plan.order_tag,
                    sl=order_stop,
                    tp=order_target,
                )
            self._last_trade_bar = core_entry_plan.last_trade_bar

        # 鈹€鈹€ Flash crash dip-buy (tactical long add-on) 鈹€鈹€
        dip_buy_plan = btc_flash_crash_dip_buy_plan(
            flash_crash_active=getattr(self, '_flash_crash_active', False),
            core_active=self._core_active,
            tactical_direction=self._tac_direction,
            entry_price=self._at("Close"),
            bar_index=i,
        )
        if dip_buy_plan.should_enter:
            dip_buy_signal = select_btc_flash_crash_dip_buy_signal(
                symbol="BTC/USDT",
                should_enter=dip_buy_plan.should_enter,
            )
            if dip_buy_signal is not None:
                self._record_legacy_entry_risk_decision(
                    signal=dip_buy_signal,
                    entry_price=dip_buy_plan.entry_price,
                    size_fraction=dip_buy_plan.size,
                    stop_price=dip_buy_plan.stop_price,
                    target_price=dip_buy_plan.target_price,
                )
                if self._platform_risk_engine_blocks_entry():
                    return
            order_is_long, order_stop, order_target = self._entry_order_parameters(
                is_long=dip_buy_plan.is_long,
                stop_price=dip_buy_plan.stop_price,
                target_price=dip_buy_plan.target_price,
            )
            self._tac_direction = dip_buy_plan.direction
            self._tac_entry_price = dip_buy_plan.entry_price
            self._tac_sl = order_stop
            self._tac_tp = order_target
            self._tac_size = dip_buy_plan.size
            self._tac_entry_bar = dip_buy_plan.entry_bar
            self._tac_module = dip_buy_plan.module
            if order_is_long:
                self._enter_long(
                    self._tac_size,
                    tag=dip_buy_plan.order_tag,
                    sl=order_stop,
                    tp=order_target,
                )
            else:
                self._enter_short(
                    self._tac_size,
                    tag=dip_buy_plan.order_tag,
                    sl=order_stop,
                    tp=order_target,
                )
            self._last_trade_bar = dip_buy_plan.last_trade_bar

        # 鈹€鈹€ Core add-on (pullback in bull) 鈹€鈹€
        if self._core_active and not hasattr(self, "_core_fully_loaded"):
            self._core_fully_loaded = False
        core_fully_loaded = getattr(self, "_core_fully_loaded", True)
        core_add_signal = self._core_add_standard_signal() if self._core_active and not core_fully_loaded else None
        should_core_add, add_size, new_core_size, new_core_fully_loaded = btc_core_add_plan(
            core_active=self._core_active,
            core_fully_loaded=core_fully_loaded,
            core_add_signal=core_add_signal is not None,
            core_size=self._core_size,
            max_position_frac=max_pos,
            risk_cfg=rcfg,
        )
        if should_core_add:
            if core_add_signal is not None:
                self._record_legacy_entry_risk_decision(
                    signal=core_add_signal,
                    entry_price=self._at("Close"),
                    size_fraction=add_size,
                    stop_price=None,
                    target_price=None,
                )
                if self._platform_risk_engine_blocks_entry():
                    return
            order_is_long, order_stop, order_target = self._entry_order_parameters(
                is_long=True,
                stop_price=None,
                target_price=None,
            )
            if order_is_long:
                self._enter_long(
                    add_size,
                    tag="core_add_long",
                    sl=order_stop,
                    tp=order_target,
                )
            else:
                self._enter_short(
                    add_size,
                    tag="core_add_long",
                    sl=order_stop,
                    tp=order_target,
                )
            core_add_state_plan = btc_core_add_state_plan(
                should_core_add=should_core_add,
                new_core_size=new_core_size,
                new_core_fully_loaded=new_core_fully_loaded,
                core_size=self._core_size,
                core_fully_loaded=core_fully_loaded,
            )
            self._core_size = core_add_state_plan.core_size
            self._core_fully_loaded = core_add_state_plan.core_fully_loaded

        # 鈹€鈹€ Bear Core 3-stage entry (Probe 鈫?Confirm 鈫?Acceleration) 鈹€鈹€
        # Stage 1: Probe (top exhaustion + neckline break) 鈫?bear group gate
        _df = self.data.df
        bear_probe_signal = self._bear_core_probe_standard_signal()
        top_score_val = (
            bear_probe_signal.score
            if bear_probe_signal is not None
            else float(_df["_top_exhaustion_score"].iloc[i]) if "_top_exhaustion_score" in _df.columns else 0
        )
        double_top_sig = bear_probe_signal is not None
        bull_guard = bool(_df["_bull_guard"].iloc[i]) if "_bull_guard" in _df.columns else False
        (
            should_probe,
            _same_group,
            probe_size,
            new_group_id,
            new_group_exposure,
            new_group_entry_bar,
            new_group_peak_r,
        ) = btc_bear_core_probe_plan(
            bar_index=i,
            core_active=self._core_active,
            bear_core_active=self._bear_core_active,
            top_score=top_score_val,
            double_top_signal=double_top_sig,
            bull_guard=bull_guard,
            group_entry_bar=self._bear_group_entry_bar,
            group_id=self._bear_group_id,
            group_exposure=self._bear_group_exposure,
            risk_cfg=rcfg,
        )
        if should_probe:
            probe_entry_plan = btc_bear_core_probe_entry_state_plan(
                should_probe=should_probe,
                entry_price=self._at("Close"),
                bar_index=i,
                equity=self.equity,
                probe_size=probe_size,
                group_id=new_group_id,
                group_exposure=new_group_exposure,
                group_entry_bar=new_group_entry_bar,
                group_peak_r=new_group_peak_r,
                bear_core_active=self._bear_core_active,
                bear_core_stage=getattr(self, '_bear_core_stage', 0),
                bear_core_entry_price=self._bear_core_entry_price,
                bear_core_entry_bar=getattr(self, '_bear_core_entry_bar', -10**9),
                bear_core_size=self._bear_core_size,
                bear_group_id=self._bear_group_id,
                bear_group_exposure=self._bear_group_exposure,
                bear_group_entry_bar=self._bear_group_entry_bar,
                bear_group_peak_r=self._bear_group_peak_r,
                days_above_dema=self._days_above_dema,
                equity_snapshot=getattr(self, "_eq_snapshot", self.equity),
            )
            bc_sl = btc_bear_core_stop(
                entry_price=probe_entry_plan.bear_core_entry_price,
                atr_4h=self._at("_atr"),
                risk_cfg=rcfg,
            )
            if bear_probe_signal is not None:
                self._record_legacy_entry_risk_decision(
                    signal=bear_probe_signal,
                    entry_price=probe_entry_plan.bear_core_entry_price,
                    size_fraction=probe_entry_plan.bear_core_size,
                    stop_price=bc_sl,
                    target_price=None,
                )
                if self._platform_risk_engine_blocks_entry():
                    return
            self._bear_core_active = probe_entry_plan.bear_core_active
            self._bear_core_stage = probe_entry_plan.bear_core_stage
            self._bear_core_entry_price = probe_entry_plan.bear_core_entry_price
            self._bear_core_entry_bar = probe_entry_plan.bear_core_entry_bar
            self._bear_probe_peak_r = probe_entry_plan.bear_probe_peak_r
            self._short_giveback_peak_r = probe_entry_plan.short_giveback_peak_r
            self._bear_core_size = probe_entry_plan.bear_core_size
            self._bear_group_id = probe_entry_plan.bear_group_id
            self._bear_group_exposure = probe_entry_plan.bear_group_exposure
            self._bear_group_entry_bar = probe_entry_plan.bear_group_entry_bar
            self._bear_group_peak_r = probe_entry_plan.bear_group_peak_r
            self._days_above_dema = probe_entry_plan.days_above_dema
            self._eq_snapshot = probe_entry_plan.equity_snapshot
            order_is_long, order_stop, order_target = self._entry_order_parameters(
                is_long=False,
                stop_price=bc_sl,
                target_price=None,
            )
            if order_is_long:
                self._enter_long(
                    self._bear_core_size,
                    tag="bear_core",
                    sl=order_stop,
                    tp=order_target,
                )
            else:
                self._enter_short(
                    self._bear_core_size,
                    tag="bear_core",
                    sl=order_stop,
                    tp=order_target,
                )
            self._last_trade_bar = probe_entry_plan.last_trade_bar

        # Stage 2: Confirm (prove + trend + group cap)
        bear_confirm_signal = self._bear_core_confirm_add_standard_signal()
        (
            should_confirm_add,
            confirm_add_size,
            confirm_target_size,
            confirm_group_exposure,
            confirm_stage,
        ) = btc_bear_core_confirm_add_plan(
            bar_index=i,
            entry_bar=getattr(self, '_bear_core_entry_bar', -10**9),
            active=bear_confirm_signal is not None,
            stage=getattr(self, '_bear_core_stage', 0),
            probe_peak_r=getattr(self, '_bear_probe_peak_r', 0.0),
            daily_ema_dir=self._at("_d_ema_dir"),
            weekly_ema_dir=self._at("_w_ema_dir"),
            close=self._at("Close"),
            weekly_ema=self._at("_w_ema_169"),
            current_size=self._bear_core_size,
            group_exposure=self._bear_group_exposure,
            group_max_exposure=self._bear_group_max_exposure,
            risk_cfg=rcfg,
        )
        if should_confirm_add:
            bc_sl = self._bear_core_sl()
            if bear_confirm_signal is not None:
                self._record_legacy_entry_risk_decision(
                    signal=bear_confirm_signal,
                    entry_price=self._at("Close"),
                    size_fraction=confirm_add_size,
                    stop_price=bc_sl,
                    target_price=None,
                )
                if self._platform_risk_engine_blocks_entry():
                    return
            order_is_long, order_stop, order_target = self._entry_order_parameters(
                is_long=False,
                stop_price=bc_sl,
                target_price=None,
            )
            if order_is_long:
                self._enter_long(
                    confirm_add_size,
                    tag="bear_core",
                    sl=order_stop,
                    tp=order_target,
                )
            else:
                self._enter_short(
                    confirm_add_size,
                    tag="bear_core",
                    sl=order_stop,
                    tp=order_target,
                )
            confirm_state_plan = btc_bear_core_confirm_add_state_plan(
                should_confirm_add=should_confirm_add,
                bar_index=i,
                target_size=confirm_target_size,
                group_exposure=confirm_group_exposure,
                stage=confirm_stage,
                bear_core_size=self._bear_core_size,
                bear_group_exposure=self._bear_group_exposure,
                bear_core_stage=getattr(self, '_bear_core_stage', 0),
                last_trade_bar=getattr(self, '_last_trade_bar', -10**9),
            )
            self._bear_core_size = confirm_state_plan.bear_core_size
            self._bear_group_exposure = confirm_state_plan.bear_group_exposure
            self._bear_core_stage = confirm_state_plan.bear_core_stage
            self._last_trade_bar = confirm_state_plan.last_trade_bar

        # Stage 3: Acceleration (group cap + trend confirmed)
        bear_accel_signal = self._bear_core_acceleration_add_standard_signal()
        adx_val = float(self.data.df["_adx_signal"].iloc[i]) if "_adx_signal" in self.data.df.columns else 0
        plus_di = float(self.data.df["_plus_di"].iloc[i]) if "_plus_di" in self.data.df.columns else 0
        minus_di = float(self.data.df["_minus_di"].iloc[i]) if "_minus_di" in self.data.df.columns else 0
        (
            should_accel_add,
            accel_add_size,
            accel_target_size,
            accel_group_exposure,
            accel_stage,
        ) = btc_bear_core_acceleration_add_plan(
            bar_index=i,
            last_trade_bar=getattr(self, '_last_trade_bar', -10**9),
            active=bear_accel_signal is not None,
            stage=getattr(self, '_bear_core_stage', 0),
            daily_ema_dir=self._at("_d_ema_dir"),
            adx=adx_val,
            plus_di=plus_di,
            minus_di=minus_di,
            current_size=self._bear_core_size,
            group_exposure=self._bear_group_exposure,
            group_max_exposure=self._bear_group_max_exposure,
            risk_cfg=rcfg,
        )
        if should_accel_add:
            bc_sl = self._bear_core_sl()
            if bear_accel_signal is not None:
                self._record_legacy_entry_risk_decision(
                    signal=bear_accel_signal,
                    entry_price=self._at("Close"),
                    size_fraction=accel_add_size,
                    stop_price=bc_sl,
                    target_price=None,
                )
                if self._platform_risk_engine_blocks_entry():
                    return
            order_is_long, order_stop, order_target = self._entry_order_parameters(
                is_long=False,
                stop_price=bc_sl,
                target_price=None,
            )
            if order_is_long:
                self._enter_long(
                    accel_add_size,
                    tag="bear_core",
                    sl=order_stop,
                    tp=order_target,
                )
            else:
                self._enter_short(
                    accel_add_size,
                    tag="bear_core",
                    sl=order_stop,
                    tp=order_target,
                )
            accel_state_plan = btc_bear_core_acceleration_add_state_plan(
                should_accel_add=should_accel_add,
                target_size=accel_target_size,
                group_exposure=accel_group_exposure,
                stage=accel_stage,
                bear_core_size=self._bear_core_size,
                bear_group_exposure=self._bear_group_exposure,
                bear_core_stage=getattr(self, '_bear_core_stage', 0),
            )
            self._bear_core_size = accel_state_plan.bear_core_size
            self._bear_group_exposure = accel_state_plan.bear_group_exposure
            self._bear_core_stage = accel_state_plan.bear_core_stage

        # 鈹€鈹€ Tactical entry 鈹€鈹€
        regime = self._current_regime()
        if regime != 4 and self._tac_direction == 0:
            signal = self._tactical_signal()
            if signal is not None:
                is_long = signal.direction == Direction.LONG
                result = self._tactical_sl_tp(is_long)
                if result:
                    sl, tp = result
                    entry = self._at("Close")
                    entry_plan = btc_tactical_entry_plan(
                        long_signal=signal.direction == Direction.LONG,
                        short_signal=signal.direction == Direction.SHORT,
                        module=signal.module,
                        entry=entry,
                        stop=sl,
                        target=tp,
                        position_size=calculate_btc_tactical_position_size(
                            module=signal.module,
                            is_long=is_long,
                            entry=entry,
                            stop=sl,
                            risk_cfg=rcfg,
                        ),
                        bar_index=i,
                    )
                    if entry_plan.should_enter:
                        self._record_legacy_entry_risk_decision(
                            signal=signal,
                            entry_price=entry_plan.entry_price,
                            size_fraction=entry_plan.size,
                            stop_price=entry_plan.stop_price,
                            target_price=entry_plan.target_price,
                        )
                        if self._platform_risk_engine_blocks_entry():
                            return
                        order_is_long, order_stop, order_target = self._entry_order_parameters(
                            is_long=entry_plan.is_long,
                            stop_price=entry_plan.stop_price,
                            target_price=entry_plan.target_price,
                        )
                        self._tac_direction = 1 if order_is_long else -1
                        self._tac_module = entry_plan.module
                        self._tp1_done = entry_plan.tp1_done
                        self._tp2_done = entry_plan.tp2_done
                        self._short_reached_1r = entry_plan.short_reached_1r
                        self._short_peak_r = entry_plan.short_peak_r
                        self._short_giveback_peak_r = entry_plan.short_giveback_peak_r
                        self._tac_entry_price = entry_plan.entry_price
                        self._tac_sl = order_stop
                        self._tac_tp = order_target
                        self._tac_size = entry_plan.size
                        self._tac_entry_bar = entry_plan.entry_bar
                        self._tac_extreme = entry_plan.extreme
                        self._last_trade_bar = entry_plan.last_trade_bar
                        if order_is_long:
                            self._enter_long(
                                self._tac_size,
                                tag=entry_plan.order_tag,
                                sl=order_stop,
                                tp=order_target,
                            )
                        else:
                            self._enter_short(
                                self._tac_size,
                                tag=entry_plan.order_tag,
                                sl=order_stop,
                                tp=order_target,
                            )


class WeightedSignalStrategy(Strategy):
    cooldown_bars = 12
    trade_size_fraction = 0.95

    def init(self):
        self.last_trade_bar = -10**9
        self._last_platform_risk_decision = None
        self._last_platform_risk_engine_decision = None
        self._last_platform_pipeline_result = None
        self._last_platform_entry_order = None
        self._platform_pipeline_results = []
        self._last_platform_risk_audit = None
        self._platform_risk_audits = []

    def _bar_index(self) -> int:
        return len(self.data.Close) - 1

    def _record_legacy_entry_risk_decision(
        self,
        *,
        signal: Signal,
        entry_price: float,
        size_fraction: float,
        stop_price: float | None,
        target_price: float | None,
    ):
        return BaseRiskStrategy._record_legacy_entry_risk_decision(
            self,
            signal=signal,
            entry_price=entry_price,
            size_fraction=size_fraction,
            stop_price=stop_price,
            target_price=target_price,
        )

    def _platform_open_entry_order(self, pipeline_result):
        return BaseRiskStrategy._platform_open_entry_order(self, pipeline_result)

    def _entry_order_parameters(
        self,
        *,
        is_long: bool,
        stop_price: float | None,
        target_price: float | None,
    ) -> tuple[bool, float | None, float | None]:
        return BaseRiskStrategy._entry_order_parameters(
            self,
            is_long=is_long,
            stop_price=stop_price,
            target_price=target_price,
        )

    def _platform_risk_engine_blocks_entry(self) -> bool:
        return BaseRiskStrategy._platform_risk_engine_blocks_entry(self)

    def _record_opposite_close_pipeline(
        self,
        *,
        signal: Signal,
        entry_price: float,
    ):
        position = getattr(self, "position", None)
        if position is None:
            return None
        size_fraction = abs(float(getattr(position, "size", self.trade_size_fraction)))
        decision = build_btc_legacy_entry_risk_decision(
            signal=signal,
            equity=self.equity,
            entry_price=entry_price,
            size_fraction=size_fraction,
            stop_price=signal.preferred_stop,
            target_price=signal.preferred_target,
            reason="legacy_compat_close_audit",
        )
        quantity = decision.quantity
        notional = decision.notional
        existing_direction = Direction.LONG if position.is_long else Direction.SHORT
        layer = _BTC_PLATFORM_LAYER_BY_MODULE["legacy_weighted"]
        state = PortfolioState(positions={
            PositionKey(signal.symbol, layer): Position(
                symbol=signal.symbol,
                layer=layer,
                direction=existing_direction,
                quantity=quantity,
                notional=notional,
                risk_amount=decision.risk_amount,
                module=signal.module,
                entry_price=entry_price,
                stop_price=signal.preferred_stop,
                target_price=signal.preferred_target,
            )
        })
        self._last_platform_pipeline_result = SignalPipeline(
            signal_runner=SignalModuleRunner([]),
            risk_engine=RiskEngine(RiskLimits()),
            portfolio_engine=PortfolioEngine(
                state=state,
                layer_by_module=_BTC_PLATFORM_LAYER_BY_MODULE,
                close_on_opposite_signal=True,
            ),
        ).run_decisions(
            [decision],
            account=AccountState(equity=float(self.equity)),
            bar_index=self._bar_index(),
        )
        if not hasattr(self, "_platform_pipeline_results"):
            self._platform_pipeline_results = []
        self._platform_pipeline_results.append(self._last_platform_pipeline_result)
        return self._last_platform_pipeline_result

    def _place_weighted_order(
        self,
        *,
        is_long: bool,
        size: float,
        stop_price: float | None,
        target_price: float | None,
    ):
        kwargs = {"size": size}
        if stop_price is not None:
            kwargs["sl"] = stop_price
        if target_price is not None:
            kwargs["tp"] = target_price
        if is_long:
            self.buy(**kwargs)
        else:
            self.sell(**kwargs)

    def next(self):
        i = len(self.data.Close) - 1
        if i - self.last_trade_bar < self.cooldown_bars:
            return

        row = self.data.df.iloc[i]
        entry_signal = select_btc_weighted_legacy_signal(row, symbol="BTC/USDT")
        long_entry = entry_signal is not None and entry_signal.direction == Direction.LONG
        short_entry = entry_signal is not None and entry_signal.direction == Direction.SHORT

        if self.position:
            if self.position.is_long and short_entry:
                self._record_opposite_close_pipeline(
                    signal=entry_signal,
                    entry_price=float(row["Close"]),
                )
                self.position.close()
                self.last_trade_bar = i
            elif self.position.is_short and long_entry:
                self._record_opposite_close_pipeline(
                    signal=entry_signal,
                    entry_price=float(row["Close"]),
                )
                self.position.close()
                self.last_trade_bar = i
            return

        if entry_signal is None:
            return
        self._record_legacy_entry_risk_decision(
            signal=entry_signal,
            entry_price=float(row["Close"]),
            size_fraction=self.trade_size_fraction,
            stop_price=entry_signal.preferred_stop,
            target_price=entry_signal.preferred_target,
        )
        if self._platform_risk_engine_blocks_entry():
            return
        order_is_long, order_stop, order_target = self._entry_order_parameters(
            is_long=long_entry,
            stop_price=entry_signal.preferred_stop,
            target_price=entry_signal.preferred_target,
        )
        self._place_weighted_order(
            is_long=order_is_long,
            size=self.trade_size_fraction,
            stop_price=order_stop,
            target_price=order_target,
        )
        self.last_trade_bar = i


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?Runner 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?


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
