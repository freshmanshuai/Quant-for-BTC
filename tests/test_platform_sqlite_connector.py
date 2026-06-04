import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


class SQLiteBarConnectorTest(unittest.TestCase):
    def test_fetch_bars_reads_sqlite_table_as_normalized_ohlcv_frame(self):
        from quant_platform.connectors_sqlite import SQLiteBarConnector
        from quant_platform.core import AssetSpec, MarketSpec

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "market.sqlite"
            conn = sqlite3.connect(path)
            try:
                conn.execute(
                    """
                    CREATE TABLE bars (
                        timestamp TEXT,
                        timeframe TEXT,
                        open REAL,
                        high REAL,
                        low REAL,
                        close REAL,
                        volume REAL
                    )
                    """
                )
                conn.executemany(
                    "INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        ("2024-01-01T00:00:00Z", "1h", 90, 95, 85, 92, 5),
                        ("2024-01-01T00:00:00Z", "4h", 100, 110, 90, 105, 10),
                        ("2024-01-01T04:00:00Z", "4h", 105, 115, 95, 112, 12),
                        ("2024-01-01T08:00:00Z", "4h", 112, 120, 108, 118, 14),
                    ],
                )
                conn.commit()
            finally:
                conn.close()

            market = MarketSpec(
                asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
                exchange="sqlite",
                market_type="spot",
            )
            connector = SQLiteBarConnector(path, tables_by_symbol={"BTC/USDT": "bars"})

            df = connector.fetch_bars(
                market,
                "4h",
                limit=1,
                start=datetime(2024, 1, 1, 4, tzinfo=timezone.utc),
                end=datetime(2024, 1, 1, 8, tzinfo=timezone.utc),
            )

        self.assertEqual(list(df.columns), ["Open", "High", "Low", "Close", "Volume"])
        self.assertEqual(len(df), 1)
        self.assertEqual(float(df.iloc[0]["Close"]), 118.0)
        self.assertEqual(str(df.index.tz), "UTC")

    def test_fetch_bars_reports_missing_symbol_mapping(self):
        from quant_platform.connectors_sqlite import SQLiteConnectorError, SQLiteBarConnector
        from quant_platform.core import AssetSpec, MarketSpec

        market = MarketSpec(
            asset=AssetSpec(symbol="ETH/USDT", base="ETH", quote="USDT"),
            exchange="sqlite",
            market_type="spot",
        )

        with self.assertRaisesRegex(SQLiteConnectorError, "No SQLite table configured for ETH/USDT"):
            SQLiteBarConnector(Path("market.sqlite"), tables_by_symbol={}).fetch_bars(market, "1h")


if __name__ == "__main__":
    unittest.main()
