"""CCXT-backed exchange connector."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import pandas as pd

from quant_platform.connectors import DataConnector
from quant_platform.core import MarketSpec

try:
    import ccxt
except ImportError:
    ccxt = None


class ConnectorError(RuntimeError):
    """Raised when a connector cannot fetch requested data."""


ExchangeFactory = Callable[[str, str, dict[str, Any]], Any]
RetrySleep = Callable[[int], None]


def _default_exchange_factory(exchange_id: str, market_type: str, config: dict[str, Any]):
    if ccxt is None:
        raise ConnectorError("CCXT connector requires the ccxt package to be installed.")
    if exchange_id == "binance" and market_type == "swap":
        return ccxt.binanceusdm(config)
    if exchange_id == "binance":
        return ccxt.binance(config)
    if exchange_id == "binanceus":
        return ccxt.binanceus(config)
    if not hasattr(ccxt, exchange_id):
        raise ConnectorError(f"Unsupported exchange: {exchange_id}")
    return getattr(ccxt, exchange_id)(config)


def ohlcv_rows_to_frame(rows: list[list]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["timestamp", "Open", "High", "Low", "Close", "Volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.set_index("timestamp")


class CcxtExchangeConnector(DataConnector):
    """Fetch normalized OHLCV bars from a CCXT exchange adapter."""

    name = "ccxt"

    def __init__(
        self,
        timeout_ms: int = 30_000,
        proxy_url: str | None = None,
        batch_size: int = 1000,
        max_pages: int = 100,
        max_retries: int = 5,
        exchange_factory: ExchangeFactory | None = None,
        retry_sleep: RetrySleep | None = None,
    ):
        self.timeout_ms = timeout_ms
        self.proxy_url = proxy_url
        self.batch_size = batch_size
        self.max_pages = max_pages
        self.max_retries = max_retries
        self.exchange_factory = exchange_factory or _default_exchange_factory
        self.retry_sleep = retry_sleep or (lambda attempt: time.sleep(min(2**attempt, 8)))

    def fetch_bars(
        self,
        market: MarketSpec,
        timeframe: str,
        limit: int | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        if market.exchange == "binanceus" and market.market_type != "spot":
            raise ConnectorError(
                "BinanceUS does not support swap (perpetual futures). "
                "Use market_type='spot' or a futures-capable exchange."
            )
        if start is not None or end is not None:
            raise ConnectorError("start/end range fetching is not implemented yet")

        config: dict[str, Any] = {"enableRateLimit": True, "timeout": self.timeout_ms}
        if self.proxy_url:
            config["httpsProxy"] = self.proxy_url

        exchange = self.exchange_factory(market.exchange, market.market_type, config)
        requested_limit = limit or self.batch_size

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                rows = self._fetch_paginated(exchange, market.asset.symbol, timeframe, requested_limit)
                if not rows:
                    raise ConnectorError(f"Fetched empty OHLCV dataset from {market.market_key}.")
                return ohlcv_rows_to_frame(rows)
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries:
                    self.retry_sleep(attempt)

        raise ConnectorError(
            f"Failed to fetch {market.asset.symbol} {timeframe} from {market.exchange} "
            f"({market.market_type}) after {self.max_retries} retries. "
            f"Root cause: {type(last_error).__name__}: {last_error}."
        ) from last_error

    def fetch_derivatives(
        self,
        market: MarketSpec,
        funding_limit: int = 1000,
        open_interest_timeframe: str = "4h",
        open_interest_limit: int = 1000,
    ) -> pd.DataFrame:
        if market.market_type != "swap":
            raise ConnectorError("Derivative data requires a swap/futures market.")

        config: dict[str, Any] = {"enableRateLimit": True, "timeout": self.timeout_ms}
        if self.proxy_url:
            config["httpsProxy"] = self.proxy_url
        exchange = self.exchange_factory(market.exchange, market.market_type, config)

        funding_rows: list[dict[str, Any]] = []
        try:
            for entry in exchange.fetch_funding_rate_history(market.asset.symbol, limit=funding_limit):
                funding_rows.append({
                    "timestamp": pd.to_datetime(entry["timestamp"], unit="ms", utc=True),
                    "funding_rate": float(entry["fundingRate"]),
                })
        except Exception:
            pass

        funding = pd.DataFrame(columns=["funding_rate"])
        if funding_rows:
            funding = pd.DataFrame(funding_rows).set_index("timestamp").sort_index()
            funding = funding.resample(open_interest_timeframe).last().ffill()

        oi_rows: list[dict[str, Any]] = []
        try:
            for entry in exchange.fetch_open_interest_history(
                market.asset.symbol,
                open_interest_timeframe,
                limit=open_interest_limit,
            ):
                oi_rows.append({
                    "timestamp": pd.to_datetime(entry["timestamp"], unit="ms", utc=True),
                    "open_interest": float(entry["openInterestAmount"]),
                })
        except Exception:
            pass

        open_interest = pd.DataFrame(columns=["open_interest"])
        if oi_rows:
            open_interest = pd.DataFrame(oi_rows).set_index("timestamp").sort_index()

        if funding.empty and open_interest.empty:
            raise ConnectorError(f"No derivative data available for {market.market_key}.")

        return funding.join(open_interest, how="outer").sort_index()

    def fetch_order_book_snapshots(
        self,
        market: MarketSpec,
        depth: int = 5,
        sample_interval: str = "1s",
        limit: int = 1000,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        if start is not None or end is not None:
            raise ConnectorError("start/end order-book snapshot fetching is not implemented yet")

        config: dict[str, Any] = {"enableRateLimit": True, "timeout": self.timeout_ms}
        if self.proxy_url:
            config["httpsProxy"] = self.proxy_url
        exchange = self.exchange_factory(market.exchange, market.market_type, config)
        order_book = exchange.fetch_order_book(market.asset.symbol, limit=depth)

        timestamp_ms = order_book.get("timestamp")
        if timestamp_ms is None:
            timestamp = pd.Timestamp.now(tz="UTC")
        else:
            timestamp = pd.to_datetime(timestamp_ms, unit="ms", utc=True)

        bids = order_book.get("bids") or []
        asks = order_book.get("asks") or []
        row: dict[str, float | None] = {}
        for level in range(depth):
            bid = bids[level] if level < len(bids) else None
            row[f"bid_price_{level + 1}"] = float(bid[0]) if bid else None
            row[f"bid_size_{level + 1}"] = float(bid[1]) if bid else None
        for level in range(depth):
            ask = asks[level] if level < len(asks) else None
            row[f"ask_price_{level + 1}"] = float(ask[0]) if ask else None
            row[f"ask_size_{level + 1}"] = float(ask[1]) if ask else None
        row["spread"] = (
            row["ask_price_1"] - row["bid_price_1"]
            if row.get("ask_price_1") is not None and row.get("bid_price_1") is not None
            else None
        )
        return pd.DataFrame([row], index=pd.DatetimeIndex([timestamp]))

    def _fetch_paginated(self, exchange, symbol: str, timeframe: str, limit: int) -> list[list]:
        all_rows: list[list] = []
        end_time: int | None = None

        for _ in range(self.max_pages):
            remaining = limit - len(all_rows)
            if remaining <= 0:
                break

            batch_limit = min(self.batch_size, remaining)
            params: dict[str, Any] = {}
            if end_time is not None:
                params["endTime"] = end_time

            rows = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=batch_limit, params=params)
            if not rows:
                break

            all_rows = rows + all_rows
            end_time = rows[0][0]

            if len(rows) < batch_limit:
                break

        return all_rows
