"""Causal expert-system candidate containing only review-supported sleeves."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quant_btc.price_action import add_continuous_price_action_features, confidence_multiplier
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
    trend_model: str = "ema"
    structure_deadband: float = 0.05
    confidence_features: tuple[str, ...] = ()


def prepare_retained_features(
    bars: pd.DataFrame,
    derivatives: pd.DataFrame | None = None,
    *,
    config: RetainedStrategyConfig | None = None,
) -> pd.DataFrame:
    """Build point-in-time features and attach funding only at settlement rows."""
    cfg = config or RetainedStrategyConfig()
    supported_confidence = {"ema_strength", "support_resistance", "jump_risk"}
    unknown_confidence = set(cfg.confidence_features).difference(supported_confidence)
    if unknown_confidence:
        raise ValueError(f"unsupported confidence features: {sorted(unknown_confidence)}")
    out = bars.copy()
    out["_atr"] = atr(out["High"], out["Low"], out["Close"], cfg.atr_period)
    out["_daily_ema"] = htf_ema(out["Close"], "1D", cfg.daily_ema_length)
    out["_weekly_ema"] = htf_ema(out["Close"], "1W", cfg.weekly_ema_length)
    out["_pullback_ema"] = ema(out["Close"], cfg.pullback_ema_length)
    if "ema_strength" in cfg.confidence_features:
        distance_scale = (6.0 * out["_atr"]).replace(0.0, float("nan"))
        out["_ema_strength"] = (
            (
                (out["Close"] - out["_daily_ema"])
                + (out["Close"] - out["_weekly_ema"])
            )
            / (2.0 * distance_scale)
        ).clip(-1.0, 1.0)
    price_action_families = set(cfg.confidence_features).difference({"ema_strength"})
    if cfg.trend_model == "sequence":
        price_action_families.add("structure")
    if price_action_families:
        out = add_continuous_price_action_features(
            out,
            atr_values=out["_atr"],
            families=tuple(sorted(price_action_families)),
        )
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
        trend_score = _trend_score(row, self.config)
        if trend_score is None:
            return []
        close = float(row["Close"])
        if trend_score <= self.config.structure_deadband:
            return []
        stop = close - self.config.core_stop_atr * float(row["_atr"])
        confidence = _adjusted_confidence(1.0, row, Direction.LONG, self.config)
        return [_signal("core_long", symbol, Direction.LONG, close, stop, None, 80.0, confidence)]


class BearTrendModule:
    """Small, symmetric bear-trend sleeve without probe/add/waterfall rules."""

    def __init__(self, config: RetainedStrategyConfig | None = None):
        self.config = config or RetainedStrategyConfig()

    def generate(self, features: pd.DataFrame, symbol: str) -> list[Signal]:
        row = features.iloc[-1]
        trend_score = _trend_score(row, self.config)
        if trend_score is None:
            return []
        close = float(row["Close"])
        if trend_score >= -self.config.structure_deadband:
            return []
        stop = close + self.config.bear_stop_atr * float(row["_atr"])
        confidence = _adjusted_confidence(1.0, row, Direction.SHORT, self.config)
        return [_signal("bear_core", symbol, Direction.SHORT, close, stop, None, 75.0, confidence)]


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
        trend_score = _trend_score(row, self.config)
        in_uptrend = trend_score is not None and trend_score > self.config.structure_deadband
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
        confidence = _adjusted_confidence(1.0, row, Direction.LONG, self.config)
        return [_signal("pullback_long", symbol, Direction.LONG, close, stop, target, 70.0, confidence)]


def _signal(
    module: str,
    symbol: str,
    direction: Direction,
    close: float,
    stop: float,
    target: float | None,
    score: float,
    confidence: float,
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
        confidence=confidence,
    )


def _trend_score(row: pd.Series, config: RetainedStrategyConfig) -> float | None:
    if config.trend_model == "sequence":
        value = row.get("_structure_score")
        return None if pd.isna(value) else float(value)
    if config.trend_model != "ema":
        raise ValueError(f"unsupported trend_model: {config.trend_model}")
    if pd.isna(row.get("_daily_ema")) or pd.isna(row.get("_weekly_ema")):
        return None
    close = float(row["Close"])
    if close > float(row["_daily_ema"]) and close > float(row["_weekly_ema"]):
        return 1.0
    if close < float(row["_daily_ema"]) and close < float(row["_weekly_ema"]):
        return -1.0
    return 0.0


def _adjusted_confidence(
    base: float,
    row: pd.Series,
    direction: Direction,
    config: RetainedStrategyConfig,
) -> float:
    return max(
        0.05,
        min(1.0, base * confidence_multiplier(row, direction, config.confidence_features)),
    )
