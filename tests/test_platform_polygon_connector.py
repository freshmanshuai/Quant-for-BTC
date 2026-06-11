import unittest
from datetime import datetime, timezone
from unittest.mock import patch


class PolygonConnectorTest(unittest.TestCase):
    def test_fetch_bars_reads_aggregate_response_as_normalized_ohlcv_frame(self):
        from quant_platform.connectors_polygon import PolygonConnector
        from quant_platform.core import AssetSpec, MarketSpec

        captured_urls = []

        def fake_http_get(url):
            captured_urls.append(url)
            return {
                "status": "OK",
                "results": [
                    {"t": 1704067200000, "o": 199.0, "h": 203.0, "l": 198.0, "c": 202.0, "v": 1000},
                    {"t": 1704153600000, "o": 202.0, "h": 206.0, "l": 201.0, "c": 205.0, "v": 1200},
                    {"t": 1704240000000, "o": 205.0, "h": 209.0, "l": 204.0, "c": 208.0, "v": 1400},
                ],
            }

        market = MarketSpec(
            asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
        )
        connector = PolygonConnector(api_key_env="POLYGON_TEST_KEY", http_get=fake_http_get)

        with patch.dict("os.environ", {"POLYGON_TEST_KEY": "demo-key"}):
            bars = connector.fetch_bars(
                market,
                "1d",
                limit=1,
                start=datetime(2024, 1, 2, tzinfo=timezone.utc),
                end=datetime(2024, 1, 3, tzinfo=timezone.utc),
            )

        self.assertIn("/v2/aggs/ticker/AAPL/range/1/day/2024-01-02/2024-01-03?", captured_urls[0])
        self.assertIn("apiKey=demo-key", captured_urls[0])
        self.assertEqual(list(bars.columns), ["Open", "High", "Low", "Close", "Volume"])
        self.assertEqual(len(bars), 1)
        self.assertEqual(float(bars.iloc[0]["Close"]), 208.0)
        self.assertEqual(str(bars.index.tz), "UTC")

    def test_fetch_bars_maps_minute_timeframes_to_polygon_range(self):
        from quant_platform.connectors_polygon import PolygonConnector
        from quant_platform.core import AssetSpec, MarketSpec

        captured_urls = []

        def fake_http_get(url):
            captured_urls.append(url)
            return {
                "status": "OK",
                "results": [
                    {"t": 1704101400000, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5, "v": 800}
                ],
            }

        market = MarketSpec(
            asset=AssetSpec(symbol="MSFT", base="MSFT", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
        )
        connector = PolygonConnector(api_key_env="POLYGON_TEST_KEY", http_get=fake_http_get)

        with patch.dict("os.environ", {"POLYGON_TEST_KEY": "demo-key"}):
            bars = connector.fetch_bars(market, "5min")

        self.assertIn("/range/5/minute/", captured_urls[0])
        self.assertEqual(float(bars.iloc[0]["Close"]), 100.5)

    def test_fetch_bars_requires_api_key_env_at_runtime(self):
        from quant_platform.connectors_polygon import PolygonConnector, PolygonConnectorError
        from quant_platform.core import AssetSpec, MarketSpec

        market = MarketSpec(
            asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
        )

        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(PolygonConnectorError, "POLYGON_TEST_KEY"):
                PolygonConnector(api_key_env="POLYGON_TEST_KEY").fetch_bars(market, "1d")

    def test_fetch_bars_reports_polygon_errors(self):
        from quant_platform.connectors_polygon import PolygonConnector, PolygonConnectorError
        from quant_platform.core import AssetSpec, MarketSpec

        def fake_http_get(_url):
            return {"status": "ERROR", "error": "invalid ticker"}

        market = MarketSpec(
            asset=AssetSpec(symbol="BAD", base="BAD", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
        )
        connector = PolygonConnector(api_key_env="POLYGON_TEST_KEY", http_get=fake_http_get)

        with patch.dict("os.environ", {"POLYGON_TEST_KEY": "demo-key"}):
            with self.assertRaisesRegex(PolygonConnectorError, "invalid ticker"):
                connector.fetch_bars(market, "1d")


if __name__ == "__main__":
    unittest.main()
