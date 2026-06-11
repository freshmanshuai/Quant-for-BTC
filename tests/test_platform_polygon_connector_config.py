import json
import tempfile
import unittest
from pathlib import Path


class PolygonConnectorConfigTest(unittest.TestCase):
    def test_loads_polygon_connector_registry_from_json_config(self):
        from quant_platform import load_data_connector_registry_json
        from quant_platform.connectors_polygon import PolygonConnector

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "data_sources.json"
            config_path.write_text(json.dumps({
                "connectors": [
                    {
                        "name": "vendor_polygon",
                        "type": "polygon",
                        "api_key_env": "POLYGON_API_KEY",
                        "symbols_by_symbol": {"BRK.B": "BRK.B"},
                    }
                ]
            }), encoding="utf-8")

            registry = load_data_connector_registry_json(config_path, base_dir=root)
            connector = registry.get("vendor_polygon")

        self.assertIsInstance(connector, PolygonConnector)
        self.assertEqual(connector.api_key_env, "POLYGON_API_KEY")
        self.assertEqual(connector.symbols_by_symbol["BRK.B"], "BRK.B")

    def test_rejects_inline_polygon_api_keys_in_config(self):
        from quant_platform import ConnectorConfigError, load_data_connector_registry_json

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "data_sources.json"
            config_path.write_text(json.dumps({
                "connectors": [
                    {
                        "name": "vendor_polygon",
                        "type": "polygon",
                        "api_key": "do-not-store-this",
                    }
                ]
            }), encoding="utf-8")

            with self.assertRaisesRegex(ConnectorConfigError, "api_key_env"):
                load_data_connector_registry_json(config_path, base_dir=root)


if __name__ == "__main__":
    unittest.main()
