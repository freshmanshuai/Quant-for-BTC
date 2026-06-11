"""Polygon.io market data connector."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote, urlencode
from urllib.request import urlopen

import pandas as pd

from quant_platform.connectors import DataConnector
from quant_platform.core import MarketSpec


class PolygonConnectorError(RuntimeError):
    """Raised when Polygon aggregate bars cannot be fetched or normalized."""


class PolygonConnector(DataConnector):
    """Fetch normalized OHLCV bars from Polygon aggregate responses."""

    name = "polygon"

    def __init__(
        self,
        *,
        api_key_env: str = "POLYGON_API_KEY",
        symbols_by_symbol: dict[str, str] | None = None,
        base_url: str = "https://api.polygon.io",
        adjusted: bool = True,
        http_get: Callable[[str], Any] | None = None,
    ):
        self.api_key_env = api_key_env
        self.symbols_by_symbol = dict(symbols_by_symbol or {})
        self.base_url = base_url.rstrip("/")
        self.adjusted = adjusted
        self.http_get = http_get or _default_http_get

    def fetch_bars(
        self,
        market: MarketSpec,
        timeframe: str,
        limit: int | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise PolygonConnectorError(
                f"Polygon connector requires API key environment variable {self.api_key_env!r}."
            )
        vendor_symbol = self.symbols_by_symbol.get(market.asset.symbol, market.asset.symbol.replace("/", "-"))
        request_start = start or datetime(1970, 1, 1, tzinfo=timezone.utc)
        request_end = end or datetime.now(timezone.utc)
        payload = self.http_get(self._build_url(vendor_symbol, timeframe, request_start, request_end, api_key, limit))
        frame = self._normalize_payload(payload, market.asset.symbol, timeframe)

        if start is not None:
            frame = frame[frame.index >= _utc_timestamp(start)]
        if end is not None:
            frame = frame[frame.index <= _utc_timestamp(end)]
        if limit is not None:
            frame = frame.tail(limit)
        if frame.empty:
            raise PolygonConnectorError(f"Polygon returned no bars for {market.asset.symbol} {timeframe}.")
        return frame

    def _build_url(
        self,
        vendor_symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        api_key: str,
        limit: int | None,
    ) -> str:
        multiplier, timespan = _polygon_range(timeframe)
        query: dict[str, str | int] = {
            "adjusted": str(self.adjusted).lower(),
            "sort": "asc",
            "apiKey": api_key,
        }
        if limit is not None:
            query["limit"] = limit
        return (
            f"{self.base_url}/v2/aggs/ticker/{quote(vendor_symbol, safe='')}"
            f"/range/{multiplier}/{timespan}/{_date_path(start)}/{_date_path(end)}?{urlencode(query)}"
        )

    def _normalize_payload(self, payload: Any, symbol: str, timeframe: str) -> pd.DataFrame:
        data = _coerce_payload(payload)
        status = str(data.get("status", "")).upper()
        if status in {"ERROR", "NOT_AUTHORIZED"}:
            raise PolygonConnectorError(str(data.get("error") or data.get("message") or status))
        results = data.get("results") or []
        if not results:
            raise PolygonConnectorError(f"Polygon response missing aggregate results for {symbol} {timeframe}.")

        frame = pd.DataFrame(
            {
                "Open": [row.get("o") for row in results],
                "High": [row.get("h") for row in results],
                "Low": [row.get("l") for row in results],
                "Close": [row.get("c") for row in results],
                "Volume": [row.get("v") for row in results],
            },
            index=pd.to_datetime([row.get("t") for row in results], unit="ms", utc=True),
        )
        frame.index.name = "timestamp"
        for column in ["Open", "High", "Low", "Close", "Volume"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame.sort_index().dropna(subset=["Open", "High", "Low", "Close", "Volume"])


def _polygon_range(timeframe: str) -> tuple[int, str]:
    normalized = timeframe.lower()
    if normalized.endswith("min"):
        return int(normalized[:-3] or "1"), "minute"
    if normalized.endswith("h"):
        return int(normalized[:-1] or "1"), "hour"
    if normalized in {"1d", "1day", "daily"}:
        return 1, "day"
    raise PolygonConnectorError(f"Unsupported Polygon timeframe: {timeframe!r}.")


def _default_http_get(url: str) -> Any:
    with urlopen(url, timeout=30) as response:
        return response.read()


def _coerce_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, bytes):
        return json.loads(payload.decode("utf-8"))
    if isinstance(payload, str):
        return json.loads(payload)
    raise PolygonConnectorError(f"Unsupported Polygon payload type: {type(payload).__name__}")


def _utc_timestamp(value: datetime) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _date_path(value: datetime) -> str:
    return _utc_timestamp(value).strftime("%Y-%m-%d")
