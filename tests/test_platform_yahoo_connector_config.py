import json
import tempfile
import unittest
from pathlib import Path


class YahooConnectorConfigTest(unittest.TestCase):
    def test_loads_yahoo_connector_registry_from_json_config(self):
        from quant_platform import load_data_connector_registry_json
        from quant_platform.core import AssetSpec, MarketSpec

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "data_sources.json"
            config_path.write_text(json.dumps({
                "connectors": [
                    {
                        "name": "research_yahoo",
                        "type": "yahoo",
                        "symbols_by_symbol": {"BRK.B": "BRK-B"},
                    }
                ]
            }), encoding="utf-8")
            market = MarketSpec(
                asset=AssetSpec(symbol="BRK.B", base="BRK.B", quote="USD"),
                exchange="nyse",
                market_type="equity",
            )
            registry = load_data_connector_registry_json(config_path, base_dir=root)
            connector = registry.get("research_yahoo")

            connector.http_get = lambda _url: {
                "chart": {
                    "result": [
                        {
                            "timestamp": [1704067200],
                            "indicators": {
                                "quote": [
                                    {
                                        "open": [540.0],
                                        "high": [545.0],
                                        "low": [539.0],
                                        "close": [544.0],
                                        "volume": [500],
                                    }
                                ]
                            },
                        }
                    ],
                    "error": None,
                }
            }

            bars = registry.fetch_bars("research_yahoo", market, "1d")

        self.assertEqual(float(bars.iloc[0]["Close"]), 544.0)
        self.assertEqual(str(bars.index.tz), "UTC")


if __name__ == "__main__":
    unittest.main()
