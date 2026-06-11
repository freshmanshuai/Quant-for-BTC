import unittest
from datetime import datetime, timezone
from unittest.mock import patch


class AlphaVantageConnectorTest(unittest.TestCase):
    def test_fetch_bars_reads_daily_response_as_normalized_ohlcv_frame(self):
        from quant_platform.connectors_alpha_vantage import AlphaVantageConnector
        from quant_platform.core import AssetSpec, MarketSpec

        captured_urls = []

        def fake_http_get(url):
            captured_urls.append(url)
            return {
                "Time Series (Daily)": {
                    "2024-01-01": {
                        "1. open": "199.0",
                        "2. high": "203.0",
                        "3. low": "198.0",
                        "4. close": "202.0",
                        "5. volume": "1000",
                    },
                    "2024-01-02": {
                        "1. open": "202.0",
                        "2. high": "206.0",
                        "3. low": "201.0",
                        "4. close": "205.0",
                        "5. volume": "1200",
                    },
                    "2024-01-03": {
                        "1. open": "205.0",
                        "2. high": "209.0",
                        "3. low": "204.0",
                        "4. close": "208.0",
                        "5. volume": "1400",
                    },
                }
            }

        market = MarketSpec(
            asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
        )
        connector = AlphaVantageConnector(api_key_env="ALPHA_VANTAGE_TEST_KEY", http_get=fake_http_get)

        with patch.dict("os.environ", {"ALPHA_VANTAGE_TEST_KEY": "demo-key"}):
            bars = connector.fetch_bars(
                market,
                "1d",
                limit=1,
                start=datetime(2024, 1, 2, tzinfo=timezone.utc),
                end=datetime(2024, 1, 3, tzinfo=timezone.utc),
            )

        self.assertIn("function=TIME_SERIES_DAILY", captured_urls[0])
        self.assertIn("symbol=AAPL", captured_urls[0])
        self.assertIn("apikey=demo-key", captured_urls[0])
        self.assertEqual(list(bars.columns), ["Open", "High", "Low", "Close", "Volume"])
        self.assertEqual(len(bars), 1)
        self.assertEqual(float(bars.iloc[0]["Close"]), 208.0)
        self.assertEqual(str(bars.index.tz), "UTC")

    def test_fetch_bars_reads_intraday_response_for_minute_timeframes(self):
        from quant_platform.connectors_alpha_vantage import AlphaVantageConnector
        from quant_platform.core import AssetSpec, MarketSpec

        captured_urls = []

        def fake_http_get(url):
            captured_urls.append(url)
            return {
                "Time Series (5min)": {
                    "2024-01-01 09:30:00": {
                        "1. open": "100.0",
                        "2. high": "101.0",
                        "3. low": "99.0",
                        "4. close": "100.5",
                        "5. volume": "800",
                    }
                }
            }

        market = MarketSpec(
            asset=AssetSpec(symbol="MSFT", base="MSFT", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
        )
        connector = AlphaVantageConnector(api_key_env="ALPHA_VANTAGE_TEST_KEY", http_get=fake_http_get)

        with patch.dict("os.environ", {"ALPHA_VANTAGE_TEST_KEY": "demo-key"}):
            bars = connector.fetch_bars(market, "5min")

        self.assertIn("function=TIME_SERIES_INTRADAY", captured_urls[0])
        self.assertIn("interval=5min", captured_urls[0])
        self.assertEqual(float(bars.iloc[0]["Close"]), 100.5)

    def test_fetch_bars_requires_api_key_env_at_runtime(self):
        from quant_platform.connectors_alpha_vantage import AlphaVantageConnector, AlphaVantageConnectorError
        from quant_platform.core import AssetSpec, MarketSpec

        market = MarketSpec(
            asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
        )

        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(AlphaVantageConnectorError, "ALPHA_VANTAGE_TEST_KEY"):
                AlphaVantageConnector(api_key_env="ALPHA_VANTAGE_TEST_KEY").fetch_bars(market, "1d")


if __name__ == "__main__":
    unittest.main()
