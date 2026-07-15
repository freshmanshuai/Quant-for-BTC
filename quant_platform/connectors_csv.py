"""Local CSV data connector."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from quant_platform.connectors import DataConnector
from quant_platform.core import MarketSpec


_TURNOVER_COLUMN_ALIASES = ("turnover", "quotevolume", "quote_volume", "quoteassetvolume", "quote_asset_volume")


class CsvConnectorError(RuntimeError):
    """Raised when a local CSV connector cannot load requested bars."""


class LocalCsvConnector(DataConnector):
    """Fetch normalized OHLCV bars from local CSV files."""

    name = "csv"

    def __init__(
        self,
        files_by_symbol: dict[str, str | Path],
        timestamp_column: str = "timestamp",
        column_map: dict[str, str] | None = None,
    ):
        self.files_by_symbol = {symbol: Path(path) for symbol, path in files_by_symbol.items()}
        self.timestamp_column = timestamp_column
        self.column_map = _normalize_column_map(column_map or {})

    def fetch_bars(
        self,
        market: MarketSpec,
        timeframe: str,
        limit: int | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        path = self.files_by_symbol.get(market.asset.symbol)
        if path is None:
            raise CsvConnectorError(f"No CSV file configured for {market.asset.symbol}.")
        if not path.exists():
            raise CsvConnectorError(f"CSV file does not exist: {path}")

        df = pd.read_csv(path)
        df = self._normalize_ohlcv(df, path)

        if start is not None:
            df = df[df.index >= pd.Timestamp(start).tz_convert("UTC")]
        if end is not None:
            df = df[df.index <= pd.Timestamp(end).tz_convert("UTC")]
        if limit is not None:
            df = df.tail(limit)

        if df.empty:
            raise CsvConnectorError(f"CSV file has no bars for {market.asset.symbol} {timeframe}.")
        return df

    def _normalize_ohlcv(self, df: pd.DataFrame, path: Path) -> pd.DataFrame:
        lower_to_original = {str(column).lower(): column for column in df.columns}
        required = {
            "timestamp": self.timestamp_column.lower(),
            "Open": self.column_map.get("open", "open"),
            "High": self.column_map.get("high", "high"),
            "Low": self.column_map.get("low", "low"),
            "Close": self.column_map.get("close", "close"),
            "Volume": self.column_map.get("volume", "volume"),
        }
        missing = [source for source in required.values() if source not in lower_to_original]
        if missing:
            raise CsvConnectorError(f"CSV file {path} is missing required columns: {', '.join(missing)}")

        out = pd.DataFrame(index=pd.to_datetime(df[lower_to_original[required["timestamp"]]], utc=True))
        for target, source in required.items():
            if target == "timestamp":
                continue
            out[target] = pd.to_numeric(df[lower_to_original[source]], errors="coerce").to_numpy()
        turnover_candidates = _prepend_unique(self.column_map.get("turnover"), _TURNOVER_COLUMN_ALIASES)
        turnover_source = _first_present_column(lower_to_original, turnover_candidates)
        if turnover_source is not None:
            out["Turnover"] = pd.to_numeric(df[turnover_source], errors="coerce").to_numpy()

        out.index.name = "timestamp"
        return out.sort_index().dropna(subset=["Open", "High", "Low", "Close", "Volume"])


def _first_present_column(lower_to_original: dict[str, object], candidates: tuple[str, ...]) -> object | None:
    for candidate in candidates:
        if candidate in lower_to_original:
            return lower_to_original[candidate]
    return None


def _normalize_column_map(column_map: dict[str, str]) -> dict[str, str]:
    return {str(target).lower(): str(source).lower() for target, source in column_map.items()}


def _prepend_unique(first: str | None, rest: tuple[str, ...]) -> tuple[str, ...]:
    if first is None:
        return rest
    return (first, *(candidate for candidate in rest if candidate != first))
