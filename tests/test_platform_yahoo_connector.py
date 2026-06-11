import unittest
from datetime import datetime, timezone


class YahooFinanceConnectorTest(unittest.TestCase):
    def test_fetch_bars_reads_chart_response_as_normalized_ohlcv_frame(self):
        from quant_platform.connectors_yahoo import YahooFinanceConnector
        from quant_platform.core import AssetSpec, MarketSpec

        captured_urls = []

        def fake_http_get(url):
            captured_urls.append(url)
            return {
                "chart": {
                    "result": [
                        {
                            "timestamp": [1704067200, 1704153600, 1704240000],
                            "indicators": {
                                "quote": [
                                    {
                                        "open": [199.0, 202.0, 205.0],
                                        "high": [203.0, 206.0, 209.0],
                                        "low": [198.0, 201.0, 204.0],
                                        "close": [202.0, 205.0, 208.0],
                                        "volume": [1000, 1200, 1400],
                                    }
                                ]
                            },
                        }
                    ],
                    "error": None,
                }
            }

        market = MarketSpec(
            asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
        )
        connector = YahooFinanceConnector(http_get=fake_http_get)

        bars = connector.fetch_bars(
            market,
            "1d",
            limit=1,
            start=datetime(2024, 1, 2, tzinfo=timezone.utc),
            end=datetime(2024, 1, 3, tzinfo=timezone.utc),
        )

        self.assertIn("/v8/finance/chart/AAPL?", captured_urls[0])
        self.assertIn("interval=1d", captured_urls[0])
        self.assertEqual(list(bars.columns), ["Open", "High", "Low", "Close", "Volume"])
        self.assertEqual(len(bars), 1)
        self.assertEqual(float(bars.iloc[0]["Close"]), 208.0)
        self.assertEqual(str(bars.index.tz), "UTC")

    def test_fetch_bars_reports_chart_errors(self):
        from quant_platform.connectors_yahoo import YahooConnectorError, YahooFinanceConnector
        from quant_platform.core import AssetSpec, MarketSpec

        def fake_http_get(_url):
            return {
                "chart": {
                    "result": None,
                    "error": {"description": "No data found"},
                }
            }

        market = MarketSpec(
            asset=AssetSpec(symbol="MSFT", base="MSFT", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
        )

        with self.assertRaisesRegex(YahooConnectorError, "No data found"):
            YahooFinanceConnector(http_get=fake_http_get).fetch_bars(market, "1d")


if __name__ == "__main__":
    unittest.main()
