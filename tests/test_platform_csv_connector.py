import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


class LocalCsvConnectorTest(unittest.TestCase):
    def test_fetch_bars_reads_local_csv_as_normalized_ohlcv_frame(self):
        import pandas as pd

        from quant_platform.connectors_csv import LocalCsvConnector
        from quant_platform.core import AssetSpec, MarketSpec

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "btc.csv"
            pd.DataFrame([
                {
                    "timestamp": "2024-01-01T00:00:00Z",
                    "open": 100,
                    "high": 110,
                    "low": 90,
                    "close": 105,
                    "volume": 10,
                },
                {
                    "timestamp": "2024-01-01T04:00:00Z",
                    "open": 105,
                    "high": 115,
                    "low": 95,
                    "close": 112,
                    "volume": 12,
                },
                {
                    "timestamp": "2024-01-01T08:00:00Z",
                    "open": 112,
                    "high": 120,
                    "low": 108,
                    "close": 118,
                    "volume": 14,
                },
            ]).to_csv(path, index=False)

            market = MarketSpec(
                asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
                exchange="local",
                market_type="spot",
            )
            connector = LocalCsvConnector(files_by_symbol={"BTC/USDT": path})

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
        from quant_platform.connectors_csv import CsvConnectorError, LocalCsvConnector
        from quant_platform.core import AssetSpec, MarketSpec

        market = MarketSpec(
            asset=AssetSpec(symbol="ETH/USDT", base="ETH", quote="USDT"),
            exchange="local",
            market_type="spot",
        )

        with self.assertRaisesRegex(CsvConnectorError, "No CSV file configured for ETH/USDT"):
            LocalCsvConnector(files_by_symbol={}).fetch_bars(market, "1h")


if __name__ == "__main__":
    unittest.main()
