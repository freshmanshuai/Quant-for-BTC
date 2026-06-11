"""Yahoo Finance market data connector."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import quote, urlencode
from urllib.request import urlopen

import pandas as pd

from quant_platform.connectors import DataConnector
from quant_platform.core import MarketSpec


class YahooConnectorError(RuntimeError):
    """Raised when Yahoo Finance chart data cannot be normalized."""


class YahooFinanceConnector(DataConnector):
    """Fetch normalized OHLCV bars from Yahoo Finance chart responses."""

    name = "yahoo"

    def __init__(
        self,
        symbols_by_symbol: dict[str, str] | None = None,
        *,
        base_url: str = "https://query1.finance.yahoo.com",
        http_get: Callable[[str], Any] | None = None,
    ):
        self.symbols_by_symbol = dict(symbols_by_symbol or {})
        self.base_url = base_url.rstrip("/")
        self.http_get = http_get or _default_http_get

    def fetch_bars(
        self,
        market: MarketSpec,
        timeframe: str,
        limit: int | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        yahoo_symbol = self.symbols_by_symbol.get(
            market.asset.symbol,
            market.asset.symbol.replace("/", "-"),
        )
        payload = self.http_get(self._build_url(yahoo_symbol, timeframe, start=start, end=end))
        frame = self._normalize_chart_payload(payload, market.asset.symbol, timeframe)

        if start is not None:
            frame = frame[frame.index >= _utc_timestamp(start)]
        if end is not None:
            frame = frame[frame.index <= _utc_timestamp(end)]
        if limit is not None:
            frame = frame.tail(limit)
        if frame.empty:
            raise YahooConnectorError(f"Yahoo Finance returned no bars for {market.asset.symbol} {timeframe}.")
        return frame

    def _build_url(
        self,
        yahoo_symbol: str,
        timeframe: str,
        *,
        start: datetime | None,
        end: datetime | None,
    ) -> str:
        query: dict[str, str | int] = {"interval": timeframe}
        if start is None and end is None:
            query["range"] = "1y"
        else:
            query["period1"] = _unix_seconds(start or datetime(1970, 1, 1, tzinfo=timezone.utc))
            query["period2"] = _unix_seconds(end or datetime.now(timezone.utc))
        return f"{self.base_url}/v8/finance/chart/{quote(yahoo_symbol, safe='')}?{urlencode(query)}"

    def _normalize_chart_payload(self, payload: Any, symbol: str, timeframe: str) -> pd.DataFrame:
        data = _coerce_payload(payload)
        chart = data.get("chart") or {}
        error = chart.get("error")
        if error:
            description = error.get("description") if isinstance(error, dict) else str(error)
            raise YahooConnectorError(description or f"Yahoo Finance chart error for {symbol}.")

        results = chart.get("result") or []
        if not results:
            raise YahooConnectorError(f"Yahoo Finance returned no chart result for {symbol} {timeframe}.")
        result = results[0]
        timestamps = result.get("timestamp") or []
        quotes = ((result.get("indicators") or {}).get("quote") or [])
        if not timestamps or not quotes:
            raise YahooConnectorError(f"Yahoo Finance chart result is missing OHLCV data for {symbol} {timeframe}.")

        quote_data = quotes[0]
        frame = pd.DataFrame(
            {
                "Open": quote_data.get("open"),
                "High": quote_data.get("high"),
                "Low": quote_data.get("low"),
                "Close": quote_data.get("close"),
                "Volume": quote_data.get("volume"),
            },
            index=pd.to_datetime(timestamps, unit="s", utc=True),
        )
        frame.index.name = "timestamp"
        for column in ["Open", "High", "Low", "Close", "Volume"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame.sort_index().dropna(subset=["Open", "High", "Low", "Close", "Volume"])


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
    raise YahooConnectorError(f"Unsupported Yahoo Finance payload type: {type(payload).__name__}")


def _utc_timestamp(value: datetime) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _unix_seconds(value: datetime) -> int:
    return int(_utc_timestamp(value).timestamp())
