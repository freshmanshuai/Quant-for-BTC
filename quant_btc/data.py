from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Literal

import pickle

import ccxt
import pandas as pd

MarketType = Literal["spot", "swap"]

# ── Cache directory ──────────────────────────────────────────────────────────
_CACHE_DIR = Path(__file__).resolve().parent.parent / "data"


class DataFetchError(RuntimeError):
    """Raised when remote data fetch fails after retries."""


def _to_ohlcv_df(rows: list[list]) -> pd.DataFrame:
    df = pd.DataFrame(
        rows, columns=["timestamp", "Open", "High", "Low", "Close", "Volume"]
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df.set_index("timestamp")


def _cache_path(
    exchange_id: str, market_type: MarketType, symbol: str, timeframe: str
) -> Path:
    """Return the parquet file path for cached OHLCV data."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe_symbol = symbol.replace("/", "_").replace(":", "_")
    fname = f"{exchange_id}_{market_type}_{safe_symbol}_{timeframe}.pkl"
    return _CACHE_DIR / fname


def _load_cache(cache_path: Path) -> pd.DataFrame | None:
    """Load cached OHLCV if available, otherwise return None."""
    if not cache_path.exists():
        return None
    try:
        with open(cache_path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _save_cache(cache_path: Path, df: pd.DataFrame) -> None:
    """Save OHLCV DataFrame to pickle cache."""
    with open(cache_path, "wb") as f:
        pickle.dump(df, f)


_BATCH_SIZE = 1000
_MAX_PAGES = 100


def _fetch_paginated(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    limit: int,
) -> list[list]:
    """Fetch OHLCV with pagination (backward from latest candle)."""
    all_rows: list[list] = []
    end_time: int | None = None

    for _ in range(_MAX_PAGES):
        remaining = limit - len(all_rows)
        if remaining <= 0:
            break

        batch_limit = min(_BATCH_SIZE, remaining)
        params: dict = {}
        if end_time is not None:
            params["endTime"] = end_time

        rows = exchange.fetch_ohlcv(
            symbol, timeframe=timeframe, limit=batch_limit, params=params
        )
        if not rows:
            break

        all_rows = rows + all_rows
        end_time = rows[0][0]

        if len(rows) < batch_limit:
            break

    return all_rows


def _build_binance(
    market_type: MarketType,
    timeout_ms: int,
    proxy_url: str | None,
) -> ccxt.Exchange:
    """Build a Binance CCXT exchange for spot or swap.

    Swap uses ``ccxt.binanceusdm()`` → ``fapi.binance.com``.
    Spot uses ``ccxt.binance()`` → ``api.binance.com``.
    """
    config: dict = {
        "enableRateLimit": True,
        "timeout": timeout_ms,
    }
    if proxy_url:
        config["httpsProxy"] = proxy_url

    if market_type == "swap":
        return ccxt.binanceusdm(config)
    else:
        return ccxt.binance(config)


def _build_binanceus(timeout_ms: int, proxy_url: str | None) -> ccxt.Exchange:
    """Build a BinanceUS CCXT exchange (spot only)."""
    config: dict = {
        "enableRateLimit": True,
        "timeout": timeout_ms,
    }
    if proxy_url:
        config["httpsProxy"] = proxy_url
    return ccxt.binanceus(config)


def _fetch_from_exchange(
    symbol: str,
    timeframe: str,
    limit: int,
    market_type: MarketType,
    exchange_id: str,
    timeout_ms: int,
    max_retries: int,
    proxy_url: str | None,
) -> pd.DataFrame:
    """Fetch OHLCV from a live exchange (internal, no caching)."""
    if exchange_id == "binance":
        exchange = _build_binance(market_type, timeout_ms, proxy_url)
    elif exchange_id == "binanceus":
        if market_type != "spot":
            raise DataFetchError(
                "BinanceUS does not support swap (perpetual futures). "
                "Use --market-type spot with BinanceUS, or use Binance swap "
                "with a non-US proxy."
            )
        exchange = _build_binanceus(timeout_ms, proxy_url)
    else:
        raise DataFetchError(f"Unsupported exchange: {exchange_id}")

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            rows = _fetch_paginated(exchange, symbol, timeframe, limit)
            if not rows:
                raise DataFetchError(
                    f"Fetched empty OHLCV dataset from {exchange_id} ({market_type})."
                )
            return _to_ohlcv_df(rows)
        except Exception as exc:
            last_error = exc
            if attempt < max_retries:
                time.sleep(min(2**attempt, 8))

    raise DataFetchError(
        f"Failed to fetch {symbol} {timeframe} from {exchange_id} ({market_type}) "
        f"after {max_retries} retries. "
        f"Root cause: {type(last_error).__name__}: {last_error}."
    ) from last_error


def fetch_ohlcv(
    symbol: str = "BTC/USDT",
    timeframe: str = "4h",
    limit: int = 50000,
    market_type: MarketType = "swap",
    exchange_id: str = "binance",
    timeout_ms: int = 30_000,
    max_retries: int = 5,
    proxy_url: str | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    """Fetch historical OHLCV bars, with optional offline caching.

    Parameters
    ----------
    market_type:
        ``"swap"`` → perpetual futures (Binance Futures, fapi.binance.com).
        ``"spot"`` → cash market (Binance or BinanceUS).
    exchange_id:
        ``"binance"`` (futures or spot) or ``"binanceus"`` (spot only).
        BinanceUS has no perpetual futures market.
    refresh:
        If True, bypass cache and re-fetch from exchange.
    """
    cache_path = _cache_path(exchange_id, market_type, symbol, timeframe)

    # ── Return cached data if available ──
    if not refresh:
        cached = _load_cache(cache_path)
        if cached is not None:
            print(
                f"[cache] Loaded {len(cached)} bars from {cache_path.name} "
                f"({cached.index[0].date()} → {cached.index[-1].date()})"
            )
            return cached

    # ── Fetch from exchange ──
    if market_type == "swap":
        df = _fetch_from_exchange(
            symbol, timeframe, limit,
            market_type, exchange_id, timeout_ms, max_retries, proxy_url,
        )
        _save_cache(cache_path, df)
        print(
            f"[fetch] {len(df)} bars saved to {cache_path.name} "
            f"({df.index[0].date()} → {df.index[-1].date()})"
        )
        return df

    # ── Spot path: Binance → BinanceUS fallback ──
    try:
        df = _fetch_from_exchange(
            symbol, timeframe, limit,
            market_type, exchange_id, timeout_ms, max_retries, proxy_url,
        )
        _save_cache(cache_path, df)
        return df
    except DataFetchError:
        if exchange_id != "binance":
            raise
        print("[fallback] Binance spot blocked → trying BinanceUS spot …")
        df = _fetch_from_exchange(
            symbol, timeframe, limit,
            "spot", "binanceus", timeout_ms, max_retries, proxy_url,
        )
        # Cache under the binanceus key so subsequent runs find it
        cache_us = _cache_path("binanceus", "spot", symbol, timeframe)
        _save_cache(cache_us, df)
        return df


# ═══════════════════════════════════════════════════════════════════════════════
# Derivative data (funding rate + open interest) — optional, short-only bonus
# ═══════════════════════════════════════════════════════════════════════════════


def fetch_derivative_data(
    symbol: str = "BTC/USDT",
    exchange_id: str = "binance",
    proxy_url: str | None = None,
    refresh: bool = False,
) -> pd.DataFrame | None:
    """Fetch funding rate + open interest history, resampled to 4H.

    Returns a DataFrame with columns ``funding_rate``, ``open_interest``
    indexed by timestamp (UTC).  Returns ``None`` if data is unavailable
    (e.g. geo-restricted or exchange doesn't support the endpoints).

    Cached at ``data/{exchange}_derivatives_{symbol}.pkl``.
    """
    cache_path = _CACHE_DIR / f"{exchange_id}_derivatives_{symbol.replace('/', '_')}.pkl"

    if not refresh:
        cached = _load_cache(cache_path)
        if cached is not None:
            return cached

    if exchange_id != "binance":
        return None  # only Binance futures supported for derivative data

    try:
        ex = ccxt.binanceusdm({
            "enableRateLimit": True,
            "timeout": 30_000,
            "httpsProxy": proxy_url,
        } if proxy_url else {"enableRateLimit": True, "timeout": 30_000})
    except Exception:
        return None

    # ── Funding rate history (8h intervals, CCXT returns dicts) ──
    fr_rows: list = []
    try:
        fr_raw = ex.fetch_funding_rate_history(symbol, limit=1000)
        for entry in fr_raw:
            fr_rows.append({
                "timestamp": pd.to_datetime(entry["timestamp"], unit="ms", utc=True),
                "funding_rate": float(entry["fundingRate"]),
            })
    except Exception:
        pass

    fr_4h = pd.DataFrame(columns=["funding_rate"])
    if fr_rows:
        fr_df = pd.DataFrame(fr_rows).set_index("timestamp").sort_index()
        # Resample to 4H: forward-fill
        fr_4h = fr_df.resample("4h").last().ffill()

    # ── Open interest history (4H, CCXT returns dicts) ──
    oi_rows: list = []
    try:
        oi_raw = ex.fetch_open_interest_history(symbol, "4h", limit=1000)
        for entry in oi_raw:
            oi_rows.append({
                "timestamp": pd.to_datetime(entry["timestamp"], unit="ms", utc=True),
                "open_interest": float(entry["openInterestAmount"]),
            })
    except Exception:
        pass

    oi_df = pd.DataFrame(columns=["open_interest"])
    if oi_rows:
        oi_df = pd.DataFrame(oi_rows).set_index("timestamp").sort_index()

    if fr_4h.empty and oi_df.empty:
        return None

    # ── Merge ──
    combined = fr_4h.join(oi_df, how="outer").sort_index()
    _save_cache(cache_path, combined)
    print(f"[fetch] Derivative data saved to {cache_path.name} ({len(combined)} rows)")
    return combined
