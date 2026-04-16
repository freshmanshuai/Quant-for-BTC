from __future__ import annotations

import ccxt
import pandas as pd


def fetch_ohlcv(symbol: str, timeframe: str, limit: int = 3000, exchange_id: str = "binance") -> pd.DataFrame:
    """Fetch historical OHLCV bars from Binance (public market data)."""
    exchange = getattr(ccxt, exchange_id)({"enableRateLimit": True})
    rows = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    df = pd.DataFrame(rows, columns=["timestamp", "Open", "High", "Low", "Close", "Volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("timestamp")
    return df
