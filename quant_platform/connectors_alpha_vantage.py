"""Alpha Vantage market data connector."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import urlopen

import pandas as pd

from quant_platform.connectors import DataConnector
from quant_platform.core import MarketSpec


class AlphaVantageConnectorError(RuntimeError):
    """Raised when Alpha Vantage data cannot be fetched or normalized."""


class AlphaVantageConnector(DataConnector):
    """Fetch normalized OHLCV bars from Alpha Vantage time-series responses."""

    name = "alpha_vantage"

    def __init__(
        self,
        *,
        api_key_env: str = "ALPHA_VANTAGE_API_KEY",
        symbols_by_symbol: dict[str, str] | None = None,
        base_url: str = "https://www.alphavantage.co/query",
        outputsize: str = "compact",
        http_get: Callable[[str], Any] | None = None,
    ):
        self.api_key_env = api_key_env
        self.symbols_by_symbol = dict(symbols_by_symbol or {})
        self.base_url = base_url
        self.outputsize = outputsize
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
            raise AlphaVantageConnectorError(
                f"Alpha Vantage connector requires API key environment variable {self.api_key_env!r}."
            )
        vendor_symbol = self.symbols_by_symbol.get(market.asset.symbol, market.asset.symbol.replace("/", "-"))
        payload = self.http_get(self._build_url(vendor_symbol, timeframe, api_key))
        frame = self._normalize_payload(payload, market.asset.symbol, timeframe)

        if start is not None:
            frame = frame[frame.index >= _utc_timestamp(start)]
        if end is not None:
            frame = frame[frame.index <= _utc_timestamp(end)]
        if limit is not None:
            frame = frame.tail(limit)
        if frame.empty:
            raise AlphaVantageConnectorError(
                f"Alpha Vantage returned no bars for {market.asset.symbol} {timeframe}."
            )
        return frame

    def _build_url(self, vendor_symbol: str, timeframe: str, api_key: str) -> str:
        query: dict[str, str] = {
            "symbol": vendor_symbol,
            "apikey": api_key,
            "outputsize": self.outputsize,
        }
        if timeframe.endswith("min"):
            query["function"] = "TIME_SERIES_INTRADAY"
            query["interval"] = timeframe
        elif timeframe in {"1d", "1day", "daily"}:
            query["function"] = "TIME_SERIES_DAILY"
        else:
            raise AlphaVantageConnectorError(f"Unsupported Alpha Vantage timeframe: {timeframe!r}.")
        return f"{self.base_url}?{urlencode(query)}"

    def _normalize_payload(self, payload: Any, symbol: str, timeframe: str) -> pd.DataFrame:
        data = _coerce_payload(payload)
        if "Error Message" in data:
            raise AlphaVantageConnectorError(str(data["Error Message"]))
        if "Note" in data:
            raise AlphaVantageConnectorError(str(data["Note"]))

        series_key = _series_key(timeframe)
        series = data.get(series_key)
        if not isinstance(series, dict) or not series:
            raise AlphaVantageConnectorError(
                f"Alpha Vantage response missing {series_key!r} for {symbol} {timeframe}."
            )

        rows = []
        for timestamp, values in series.items():
            rows.append(
                {
                    "timestamp": timestamp,
                    "Open": values.get("1. open"),
                    "High": values.get("2. high"),
                    "Low": values.get("3. low"),
                    "Close": values.get("4. close"),
                    "Volume": values.get("5. volume"),
                }
            )
        frame = pd.DataFrame(rows)
        frame.index = pd.to_datetime(frame.pop("timestamp"), utc=True)
        frame.index.name = "timestamp"
        for column in ["Open", "High", "Low", "Close", "Volume"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame.sort_index().dropna(subset=["Open", "High", "Low", "Close", "Volume"])


def _series_key(timeframe: str) -> str:
    if timeframe.endswith("min"):
        return f"Time Series ({timeframe})"
    return "Time Series (Daily)"


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
    raise AlphaVantageConnectorError(f"Unsupported Alpha Vantage payload type: {type(payload).__name__}")


def _utc_timestamp(value: datetime) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")
