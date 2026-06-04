import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from serve.valuescan_client import ValuescanConfigError

try:
    from serve.app import create_app
except ModuleNotFoundError as exc:
    create_app = None
    _missing_flask = exc.name == "flask"
else:
    _missing_flask = False


class FakeValuescanClient:
    def resolve_token(self, token):
        return {"id": 1, "symbol": token, "name": "Bitcoin"}

    def support_resistance(self, vs_token_id, date_ms):
        return {"data": [{"price": "70000", "denseArea": 1}]}

    def price_market(self, vs_token_id, start_ms, end_ms):
        return {"data": [{"date": end_ms, "priceMarketType": 1, "symbol": "BTC"}]}

    def social_sentiment(self, vs_token_id):
        return {
            "data": {
                "symbol": "BTC",
                "bullishRatio": 0.45,
                "neutralRatio": 0.35,
                "bearishRatio": 0.20,
                "bullishContents": [{"english": "Bullish summary", "updateTime": 1}],
                "neutralContents": [],
                "bearishContents": [{"english": "Bearish summary", "updateTime": 1}],
            }
        }

    def market_analysis_history(self, page=1, page_size=10):
        return {"data": [{"uniqueId": "m1", "ts": 1775734240000, "content": "BTC market analysis"}]}

    def chance_coin_list(self):
        return {"data": [{"vsTokenId": "1", "symbol": "BTC", "score": 66, "grade": 2}]}

    def risk_coin_list(self):
        return {"data": [{"vsTokenId": "1027", "symbol": "ETH", "score": 58, "grade": 1}]}

    def funds_coin_list(self):
        return {"data": [{"vsTokenId": "1", "symbol": "BTC", "tradeType": 2}]}

    def chance_coin_messages(self, vs_token_id):
        return {"data": [{"symbol": "BTC", "scoring": 65, "updateTime": 1}]}

    def risk_coin_messages(self, vs_token_id):
        return {"data": [{"symbol": "ETH", "scoring": 55, "updateTime": 1}]}

    def funds_coin_messages(self, vs_token_id, trade_type=1):
        return {"data": [{"symbol": "BTC", "tradeType": 2, "updateTime": 1}]}

    def stream_events(self, channel, tokens=None):
        yield "event: connected\ndata: subscribed\n\n"
        yield f"event: {channel}\ndata: {{\"ok\":true}}\n\n"


@unittest.skipIf(_missing_flask, "Flask is not installed in this test environment")
class ValuescanRoutesTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    @patch("serve.app.ValuescanClient", return_value=FakeValuescanClient(), create=True)
    def test_overview_route_returns_btc_ai_snapshot(self, _client_cls):
        response = self.client.get("/api/valuescan/ai/overview?token=BTC")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["token"]["vsTokenId"], 1)
        self.assertEqual(payload["token"]["symbol"], "BTC")
        self.assertEqual(payload["supportResistance"][0]["price"], "70000")
        self.assertEqual(payload["priceMarket"][0]["priceMarketType"], 1)
        self.assertEqual(payload["socialSentiment"]["bullishRatio"], 0.45)
        self.assertEqual(payload["marketAnalysis"][0]["content"], "BTC market analysis")

    @patch("serve.app.ValuescanClient", return_value=FakeValuescanClient(), create=True)
    def test_lists_route_returns_ai_tracking_lists_and_messages(self, _client_cls):
        response = self.client.get("/api/valuescan/ai/lists")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["opportunities"][0]["symbol"], "BTC")
        self.assertEqual(payload["risks"][0]["symbol"], "ETH")
        self.assertEqual(payload["funds"][0]["tradeType"], 2)
        self.assertEqual(payload["messages"]["opportunities"][0]["scoring"], 65)

    @patch("serve.app.ParquetExternalMetricStore", create=True)
    @patch("serve.app.get_ohlcv", create=True)
    @patch("serve.app.ValuescanClient", return_value=FakeValuescanClient(), create=True)
    def test_features_route_returns_read_only_features_and_cache_metadata(self, _client_cls, get_ohlcv, store_cls):
        get_ohlcv.return_value = pd.DataFrame(
            {
                "Open": [99.0, 100.0],
                "High": [101.0, 102.0],
                "Low": [98.0, 99.0],
                "Close": [100.0, 101.0],
                "Volume": [10.0, 11.0],
            },
            index=pd.date_range("2026-06-03", periods=2, freq="4h", tz="UTC"),
        )
        store_cls.return_value.write.return_value = Path("data/external_metrics/api/valuescan/BTC/4h/ai_tracking.parquet")

        response = self.client.get("/api/valuescan/ai/features?token=BTC&timeframe=4h&limit=1")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["symbol"], "BTC")
        self.assertEqual(payload["timeframe"], "4h")
        self.assertIn("valuescan_bullish_ratio", payload["columns"])
        self.assertEqual(payload["cache"]["cacheKey"], "api/valuescan/BTC/4h/ai_tracking")
        self.assertEqual(payload["cache"]["path"], str(store_cls.return_value.write.return_value))
        store_cls.return_value.write.assert_called_once()

    @patch("serve.app.ValuescanClient", return_value=FakeValuescanClient(), create=True)
    def test_stream_route_proxies_sse_without_exposing_signed_url(self, _client_cls):
        response = self.client.get("/api/valuescan/ai/stream?type=signal&tokens=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/event-stream")
        body = response.data.decode("utf-8")
        self.assertIn("event: connected", body)
        self.assertIn("event: signal", body)
        self.assertNotIn("apiKey=", body)
        self.assertNotIn("sign=", body)

    @patch("serve.app.ValuescanClient", create=True)
    def test_overview_route_returns_503_when_credentials_missing(self, client_cls):
        client_cls.return_value.resolve_token.side_effect = ValuescanConfigError("Missing VS_OPEN_API_KEY")

        response = self.client.get("/api/valuescan/ai/overview?token=BTC")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], "valuescan_not_configured")


if __name__ == "__main__":
    unittest.main()
