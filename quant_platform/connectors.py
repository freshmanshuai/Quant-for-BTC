"""Connector contracts for market data adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import pandas as pd

from quant_platform.core import MarketSpec
from quant_platform.data import BarSeriesId, DerivativeSeriesId, OrderBookSeriesId
from quant_platform.stores import MissingStorageDependency


class DataConnector(ABC):
    """Base contract for exchange, vendor, local-file, or database data adapters."""

    name: str

    @abstractmethod
    def fetch_bars(
        self,
        market: MarketSpec,
        timeframe: str,
        limit: int | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Any:
        """Fetch normalized OHLCV bars for the requested market and timeframe."""

    def fetch_derivatives(
        self,
        market: MarketSpec,
        funding_limit: int = 1000,
        open_interest_timeframe: str = "4h",
        open_interest_limit: int = 1000,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Any:
        """Fetch normalized funding/open-interest data when supported."""
        raise NotImplementedError(f"Data connector {self.name!r} does not support derivative data.")

    def fetch_order_book_snapshots(
        self,
        market: MarketSpec,
        depth: int = 5,
        sample_interval: str = "1s",
        limit: int = 1000,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Any:
        """Fetch normalized order-book snapshots when supported."""
        raise NotImplementedError(f"Data connector {self.name!r} does not support order-book data.")


class DataConnectorRegistry:
    """Routes market data requests to named connector adapters."""

    def __init__(self, connectors: list[DataConnector] | None = None):
        self._connectors: dict[str, DataConnector] = {}
        for connector in connectors or []:
            self.register(connector)

    def register(self, connector: DataConnector, name: str | None = None) -> "DataConnectorRegistry":
        source = name or connector.name
        self._connectors[source] = connector
        return self

    def get(self, source: str) -> DataConnector:
        try:
            return self._connectors[source]
        except KeyError as exc:
            raise KeyError(f"No data connector registered for source {source!r}.") from exc

    def fetch_bars(
        self,
        source: str,
        market: MarketSpec,
        timeframe: str,
        limit: int | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Any:
        return self.get(source).fetch_bars(
            market,
            timeframe,
            limit=limit,
            start=start,
            end=end,
        )

    def fetch_derivatives(
        self,
        source: str,
        market: MarketSpec,
        funding_limit: int = 1000,
        open_interest_timeframe: str = "4h",
        open_interest_limit: int = 1000,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Any:
        range_kwargs = {}
        if start is not None:
            range_kwargs["start"] = start
        if end is not None:
            range_kwargs["end"] = end
        return self.get(source).fetch_derivatives(
            market,
            funding_limit=funding_limit,
            open_interest_timeframe=open_interest_timeframe,
            open_interest_limit=open_interest_limit,
            **range_kwargs,
        )

    def fetch_order_book_snapshots(
        self,
        source: str,
        market: MarketSpec,
        depth: int = 5,
        sample_interval: str = "1s",
        limit: int = 1000,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Any:
        return self.get(source).fetch_order_book_snapshots(
            market,
            depth=depth,
            sample_interval=sample_interval,
            limit=limit,
            start=start,
            end=end,
        )


def fetch_bars_with_cache(
    *,
    connector: DataConnector,
    store: Any,
    source: str,
    market: MarketSpec,
    timeframe: str,
    limit: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    refresh: bool = False,
) -> Any:
    """Fetch bars through a DataConnector with a BarStore read/write boundary."""
    series_id = BarSeriesId(
        symbol=market.asset.symbol,
        exchange=market.exchange,
        market_type=market.market_type,
        timeframe=timeframe,
        source=source,
    )
    if not refresh:
        try:
            return _filter_bars(store.read(series_id), limit=limit, start=start, end=end)
        except (FileNotFoundError, MissingStorageDependency):
            pass

    bars = connector.fetch_bars(market, timeframe, limit=limit, start=start, end=end)
    try:
        store.write(series_id, bars)
    except MissingStorageDependency:
        pass
    return bars


def fetch_derivatives_with_cache(
    *,
    connector: DataConnector,
    store: Any,
    source: str,
    market: MarketSpec,
    funding_limit: int = 1000,
    open_interest_timeframe: str = "4h",
    open_interest_limit: int = 1000,
    start: datetime | None = None,
    end: datetime | None = None,
    refresh: bool = False,
) -> Any:
    """Fetch derivatives through a DataConnector with a DerivativeStore read/write boundary."""
    series_id = DerivativeSeriesId(
        symbol=market.asset.symbol,
        exchange=market.exchange,
        market_type=market.market_type,
        timeframe=open_interest_timeframe,
        source=source,
    )
    if not refresh:
        try:
            return _filter_time_index(store.read(series_id), start=start, end=end)
        except (FileNotFoundError, MissingStorageDependency):
            pass

    range_kwargs = {}
    if start is not None:
        range_kwargs["start"] = start
    if end is not None:
        range_kwargs["end"] = end
    derivatives = connector.fetch_derivatives(
        market,
        funding_limit=funding_limit,
        open_interest_timeframe=open_interest_timeframe,
        open_interest_limit=open_interest_limit,
        **range_kwargs,
    )
    derivatives = _filter_time_index(derivatives, start=start, end=end)
    try:
        store.write(series_id, derivatives)
    except MissingStorageDependency:
        pass
    return derivatives


def fetch_order_book_snapshots_with_cache(
    *,
    connector: DataConnector,
    store: Any,
    source: str,
    market: MarketSpec,
    depth: int = 5,
    sample_interval: str = "1s",
    limit: int = 1000,
    start: datetime | None = None,
    end: datetime | None = None,
    refresh: bool = False,
) -> Any:
    """Fetch order-book snapshots through a DataConnector with an OrderBookStore boundary."""
    series_id = OrderBookSeriesId(
        symbol=market.asset.symbol,
        exchange=market.exchange,
        market_type=market.market_type,
        depth=depth,
        sample_interval=sample_interval,
        source=source,
    )
    if not refresh:
        try:
            return store.read(series_id)
        except (FileNotFoundError, MissingStorageDependency):
            pass

    snapshots = connector.fetch_order_book_snapshots(
        market,
        depth=depth,
        sample_interval=sample_interval,
        limit=limit,
        start=start,
        end=end,
    )
    try:
        store.write(series_id, snapshots)
    except MissingStorageDependency:
        pass
    return snapshots


def _filter_bars(
    bars: Any,
    *,
    limit: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> Any:
    frame = _filter_time_index(bars, start=start, end=end)
    if limit is not None:
        frame = frame.tail(limit)
    return frame


def _filter_time_index(
    frame: Any,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> Any:
    if start is not None:
        frame = frame[frame.index >= _utc_timestamp(start)]
    if end is not None:
        frame = frame[frame.index <= _utc_timestamp(end)]
    return frame


def _utc_timestamp(value: datetime) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")
