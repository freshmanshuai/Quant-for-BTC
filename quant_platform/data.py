"""Standard data identifiers for bars and future stores."""

from __future__ import annotations

from dataclasses import dataclass


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
