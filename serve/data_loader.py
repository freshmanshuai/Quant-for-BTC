"""Singleton data loader for visualization server.

Loads cached OHLCV pickle files and trade_log CSV.
All DataFrames are loaded once on first access and cached in memory.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from quant_platform.data import BarSeriesId
from quant_platform.stores import MissingStorageDependency, ParquetBarStore

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
_BAR_STORE_DIR = _DATA_DIR / "bars"
_RESULTS_DIR = _PROJECT_ROOT / "backtest_results" / "latest"

_cache: dict[str, pd.DataFrame] = {}


def _load_pickle(name: str) -> pd.DataFrame:
    path = _DATA_DIR / name
    if not path.exists():
        return pd.DataFrame()
    with open(path, "rb") as f:
        return pickle.load(f)


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _bar_series_id(timeframe: str) -> BarSeriesId:
    return BarSeriesId(
        symbol="BTC/USDT",
        exchange="binance",
        market_type="swap",
        timeframe=timeframe,
        source="ccxt",
    )


def _load_bar_store(timeframe: str) -> pd.DataFrame | None:
    try:
        return ParquetBarStore(_BAR_STORE_DIR).read(_bar_series_id(timeframe))
    except (FileNotFoundError, MissingStorageDependency):
        return None


def get_ohlcv(timeframe: str = "4h") -> pd.DataFrame:
    """Return cached OHLCV DataFrame for the given timeframe."""
    key = f"ohlcv_{timeframe}"
    if key in _cache:
        return _cache[key]

    df = _load_bar_store(timeframe)
    if df is not None:
        _cache[key] = df
        return df

    if timeframe == "15m":
        df = _load_pickle("binance_swap_BTC_USDT_15m.pkl")
    elif timeframe == "1h":
        # Resample 15m to 1h
        df_15m = get_ohlcv("15m")
        if df_15m.empty:
            return df_15m
        df = df_15m.resample("1h").agg({
            "Open": "first", "High": "max", "Low": "min",
            "Close": "last", "Volume": "sum",
        }).dropna()
    else:  # 4h
        df = _load_pickle("binance_swap_BTC_USDT_4h.pkl")

    _cache[key] = df
    return df


def get_trade_log() -> pd.DataFrame:
    """Return trade_log DataFrame from CSV."""
    key = "trade_log"
    if key in _cache:
        return _cache[key]

    path = _RESULTS_DIR / "trade_log.csv"
    df = _load_csv(path)
    if not df.empty:
        df = df.where(pd.notna(df), None)  # NaN → None for JSON
    _cache[key] = df
    return df


def get_equity_curve() -> pd.DataFrame:
    """Reconstruct equity curve from trade log PnL."""
    trades = get_trade_log()
    if trades.empty:
        return pd.DataFrame()

    initial = 100_000.0
    # Sort by exit time
    trades_sorted = trades.sort_values("exit_time")
    equity = initial + trades_sorted["pnl"].cumsum()

    # Create a daily series (normalize timezone)
    exit_times = pd.to_datetime(trades_sorted["exit_time"]).dt.tz_localize(None)
    eq_series = pd.Series(equity.values, index=exit_times)
    eq_daily = eq_series.resample("D").last().ffill()
    # Pad start
    if len(eq_daily) > 0:
        eq_daily.loc[pd.Timestamp("2019-09-01")] = float(initial)
        eq_daily = eq_daily.sort_index().ffill()

    peak = eq_daily.cummax()
    dd_pct = (eq_daily - peak) / peak * 100

    result = pd.DataFrame({
        "equity": eq_daily.values,
        "drawdown_pct": dd_pct.values,
    }, index=eq_daily.index)
    result.index.name = "date"
    return result.reset_index()


def get_monthly_returns() -> list[dict]:
    """Monthly return data for heatmap."""
    eq = get_equity_curve()
    if eq.empty:
        return []

    eq_dt = eq.set_index("date")["equity"]
    eq_dt.index = pd.to_datetime(eq_dt.index)
    monthly = eq_dt.resample("ME").last().pct_change().dropna() * 100
    result = []
    for ts, val in monthly.items():
        result.append({
            "year": ts.year,
            "month": ts.month,
            "return_pct": round(float(val), 2),
        })
    return result


def get_summary_stats() -> dict:
    """Key performance metrics from trade log."""
    trades = get_trade_log()
    if trades.empty:
        return {}

    pnl = trades["pnl"].values
    total_pnl = float(pnl.sum())
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    n = len(trades)
    n_wins = len(wins)

    eq_curve = get_equity_curve()
    max_dd = float(eq_curve["drawdown_pct"].min()) if not eq_curve.empty else 0

    return {
        "initial_capital": 100_000,
        "final_equity": 100_000 + total_pnl,
        "total_return_pct": round(total_pnl / 100_000 * 100, 2),
        "total_pnl": round(total_pnl, 2),
        "total_trades": n,
        "win_rate_pct": round(n_wins / n * 100, 1) if n > 0 else 0,
        "profit_factor": round(float(wins.sum() / abs(losses.sum())), 2) if len(losses) > 0 and losses.sum() != 0 else 0,
        "best_trade": round(float(trades["pnl"].max()), 2),
        "worst_trade": round(float(trades["pnl"].min()), 2),
        "max_drawdown_pct": round(max_dd, 2),
        "long_trades": int((trades["direction"] == "LONG").sum()),
        "short_trades": int((trades["direction"] == "SHORT").sum()),
    }
