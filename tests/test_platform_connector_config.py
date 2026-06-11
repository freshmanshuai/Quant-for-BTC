import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd


class ConnectorConfigTest(unittest.TestCase):
    def test_loads_csv_connector_registry_from_json_config(self):
        from quant_platform import load_data_connector_registry_json
        from quant_platform.core import AssetSpec, MarketSpec

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            csv_path = root / "data" / "aapl_1d.csv"
            csv_path.parent.mkdir()
            pd.DataFrame([
                {
                    "timestamp": "2026-06-01T00:00:00Z",
                    "open": 199.0,
                    "high": 203.0,
                    "low": 198.0,
                    "close": 202.0,
                    "volume": 1000.0,
                }
            ]).to_csv(csv_path, index=False)
            config_path = root / "data_sources.json"
            config_path.write_text(json.dumps({
                "connectors": [
                    {
                        "name": "research_csv",
                        "type": "csv",
                        "files_by_symbol": {"AAPL": "data/aapl_1d.csv"},
                    }
                ]
            }), encoding="utf-8")
            market = MarketSpec(
                asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
                exchange="nasdaq",
                market_type="equity",
            )

            registry = load_data_connector_registry_json(config_path, base_dir=root)
            bars = registry.fetch_bars("research_csv", market, "1d")

        self.assertEqual(list(bars.columns), ["Open", "High", "Low", "Close", "Volume"])
        self.assertEqual(len(bars), 1)
        self.assertEqual(float(bars.iloc[0]["Close"]), 202.0)
        self.assertEqual(str(bars.index.tz), "UTC")

    def test_loads_sqlite_connector_registry_from_json_config(self):
        from quant_platform import load_data_connector_registry_json
        from quant_platform.core import AssetSpec, MarketSpec

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            database_path = root / "data" / "market.sqlite"
            database_path.parent.mkdir()
            conn = sqlite3.connect(database_path)
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
                conn.execute(
                    "INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("2026-06-01T00:00:00Z", "1d", 199.0, 203.0, 198.0, 202.0, 1000.0),
                )
                conn.commit()
            finally:
                conn.close()
            config_path = root / "data_sources.json"
            config_path.write_text(json.dumps({
                "connectors": [
                    {
                        "name": "research_sqlite",
                        "type": "sqlite",
                        "database_path": "data/market.sqlite",
                        "tables_by_symbol": {"AAPL": "bars"},
                    }
                ]
            }), encoding="utf-8")
            market = MarketSpec(
                asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
                exchange="nasdaq",
                market_type="equity",
            )

            registry = load_data_connector_registry_json(config_path, base_dir=root)
            bars = registry.fetch_bars("research_sqlite", market, "1d")

        self.assertEqual(list(bars.columns), ["Open", "High", "Low", "Close", "Volume"])
        self.assertEqual(len(bars), 1)
        self.assertEqual(float(bars.iloc[0]["Close"]), 202.0)
        self.assertEqual(str(bars.index.tz), "UTC")

    def test_loads_ccxt_connector_registry_from_json_config(self):
        from quant_platform import load_data_connector_registry_json
        from quant_platform.connectors_ccxt import CcxtExchangeConnector

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "data_sources.json"
            config_path.write_text(json.dumps({
                "connectors": [
                    {
                        "name": "exchange_ccxt",
                        "type": "ccxt",
                        "timeout_ms": 15_000,
                        "proxy_url": "http://127.0.0.1:7890",
                        "batch_size": 500,
                        "max_pages": 3,
                        "max_retries": 2,
                    }
                ]
            }), encoding="utf-8")

            registry = load_data_connector_registry_json(config_path, base_dir=root)
            connector = registry.get("exchange_ccxt")

        self.assertIsInstance(connector, CcxtExchangeConnector)
        self.assertEqual(connector.timeout_ms, 15_000)
        self.assertEqual(connector.proxy_url, "http://127.0.0.1:7890")
        self.assertEqual(connector.batch_size, 500)
        self.assertEqual(connector.max_pages, 3)
        self.assertEqual(connector.max_retries, 2)


if __name__ == "__main__":
    unittest.main()
