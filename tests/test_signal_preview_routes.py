import unittest
from unittest.mock import patch

try:
    from serve.app import create_app
except ModuleNotFoundError as exc:
    create_app = None
    _missing_flask = exc.name == "flask"
else:
    _missing_flask = False


@unittest.skipIf(_missing_flask, "Flask is not installed in this test environment")
class SignalPreviewRoutesTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = self.app.test_client()

    @patch("serve.app.get_btc_signal_preview")
    def test_signal_preview_route_returns_standardized_signals(self, preview):
        preview.return_value = {
            "symbol": "BTC/USDT",
            "timeframe": "4h",
            "rows": 120,
            "signalCount": 1,
            "signals": [
                {
                    "module": "breakout",
                    "symbol": "BTC/USDT",
                    "direction": "long",
                    "score": 88.0,
                    "confidence": 0.88,
                    "required_data": ["ohlcv:4h"],
                }
            ],
        }

        response = self.client.get("/api/signals/preview?timeframe=4h&symbol=BTC/USDT&limit=10")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["signalCount"], 1)
        self.assertEqual(payload["signals"][0]["module"], "breakout")
        preview.assert_called_once_with(timeframe="4h", symbol="BTC/USDT", limit=10)

    @patch("serve.app.get_btc_pipeline_preview")
    def test_signal_pipeline_preview_route_returns_risk_and_portfolio_plan(self, preview):
        preview.return_value = {
            "symbol": "BTC/USDT",
            "timeframe": "4h",
            "signalCount": 1,
            "riskDecisionCount": 1,
            "orderCount": 1,
            "deliveryCount": 1,
            "signals": [{"module": "breakout", "direction": "long"}],
            "riskDecisions": [{"allowed": True, "reason": "allowed"}],
            "orders": [{"action": "open", "symbol": "BTC/USDT"}],
            "deliveries": [{"channel": "dashboard", "ok": True}],
        }

        response = self.client.get("/api/signals/pipeline-preview?timeframe=4h&symbol=BTC/USDT&equity=15000")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["riskDecisionCount"], 1)
        self.assertEqual(payload["orders"][0]["action"], "open")
        preview.assert_called_once_with(timeframe="4h", symbol="BTC/USDT", equity=15_000.0)

    @patch("serve.app.get_signal_research_preview")
    def test_signal_research_preview_route_accepts_market_selection(self, preview):
        preview.return_value = {
            "symbol": "AAPL",
            "timeframe": "1d",
            "market": {"exchange": "nasdaq", "marketType": "equity"},
            "regimeProfile": {"trendEmaLength": 50},
            "signalCount": 0,
            "riskDecisionCount": 0,
            "orderCount": 0,
            "deliveryCount": 0,
            "signals": [],
            "riskDecisions": [],
            "orders": [],
            "deliveries": [],
        }

        response = self.client.get(
            "/api/signals/research-preview?timeframe=1d&symbol=AAPL&exchange=nasdaq&market_type=equity&equity=15000"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["market"]["exchange"], "nasdaq")
        self.assertEqual(payload["market"]["marketType"], "equity")
        preview.assert_called_once()
        kwargs = preview.call_args.kwargs
        self.assertEqual(kwargs["timeframe"], "1d")
        self.assertEqual(kwargs["symbol"], "AAPL")
        self.assertEqual(kwargs["exchange"], "nasdaq")
        self.assertEqual(kwargs["market_type"], "equity")
        self.assertEqual(kwargs["equity"], 15_000.0)
        self.assertIn("load_ohlcv", kwargs)

    @patch("serve.app.get_btc_event_backtest_preview")
    def test_signal_event_backtest_preview_route_returns_event_driven_results(self, preview):
        preview.return_value = {
            "symbol": "BTC/USDT",
            "timeframe": "4h",
            "rows": 120,
            "stepCount": 120,
            "tradeCount": 3,
            "summary": {"finalEquity": 10123.4},
            "trades": [],
            "equityCurve": [],
            "attribution": {"bySymbol": {}, "byLayer": {}, "byModule": {}},
        }

        response = self.client.get("/api/signals/event-backtest-preview?timeframe=4h&symbol=BTC/USDT&equity=25000")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["tradeCount"], 3)
        self.assertEqual(payload["summary"]["finalEquity"], 10123.4)
        preview.assert_called_once_with(timeframe="4h", symbol="BTC/USDT", equity=25_000.0)

    @patch("serve.app.get_btc_migration_comparison_preview")
    def test_signal_migration_comparison_route_returns_legacy_event_delta(self, preview):
        preview.return_value = {
            "symbol": "BTC/USDT",
            "timeframe": "4h",
            "legacy": {"tradeCount": 10},
            "event": {"tradeCount": 8},
            "delta": {"tradeCount": -2},
        }

        response = self.client.get("/api/signals/migration-comparison-preview?timeframe=4h&symbol=BTC/USDT&equity=30000")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["delta"]["tradeCount"], -2)
        preview.assert_called_once_with(timeframe="4h", symbol="BTC/USDT", equity=30_000.0)


if __name__ == "__main__":
    unittest.main()
