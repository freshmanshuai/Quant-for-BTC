import json
import tempfile
import unittest
from pathlib import Path


class AlphaVantageConnectorConfigTest(unittest.TestCase):
    def test_loads_alpha_vantage_connector_registry_from_json_config(self):
        from quant_platform import load_data_connector_registry_json
        from quant_platform.connectors_alpha_vantage import AlphaVantageConnector

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "data_sources.json"
            config_path.write_text(json.dumps({
                "connectors": [
                    {
                        "name": "vendor_alpha_vantage",
                        "type": "alpha_vantage",
                        "api_key_env": "ALPHA_VANTAGE_API_KEY",
                        "symbols_by_symbol": {"BRK.B": "BRK-B"},
                    }
                ]
            }), encoding="utf-8")

            registry = load_data_connector_registry_json(config_path, base_dir=root)
            connector = registry.get("vendor_alpha_vantage")

        self.assertIsInstance(connector, AlphaVantageConnector)
        self.assertEqual(connector.api_key_env, "ALPHA_VANTAGE_API_KEY")
        self.assertEqual(connector.symbols_by_symbol["BRK.B"], "BRK-B")

    def test_rejects_inline_alpha_vantage_api_keys_in_config(self):
        from quant_platform import ConnectorConfigError, load_data_connector_registry_json

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "data_sources.json"
            config_path.write_text(json.dumps({
                "connectors": [
                    {
                        "name": "vendor_alpha_vantage",
                        "type": "alpha_vantage",
                        "api_key": "do-not-store-this",
                    }
                ]
            }), encoding="utf-8")

            with self.assertRaisesRegex(ConnectorConfigError, "api_key_env"):
                load_data_connector_registry_json(config_path, base_dir=root)


if __name__ == "__main__":
    unittest.main()
