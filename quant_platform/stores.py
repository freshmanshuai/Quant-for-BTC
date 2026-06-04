"""Storage primitives for normalized market data."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from quant_platform.data import BarSeriesId, DerivativeSeriesId, ExternalMetricSeriesId, FeatureSeriesId


class MissingStorageDependency(RuntimeError):
    """Raised when a storage backend dependency is not installed."""


class SQLiteBarStore:
    """SQLite bar storage keyed by `BarSeriesId`."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def path_for(self, series_id: BarSeriesId) -> Path:
        safe_symbol = series_id.symbol.replace("/", "_")
        return (
            self.root
            / series_id.source
            / series_id.exchange
            / series_id.market_type
            / safe_symbol
            / f"{series_id.timeframe}.sqlite"
        )

    def write(self, series_id: BarSeriesId, bars: pd.DataFrame) -> Path:
        path = self.path_for(series_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = bars[["Open", "High", "Low", "Close", "Volume"]].copy()
        frame.index = pd.to_datetime(frame.index, utc=True)

        rows = [
            (
                timestamp.isoformat(),
                float(row.Open),
                float(row.High),
                float(row.Low),
                float(row.Close),
                float(row.Volume),
            )
            for timestamp, row in frame.iterrows()
        ]
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bars (
                    timestamp TEXT PRIMARY KEY,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL
                )
                """
            )
            conn.execute("DELETE FROM bars")
            conn.executemany(
                """
                INSERT INTO bars (timestamp, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()
        return path

    def read(self, series_id: BarSeriesId) -> pd.DataFrame:
        path = self.path_for(series_id)
        conn = sqlite3.connect(path)
        try:
            frame = pd.read_sql_query(
                """
                SELECT timestamp, open, high, low, close, volume
                FROM bars
                ORDER BY timestamp
                """,
                conn,
            )
        finally:
            conn.close()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame = frame.set_index("timestamp")
        frame.columns = ["Open", "High", "Low", "Close", "Volume"]
        return frame


class ParquetBarStore:
    """Parquet-first bar storage keyed by `BarSeriesId`."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def path_for(self, series_id: BarSeriesId) -> Path:
        safe_symbol = series_id.symbol.replace("/", "_")
        return (
            self.root
            / series_id.source
            / series_id.exchange
            / series_id.market_type
            / safe_symbol
            / f"{series_id.timeframe}.parquet"
        )

    def write(self, series_id: BarSeriesId, bars: pd.DataFrame) -> Path:
        path = self.path_for(series_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            bars.to_parquet(path)
        except ImportError as exc:
            raise MissingStorageDependency(
                "Parquet storage requires pyarrow or fastparquet. Install pyarrow to enable BarStore persistence."
            ) from exc
        return path

    def read(self, series_id: BarSeriesId) -> pd.DataFrame:
        try:
            return pd.read_parquet(self.path_for(series_id))
        except ImportError as exc:
            raise MissingStorageDependency(
                "Parquet storage requires pyarrow or fastparquet. Install pyarrow to enable BarStore persistence."
            ) from exc


class ParquetFeatureStore:
    """Parquet-first feature storage keyed by `FeatureSeriesId`."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def path_for(self, series_id: FeatureSeriesId) -> Path:
        safe_symbol = series_id.symbol.replace("/", "_")
        safe_feature_set = series_id.feature_set.replace("/", "_")
        return (
            self.root
            / series_id.source
            / series_id.exchange
            / series_id.market_type
            / safe_symbol
            / series_id.timeframe
            / f"{safe_feature_set}.parquet"
        )

    def write(self, series_id: FeatureSeriesId, features: pd.DataFrame) -> Path:
        path = self.path_for(series_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            features.to_parquet(path)
        except ImportError as exc:
            raise MissingStorageDependency(
                "Parquet storage requires pyarrow or fastparquet. Install pyarrow to enable FeatureStore persistence."
            ) from exc
        return path

    def read(self, series_id: FeatureSeriesId) -> pd.DataFrame:
        try:
            return pd.read_parquet(self.path_for(series_id))
        except ImportError as exc:
            raise MissingStorageDependency(
                "Parquet storage requires pyarrow or fastparquet. Install pyarrow to enable FeatureStore persistence."
            ) from exc


class SQLiteFeatureStore:
    """SQLite feature storage keyed by `FeatureSeriesId`."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def path_for(self, series_id: FeatureSeriesId) -> Path:
        safe_symbol = series_id.symbol.replace("/", "_")
        safe_feature_set = series_id.feature_set.replace("/", "_")
        return (
            self.root
            / series_id.source
            / series_id.exchange
            / series_id.market_type
            / safe_symbol
            / series_id.timeframe
            / f"{safe_feature_set}.sqlite"
        )

    def write(self, series_id: FeatureSeriesId, features: pd.DataFrame) -> Path:
        path = self.path_for(series_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = features.copy()
        frame.index = pd.to_datetime(frame.index, utc=True)
        frame.insert(0, "timestamp", [timestamp.isoformat() for timestamp in frame.index])

        conn = sqlite3.connect(path)
        try:
            frame.to_sql("features", conn, if_exists="replace", index=False)
            conn.commit()
        finally:
            conn.close()
        return path

    def read(self, series_id: FeatureSeriesId) -> pd.DataFrame:
        path = self.path_for(series_id)
        conn = sqlite3.connect(path)
        try:
            frame = pd.read_sql_query("SELECT * FROM features ORDER BY timestamp", conn)
        finally:
            conn.close()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        return frame.set_index("timestamp")


class ParquetExternalMetricStore:
    """Parquet-first external metric storage keyed by `ExternalMetricSeriesId`."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def path_for(self, series_id: ExternalMetricSeriesId) -> Path:
        safe_symbol = series_id.symbol.replace("/", "_")
        safe_dataset = series_id.dataset.replace("/", "_")
        return (
            self.root
            / series_id.source
            / series_id.provider
            / safe_symbol
            / series_id.timeframe
            / f"{safe_dataset}.parquet"
        )

    def write(self, series_id: ExternalMetricSeriesId, metrics: pd.DataFrame) -> Path:
        path = self.path_for(series_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            metrics.to_parquet(path)
        except ImportError as exc:
            raise MissingStorageDependency(
                "Parquet storage requires pyarrow or fastparquet. Install pyarrow to enable ExternalMetricStore persistence."
            ) from exc
        return path

    def read(self, series_id: ExternalMetricSeriesId) -> pd.DataFrame:
        try:
            return pd.read_parquet(self.path_for(series_id))
        except ImportError as exc:
            raise MissingStorageDependency(
                "Parquet storage requires pyarrow or fastparquet. Install pyarrow to enable ExternalMetricStore persistence."
            ) from exc


class SQLiteExternalMetricStore:
    """SQLite external metric storage keyed by `ExternalMetricSeriesId`."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def path_for(self, series_id: ExternalMetricSeriesId) -> Path:
        safe_symbol = series_id.symbol.replace("/", "_")
        safe_dataset = series_id.dataset.replace("/", "_")
        return (
            self.root
            / series_id.source
            / series_id.provider
            / safe_symbol
            / series_id.timeframe
            / f"{safe_dataset}.sqlite"
        )

    def write(self, series_id: ExternalMetricSeriesId, metrics: pd.DataFrame) -> Path:
        path = self.path_for(series_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = metrics.copy()
        frame.index = pd.to_datetime(frame.index, utc=True)
        frame.insert(0, "timestamp", [timestamp.isoformat() for timestamp in frame.index])

        conn = sqlite3.connect(path)
        try:
            frame.to_sql("external_metrics", conn, if_exists="replace", index=False)
            conn.commit()
        finally:
            conn.close()
        return path

    def read(self, series_id: ExternalMetricSeriesId) -> pd.DataFrame:
        path = self.path_for(series_id)
        conn = sqlite3.connect(path)
        try:
            frame = pd.read_sql_query("SELECT * FROM external_metrics ORDER BY timestamp", conn)
        finally:
            conn.close()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        return frame.set_index("timestamp")


class ParquetDerivativeStore:
    """Parquet-first derivatives storage keyed by `DerivativeSeriesId`."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def path_for(self, series_id: DerivativeSeriesId) -> Path:
        safe_symbol = series_id.symbol.replace("/", "_")
        return (
            self.root
            / series_id.source
            / series_id.exchange
            / series_id.market_type
            / safe_symbol
            / f"{series_id.timeframe}.parquet"
        )

    def write(self, series_id: DerivativeSeriesId, derivatives: pd.DataFrame) -> Path:
        path = self.path_for(series_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            derivatives.to_parquet(path)
        except ImportError as exc:
            raise MissingStorageDependency(
                "Parquet storage requires pyarrow or fastparquet. Install pyarrow to enable DerivativeStore persistence."
            ) from exc
        return path

    def read(self, series_id: DerivativeSeriesId) -> pd.DataFrame:
        try:
            return pd.read_parquet(self.path_for(series_id))
        except ImportError as exc:
            raise MissingStorageDependency(
                "Parquet storage requires pyarrow or fastparquet. Install pyarrow to enable DerivativeStore persistence."
            ) from exc


class SQLiteDerivativeStore:
    """SQLite derivatives storage keyed by `DerivativeSeriesId`."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def path_for(self, series_id: DerivativeSeriesId) -> Path:
        safe_symbol = series_id.symbol.replace("/", "_")
        return (
            self.root
            / series_id.source
            / series_id.exchange
            / series_id.market_type
            / safe_symbol
            / f"{series_id.timeframe}.sqlite"
        )

    def write(self, series_id: DerivativeSeriesId, derivatives: pd.DataFrame) -> Path:
        path = self.path_for(series_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = derivatives.copy()
        frame.index = pd.to_datetime(frame.index, utc=True)
        frame.insert(0, "timestamp", [timestamp.isoformat() for timestamp in frame.index])

        conn = sqlite3.connect(path)
        try:
            frame.to_sql("derivatives", conn, if_exists="replace", index=False)
            conn.commit()
        finally:
            conn.close()
        return path

    def read(self, series_id: DerivativeSeriesId) -> pd.DataFrame:
        path = self.path_for(series_id)
        conn = sqlite3.connect(path)
        try:
            frame = pd.read_sql_query("SELECT * FROM derivatives ORDER BY timestamp", conn)
        finally:
            conn.close()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        return frame.set_index("timestamp")
