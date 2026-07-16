"""Standard data identifiers and causal OHLCV quality guards."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd


class DataQualityError(ValueError):
    """Raised when OHLCV data cannot be made safe for causal research."""


def clean_ohlcv_bars(
    bars: pd.DataFrame,
    timeframe: str,
    *,
    as_of: datetime | pd.Timestamp | None = None,
    require_contiguous: bool = False,
) -> pd.DataFrame:
    """Remove duplicates/forming bars and fail closed on invalid OHLCV rows."""
    if not isinstance(bars.index, pd.DatetimeIndex):
        raise DataQualityError("OHLCV data requires a DatetimeIndex")
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = sorted(required.difference(bars.columns))
    if missing:
        raise DataQualityError(f"OHLCV data missing columns: {', '.join(missing)}")

    interval = _timeframe_delta(timeframe)
    out = bars.sort_index()
    out = out.loc[~out.index.duplicated(keep="last")].copy()
    if out.empty:
        return out

    cutoff = pd.Timestamp(as_of or datetime.now(timezone.utc))
    if out.index.tz is not None and cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    elif out.index.tz is None and cutoff.tzinfo is not None:
        cutoff = cutoff.tz_convert("UTC").tz_localize(None)
    out = out.loc[out.index + interval <= cutoff]

    numeric = out[["Open", "High", "Low", "Close", "Volume"]].apply(
        pd.to_numeric, errors="coerce"
    )
    invalid = (
        numeric.isna().any(axis=1)
        | (numeric[["Open", "High", "Low", "Close"]] <= 0).any(axis=1)
        | (numeric["Volume"] < 0)
        | (numeric["High"] < numeric[["Open", "Close", "Low"]].max(axis=1))
        | (numeric["Low"] > numeric[["Open", "Close", "High"]].min(axis=1))
    )
    if invalid.any():
        raise DataQualityError(f"invalid OHLCV geometry at {out.index[invalid][0]}")

    if require_contiguous and len(out) > 1:
        gaps = out.index.to_series().diff().iloc[1:]
        bad_gaps = gaps[gaps != interval]
        if not bad_gaps.empty:
            raise DataQualityError(f"OHLCV gap detected before {bad_gaps.index[0]}")
    return out


def _timeframe_delta(timeframe: str) -> pd.Timedelta:
    try:
        interval = pd.to_timedelta(timeframe.strip().lower())
    except ValueError as exc:
        raise DataQualityError(f"unsupported fixed timeframe: {timeframe}") from exc
    if interval <= pd.Timedelta(0):
        raise DataQualityError("timeframe must be positive")
    return interval


@dataclass(frozen=True)
class BarSeriesId:
    """Identifies one normalized bar series."""

    symbol: str
    exchange: str
    market_type: str
    timeframe: str
    source: str

    @property
    def cache_key(self) -> str:
        safe_symbol = self.symbol.replace("/", "_")
        return f"{self.source}/{self.exchange}/{self.market_type}/{safe_symbol}/{self.timeframe}"


@dataclass(frozen=True)
class FeatureSeriesId:
    """Identifies one persisted feature set for a normalized market series."""

    symbol: str
    exchange: str
    market_type: str
    timeframe: str
    source: str
    feature_set: str

    @property
    def cache_key(self) -> str:
        safe_symbol = self.symbol.replace("/", "_")
        safe_feature_set = self.feature_set.replace("/", "_")
        return f"{self.source}/{self.exchange}/{self.market_type}/{safe_symbol}/{self.timeframe}/{safe_feature_set}"


@dataclass(frozen=True)
class DerivativeSeriesId:
    """Identifies one normalized funding/open-interest derivative series."""

    symbol: str
    exchange: str
    market_type: str
    timeframe: str
    source: str

    @property
    def cache_key(self) -> str:
        safe_symbol = self.symbol.replace("/", "_")
        return f"{self.source}/{self.exchange}/{self.market_type}/{safe_symbol}/{self.timeframe}/derivatives"


@dataclass(frozen=True)
class OrderBookSeriesId:
    """Identifies one normalized order-book snapshot series."""

    symbol: str
    exchange: str
    market_type: str
    depth: int
    sample_interval: str
    source: str

    @property
    def cache_key(self) -> str:
        safe_symbol = self.symbol.replace("/", "_")
        return (
            f"{self.source}/{self.exchange}/{self.market_type}/{safe_symbol}"
            f"/order_book/depth_{self.depth}/{self.sample_interval}"
        )


@dataclass(frozen=True)
class ExternalMetricSeriesId:
    """Identifies one normalized external metric series such as on-chain or sentiment data."""

    symbol: str
    provider: str
    dataset: str
    timeframe: str
    source: str

    @property
    def cache_key(self) -> str:
        safe_symbol = self.symbol.replace("/", "_")
        safe_dataset = self.dataset.replace("/", "_")
        return f"{self.source}/{self.provider}/{safe_symbol}/{self.timeframe}/{safe_dataset}"
