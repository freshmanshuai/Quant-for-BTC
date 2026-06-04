import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from quant_platform.signals import Direction, Signal


class SignalPreviewServiceTest(unittest.TestCase):
    def test_default_btc_feature_builder_caches_base_feature_engine_output(self):
        from serve import signal_preview

        index = pd.date_range("2026-06-03", periods=60, freq="4h", tz="UTC")
        close = pd.Series(range(100, 160), index=index, dtype=float)
        bars = pd.DataFrame(
            {
                "Open": close - 0.5,
                "High": close + 1.0,
                "Low": close - 1.0,
                "Close": close,
                "Volume": close * 10,
            },
            index=index,
        )

        class FakeStore:
            instances = []

            def __init__(self, root):
                self.root = Path(root)
                self.calls = []
                FakeStore.instances.append(self)

            def write(self, series_id, features):
                self.calls.append((series_id, features.copy()))
                return self.root / "feature_engine" / "binance" / "swap" / "BTC_USDT" / "4h" / "btc_compat_v1.parquet"

        original_store = signal_preview.ParquetFeatureStore
        signal_preview.ParquetFeatureStore = FakeStore
        try:
            features = signal_preview._default_btc_feature_builder(bars, timeframe="4h", symbol="BTC/USDT")
        finally:
            signal_preview.ParquetFeatureStore = original_store

        self.assertIn("long_entry", features.columns)
        self.assertEqual(
            FakeStore.instances[0].calls[0][0].cache_key,
            "feature_engine/binance/swap/BTC_USDT/4h/btc_compat_v1",
        )
        self.assertIn("ema55", FakeStore.instances[0].calls[0][1].columns)

    def test_builds_btc_signal_preview_from_cached_bars_and_standardized_signals(self):
        from serve.signal_preview import get_btc_signal_preview

        bars = pd.DataFrame(
            {
                "Open": [99.0, 100.0],
                "High": [101.0, 103.0],
                "Low": [98.0, 99.0],
                "Close": [100.0, 102.0],
                "Volume": [10.0, 12.0],
            },
            index=pd.date_range("2024-01-01", periods=2, freq="4h", tz="UTC"),
        )

        def load_ohlcv(timeframe):
            self.assertEqual(timeframe, "4h")
            return bars

        def build_features(frame):
            self.assertEqual(len(frame), 2)
            return frame.assign(breakout_long=[False, True])

        def generate_signals(features, symbol):
            self.assertEqual(symbol, "BTC/USDT")
            return [
                Signal(
                    module="breakout",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=88.0,
                    entry_reason="breakout",
                    invalidation="close back inside channel",
                    confidence=0.88,
                    required_data=("ohlcv:4h",),
                )
            ]

        payload = get_btc_signal_preview(
            timeframe="4h",
            symbol="BTC/USDT",
            limit=25,
            load_ohlcv=load_ohlcv,
            build_features=build_features,
            generate_signals=generate_signals,
        )

        self.assertEqual(payload["timeframe"], "4h")
        self.assertEqual(payload["symbol"], "BTC/USDT")
        self.assertEqual(payload["rows"], 2)
        self.assertEqual(payload["signalCount"], 1)
        self.assertEqual(payload["signals"][0]["module"], "breakout")
        self.assertEqual(payload["signals"][0]["direction"], "long")
        self.assertEqual(payload["latestBar"]["close"], 102.0)

    def test_builds_btc_pipeline_preview_with_risk_portfolio_and_delivery(self):
        from serve.signal_preview import get_btc_pipeline_preview

        bars = pd.DataFrame(
            {
                "Open": [99.0],
                "High": [101.0],
                "Low": [98.0],
                "Close": [100.0],
                "Volume": [10.0],
            },
            index=pd.date_range("2024-01-01", periods=1, freq="4h", tz="UTC"),
        )

        def build_features(frame):
            return frame

        def generate_signals(features, symbol):
            return [
                Signal(
                    module="breakout",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=88.0,
                    entry_reason="breakout",
                    invalidation="close back inside channel",
                    preferred_stop=90.0,
                    preferred_target=120.0,
                    confidence=0.88,
                    required_data=("ohlcv:4h",),
                )
            ]

        payload = get_btc_pipeline_preview(
            timeframe="4h",
            symbol="BTC/USDT",
            equity=10_000.0,
            load_ohlcv=lambda _: bars,
            build_features=build_features,
            generate_signals=generate_signals,
        )

        self.assertEqual(payload["signalCount"], 1)
        self.assertEqual(payload["riskDecisionCount"], 1)
        self.assertTrue(payload["riskDecisions"][0]["allowed"])
        self.assertEqual(payload["riskDecisions"][0]["stop_price"], 90.0)
        self.assertEqual(payload["orderCount"], 1)
        self.assertEqual(payload["orders"][0]["action"], "open")
        self.assertEqual(payload["deliveryCount"], 1)
        self.assertEqual(payload["deliveries"][0]["channel"], "dashboard")

    def test_btc_pipeline_preview_applies_default_market_spec_steps(self):
        from serve.signal_preview import get_btc_pipeline_preview

        bars = pd.DataFrame(
            {
                "Open": [99.0],
                "High": [101.0],
                "Low": [98.0],
                "Close": [100.0],
                "Volume": [10.0],
            },
            index=pd.date_range("2024-01-01", periods=1, freq="4h", tz="UTC"),
        )

        def generate_signals(features, symbol):
            return [
                Signal(
                    module="breakout",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=88.0,
                    entry_reason="breakout",
                    invalidation="close back inside channel",
                    preferred_stop=90.003,
                    preferred_target=120.006,
                    confidence=0.88,
                    required_data=("ohlcv:4h",),
                )
            ]

        payload = get_btc_pipeline_preview(
            timeframe="4h",
            symbol="BTC/USDT",
            equity=10_000.0,
            load_ohlcv=lambda _: bars,
            build_features=lambda frame: frame,
            generate_signals=generate_signals,
        )

        self.assertEqual(payload["riskDecisions"][0]["stop_price"], 90.003)
        self.assertEqual(payload["orders"][0]["quantity"], 20.006)
        self.assertEqual(payload["orders"][0]["entry_price"], 100.0)
        self.assertEqual(payload["orders"][0]["stop_price"], 90.0)
        self.assertEqual(payload["orders"][0]["target_price"], 120.0)

    def test_btc_market_spec_can_be_loaded_from_project_json_config(self):
        from serve import signal_preview

        records = [{
            "symbol": "BTC/USDT",
            "base": "BTC",
            "quote": "USDT",
            "exchange": "binance",
            "market_type": "swap",
            "tick_size": 0.01,
            "lot_size": 0.01,
            "fee_rate": 0.0005,
            "supports_short": True,
            "supports_leverage": True,
        }]
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "markets.json"
            path.write_text(json.dumps({"markets": records}), encoding="utf-8")
            original_path = signal_preview._MARKET_CATALOG_PATH
            try:
                signal_preview._MARKET_CATALOG_PATH = path
                market = signal_preview.build_btc_market_spec("BTC/USDT")
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_path

        self.assertEqual(market.tick_size, 0.01)
        self.assertEqual(market.lot_size, 0.01)
        self.assertEqual(market.fee_rate, 0.0005)

    def test_market_spec_resolution_is_not_btc_specific(self):
        from serve import signal_preview

        records = [{
            "symbol": "AAPL",
            "base": "AAPL",
            "quote": "USD",
            "exchange": "nasdaq",
            "market_type": "equity",
            "tick_size": 0.01,
            "lot_size": 0.001,
            "trading_session": "US_REGULAR",
            "supports_short": False,
            "supports_leverage": False,
        }]
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "markets.json"
            path.write_text(json.dumps({"markets": records}), encoding="utf-8")
            original_path = signal_preview._MARKET_CATALOG_PATH
            try:
                signal_preview._MARKET_CATALOG_PATH = path
                market = signal_preview.resolve_market_spec("AAPL", exchange="nasdaq", market_type="equity")
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_path

        self.assertEqual(market.asset.quote, "USD")
        self.assertEqual(market.trading_session, "US_REGULAR")
        self.assertFalse(market.supports_short)

    def test_regime_profile_resolution_is_not_btc_specific(self):
        from serve import signal_preview

        payload = {
            "default": {"trend_ema_length": 169},
            "profiles": [
                {
                    "exchange": "nasdaq",
                    "market_type": "equity",
                    "trend_ema_length": 50,
                    "weekly_rule": "1W-FRI",
                }
            ],
        }
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "regime_profiles.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            original_path = signal_preview._REGIME_PROFILE_PATH
            try:
                signal_preview._REGIME_PROFILE_PATH = path
                equity_market = signal_preview.resolve_market_spec("AAPL", exchange="nasdaq", market_type="equity")
                equity_profile = signal_preview.resolve_regime_profile(equity_market)
                btc_profile = signal_preview.resolve_regime_profile(
                    signal_preview.build_btc_market_spec("BTC/USDT")
                )
            finally:
                signal_preview._REGIME_PROFILE_PATH = original_path

        self.assertEqual(equity_profile.trend_ema_length, 50)
        self.assertEqual(equity_profile.weekly_rule, "1W-FRI")
        self.assertEqual(btc_profile.trend_ema_length, 169)

    def test_generic_research_preview_uses_configured_non_btc_market_and_regime_profile(self):
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [198.0],
                "High": [202.0],
                "Low": [197.0],
                "Close": [200.0],
                "Volume": [1000.0],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="1D", tz="UTC"),
        )
        market_records = [{
            "symbol": "AAPL",
            "base": "AAPL",
            "quote": "USD",
            "exchange": "nasdaq",
            "market_type": "equity",
            "tick_size": 0.01,
            "lot_size": 0.001,
            "trading_session": "US_REGULAR",
            "supports_short": False,
            "supports_leverage": False,
        }]
        regime_payload = {
            "default": {"trend_ema_length": 169},
            "profiles": [{
                "exchange": "nasdaq",
                "market_type": "equity",
                "trend_ema_length": 50,
                "weekly_rule": "1W-FRI",
            }],
        }

        def build_features(frame, market, regime_profile):
            self.assertEqual(market.market_key, "nasdaq:equity:AAPL")
            self.assertEqual(regime_profile.trend_ema_length, 50)
            return frame.assign(research_feature=[1.0])

        def generate_signals(features, symbol, market, regime_profile):
            self.assertEqual(symbol, "AAPL")
            self.assertEqual(market.trading_session, "US_REGULAR")
            self.assertEqual(regime_profile.weekly_rule, "1W-FRI")
            return [
                Signal(
                    module="research_short",
                    symbol=symbol,
                    direction=Direction.SHORT,
                    score=75.0,
                    entry_reason="research setup",
                    invalidation="close above stop",
                    preferred_stop=205.0,
                    preferred_target=190.0,
                    confidence=0.75,
                    required_data=("ohlcv:1d",),
                )
            ]

        with TemporaryDirectory() as tmpdir:
            market_path = Path(tmpdir) / "markets.json"
            regime_path = Path(tmpdir) / "regime_profiles.json"
            market_path.write_text(json.dumps({"markets": market_records}), encoding="utf-8")
            regime_path.write_text(json.dumps(regime_payload), encoding="utf-8")
            original_market_path = signal_preview._MARKET_CATALOG_PATH
            original_regime_path = signal_preview._REGIME_PROFILE_PATH
            try:
                signal_preview._MARKET_CATALOG_PATH = market_path
                signal_preview._REGIME_PROFILE_PATH = regime_path
                payload = signal_preview.get_signal_research_preview(
                    timeframe="1d",
                    symbol="AAPL",
                    exchange="nasdaq",
                    market_type="equity",
                    equity=10_000.0,
                    load_ohlcv=lambda timeframe, market: bars,
                    build_features=build_features,
                    generate_signals=generate_signals,
                )
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path
                signal_preview._REGIME_PROFILE_PATH = original_regime_path

        self.assertEqual(payload["symbol"], "AAPL")
        self.assertEqual(payload["market"]["exchange"], "nasdaq")
        self.assertEqual(payload["market"]["marketType"], "equity")
        self.assertFalse(payload["market"]["supportsShort"])
        self.assertEqual(payload["regimeProfile"]["trendEmaLength"], 50)
        self.assertEqual(payload["regimeProfile"]["weeklyRule"], "1W-FRI")
        self.assertEqual(payload["signalCount"], 1)
        self.assertEqual(payload["riskDecisionCount"], 1)
        self.assertFalse(payload["riskDecisions"][0]["allowed"])
        self.assertEqual(payload["riskDecisions"][0]["reason"], "short_not_supported")
        self.assertEqual(payload["orderCount"], 1)
        self.assertEqual(payload["orders"][0]["reason"], "risk_blocked:short_not_supported")

    def test_builds_btc_event_backtest_preview_from_standardized_signals(self):
        from serve.signal_preview import get_btc_event_backtest_preview

        bars = pd.DataFrame(
            {
                "Open": [99.0, 100.0, 109.0, 114.0],
                "High": [101.0, 106.0, 111.0, 116.0],
                "Low": [98.0, 99.0, 108.0, 113.0],
                "Close": [100.0, 105.0, 110.0, 115.0],
                "Volume": [10.0, 12.0, 14.0, 16.0],
            },
            index=pd.date_range("2024-01-01", periods=4, freq="4h", tz="UTC"),
        )

        def generate_signals(features, symbol):
            if len(features) != 2:
                return []
            close = float(features["Close"].iloc[-1])
            return [
                Signal(
                    module="breakout",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=88.0,
                    entry_reason="breakout",
                    invalidation="close back inside channel",
                    preferred_stop=close - 5.0,
                    preferred_target=close + 10.0,
                    confidence=0.88,
                    required_data=("ohlcv:4h",),
                )
            ]

        payload = get_btc_event_backtest_preview(
            timeframe="4h",
            symbol="BTC/USDT",
            equity=10_000.0,
            load_ohlcv=lambda _: bars,
            build_features=lambda frame: frame,
            generate_signals=generate_signals,
        )

        self.assertEqual(payload["rows"], 4)
        self.assertEqual(payload["stepCount"], 4)
        self.assertEqual(payload["tradeCount"], 1)
        self.assertEqual(payload["orderCount"], 2)
        self.assertEqual(payload["trades"][0]["module"], "breakout")
        self.assertEqual(payload["trades"][0]["exit_reason"], "target")
        self.assertAlmostEqual(payload["trades"][0]["gross_pnl"], 400.0)
        self.assertAlmostEqual(payload["summary"]["finalEquity"], 10_400.0)
        self.assertEqual(payload["attribution"]["bySymbol"]["BTC/USDT"]["tradeCount"], 1)
        self.assertEqual(payload["equityCurve"][-1]["equity"], 10_400.0)

    def test_compares_legacy_summary_with_event_backtest_preview(self):
        from serve.signal_preview import get_btc_migration_comparison_preview

        bars = pd.DataFrame(
            {
                "Open": [99.0, 100.0, 109.0, 114.0],
                "High": [101.0, 106.0, 111.0, 116.0],
                "Low": [98.0, 99.0, 108.0, 113.0],
                "Close": [100.0, 105.0, 110.0, 115.0],
                "Volume": [10.0, 12.0, 14.0, 16.0],
            },
            index=pd.date_range("2024-01-01", periods=4, freq="4h", tz="UTC"),
        )
        legacy_trades = pd.DataFrame({"pnl": [120.0, -20.0]})

        def generate_signals(features, symbol):
            if len(features) != 2:
                return []
            close = float(features["Close"].iloc[-1])
            return [
                Signal(
                    module="breakout",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=88.0,
                    entry_reason="breakout",
                    invalidation="close back inside channel",
                    preferred_stop=close - 5.0,
                    preferred_target=close + 10.0,
                    confidence=0.88,
                )
            ]

        payload = get_btc_migration_comparison_preview(
            timeframe="4h",
            symbol="BTC/USDT",
            equity=10_000.0,
            load_ohlcv=lambda _: bars,
            build_features=lambda frame: frame,
            generate_signals=generate_signals,
            load_trade_log=lambda: legacy_trades,
            load_legacy_summary=lambda: {
                "total_trades": 2,
                "total_pnl": 100.0,
                "final_equity": 10_100.0,
                "win_rate_pct": 50.0,
            },
        )

        self.assertEqual(payload["legacy"]["tradeCount"], 2)
        self.assertEqual(payload["legacy"]["sourceTradeRows"], 2)
        self.assertEqual(payload["event"]["tradeCount"], 1)
        self.assertAlmostEqual(payload["event"]["realizedPnl"], 400.0)
        self.assertAlmostEqual(payload["event"]["winRatePct"], 100.0)
        self.assertEqual(payload["delta"]["tradeCount"], -1)
        self.assertAlmostEqual(payload["delta"]["totalPnl"], 300.0)
        self.assertAlmostEqual(payload["delta"]["finalEquity"], 300.0)
        self.assertAlmostEqual(payload["delta"]["winRatePct"], 50.0)


if __name__ == "__main__":
    unittest.main()
