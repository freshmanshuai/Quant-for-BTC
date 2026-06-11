import tempfile
import unittest
import sqlite3
from pathlib import Path

import pandas as pd


class BarStoreTest(unittest.TestCase):
    def test_parquet_store_builds_deterministic_path(self):
        from quant_platform.data import BarSeriesId
        from quant_platform.stores import ParquetBarStore

        store = ParquetBarStore(Path("bars"))
        series_id = BarSeriesId(
            symbol="BTC/USDT",
            exchange="binance",
            market_type="swap",
            timeframe="4h",
            source="ccxt",
        )

        self.assertEqual(
            store.path_for(series_id),
            Path("bars") / "ccxt" / "binance" / "swap" / "BTC_USDT" / "4h.parquet",
        )

    def test_parquet_store_round_trip_or_reports_missing_engine(self):
        from quant_platform.data import BarSeriesId
        from quant_platform.stores import MissingStorageDependency, ParquetBarStore

        df = pd.DataFrame(
            {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [10.0]},
            index=pd.to_datetime([1700000000000], unit="ms", utc=True),
        )
        series_id = BarSeriesId("BTC/USDT", "binance", "swap", "1h", "ccxt")

        with tempfile.TemporaryDirectory() as tmp:
            store = ParquetBarStore(Path(tmp))
            try:
                store.write(series_id, df)
            except MissingStorageDependency as exc:
                self.assertIn("pyarrow", str(exc))
                return

            loaded = store.read(series_id)
            self.assertEqual(float(loaded.iloc[0]["Close"]), 1.5)
            self.assertEqual(str(loaded.index.tz), "UTC")

    def test_sqlite_bar_store_builds_deterministic_path(self):
        from quant_platform.data import BarSeriesId
        from quant_platform.stores import SQLiteBarStore

        store = SQLiteBarStore(Path("bars_sqlite"))
        series_id = BarSeriesId("BTC/USDT", "binance", "swap", "4h", "ccxt")

        self.assertEqual(
            store.path_for(series_id),
            Path("bars_sqlite") / "ccxt" / "binance" / "swap" / "BTC_USDT" / "4h.sqlite",
        )

    def test_sqlite_bar_store_round_trip_preserves_utc_index_and_ohlcv(self):
        from quant_platform.data import BarSeriesId
        from quant_platform.stores import SQLiteBarStore

        bars = pd.DataFrame(
            {
                "Open": [100.0, 101.0],
                "High": [110.0, 111.0],
                "Low": [90.0, 91.0],
                "Close": [105.0, 106.0],
                "Volume": [10.0, 11.0],
            },
            index=pd.to_datetime([1700000000000, 1700003600000], unit="ms", utc=True),
        )
        series_id = BarSeriesId("ETH/USDT", "local", "spot", "1h", "csv")

        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteBarStore(Path(tmp))
            path = store.write(series_id, bars)
            loaded = store.read(series_id)

        self.assertEqual(path.name, "1h.sqlite")
        self.assertEqual(list(loaded.columns), ["Open", "High", "Low", "Close", "Volume"])
        self.assertEqual(len(loaded), 2)
        self.assertEqual(float(loaded.iloc[-1]["Close"]), 106.0)
        self.assertEqual(str(loaded.index.tz), "UTC")

    def test_sqlite_bar_store_preserves_optional_turnover_column(self):
        from quant_platform.data import BarSeriesId
        from quant_platform.stores import SQLiteBarStore

        bars = pd.DataFrame(
            {
                "Open": [100.0, 101.0],
                "High": [110.0, 111.0],
                "Low": [90.0, 91.0],
                "Close": [105.0, 106.0],
                "Volume": [10.0, 11.0],
                "Turnover": [1050.0, 1166.0],
            },
            index=pd.to_datetime([1700000000000, 1700003600000], unit="ms", utc=True),
        )
        series_id = BarSeriesId("ETH/USDT", "local", "spot", "1h", "csv")

        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteBarStore(Path(tmp))
            store.write(series_id, bars)
            loaded = store.read(series_id)

        self.assertEqual(list(loaded.columns), ["Open", "High", "Low", "Close", "Volume", "Turnover"])
        self.assertEqual(float(loaded.iloc[-1]["Turnover"]), 1166.0)

    def test_sqlite_bar_store_upgrades_existing_ohlcv_schema_for_turnover(self):
        from quant_platform.data import BarSeriesId
        from quant_platform.stores import SQLiteBarStore

        series_id = BarSeriesId("ETH/USDT", "local", "spot", "1h", "csv")
        bars = pd.DataFrame(
            {
                "Open": [101.0],
                "High": [111.0],
                "Low": [91.0],
                "Close": [106.0],
                "Volume": [11.0],
                "Turnover": [1166.0],
            },
            index=pd.to_datetime([1700003600000], unit="ms", utc=True),
        )

        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteBarStore(Path(tmp))
            path = store.path_for(series_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path)
            try:
                conn.execute(
                    """
                    CREATE TABLE bars (
                        timestamp TEXT PRIMARY KEY,
                        open REAL NOT NULL,
                        high REAL NOT NULL,
                        low REAL NOT NULL,
                        close REAL NOT NULL,
                        volume REAL NOT NULL
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

            store.write(series_id, bars)
            loaded = store.read(series_id)

        self.assertEqual(list(loaded.columns), ["Open", "High", "Low", "Close", "Volume", "Turnover"])
        self.assertEqual(float(loaded.iloc[0]["Turnover"]), 1166.0)


if __name__ == "__main__":
    unittest.main()
