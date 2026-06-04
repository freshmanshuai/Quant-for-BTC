"""Connector contracts for market data adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from quant_platform.core import MarketSpec


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
    ) -> Any:
        """Fetch normalized funding/open-interest data when supported."""
        raise NotImplementedError(f"Data connector {self.name!r} does not support derivative data.")


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
    ) -> Any:
        return self.get(source).fetch_derivatives(
            market,
            funding_limit=funding_limit,
            open_interest_timeframe=open_interest_timeframe,
            open_interest_limit=open_interest_limit,
        )
