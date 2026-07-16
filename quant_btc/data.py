from __future__ import annotations

from pathlib import Path
from typing import Literal

import pickle

import pandas as pd
from quant_platform.connectors import fetch_derivatives_with_cache
from quant_platform.connectors_ccxt import CcxtExchangeConnector, ConnectorError
from quant_platform.core import AssetSpec, MarketSpec
from quant_platform.data import BarSeriesId, DerivativeSeriesId, clean_ohlcv_bars
from quant_platform.stores import MissingStorageDependency, ParquetBarStore, ParquetDerivativeStore

MarketType = Literal["spot", "swap"]

# Cache directory
_CACHE_DIR = Path(__file__).resolve().parent.parent / "data"
_BAR_STORE_DIR = _CACHE_DIR / "bars"
_DERIVATIVE_STORE_DIR = _CACHE_DIR / "derivatives"


class DataFetchError(RuntimeError):
    """Raised when remote data fetch fails after retries."""


def _clean_bars(bars: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    cleaned = clean_ohlcv_bars(bars, timeframe)
    return bars if cleaned.equals(bars) else cleaned


def _cache_path(
    exchange_id: str, market_type: MarketType, symbol: str, timeframe: str
) -> Path:
    """Return the parquet file path for cached OHLCV data."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe_symbol = symbol.replace("/", "_").replace(":", "_")
    fname = f"{exchange_id}_{market_type}_{safe_symbol}_{timeframe}.pkl"
    return _CACHE_DIR / fname


def _series_id(exchange_id: str, market_type: MarketType, symbol: str, timeframe: str) -> BarSeriesId:
    return BarSeriesId(
        symbol=symbol,
        exchange=exchange_id,
        market_type=market_type,
        timeframe=timeframe,
        source="ccxt",
    )


def _derivative_series_id(exchange_id: str, symbol: str, timeframe: str = "4h") -> DerivativeSeriesId:
    return DerivativeSeriesId(
        symbol=symbol,
        exchange=exchange_id,
        market_type="swap",
        timeframe=timeframe,
        source="ccxt",
    )


def _load_bar_store(series_id: BarSeriesId) -> pd.DataFrame | None:
    try:
        return ParquetBarStore(_BAR_STORE_DIR).read(series_id)
    except (FileNotFoundError, MissingStorageDependency):
        return None


def _save_bar_store(series_id: BarSeriesId, df: pd.DataFrame) -> None:
    try:
        ParquetBarStore(_BAR_STORE_DIR).write(series_id, df)
    except MissingStorageDependency:
        return


def _load_derivative_store(series_id: DerivativeSeriesId) -> pd.DataFrame | None:
    try:
        return ParquetDerivativeStore(_DERIVATIVE_STORE_DIR).read(series_id)
    except (FileNotFoundError, MissingStorageDependency):
        return None


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
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "wb") as f:
        pickle.dump(df, f)




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
    base, quote = symbol.split("/", 1) if "/" in symbol else (symbol, "")
    market = MarketSpec(
        asset=AssetSpec(symbol=symbol, base=base, quote=quote),
        exchange=exchange_id,
        market_type=market_type,
        supports_short=market_type == "swap",
        supports_leverage=market_type == "swap",
    )
    connector = CcxtExchangeConnector(
        timeout_ms=timeout_ms,
        proxy_url=proxy_url,
        max_retries=max_retries,
    )
    try:
        return connector.fetch_bars(market, timeframe, limit=limit)
    except ConnectorError as exc:
        raise DataFetchError(str(exc)) from exc


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
        ``"swap"`` ->perpetual futures (Binance Futures, fapi.binance.com).
        ``"spot"`` ->cash market (Binance or BinanceUS).
    exchange_id:
        ``"binance"`` (futures or spot) or ``"binanceus"`` (spot only).
        BinanceUS has no perpetual futures market.
    refresh:
        If True, bypass cache and re-fetch from exchange.
    """
    cache_path = _cache_path(exchange_id, market_type, symbol, timeframe)
    series_id = _series_id(exchange_id, market_type, symbol, timeframe)

    # Return cached data if available
    if not refresh:
        bars = _load_bar_store(series_id)
        if bars is not None:
            print(
                f"[cache] Loaded {len(bars)} bars from Parquet store "
                f"({bars.index[0].date()} -> {bars.index[-1].date()})"
            )
            return _clean_bars(bars, timeframe)

        cached = _load_cache(cache_path)
        if cached is not None:
            print(
                f"[cache] Loaded {len(cached)} bars from {cache_path.name} "
                f"({cached.index[0].date()} ->{cached.index[-1].date()})"
            )
            return _clean_bars(cached, timeframe)

    # Fetch from exchange
    if market_type == "swap":
        df = _fetch_from_exchange(
            symbol, timeframe, limit,
            market_type, exchange_id, timeout_ms, max_retries, proxy_url,
        )
        df = _clean_bars(df, timeframe)
        _save_bar_store(series_id, df)
        _save_cache(cache_path, df)
        print(
            f"[fetch] {len(df)} bars saved to {cache_path.name} "
            f"({df.index[0].date()} ->{df.index[-1].date()})"
        )
        return df

    # Spot path: Binance -> BinanceUS fallback
    try:
        df = _fetch_from_exchange(
            symbol, timeframe, limit,
            market_type, exchange_id, timeout_ms, max_retries, proxy_url,
        )
        df = _clean_bars(df, timeframe)
        _save_bar_store(series_id, df)
        _save_cache(cache_path, df)
        return df
    except DataFetchError:
        if exchange_id != "binance":
            raise
        print("[fallback] Binance spot blocked; trying BinanceUS spot ...")
        df = _fetch_from_exchange(
            symbol, timeframe, limit,
            "spot", "binanceus", timeout_ms, max_retries, proxy_url,
        )
        df = _clean_bars(df, timeframe)
        # Cache under the binanceus key so subsequent runs find it
        _save_bar_store(_series_id("binanceus", "spot", symbol, timeframe), df)
        cache_us = _cache_path("binanceus", "spot", symbol, timeframe)
        _save_cache(cache_us, df)
        return df


# Multi-timeframe data loading

def load_mtf_data(
    symbol: str = "BTC/USDT",
    timeframes: tuple[str, ...] = ("4h", "15m"),
    market_type: MarketType = "swap",
    exchange_id: str = "binance",
    proxy_url: str | None = None,
    refresh: bool = False,
) -> dict[str, pd.DataFrame]:
    """Load OHLCV data for multiple timeframes with caching.

    Returns ``{"4h": df_4h, "15m": df_15m}``.
    """
    result = {}
    for tf in timeframes:
        # 15m needs more bars to cover the same time range
        limit = 50000 if tf == "4h" else 100000
        result[tf] = fetch_ohlcv(
            symbol=symbol, timeframe=tf, limit=limit,
            market_type=market_type, exchange_id=exchange_id,
            proxy_url=proxy_url, refresh=refresh,
        )
    return result


# Derivative data (funding rate + open interest) - optional, short-only bonus

def fetch_derivative_data(
    symbol: str = "BTC/USDT",
    exchange_id: str = "binance",
    proxy_url: str | None = None,
    refresh: bool = False,
) -> pd.DataFrame | None:
    """Fetch funding rate + open interest history, resampled to 4H.

    Returns a DataFrame with columns ``funding_rate``, ``open_interest``
    indexed by timestamp (UTC). Returns ``None`` if data is unavailable.

    Cached at ``data/{exchange}_derivatives_{symbol}.pkl``.
    """
    cache_path = _CACHE_DIR / f"{exchange_id}_derivatives_{symbol.replace('/', '_')}.pkl"
    series_id = _derivative_series_id(exchange_id, symbol)

    if not refresh:
        derivatives = _load_derivative_store(series_id)
        if derivatives is not None:
            return derivatives

        cached = _load_cache(cache_path)
        if cached is not None:
            return cached

    if exchange_id != "binance":
        return None

    base, quote = symbol.split("/", 1) if "/" in symbol else (symbol, "")
    market = MarketSpec(
        asset=AssetSpec(symbol=symbol, base=base, quote=quote),
        exchange=exchange_id,
        market_type="swap",
        supports_short=True,
        supports_leverage=True,
    )
    connector = CcxtExchangeConnector(timeout_ms=30_000, proxy_url=proxy_url, max_retries=5)
    try:
        combined = fetch_derivatives_with_cache(
            connector=connector,
            store=ParquetDerivativeStore(_DERIVATIVE_STORE_DIR),
            source="ccxt",
            market=market,
            open_interest_timeframe="4h",
            refresh=True,
        )
    except ConnectorError:
        return None

    _save_cache(cache_path, combined)
    print(f"[fetch] Derivative data saved to {cache_path.name} ({len(combined)} rows)")
    return combined
