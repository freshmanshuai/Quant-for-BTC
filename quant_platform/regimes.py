"""Regime classification models for asset-specific market profiles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import fields
from enum import IntEnum
from pathlib import Path

import numpy as np
import pandas as pd

from quant_platform.core import MarketSpec
from quant_platform.features import adx, atr, htf_ema, rolling_pct_rank


class RegimeLabel(IntEnum):
    """Common numeric regime labels used by legacy and platform code."""

    RANGING = 0
    BULL = 1
    BEAR = 2
    COMPRESSION = 3
    HIGH_RISK = 4


@dataclass(frozen=True)
class RegimeProfile:
    """Asset-specific parameters for classifying market state."""

    trend_ema_length: int = 169
    daily_rule: str = "1D"
    weekly_rule: str = "1W"
    ema_slope_threshold: float = 0.001
    atr_period: int = 14
    adx_period: int = 14
    bb_period: int = 20
    bb_std_mult: float = 2.0
    regime_lookback: int = 120
    compression_bb_pct: float = 0.25
    compression_atr_pct: float = 0.30
    high_vol_atr_pct: float = 0.90
    high_vol_large_candle_mult: float = 2.0
    adx_ranging_threshold: float = 20.0
    opposing_large_window: int = 5


class RegimeProfileRegistry:
    """Select asset-specific regime profiles with market-level fallback."""

    def __init__(self, default_profile: RegimeProfile | None = None):
        self.default_profile = default_profile or RegimeProfile()
        self._symbol_profiles: dict[str, RegimeProfile] = {}
        self._market_profiles: dict[tuple[str, str], RegimeProfile] = {}

    def register(self, symbol: str, profile: RegimeProfile) -> "RegimeProfileRegistry":
        self._symbol_profiles[symbol] = profile
        return self

    def register_market(
        self,
        exchange: str,
        market_type: str,
        profile: RegimeProfile,
    ) -> "RegimeProfileRegistry":
        self._market_profiles[(exchange, market_type)] = profile
        return self

    def profile_for(self, market: MarketSpec) -> RegimeProfile:
        symbol_profile = self._symbol_profiles.get(market.asset.symbol)
        if symbol_profile is not None:
            return symbol_profile
        return self._market_profiles.get((market.exchange, market.market_type), self.default_profile)


def load_regime_profile_registry_json(path: str | Path) -> RegimeProfileRegistry:
    """Load a regime profile registry from a project JSON config file."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    registry = RegimeProfileRegistry(default_profile=_profile_from_record(payload.get("default", {})))
    for record in payload.get("profiles", []):
        profile = _profile_from_record(record)
        symbol = record.get("symbol")
        exchange = record.get("exchange")
        market_type = record.get("market_type")
        if symbol:
            registry.register(str(symbol), profile)
        elif exchange and market_type:
            registry.register_market(str(exchange), str(market_type), profile)
        else:
            raise ValueError("Regime profile record requires either symbol or exchange and market_type")
    return registry


class RegimeModel:
    """Classify bars into Ranging/Bull/Bear/Compression/HighRisk regimes."""

    def __init__(self, profile: RegimeProfile):
        self.profile = profile

    def classify(self, bars: pd.DataFrame) -> pd.DataFrame:
        out = bars.copy()
        cfg = self.profile
        close = out["Close"]

        atr_value = atr(out["High"], out["Low"], close, cfg.atr_period)
        out["_atr"] = atr_value

        daily_ema = htf_ema(close, cfg.daily_rule, cfg.trend_ema_length)
        weekly_ema = htf_ema(close, cfg.weekly_rule, cfg.trend_ema_length)
        out[f"_d_ema_{cfg.trend_ema_length}"] = daily_ema
        out[f"_w_ema_{cfg.trend_ema_length}"] = weekly_ema
        out["_d_ema_dir"] = step_series_direction(daily_ema, cfg.ema_slope_threshold)
        out["_w_ema_dir"] = step_series_direction(weekly_ema, cfg.ema_slope_threshold)

        bb_width = bollinger_width(close, cfg.bb_period, cfg.bb_std_mult)
        bb_pct = rolling_pct_rank(bb_width, cfg.regime_lookback)
        atr_pct = rolling_pct_rank(atr_value / close, cfg.regime_lookback)
        adx_value = adx(out["High"], out["Low"], close, cfg.adx_period)
        out["_bb_width_pct"] = bb_pct
        out["_atr_pct"] = atr_pct
        out["_adx"] = adx_value

        body = (out["Close"] - out["Open"]).abs()
        large_body = body > (cfg.high_vol_large_candle_mult * atr_value)
        bull_large = large_body & (out["Close"] > out["Open"])
        bear_large = large_body & (out["Close"] < out["Open"])
        opposing_large = (
            bull_large.rolling(cfg.opposing_large_window, min_periods=1).max().astype(bool)
            & bear_large.rolling(cfg.opposing_large_window, min_periods=1).max().astype(bool)
        )

        regime = pd.Series(RegimeLabel.RANGING.value, index=out.index, dtype=int)

        high_vol = (atr_pct >= cfg.high_vol_atr_pct) | opposing_large
        regime[high_vol] = RegimeLabel.HIGH_RISK.value

        bull_cond = (
            (close > daily_ema)
            & (out["_d_ema_dir"] > 0)
            & (regime == RegimeLabel.RANGING.value)
        )
        regime[bull_cond] = RegimeLabel.BULL.value

        bear_cond = (
            (close < daily_ema)
            & (out["_d_ema_dir"] < 0)
            & (regime == RegimeLabel.RANGING.value)
        )
        regime[bear_cond] = RegimeLabel.BEAR.value

        compression_cond = (
            (bb_pct <= cfg.compression_bb_pct)
            & (atr_pct <= cfg.compression_atr_pct)
            & (adx_value < cfg.adx_ranging_threshold)
            & (regime == RegimeLabel.RANGING.value)
        )
        regime[compression_cond] = RegimeLabel.COMPRESSION.value

        out["_regime"] = regime
        return out


def ema_direction(ema_series: pd.Series, threshold: float = 0.001) -> pd.Series:
    pct = ema_series.pct_change(1, fill_method=None).fillna(0)
    return pd.Series(
        np.where(pct > threshold, 1, np.where(pct < -threshold, -1, 0)),
        index=ema_series.index,
    )


def step_series_direction(ema_series: pd.Series, threshold: float = 0.001) -> pd.Series:
    """Compare distinct HTF observations and carry direction to the next update."""
    observations = ema_series[ema_series.notna() & ema_series.ne(ema_series.shift(1))]
    if observations.empty:
        return pd.Series(0, index=ema_series.index, dtype=int)
    pct = observations.pct_change(fill_method=None)
    direction = pd.Series(
        np.where(pct > threshold, 1, np.where(pct < -threshold, -1, 0)),
        index=observations.index,
        dtype=int,
    )
    return direction.reindex(ema_series.index, method="ffill").fillna(0).astype(int)


def bollinger_width(close: pd.Series, period: int, std_mult: float) -> pd.Series:
    sma = close.rolling(period, min_periods=1).mean()
    std = close.rolling(period, min_periods=1).std()
    return (std_mult * std) / sma


def _profile_from_record(record: dict) -> RegimeProfile:
    profile_fields = {field.name for field in fields(RegimeProfile)}
    values = {key: value for key, value in record.items() if key in profile_fields}
    return RegimeProfile(**values)
