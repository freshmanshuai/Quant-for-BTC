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

    @patch("serve.app.get_btc_latest_signal_snapshot")
    def test_signal_latest_route_returns_standardized_pipeline_snapshot(self, latest):
        latest.return_value = {
            "mode": "latest",
            "readOnly": True,
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
            "riskDiagnostics": {"portfolio": {"used": 200.0}},
        }

        response = self.client.get("/api/signals/latest?timeframe=4h&symbol=BTC/USDT&equity=15000")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["mode"], "latest")
        self.assertTrue(payload["readOnly"])
        self.assertEqual(payload["riskDecisionCount"], 1)
        latest.assert_called_once_with(timeframe="4h", symbol="BTC/USDT", equity=15_000.0)

    def test_signal_markets_route_returns_configured_market_options(self):
        response = self.client.get("/api/signals/markets")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        markets = {
            (row["symbol"], row["exchange"], row["marketType"])
            for row in payload["markets"]
        }
        self.assertIn(("BTC/USDT", "binance", "swap"), markets)
        self.assertIn(("AAPL", "nasdaq", "equity"), markets)

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
            "/api/signals/research-preview?timeframe=1d&symbol=AAPL&exchange=nasdaq&market_type=equity&equity=15000&refresh_features=true&refresh_bars=true&max_exchange_risk=0.03&max_market_type_risk=0.04"
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
        self.assertTrue(kwargs["refresh_features"])
        self.assertTrue(kwargs["refresh_bars"])
        self.assertEqual(kwargs["risk_limits"].max_exchange_risk, 0.03)
        self.assertEqual(kwargs["risk_limits"].max_market_type_risk, 0.04)
        self.assertNotIn("load_ohlcv", kwargs)

    @patch("serve.app.get_signal_research_event_backtest_preview")
    def test_signal_research_event_backtest_preview_route_accepts_market_selection(self, preview):
        preview.return_value = {
            "symbol": "AAPL",
            "timeframe": "1d",
            "market": {"exchange": "nasdaq", "marketType": "equity"},
            "regimeProfile": {"trendEmaLength": 50},
            "rows": 4,
            "stepCount": 4,
            "tradeCount": 1,
            "summary": {"finalEquity": 10400.0},
            "orders": [],
            "trades": [],
            "equityCurve": [],
            "exposureCurve": [],
            "attribution": {"bySymbol": {}, "byLayer": {}, "byModule": {}},
        }

        response = self.client.get(
            "/api/signals/research-event-backtest-preview?timeframe=1d&symbol=AAPL&exchange=nasdaq&market_type=equity&equity=15000&refresh_features=true&refresh_bars=true&intrabar_entry_limit=true&intrabar_stop_target=true&fee_rate=0.001&slippage_bps=3&max_entry_order_age_bars=1&max_exit_order_age_bars=2&max_entry_fill_fraction_per_bar=0.25&max_entry_volume_fraction_per_bar=0.2&max_exit_fill_fraction_per_bar=0.5&max_exit_volume_fraction_per_bar=0.1&entry_spread_feature=order_book_spread&exit_spread_feature=order_book_spread&max_exchange_risk=0.03&max_market_type_risk=0.04"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["market"]["exchange"], "nasdaq")
        self.assertEqual(payload["tradeCount"], 1)
        preview.assert_called_once()
        kwargs = preview.call_args.kwargs
        self.assertEqual(kwargs["timeframe"], "1d")
        self.assertEqual(kwargs["symbol"], "AAPL")
        self.assertEqual(kwargs["exchange"], "nasdaq")
        self.assertEqual(kwargs["market_type"], "equity")
        self.assertEqual(kwargs["equity"], 15_000.0)
        self.assertTrue(kwargs["refresh_features"])
        self.assertTrue(kwargs["refresh_bars"])
        self.assertEqual(kwargs["risk_limits"].max_exchange_risk, 0.03)
        self.assertEqual(kwargs["risk_limits"].max_market_type_risk, 0.04)
        self.assertTrue(kwargs["execution"].intrabar_entry_limit)
        self.assertTrue(kwargs["execution"].intrabar_stop_target)
        self.assertEqual(kwargs["execution"].fee_rate, 0.001)
        self.assertEqual(kwargs["execution"].slippage_bps, 3.0)
        self.assertEqual(kwargs["execution"].max_entry_order_age_bars, 1)
        self.assertEqual(kwargs["execution"].max_exit_order_age_bars, 2)
        self.assertEqual(kwargs["execution"].max_entry_fill_fraction_per_bar, 0.25)
        self.assertEqual(kwargs["execution"].max_entry_volume_fraction_per_bar, 0.2)
        self.assertEqual(kwargs["execution"].max_exit_fill_fraction_per_bar, 0.5)
        self.assertEqual(kwargs["execution"].max_exit_volume_fraction_per_bar, 0.1)
        self.assertEqual(kwargs["execution"].entry_spread_feature, "order_book_spread")
        self.assertEqual(kwargs["execution"].exit_spread_feature, "order_book_spread")

    @patch("serve.app.get_signal_research_event_backtest_preview")
    def test_signal_research_event_backtest_preview_route_accepts_market_lists(self, preview):
        preview.return_value = {
            "symbols": ["AAPL", "MSFT"],
            "timeframe": "1d",
            "markets": {
                "AAPL": {"exchange": "nasdaq", "marketType": "equity"},
                "MSFT": {"exchange": "nasdaq", "marketType": "equity"},
            },
            "rows": 6,
            "stepCount": 6,
            "tradeCount": 0,
            "summary": {"finalEquity": 15000.0},
            "orders": [],
            "trades": [],
            "equityCurve": [],
            "exposureCurve": [],
            "attribution": {"bySymbol": {}, "byLayer": {}, "byModule": {}},
        }

        response = self.client.get(
            "/api/signals/research-event-backtest-preview?timeframe=1d&symbol=AAPL,MSFT&exchange=nasdaq,nasdaq&market_type=equity,equity&equity=15000"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["symbols"], ["AAPL", "MSFT"])
        preview.assert_called_once()
        kwargs = preview.call_args.kwargs
        self.assertEqual(kwargs["symbol"], ["AAPL", "MSFT"])
        self.assertEqual(kwargs["exchange"], ["nasdaq", "nasdaq"])
        self.assertEqual(kwargs["market_type"], ["equity", "equity"])
        self.assertEqual(kwargs["equity"], 15_000.0)

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
            "riskAudit": {"auditCount": 2, "wouldBlockIfEnforcedCount": 1},
            "delta": {"tradeCount": -2},
        }

        response = self.client.get("/api/signals/migration-comparison-preview?timeframe=4h&symbol=BTC/USDT&equity=30000")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["delta"]["tradeCount"], -2)
        self.assertEqual(payload["riskAudit"]["wouldBlockIfEnforcedCount"], 1)
        preview.assert_called_once_with(timeframe="4h", symbol="BTC/USDT", equity=30_000.0)


if __name__ == "__main__":
    unittest.main()
