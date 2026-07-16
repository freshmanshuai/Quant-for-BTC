"""Causal expert-system candidate containing only review-supported sleeves."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quant_platform.features import atr, ema, htf_ema
from quant_platform.signals import Direction, Signal


@dataclass(frozen=True)
class RetainedStrategyConfig:
    daily_ema_length: int = 169
    weekly_ema_length: int = 40
    atr_period: int = 14
    core_stop_atr: float = 3.0
    bear_stop_atr: float = 4.0
    pullback_ema_length: int = 20
    pullback_stop_atr: float = 2.0
    pullback_target_atr: float = 4.0


def prepare_retained_features(
    bars: pd.DataFrame,
    derivatives: pd.DataFrame | None = None,
    *,
    config: RetainedStrategyConfig | None = None,
) -> pd.DataFrame:
    """Build point-in-time features and attach funding only at settlement rows."""
    cfg = config or RetainedStrategyConfig()
    out = bars.copy()
    out["_atr"] = atr(out["High"], out["Low"], out["Close"], cfg.atr_period)
    out["_daily_ema"] = htf_ema(out["Close"], "1D", cfg.daily_ema_length)
    out["_weekly_ema"] = htf_ema(out["Close"], "1W", cfg.weekly_ema_length)
    out["_pullback_ema"] = ema(out["Close"], cfg.pullback_ema_length)
    out["funding_rate"] = float("nan")
    if derivatives is not None and not derivatives.empty:
        rates = pd.to_numeric(derivatives["funding_rate"], errors="coerce")
        rates = rates.loc[~rates.index.duplicated(keep="last")]
        # Multiple dynamic settlements inside a 4H bar are additive cash flows.
        rates = rates.groupby(rates.index.floor("4h")).sum(min_count=1)
        common = out.index.intersection(rates.index)
        out.loc[common, "funding_rate"] = rates.reindex(common)
    return out


def validate_funding_coverage(
    bars: pd.DataFrame,
    derivatives: pd.DataFrame | None,
    *,
    max_gap: str = "12h",
) -> None:
    """Reject swap backtests whose historical settlement ledger is incomplete."""
    if derivatives is None or derivatives.empty or "funding_rate" not in derivatives.columns:
        raise ValueError("swap backtest requires historical funding_rate settlements")
    rates = derivatives["funding_rate"].dropna().sort_index()
    if rates.empty:
        raise ValueError("swap backtest requires non-empty funding_rate settlements")
    tolerance = pd.Timedelta(max_gap)
    bar_start = bars.index.min()
    bar_end = bars.index.max()
    if rates.index.min() > bar_start + tolerance or rates.index.max() < bar_end - tolerance:
        raise ValueError("funding history does not cover the OHLCV backtest window")
    gaps = rates.index.to_series().diff().dropna()
    if not gaps.empty and gaps.max() > tolerance:
        raise ValueError(f"funding history contains a gap of {gaps.max()}")


class CoreTrendModule:
    """Long trend-beta sleeve; not presented as independent alpha."""

    def __init__(self, config: RetainedStrategyConfig | None = None):
        self.config = config or RetainedStrategyConfig()

    def generate(self, features: pd.DataFrame, symbol: str) -> list[Signal]:
        row = features.iloc[-1]
        if pd.isna(row["_daily_ema"]) or pd.isna(row["_weekly_ema"]):
            return []
        close = float(row["Close"])
        if not (close > float(row["_daily_ema"]) and close > float(row["_weekly_ema"])):
            return []
        stop = close - self.config.core_stop_atr * float(row["_atr"])
        return [_signal("core_long", symbol, Direction.LONG, close, stop, None, 80.0)]


class BearTrendModule:
    """Small, symmetric bear-trend sleeve without probe/add/waterfall rules."""

    def __init__(self, config: RetainedStrategyConfig | None = None):
        self.config = config or RetainedStrategyConfig()

    def generate(self, features: pd.DataFrame, symbol: str) -> list[Signal]:
        row = features.iloc[-1]
        if pd.isna(row["_daily_ema"]) or pd.isna(row["_weekly_ema"]):
            return []
        close = float(row["Close"])
        if not (close < float(row["_daily_ema"]) and close < float(row["_weekly_ema"])):
            return []
        stop = close + self.config.bear_stop_atr * float(row["_atr"])
        return [_signal("bear_core", symbol, Direction.SHORT, close, stop, None, 75.0)]


class PullbackLongModule:
    """Low-weight long pullback continuation overlay."""

    def __init__(self, config: RetainedStrategyConfig | None = None):
        self.config = config or RetainedStrategyConfig()

    def generate(self, features: pd.DataFrame, symbol: str) -> list[Signal]:
        if len(features) < 2:
            return []
        previous = features.iloc[-2]
        row = features.iloc[-1]
        required = ("_daily_ema", "_weekly_ema", "_pullback_ema", "_atr")
        if any(pd.isna(row[name]) for name in required):
            return []
        close = float(row["Close"])
        in_uptrend = close > float(row["_daily_ema"]) and close > float(row["_weekly_ema"])
        resumed = (
            float(previous["Low"]) <= float(previous["_pullback_ema"])
            and close > float(row["_pullback_ema"])
            and close > float(previous["Close"])
        )
        if not (in_uptrend and resumed):
            return []
        atr_value = float(row["_atr"])
        stop = min(float(row["Low"]), close - self.config.pullback_stop_atr * atr_value)
        target = close + self.config.pullback_target_atr * atr_value
        return [_signal("pullback_long", symbol, Direction.LONG, close, stop, target, 70.0)]


def _signal(
    module: str,
    symbol: str,
    direction: Direction,
    close: float,
    stop: float,
    target: float | None,
    score: float,
) -> Signal:
    return Signal(
        module=module,
        symbol=symbol,
        direction=direction,
        score=score,
        entry_reason=module,
        invalidation="completed-bar trend/ATR invalidation",
        preferred_stop=stop,
        preferred_target=target,
        confidence=score / 100.0,
    )
