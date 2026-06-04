"""Feature engineering primitives for reusable signal research."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

from quant_platform.data import FeatureSeriesId


class FeatureModule(Protocol):
    """A reusable transformation that adds derived feature columns."""

    name: str

    def apply(self, bars: pd.DataFrame) -> pd.DataFrame:
        """Return a DataFrame with this module's feature columns added."""


class FeatureEngine:
    """Apply registered feature modules in a deterministic order."""

    def __init__(self, modules: Sequence[FeatureModule]):
        self.modules = list(modules)

    def run(self, bars: pd.DataFrame) -> pd.DataFrame:
        out = bars.copy()
        for module in self.modules:
            out = module.apply(out)
        return out


class FeatureStoreWriter(Protocol):
    """Storage boundary for persisted feature sets."""

    def write(self, series_id: FeatureSeriesId, features: pd.DataFrame) -> Path:
        """Persist a feature frame and return the storage path."""


@dataclass(frozen=True)
class FeatureRunResult:
    """Result of a feature engine run with optional cache metadata."""

    features: pd.DataFrame
    cache: dict[str, object] | None = None


def run_feature_engine_with_cache(
    engine: FeatureEngine,
    bars: pd.DataFrame,
    *,
    series_id: FeatureSeriesId,
    store: FeatureStoreWriter | None = None,
) -> FeatureRunResult:
    """Run a feature engine and optionally persist the resulting feature frame."""
    features = engine.run(bars)
    if store is None:
        return FeatureRunResult(features=features)
    path = store.write(series_id, features)
    return FeatureRunResult(
        features=features,
        cache={
            "cacheKey": series_id.cache_key,
            "path": str(path),
            "rows": int(len(features)),
            "columns": list(features.columns),
        },
    )


@dataclass(frozen=True)
class TechnicalIndicatorConfig:
    """Parameters for common indicator columns shared by signal modules."""

    ema_lengths: tuple[int, ...] = (55, 69, 144, 169)
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    rsi_period: int = 14
    htf_ema_rules: dict[str, str] = field(default_factory=dict)
    htf_ema_length: int = 169
    htf_ema_lengths: dict[str, int] | None = None


class TechnicalIndicatorModule:
    """Add EMA, MACD, higher-timeframe EMA, and RSI columns."""

    name = "technical_indicators"

    def __init__(self, config: TechnicalIndicatorConfig):
        self.config = config

    def apply(self, bars: pd.DataFrame) -> pd.DataFrame:
        out = bars.copy()
        close = out["Close"]

        for length in self.config.ema_lengths:
            out[f"ema{length}"] = ema(close, length)

        out["macd"], out["macd_signal"] = macd(
            close,
            fast=self.config.macd_fast,
            slow=self.config.macd_slow,
            signal=self.config.macd_signal,
        )
        out["macd_hist"] = out["macd"] - out["macd_signal"]

        htf_lengths = self.config.htf_ema_lengths or {}
        for column, rule in self.config.htf_ema_rules.items():
            length = htf_lengths.get(column, self.config.htf_ema_length)
            out[column] = htf_ema(close, rule, length)

        out[f"rsi_{self.config.rsi_period}"] = rsi(close, self.config.rsi_period)
        return out


@dataclass(frozen=True)
class DonchianConfig:
    """Rolling high/low channel settings keyed by output prefix."""

    channel_periods: dict[str, int] = field(default_factory=lambda: {"donchian": 20})
    column_names: dict[str, tuple[str, str]] = field(default_factory=dict)


class DonchianFeatureModule:
    """Add rolling high/low channel columns."""

    name = "donchian"

    def __init__(self, config: DonchianConfig):
        self.config = config

    def apply(self, bars: pd.DataFrame) -> pd.DataFrame:
        out = bars.copy()
        for prefix, period in self.config.channel_periods.items():
            high_col, low_col = self.config.column_names.get(
                prefix,
                (f"{prefix}_high_{period}", f"{prefix}_low_{period}"),
            )
            out[high_col] = out["High"].rolling(period, min_periods=1).max()
            out[low_col] = out["Low"].rolling(period, min_periods=1).min()
        return out


@dataclass(frozen=True)
class VolumeConfig:
    """Rolling volume normalization settings."""

    lookback: int = 50
    zscore_column: str | None = None


class VolumeFeatureModule:
    """Add rolling volume mean, standard deviation, and z-score columns."""

    name = "volume"

    def __init__(self, config: VolumeConfig):
        self.config = config

    def apply(self, bars: pd.DataFrame) -> pd.DataFrame:
        out = bars.copy()
        lookback = self.config.lookback
        sma_col = f"vol_sma_{lookback}"
        std_col = f"vol_std_{lookback}"
        z_col = self.config.zscore_column or f"vol_zscore_{lookback}"
        out[sma_col] = out["Volume"].rolling(lookback, min_periods=1).mean()
        out[std_col] = out["Volume"].rolling(lookback, min_periods=1).std()
        out[z_col] = (out["Volume"] - out[sma_col]) / out[std_col].clip(lower=1e-10)
        return out


@dataclass(frozen=True)
class VolatilityConfig:
    """ATR, ATR percentile, and ADX settings."""

    period: int = 14
    percentile_lookback: int = 120
    atr_column: str | None = None
    atr_percentile_column: str | None = None
    adx_column: str | None = None


class VolatilityFeatureModule:
    """Add ATR, ATR percentile rank, and ADX columns."""

    name = "volatility"

    def __init__(self, config: VolatilityConfig):
        self.config = config

    def apply(self, bars: pd.DataFrame) -> pd.DataFrame:
        out = bars.copy()
        period = self.config.period
        atr_col = self.config.atr_column or f"_atr_{period}"
        atr_pct_col = self.config.atr_percentile_column or f"_atr_pct_{period}"
        adx_col = self.config.adx_column or f"_adx_{period}"
        out[atr_col] = atr(out["High"], out["Low"], out["Close"], period)
        out[atr_pct_col] = rolling_pct_rank(out[atr_col] / out["Close"], self.config.percentile_lookback)
        out[adx_col] = adx(out["High"], out["Low"], out["Close"], period)
        return out


@dataclass(frozen=True)
class BollingerConfig:
    """Bollinger band settings."""

    period: int = 20
    std_mult: float = 2.0
    upper_column: str | None = None
    lower_column: str | None = None


class BollingerFeatureModule:
    """Add Bollinger upper and lower band columns."""

    name = "bollinger"

    def __init__(self, config: BollingerConfig):
        self.config = config

    def apply(self, bars: pd.DataFrame) -> pd.DataFrame:
        out = bars.copy()
        period = self.config.period
        upper_col = self.config.upper_column or f"bb_upper_{period}"
        lower_col = self.config.lower_column or f"bb_lower_{period}"
        mid = out["Close"].rolling(period, min_periods=1).mean()
        std = out["Close"].rolling(period, min_periods=1).std()
        out[upper_col] = mid + self.config.std_mult * std
        out[lower_col] = mid - self.config.std_mult * std
        return out


class PriceActionFeatureModule:
    """Add simple candle anatomy features."""

    name = "price_action"

    def apply(self, bars: pd.DataFrame) -> pd.DataFrame:
        out = bars.copy()
        candle_range = (out["High"] - out["Low"]).clip(lower=1e-10)
        out["_lower_shadow"] = (np.minimum(out["Open"], out["Close"]) - out["Low"]) / candle_range
        out["_upper_shadow"] = (out["High"] - np.maximum(out["Open"], out["Close"])) / candle_range
        return out


@dataclass(frozen=True)
class DerivativesFeatureConfig:
    """Funding/open-interest feature settings."""

    funding_zscore_lookback: int = 90
    funding_min_periods: int = 30
    open_interest_change_periods: int = 6
    price_change_periods: int | None = None
    funding_rate_column: str = "funding_rate"
    open_interest_column: str = "open_interest"


class DerivativesFeatureModule:
    """Align funding and open-interest data to bars and add reusable derivative features."""

    name = "derivatives"

    def __init__(self, derivatives: pd.DataFrame | None, config: DerivativesFeatureConfig | None = None):
        self.derivatives = derivatives
        self.config = config or DerivativesFeatureConfig()

    def apply(self, bars: pd.DataFrame) -> pd.DataFrame:
        out = bars.copy()
        cfg = self.config
        periods = cfg.open_interest_change_periods
        price_periods = cfg.price_change_periods or periods

        funding = _aligned_derivative_series(
            self.derivatives,
            cfg.funding_rate_column,
            out.index,
            default=0.0,
        )
        open_interest = _aligned_derivative_series(
            self.derivatives,
            cfg.open_interest_column,
            out.index,
            default=0.0,
        )

        out[cfg.funding_rate_column] = funding
        out[cfg.open_interest_column] = open_interest

        funding_min_periods = min(cfg.funding_min_periods, cfg.funding_zscore_lookback)
        funding_sma = funding.rolling(cfg.funding_zscore_lookback, min_periods=funding_min_periods).mean()
        funding_std = funding.rolling(cfg.funding_zscore_lookback, min_periods=funding_min_periods).std()
        out[f"funding_zscore_{cfg.funding_zscore_lookback}"] = (
            (funding - funding_sma) / funding_std.clip(lower=1e-10)
        ).fillna(0.0)
        out[f"open_interest_change_{periods}"] = open_interest.pct_change(periods).fillna(0.0)
        out[f"derivative_price_change_{price_periods}"] = out["Close"].pct_change(price_periods).fillna(0.0)
        return out


@dataclass(frozen=True)
class ExternalMetricFeatureConfig:
    """Settings for point-in-time external metrics such as on-chain and sentiment data."""

    prefix: str
    columns: tuple[str, ...] | None = None
    fill_value: float = 0.0
    forward_fill: bool = True


class ExternalMetricFeatureModule:
    """Align external metric series to bars and expose them as prefixed numeric features."""

    name = "external_metrics"

    def __init__(self, metrics: pd.DataFrame | None, config: ExternalMetricFeatureConfig):
        self.metrics = metrics
        self.config = config

    def apply(self, bars: pd.DataFrame) -> pd.DataFrame:
        out = bars.copy()
        cfg = self.config
        columns = cfg.columns or self._numeric_metric_columns()
        for column in columns:
            out[f"{cfg.prefix}_{column}"] = _aligned_external_metric_series(
                self.metrics,
                column,
                out.index,
                fill_value=cfg.fill_value,
                forward_fill=cfg.forward_fill,
            )
        return out

    def _numeric_metric_columns(self) -> tuple[str, ...]:
        if self.metrics is None or self.metrics.empty:
            return ()
        numeric = self.metrics.select_dtypes(include=[np.number])
        return tuple(str(column) for column in numeric.columns)


def _aligned_derivative_series(
    derivatives: pd.DataFrame | None,
    column: str,
    index: pd.Index,
    *,
    default: float,
) -> pd.Series:
    if derivatives is None or derivatives.empty or column not in derivatives.columns:
        return pd.Series(default, index=index, dtype=float)
    return derivatives[column].reindex(index, method="ffill").fillna(default).astype(float)


def _aligned_external_metric_series(
    metrics: pd.DataFrame | None,
    column: str,
    index: pd.Index,
    *,
    fill_value: float,
    forward_fill: bool,
) -> pd.Series:
    if metrics is None or metrics.empty or column not in metrics.columns:
        return pd.Series(fill_value, index=index, dtype=float)
    series = pd.to_numeric(metrics[column], errors="coerce")
    if forward_fill:
        aligned = series.reindex(index, method="ffill")
    else:
        aligned = series.reindex(index)
    return aligned.fillna(fill_value).astype(float)


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False, min_periods=1).mean()


def macd(close: pd.Series, fast: int, slow: int, signal: int):
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    return macd_line, signal_line


def htf_ema(close: pd.Series, rule: str, length: int) -> pd.Series:
    htf_close = close.resample(rule).last().ffill()
    htf = ema(htf_close, length)
    return htf.reindex(close.index, method="ffill")


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(span=period, adjust=False, min_periods=1).mean()
    avg_loss = loss.ewm(span=period, adjust=False, min_periods=1).mean()
    rs = avg_gain / avg_loss.clip(lower=1e-10)
    return 100.0 - 100.0 / (1.0 + rs)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    true_range = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(span=period, adjust=False, min_periods=1).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    true_range = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    atr_value = true_range.ewm(span=period, adjust=False, min_periods=1).mean()

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index
    )
    plus_di = 100 * plus_dm.ewm(span=period, adjust=False, min_periods=1).mean() / atr_value
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False, min_periods=1).mean() / atr_value

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).clip(lower=1e-10)
    return dx.ewm(span=period, adjust=False, min_periods=1).mean()


def rolling_pct_rank(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=1).apply(
        lambda x: (x <= x.iloc[-1]).sum() / max(len(x), 1),
        raw=False,
    )
