from __future__ import annotations

import time

import ccxt
import pandas as pd


class DataFetchError(RuntimeError):
    """Raised when remote data fetch fails after retries."""


def _to_ohlcv_df(rows: list[list]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["timestamp", "Open", "High", "Low", "Close", "Volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.set_index("timestamp")


def _fetch_from_exchange(
    symbol: str,
    timeframe: str,
    limit: int,
    exchange_id: str,
    timeout_ms: int,
    max_retries: int,
    proxy_url: str | None,
) -> pd.DataFrame:
    # Use CCXT's native endpoint routing for each exchange.
    # Do not override exchange.urls["api"], otherwise paths like /api/v3 can be lost.
    exchange_config = {"enableRateLimit": True, "timeout": timeout_ms}
    if proxy_url:
        exchange_config["httpProxy"] = proxy_url
        exchange_config["httpsProxy"] = proxy_url

    exchange = getattr(ccxt, exchange_id)(exchange_config)

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            rows = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if not rows:
                raise DataFetchError(f"Fetched empty OHLCV dataset from {exchange_id}.")
            return _to_ohlcv_df(rows)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < max_retries:
                time.sleep(min(2**attempt, 8))

    raise DataFetchError(
        f"Failed to fetch {symbol} {timeframe} from {exchange_id} after {max_retries} retries. "
        f"Root cause: {type(last_error).__name__}: {last_error}."
    ) from last_error


def fetch_ohlcv(
    symbol: str,
    timeframe: str,
    limit: int = 3000,
    exchange_id: str = "binance",
    timeout_ms: int = 20_000,
    max_retries: int = 3,
    fallback_to_binanceus: bool = True,
    proxy_url: str | None = None,
) -> pd.DataFrame:
    """Fetch historical OHLCV bars with optional Binance->BinanceUS fallback.

    If `exchange_id=binance` and region/network blocks Binance, this will
    automatically retry on BinanceUS when `fallback_to_binanceus=True`.
    """
    try:
        return _fetch_from_exchange(
            symbol, timeframe, limit, exchange_id, timeout_ms, max_retries, proxy_url
        )
    except DataFetchError:
        should_fallback = exchange_id == "binance" and fallback_to_binanceus
        if not should_fallback:
            raise

        # Fallback for US users or restricted-location responses from Binance main site.
        return _fetch_from_exchange(
            symbol, timeframe, limit, "binanceus", timeout_ms, max_retries, proxy_url
        )
