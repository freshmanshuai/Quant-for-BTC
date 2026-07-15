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
        self.assertEqual(payload["riskDiagnostics"]["portfolio"]["used"], 200.0)
        self.assertEqual(payload["riskDiagnostics"]["portfolio"]["budget"], 600.0)
        self.assertEqual(payload["riskDiagnostics"]["portfolio"]["remaining"], 400.0)
        self.assertEqual(payload["riskDiagnostics"]["symbols"]["BTC/USDT"]["used"], 200.0)
        self.assertEqual(payload["riskDiagnostics"]["modules"]["breakout"]["used"], 200.0)

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

    def test_btc_latest_signal_snapshot_reuses_standardized_pipeline_payload(self):
        from serve.signal_preview import get_btc_latest_signal_snapshot

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
                    preferred_stop=90.0,
                    preferred_target=120.0,
                    confidence=0.88,
                    required_data=("ohlcv:4h",),
                )
            ]

        payload = get_btc_latest_signal_snapshot(
            timeframe="4h",
            symbol="BTC/USDT",
            equity=10_000.0,
            load_ohlcv=lambda _: bars,
            build_features=lambda frame: frame,
            generate_signals=generate_signals,
        )

        self.assertEqual(payload["mode"], "latest")
        self.assertTrue(payload["readOnly"])
        self.assertEqual(payload["signalCount"], 1)
        self.assertEqual(payload["riskDecisionCount"], 1)
        self.assertEqual(payload["orderCount"], 1)
        self.assertEqual(payload["signals"][0]["module"], "breakout")
        self.assertTrue(payload["riskDecisions"][0]["allowed"])
        self.assertEqual(payload["orders"][0]["action"], "open")
        self.assertEqual(payload["riskDiagnostics"]["portfolio"]["used"], 200.0)

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
            "session_timezone": "America/New_York",
            "session_open": "09:30",
            "session_close": "16:00",
            "trading_days": ["mon", "tue", "wed", "thu", "fri"],
            "correlation_group": "us_equity_beta",
            "max_leverage": 2.0,
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
        self.assertEqual(market.session_timezone, "America/New_York")
        self.assertEqual(market.session_open, "09:30")
        self.assertEqual(market.session_close, "16:00")
        self.assertEqual(market.trading_days, ("mon", "tue", "wed", "thu", "fri"))
        self.assertFalse(market.supports_short)

    def test_market_options_include_structured_session_metadata(self):
        from serve import signal_preview

        records = [{
            "symbol": "AAPL",
            "base": "AAPL",
            "quote": "USD",
            "exchange": "nasdaq",
            "market_type": "equity",
            "trading_session": "US_REGULAR",
            "session_timezone": "America/New_York",
            "session_open": "09:30",
            "session_close": "16:00",
            "trading_days": ["mon", "tue", "wed", "thu", "fri"],
            "correlation_group": "us_equity_beta",
            "max_leverage": 2.0,
            "supports_short": False,
            "supports_leverage": False,
        }]
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "markets.json"
            path.write_text(json.dumps({"markets": records}), encoding="utf-8")
            original_path = signal_preview._MARKET_CATALOG_PATH
            try:
                signal_preview._MARKET_CATALOG_PATH = path
                payload = signal_preview.get_signal_market_options()
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_path

        market = payload["markets"][0]
        self.assertEqual(market["tradingSession"], "US_REGULAR")
        self.assertEqual(market["sessionTimezone"], "America/New_York")
        self.assertEqual(market["sessionOpen"], "09:30")
        self.assertEqual(market["sessionClose"], "16:00")
        self.assertEqual(market["tradingDays"], ["mon", "tue", "wed", "thu", "fri"])
        self.assertEqual(market["correlationGroup"], "us_equity_beta")
        self.assertEqual(market["maxLeverage"], 2.0)

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
                "high_vol_atr_pct": 0.0,
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
        self.assertEqual(payload["latestRegime"]["value"], 4)
        self.assertEqual(payload["latestRegime"]["label"], "high_risk")
        self.assertEqual(payload["latestRegime"]["time"], "2026-06-03T00:00:00+00:00")
        self.assertEqual(payload["signalCount"], 1)
        self.assertEqual(payload["riskDecisionCount"], 1)
        self.assertFalse(payload["riskDecisions"][0]["allowed"])
        self.assertEqual(payload["riskDecisions"][0]["reason"], "short_not_supported")
        self.assertEqual(payload["orderCount"], 1)
        self.assertEqual(payload["orders"][0]["reason"], "risk_blocked:short_not_supported")

    def test_generic_research_preview_applies_configured_market_type_risk_limit(self):
        from serve import signal_preview
        from quant_platform.risk import RiskLimits

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
            "supports_short": True,
            "supports_leverage": False,
        }]

        def generate_signals(features, symbol, market, regime_profile):
            return [
                Signal(
                    module="research_long",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=75.0,
                    entry_reason="research setup",
                    invalidation="close below stop",
                    preferred_stop=190.0,
                    preferred_target=220.0,
                    confidence=0.75,
                )
            ]

        with TemporaryDirectory() as tmpdir:
            market_path = Path(tmpdir) / "markets.json"
            market_path.write_text(json.dumps({"markets": market_records}), encoding="utf-8")
            original_market_path = signal_preview._MARKET_CATALOG_PATH
            try:
                signal_preview._MARKET_CATALOG_PATH = market_path
                payload = signal_preview.get_signal_research_preview(
                    timeframe="1d",
                    symbol="AAPL",
                    exchange="nasdaq",
                    market_type="equity",
                    equity=10_000.0,
                    load_ohlcv=lambda timeframe, market: bars,
                    build_features=lambda frame, market, regime_profile: frame,
                    generate_signals=generate_signals,
                    risk_limits=RiskLimits(max_market_type_risk=0.01),
                )
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path

        self.assertEqual(payload["riskDecisionCount"], 1)
        self.assertFalse(payload["riskDecisions"][0]["allowed"])
        self.assertEqual(payload["riskDecisions"][0]["reason"], "market_type_risk_budget_exhausted")

    def test_generic_research_preview_defaults_to_cached_feature_engine_output(self):
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [99.0, 100.0, 101.0, 102.0, 103.0],
                "High": [101.0, 102.0, 103.0, 104.0, 105.0],
                "Low": [98.0, 99.0, 100.0, 101.0, 102.0],
                "Close": [100.0, 101.0, 102.0, 103.0, 104.0],
                "Volume": [1000.0, 1100.0, 1050.0, 1200.0, 1300.0],
            },
            index=pd.date_range("2026-06-01", periods=5, freq="D", tz="UTC"),
        )
        market_records = [{
            "symbol": "AAPL",
            "base": "AAPL",
            "quote": "USD",
            "exchange": "nasdaq",
            "market_type": "equity",
            "tick_size": 0.01,
            "lot_size": 0.001,
            "supports_short": False,
            "supports_leverage": False,
        }]
        regime_payload = {
            "default": {"trend_ema_length": 169},
            "profiles": [{
                "exchange": "nasdaq",
                "market_type": "equity",
                "trend_ema_length": 50,
            }],
        }
        calls = {}

        class FakeStore:
            def __init__(self, root):
                calls["parquet_store_root"] = Path(root)

            def write(self, series_id, features):
                calls["series_id"] = series_id
                calls["features"] = features.copy()
                return calls["parquet_store_root"] / "feature_engine" / "nasdaq" / "equity" / "AAPL" / "1d" / "research_default_v1_ema50_atr14_adx14_bb20x2.parquet"

        class FakeSQLiteStore:
            def __init__(self, root):
                calls["sqlite_store_root"] = Path(root)

            def write(self, series_id, features):
                calls["series_id"] = series_id
                calls["features"] = features.copy()
                return calls["sqlite_store_root"] / "feature_engine" / "nasdaq" / "equity" / "AAPL" / "1d" / "research_default_v1_ema50_atr14_adx14_bb20x2.sqlite"

        observed = {}

        def generate_signals(features, symbol, market, regime_profile):
            observed["columns"] = list(features.columns)
            return []

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            market_path = root / "markets.json"
            regime_path = root / "regime_profiles.json"
            data_source_path = root / "research_data_sources.json"
            market_path.write_text(json.dumps({"markets": market_records}), encoding="utf-8")
            regime_path.write_text(json.dumps(regime_payload), encoding="utf-8")
            data_source_path.write_text(json.dumps({"feature_store_type": "sqlite"}), encoding="utf-8")
            original_market_path = signal_preview._MARKET_CATALOG_PATH
            original_regime_path = signal_preview._REGIME_PROFILE_PATH
            original_data_source_path = signal_preview._RESEARCH_DATA_SOURCE_PATH
            original_root = signal_preview._PROJECT_ROOT
            original_store = signal_preview.ParquetFeatureStore
            original_sqlite_store = signal_preview.SQLiteFeatureStore
            try:
                signal_preview._MARKET_CATALOG_PATH = market_path
                signal_preview._REGIME_PROFILE_PATH = regime_path
                signal_preview._RESEARCH_DATA_SOURCE_PATH = data_source_path
                signal_preview._PROJECT_ROOT = root
                signal_preview.ParquetFeatureStore = FakeStore
                signal_preview.SQLiteFeatureStore = FakeSQLiteStore
                payload = signal_preview.get_signal_research_preview(
                    timeframe="1d",
                    symbol="AAPL",
                    exchange="nasdaq",
                    market_type="equity",
                    equity=10_000.0,
                    load_ohlcv=lambda timeframe, market: bars,
                    generate_signals=generate_signals,
                )
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path
                signal_preview._REGIME_PROFILE_PATH = original_regime_path
                signal_preview._RESEARCH_DATA_SOURCE_PATH = original_data_source_path
                signal_preview._PROJECT_ROOT = original_root
                signal_preview.ParquetFeatureStore = original_store
                signal_preview.SQLiteFeatureStore = original_sqlite_store

        self.assertEqual(payload["rows"], 5)
        self.assertEqual(calls["series_id"].cache_key, "feature_engine/nasdaq/equity/AAPL/1d/research_default_v1_ema50_atr14_adx14_bb20x2")
        self.assertNotIn("parquet_store_root", calls)
        self.assertEqual(calls["sqlite_store_root"], root / "data" / "research_features")
        self.assertTrue(payload["featureCache"]["path"].endswith(".sqlite"))
        self.assertIn("ema50", calls["features"].columns)
        self.assertIn("donchian_high_20", calls["features"].columns)
        self.assertIn("ema50", observed["columns"])

    def test_default_research_feature_builder_uses_configured_feature_modules(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.regimes import RegimeProfile
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [99.0, 100.0, 101.0, 102.0, 103.0],
                "High": [101.0, 102.0, 103.0, 104.0, 105.0],
                "Low": [98.0, 99.0, 100.0, 101.0, 102.0],
                "Close": [100.0, 101.0, 102.0, 103.0, 104.0],
                "Volume": [1000.0, 1100.0, 1050.0, 1200.0, 1300.0],
            },
            index=pd.date_range("2026-06-01", periods=5, freq="D", tz="UTC"),
        )
        market = MarketSpec(
            asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
        )
        feature_module_payload = {
            "default_module_set": "research_default",
            "module_sets": [{
                "name": "research_default",
                "modules": [
                    {
                        "type": "technical_indicators",
                        "params": {"ema_lengths": ["$regime.trend_ema_length"]},
                    },
                    {"type": "donchian", "params": {"channel_periods": {"fast": 3}}},
                    {"type": "price_action"},
                ],
            }],
        }

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            feature_module_path = root / "research_feature_modules.json"
            feature_module_path.write_text(json.dumps(feature_module_payload), encoding="utf-8")
            original_feature_module_path = getattr(signal_preview, "_RESEARCH_FEATURE_MODULE_PATH", None)
            original_store = signal_preview.ParquetFeatureStore

            class FakeStore:
                def __init__(self, root):
                    pass

                def write(self, series_id, features):
                    return root / "features.parquet"

            try:
                signal_preview._RESEARCH_FEATURE_MODULE_PATH = feature_module_path
                signal_preview.ParquetFeatureStore = FakeStore
                features = signal_preview._default_research_feature_builder(
                    bars,
                    market,
                    RegimeProfile(trend_ema_length=50),
                    timeframe="1d",
                )
            finally:
                if original_feature_module_path is None:
                    delattr(signal_preview, "_RESEARCH_FEATURE_MODULE_PATH")
                else:
                    signal_preview._RESEARCH_FEATURE_MODULE_PATH = original_feature_module_path
                signal_preview.ParquetFeatureStore = original_store

        self.assertIn("ema50", features.columns)
        self.assertIn("fast_high_3", features.columns)
        self.assertNotIn("donchian_high_20", features.columns)

    def test_default_research_feature_cache_key_includes_profile_feature_parameters(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.regimes import RegimeProfile
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [99.0, 100.0],
                "High": [101.0, 102.0],
                "Low": [98.0, 99.0],
                "Close": [100.0, 101.0],
                "Volume": [1000.0, 1100.0],
            },
            index=pd.date_range("2026-06-01", periods=2, freq="D", tz="UTC"),
        )
        market = MarketSpec(
            asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
        )
        cache_keys = []

        class FeatureResult:
            def __init__(self, features):
                self.features = features
                self.cache = {"hit": False}

        def fake_run_feature_engine_with_cache(engine, frame, *, series_id, store=None, refresh=False):
            cache_keys.append(series_id.cache_key)
            return FeatureResult(frame)

        original_run = signal_preview.run_feature_engine_with_cache
        try:
            signal_preview.run_feature_engine_with_cache = fake_run_feature_engine_with_cache
            signal_preview._default_research_feature_builder(
                bars,
                market,
                RegimeProfile(trend_ema_length=50),
                timeframe="1d",
            )
            signal_preview._default_research_feature_builder(
                bars,
                market,
                RegimeProfile(trend_ema_length=169),
                timeframe="1d",
            )
        finally:
            signal_preview.run_feature_engine_with_cache = original_run

        self.assertEqual(cache_keys[0], "feature_engine/nasdaq/equity/AAPL/1d/research_default_v1_ema50_atr14_adx14_bb20x2")
        self.assertEqual(cache_keys[1], "feature_engine/nasdaq/equity/AAPL/1d/research_default_v1_ema169_atr14_adx14_bb20x2")
        self.assertNotEqual(cache_keys[0], cache_keys[1])

    def test_default_research_feature_cache_key_includes_turnover_schema(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.regimes import RegimeProfile
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [99.0, 100.0],
                "High": [101.0, 102.0],
                "Low": [98.0, 99.0],
                "Close": [100.0, 101.0],
                "Volume": [1000.0, 1100.0],
            },
            index=pd.date_range("2026-06-01", periods=2, freq="D", tz="UTC"),
        )
        turnover_bars = bars.assign(Turnover=bars["Close"] * bars["Volume"])
        market = MarketSpec(
            asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
        )
        cache_keys = []

        class FeatureResult:
            def __init__(self, features):
                self.features = features
                self.cache = {"hit": False}

        def fake_run_feature_engine_with_cache(engine, frame, *, series_id, store=None, refresh=False):
            cache_keys.append(series_id.cache_key)
            return FeatureResult(frame)

        original_run = signal_preview.run_feature_engine_with_cache
        try:
            signal_preview.run_feature_engine_with_cache = fake_run_feature_engine_with_cache
            signal_preview._default_research_feature_builder(
                bars,
                market,
                RegimeProfile(trend_ema_length=50),
                timeframe="1d",
            )
            signal_preview._default_research_feature_builder(
                turnover_bars,
                market,
                RegimeProfile(trend_ema_length=50),
                timeframe="1d",
            )
        finally:
            signal_preview.run_feature_engine_with_cache = original_run

        self.assertEqual(cache_keys[0], "feature_engine/nasdaq/equity/AAPL/1d/research_default_v1_ema50_atr14_adx14_bb20x2")
        self.assertEqual(cache_keys[1], "feature_engine/nasdaq/equity/AAPL/1d/research_default_v1_ema50_atr14_adx14_bb20x2_turnover")
        self.assertNotEqual(cache_keys[0], cache_keys[1])

    def test_default_research_feature_builder_uses_profile_volatility_and_bollinger_parameters(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.regimes import RegimeProfile
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [99.0, 100.0, 101.0, 102.0, 103.0],
                "High": [101.0, 102.0, 103.0, 104.0, 105.0],
                "Low": [98.0, 99.0, 100.0, 101.0, 102.0],
                "Close": [100.0, 101.0, 102.0, 103.0, 104.0],
                "Volume": [1000.0, 1100.0, 1050.0, 1200.0, 1300.0],
            },
            index=pd.date_range("2026-06-01", periods=5, freq="D", tz="UTC"),
        )
        market = MarketSpec(
            asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
        )
        calls = {}

        class FakeStore:
            def __init__(self, root):
                calls["store_root"] = Path(root)

            def read(self, series_id):
                raise FileNotFoundError(series_id.cache_key)

            def write(self, series_id, features):
                calls["series_id"] = series_id
                calls["features"] = features.copy()
                return Path("features") / f"{series_id.feature_set}.parquet"

        original_store = signal_preview.ParquetFeatureStore
        try:
            signal_preview.ParquetFeatureStore = FakeStore
            result = signal_preview._default_research_feature_builder(
                bars,
                market,
                RegimeProfile(
                    trend_ema_length=50,
                    atr_period=10,
                    adx_period=21,
                    bb_period=30,
                    bb_std_mult=2.5,
                    regime_lookback=40,
                ),
                timeframe="1d",
                refresh=True,
            )
        finally:
            signal_preview.ParquetFeatureStore = original_store

        self.assertEqual(
            calls["series_id"].cache_key,
            "feature_engine/nasdaq/equity/AAPL/1d/research_default_v1_ema50_atr10_adx21_bb30x2p5",
        )
        for col in ["ema50", "_atr_10", "_atr_pct_10", "_adx_21", "bb_upper_30", "bb_lower_30"]:
            self.assertIn(col, result.columns)
            self.assertIn(col, calls["features"].columns)
        self.assertNotIn("_atr_14", result.columns)
        self.assertNotIn("_adx_14", result.columns)
        self.assertNotIn("bb_upper_20", result.columns)

    def test_generic_research_preview_can_refresh_cached_feature_engine_output(self):
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [99.0, 100.0],
                "High": [101.0, 102.0],
                "Low": [98.0, 99.0],
                "Close": [100.0, 101.0],
                "Volume": [1000.0, 1100.0],
            },
            index=pd.date_range("2026-06-01", periods=2, freq="D", tz="UTC"),
        )
        market_records = [{
            "symbol": "AAPL",
            "base": "AAPL",
            "quote": "USD",
            "exchange": "nasdaq",
            "market_type": "equity",
            "tick_size": 0.01,
            "lot_size": 0.001,
            "supports_short": False,
            "supports_leverage": False,
        }]
        regime_payload = {"default": {"trend_ema_length": 50}}
        calls = {}

        class FeatureResult:
            def __init__(self, features):
                self.features = features
                self.cache = {"hit": False}

        def fake_run_feature_engine_with_cache(engine, frame, *, series_id, store=None, refresh=False):
            calls["refresh"] = refresh
            calls["series_id"] = series_id
            return FeatureResult(frame.assign(refreshed_feature=[1.0, 1.0]))

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            market_path = root / "markets.json"
            regime_path = root / "regime_profiles.json"
            market_path.write_text(json.dumps({"markets": market_records}), encoding="utf-8")
            regime_path.write_text(json.dumps(regime_payload), encoding="utf-8")
            original_market_path = signal_preview._MARKET_CATALOG_PATH
            original_regime_path = signal_preview._REGIME_PROFILE_PATH
            original_run = signal_preview.run_feature_engine_with_cache
            try:
                signal_preview._MARKET_CATALOG_PATH = market_path
                signal_preview._REGIME_PROFILE_PATH = regime_path
                signal_preview.run_feature_engine_with_cache = fake_run_feature_engine_with_cache
                payload = signal_preview.get_signal_research_preview(
                    timeframe="1d",
                    symbol="AAPL",
                    exchange="nasdaq",
                    market_type="equity",
                    equity=10_000.0,
                    load_ohlcv=lambda timeframe, market: bars,
                    generate_signals=lambda features, symbol, market, regime_profile: [],
                    refresh_features=True,
                )
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path
                signal_preview._REGIME_PROFILE_PATH = original_regime_path
                signal_preview.run_feature_engine_with_cache = original_run

        self.assertEqual(payload["rows"], 2)
        self.assertTrue(calls["refresh"])
        self.assertEqual(calls["series_id"].cache_key, "feature_engine/nasdaq/equity/AAPL/1d/research_default_v1_ema50_atr14_adx14_bb20x2")
        self.assertEqual(payload["featureCache"], {"hit": False})

    def test_generic_research_preview_can_refresh_research_bar_cache(self):
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [99.0],
                "High": [101.0],
                "Low": [98.0],
                "Close": [100.0],
                "Volume": [1000.0],
            },
            index=pd.date_range("2026-06-01", periods=1, freq="D", tz="UTC"),
        )
        market_records = [{
            "symbol": "AAPL",
            "base": "AAPL",
            "quote": "USD",
            "exchange": "nasdaq",
            "market_type": "equity",
            "tick_size": 0.01,
            "lot_size": 0.001,
            "supports_short": False,
            "supports_leverage": False,
        }]
        regime_payload = {"default": {"trend_ema_length": 50}}
        calls = {}

        def load_research_preview_bars(timeframe, market, *, refresh=False):
            calls["timeframe"] = timeframe
            calls["market"] = market
            calls["refresh"] = refresh
            return bars

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            market_path = root / "markets.json"
            regime_path = root / "regime_profiles.json"
            market_path.write_text(json.dumps({"markets": market_records}), encoding="utf-8")
            regime_path.write_text(json.dumps(regime_payload), encoding="utf-8")
            original_market_path = signal_preview._MARKET_CATALOG_PATH
            original_regime_path = signal_preview._REGIME_PROFILE_PATH
            original_loader = signal_preview.load_research_preview_bars
            try:
                signal_preview._MARKET_CATALOG_PATH = market_path
                signal_preview._REGIME_PROFILE_PATH = regime_path
                signal_preview.load_research_preview_bars = load_research_preview_bars
                payload = signal_preview.get_signal_research_preview(
                    timeframe="1d",
                    symbol="AAPL",
                    exchange="nasdaq",
                    market_type="equity",
                    equity=10_000.0,
                    build_features=lambda frame, market, regime_profile: frame,
                    generate_signals=lambda features, symbol, market, regime_profile: [],
                    refresh_bars=True,
                )
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path
                signal_preview._REGIME_PROFILE_PATH = original_regime_path
                signal_preview.load_research_preview_bars = original_loader

        self.assertEqual(payload["rows"], 1)
        self.assertEqual(calls["timeframe"], "1d")
        self.assertEqual(calls["market"].market_key, "nasdaq:equity:AAPL")
        self.assertTrue(calls["refresh"])

    def test_generic_research_event_backtest_preview_runs_non_btc_market(self):
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [99.0, 100.0, 109.0, 114.0],
                "High": [101.0, 106.0, 111.0, 116.0],
                "Low": [98.0, 99.0, 108.0, 113.0],
                "Close": [100.0, 105.0, 110.0, 115.0],
                "Volume": [1000.0, 1200.0, 1400.0, 1600.0],
            },
            index=pd.date_range("2026-06-03", periods=4, freq="1D", tz="UTC"),
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
                "high_vol_atr_pct": 0.0,
            }],
        }

        def build_features(frame, market, regime_profile):
            self.assertEqual(market.market_key, "nasdaq:equity:AAPL")
            self.assertEqual(regime_profile.weekly_rule, "1W-FRI")
            return frame.assign(research_feature=[1.0, 1.0, 1.0, 1.0])

        def generate_signals(features, symbol, market, regime_profile):
            self.assertEqual(symbol, "AAPL")
            self.assertEqual(market.trading_session, "US_REGULAR")
            self.assertEqual(regime_profile.trend_ema_length, 50)
            if len(features) != 2:
                return []
            close = float(features["Close"].iloc[-1])
            return [
                Signal(
                    module="research_breakout",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=80.0,
                    entry_reason="research breakout",
                    invalidation="close below stop",
                    preferred_stop=close - 5.0,
                    preferred_target=close + 10.0,
                    confidence=0.8,
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
                payload = signal_preview.get_signal_research_event_backtest_preview(
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
        self.assertEqual(payload["regimeProfile"]["trendEmaLength"], 50)
        self.assertEqual(payload["latestRegime"]["value"], 4)
        self.assertEqual(payload["latestRegime"]["label"], "high_risk")
        self.assertEqual(payload["latestRegime"]["time"], "2026-06-06T00:00:00+00:00")
        self.assertEqual(payload["rows"], 4)
        self.assertEqual(payload["stepCount"], 4)
        self.assertEqual(payload["signalCount"], 1)
        self.assertEqual(payload["orderCount"], 2)
        self.assertEqual(payload["tradeCount"], 1)
        self.assertEqual(payload["orders"][0]["symbol"], "AAPL")
        self.assertEqual(payload["orders"][0]["module"], "research_breakout")
        self.assertEqual(payload["orderStatusCounts"]["filled"], 1)
        self.assertEqual(payload["orderStatusCounts"]["submitted"], 0)
        self.assertEqual(payload["trades"][0]["symbol"], "AAPL")
        self.assertEqual(payload["trades"][0]["module"], "research_breakout")
        self.assertEqual(payload["trades"][0]["exit_reason"], "target")
        self.assertAlmostEqual(payload["summary"]["finalEquity"], 10_400.0)
        self.assertEqual(payload["attribution"]["bySymbol"]["AAPL"]["tradeCount"], 1)
        self.assertEqual(len(payload["equityCurve"]), 4)
        self.assertEqual(len(payload["exposureCurve"]), 4)
        self.assertEqual(payload["exposureCurve"][1]["positionCount"], 1)
        self.assertEqual(payload["latestBar"]["close"], 115.0)

    def test_generic_research_event_backtest_preview_exposes_open_order_ages(self):
        from quant_platform.backtest import BacktestExecutionConfig
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [99.0, 100.0, 104.0, 104.0],
                "High": [101.0, 104.0, 104.0, 104.0],
                "Low": [98.0, 103.0, 103.0, 103.0],
                "Close": [100.0, 105.0, 104.0, 104.0],
                "Volume": [1000.0, 1200.0, 1400.0, 1600.0],
            },
            index=pd.date_range("2026-06-03", periods=4, freq="1D", tz="UTC"),
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
            "profiles": [{"exchange": "nasdaq", "market_type": "equity", "trend_ema_length": 50}],
        }

        def generate_signals(features, symbol, market, regime_profile):
            if len(features) != 2:
                return []
            close = float(features["Close"].iloc[-1])
            return [
                Signal(
                    module="research_breakout",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=80.0,
                    entry_reason="research breakout",
                    invalidation="close below stop",
                    preferred_stop=close - 5.0,
                    preferred_target=close + 10.0,
                    confidence=0.8,
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
                payload = signal_preview.get_signal_research_event_backtest_preview(
                    timeframe="1d",
                    symbol="AAPL",
                    exchange="nasdaq",
                    market_type="equity",
                    equity=10_000.0,
                    load_ohlcv=lambda timeframe, market: bars,
                    build_features=lambda frame, market, regime_profile: frame,
                    generate_signals=generate_signals,
                    execution=BacktestExecutionConfig(intrabar_entry_limit=True),
                )
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path
                signal_preview._REGIME_PROFILE_PATH = original_regime_path

        self.assertEqual(payload["filledOrderCount"], 0)
        self.assertEqual(payload["terminalOrderCount"], 0)
        self.assertEqual(payload["orderStatusCounts"]["submitted"], 1)
        self.assertEqual(payload["orderLifecycleSummary"]["totalOrderCount"], 1)
        self.assertEqual(payload["orderLifecycleSummary"]["openCount"], 1)
        self.assertEqual(payload["orderLifecycleSummary"]["resolvedCount"], 0)
        self.assertAlmostEqual(payload["orderLifecycleSummary"]["openRate"], 1.0)
        self.assertAlmostEqual(payload["orderLifecycleSummary"]["fillRate"], 0.0)
        self.assertEqual(payload["openOrderAgeSummary"]["openCount"], 1)
        self.assertEqual(payload["openOrderAgeSummary"]["submittedCount"], 1)
        self.assertAlmostEqual(payload["openOrderAgeSummary"]["averageAgeBars"], 2.0)
        self.assertEqual(payload["openOrderAgeSummary"]["maxAgeBars"], 2)
        self.assertEqual(payload["openOrderAges"][0]["status"], "submitted")
        self.assertEqual(payload["openOrderAges"][0]["ageBars"], 2)
        self.assertEqual(payload["openOrderAges"][0]["submittedBarIndex"], 1)
        self.assertEqual(payload["openOrderAges"][0]["currentBarIndex"], 3)

    def test_generic_research_event_backtest_preview_exposes_terminal_orders(self):
        from quant_platform.backtest import BacktestExecutionConfig
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [99.0, 100.0, 104.0, 104.0],
                "High": [101.0, 104.0, 104.0, 104.0],
                "Low": [98.0, 103.0, 103.0, 103.0],
                "Close": [100.0, 105.0, 104.0, 104.0],
                "Volume": [1000.0, 1200.0, 1400.0, 1600.0],
            },
            index=pd.date_range("2026-06-03", periods=4, freq="1D", tz="UTC"),
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
            "profiles": [{"exchange": "nasdaq", "market_type": "equity", "trend_ema_length": 50}],
        }

        def generate_signals(features, symbol, market, regime_profile):
            if len(features) != 2:
                return []
            close = float(features["Close"].iloc[-1])
            return [
                Signal(
                    module="research_breakout",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=80.0,
                    entry_reason="research breakout",
                    invalidation="close below stop",
                    preferred_stop=close - 5.0,
                    preferred_target=close + 10.0,
                    confidence=0.8,
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
                payload = signal_preview.get_signal_research_event_backtest_preview(
                    timeframe="1d",
                    symbol="AAPL",
                    exchange="nasdaq",
                    market_type="equity",
                    equity=10_000.0,
                    load_ohlcv=lambda timeframe, market: bars,
                    build_features=lambda frame, market, regime_profile: frame,
                    generate_signals=generate_signals,
                    execution=BacktestExecutionConfig(
                        intrabar_entry_limit=True,
                        max_entry_order_age_bars=1,
                    ),
                )
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path
                signal_preview._REGIME_PROFILE_PATH = original_regime_path

        self.assertEqual(payload["filledOrderCount"], 0)
        self.assertEqual(payload["terminalOrderCount"], 1)
        self.assertEqual(payload["terminalOrderReasonCounts"], {"entry_order_expired": 1})
        self.assertEqual(payload["terminalOrders"][0]["status"], "canceled")
        self.assertEqual(payload["terminalOrders"][0]["reason"], "entry_order_expired")
        self.assertEqual(payload["orderActionCounts"]["open"], 1)
        self.assertEqual(payload["orderActionCounts"]["close"], 0)
        self.assertEqual(payload["orderModuleCounts"], {"research_breakout": 1})
        self.assertEqual(payload["orderSymbolCounts"], {"AAPL": 1})
        self.assertEqual(payload["orderLayerCounts"], {"tactical": 1})
        self.assertEqual(payload["orderLatencySummary"]["resolvedCount"], 1)
        self.assertAlmostEqual(payload["orderLatencySummary"]["averageWaitBars"], 2.0)
        self.assertEqual(payload["orderLatencySummary"]["maxWaitBars"], 2)
        self.assertEqual(payload["orderLatency"][0]["status"], "canceled")
        self.assertEqual(payload["orderLatency"][0]["waitBars"], 2)
        self.assertEqual(payload["orderStatusCounts"]["canceled"], 1)
        self.assertEqual(payload["orderStatusCounts"]["submitted"], 0)
        self.assertEqual(payload["orderLifecycleSummary"]["totalOrderCount"], 1)
        self.assertEqual(payload["orderLifecycleSummary"]["terminalCount"], 1)
        self.assertEqual(payload["orderLifecycleSummary"]["canceledCount"], 1)
        self.assertAlmostEqual(payload["orderLifecycleSummary"]["terminalRate"], 1.0)
        self.assertEqual(payload["orderLifecycleByAction"]["open"]["totalOrderCount"], 1)
        self.assertEqual(payload["orderLifecycleByAction"]["open"]["terminalCount"], 1)
        self.assertEqual(payload["orderLifecycleByAction"]["open"]["canceledCount"], 1)
        self.assertAlmostEqual(payload["orderLifecycleByAction"]["open"]["terminalRate"], 1.0)
        self.assertEqual(payload["orderLifecycleByAction"]["close"]["totalOrderCount"], 0)
        self.assertAlmostEqual(payload["orderLifecycleByAction"]["close"]["fillRate"], 0.0)
        self.assertEqual(payload["orderLifecycleByModule"]["research_breakout"]["totalOrderCount"], 1)
        self.assertEqual(payload["orderLifecycleByModule"]["research_breakout"]["terminalCount"], 1)
        self.assertEqual(payload["orderLifecycleByModule"]["research_breakout"]["canceledCount"], 1)
        self.assertAlmostEqual(payload["orderLifecycleByModule"]["research_breakout"]["terminalRate"], 1.0)
        self.assertEqual(payload["orderLifecycleBySymbol"]["AAPL"]["totalOrderCount"], 1)
        self.assertEqual(payload["orderLifecycleBySymbol"]["AAPL"]["terminalCount"], 1)
        self.assertEqual(payload["orderLifecycleBySymbol"]["AAPL"]["canceledCount"], 1)
        self.assertAlmostEqual(payload["orderLifecycleBySymbol"]["AAPL"]["terminalRate"], 1.0)
        self.assertEqual(payload["orderLifecycleByLayer"]["tactical"]["totalOrderCount"], 1)
        self.assertEqual(payload["orderLifecycleByLayer"]["tactical"]["terminalCount"], 1)
        self.assertEqual(payload["orderLifecycleByLayer"]["tactical"]["canceledCount"], 1)
        self.assertAlmostEqual(payload["orderLifecycleByLayer"]["tactical"]["terminalRate"], 1.0)
        self.assertEqual(payload["orderLifecycleByDirection"]["long"]["totalOrderCount"], 1)
        self.assertEqual(payload["orderLifecycleByDirection"]["long"]["terminalCount"], 1)
        self.assertEqual(payload["orderLifecycleByDirection"]["long"]["canceledCount"], 1)
        self.assertAlmostEqual(payload["orderLifecycleByDirection"]["long"]["terminalRate"], 1.0)
        self.assertEqual(payload["tradeCount"], 0)
        self.assertEqual(payload["exposureCurve"][-1]["positionCount"], 0)

    def test_generic_research_event_backtest_preview_exposes_final_portfolio_state(self):
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [99.0, 100.0, 104.0],
                "High": [101.0, 106.0, 108.0],
                "Low": [98.0, 99.0, 103.0],
                "Close": [100.0, 105.0, 107.0],
                "Volume": [1000.0, 1200.0, 1400.0],
            },
            index=pd.date_range("2026-06-03", periods=3, freq="1D", tz="UTC"),
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
            "profiles": [{"exchange": "nasdaq", "market_type": "equity", "trend_ema_length": 50}],
        }

        def generate_signals(features, symbol, market, regime_profile):
            if len(features) != 2:
                return []
            close = float(features["Close"].iloc[-1])
            return [
                Signal(
                    module="research_breakout",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=80.0,
                    entry_reason="research breakout",
                    invalidation="close below stop",
                    preferred_stop=close - 5.0,
                    preferred_target=close + 100.0,
                    confidence=0.8,
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
                payload = signal_preview.get_signal_research_event_backtest_preview(
                    timeframe="1d",
                    symbol="AAPL",
                    exchange="nasdaq",
                    market_type="equity",
                    equity=10_000.0,
                    load_ohlcv=lambda timeframe, market: bars,
                    build_features=lambda frame, market, regime_profile: frame,
                    generate_signals=generate_signals,
                )
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path
                signal_preview._REGIME_PROFILE_PATH = original_regime_path

        self.assertEqual(payload["finalPortfolio"]["positionCount"], 1)
        self.assertEqual(payload["finalPortfolio"]["openRisk"], 200.0)
        position = payload["finalPortfolio"]["positions"][0]
        self.assertEqual(position["symbol"], "AAPL")
        self.assertEqual(position["layer"], "tactical")
        self.assertEqual(position["module"], "research_breakout")
        self.assertEqual(position["direction"], "long")
        self.assertAlmostEqual(position["entryPrice"], 105.0)
        self.assertAlmostEqual(position["stopPrice"], 100.0)
        self.assertAlmostEqual(position["targetPrice"], 205.0)

    def test_generic_research_event_backtest_preview_can_refresh_cached_feature_engine_output(self):
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [99.0, 100.0],
                "High": [101.0, 102.0],
                "Low": [98.0, 99.0],
                "Close": [100.0, 101.0],
                "Volume": [1000.0, 1100.0],
            },
            index=pd.date_range("2026-06-01", periods=2, freq="D", tz="UTC"),
        )
        market_records = [{
            "symbol": "AAPL",
            "base": "AAPL",
            "quote": "USD",
            "exchange": "nasdaq",
            "market_type": "equity",
            "tick_size": 0.01,
            "lot_size": 0.001,
            "supports_short": False,
            "supports_leverage": False,
        }]
        regime_payload = {"default": {"trend_ema_length": 50}}
        calls = {}
        observed = {}

        class FeatureResult:
            def __init__(self, features):
                self.features = features
                self.cache = {"hit": False}

        def fake_run_feature_engine_with_cache(engine, frame, *, series_id, store=None, refresh=False):
            calls["refresh"] = refresh
            calls["series_id"] = series_id
            return FeatureResult(frame.assign(refreshed_feature=[1.0, 1.0]))

        def generate_signals(features, symbol, market, regime_profile):
            observed["columns"] = list(features.columns)
            return []

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            market_path = root / "markets.json"
            regime_path = root / "regime_profiles.json"
            market_path.write_text(json.dumps({"markets": market_records}), encoding="utf-8")
            regime_path.write_text(json.dumps(regime_payload), encoding="utf-8")
            original_market_path = signal_preview._MARKET_CATALOG_PATH
            original_regime_path = signal_preview._REGIME_PROFILE_PATH
            original_run = signal_preview.run_feature_engine_with_cache
            try:
                signal_preview._MARKET_CATALOG_PATH = market_path
                signal_preview._REGIME_PROFILE_PATH = regime_path
                signal_preview.run_feature_engine_with_cache = fake_run_feature_engine_with_cache
                payload = signal_preview.get_signal_research_event_backtest_preview(
                    timeframe="1d",
                    symbol="AAPL",
                    exchange="nasdaq",
                    market_type="equity",
                    equity=10_000.0,
                    load_ohlcv=lambda timeframe, market: bars,
                    generate_signals=generate_signals,
                    refresh_features=True,
                )
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path
                signal_preview._REGIME_PROFILE_PATH = original_regime_path
                signal_preview.run_feature_engine_with_cache = original_run

        self.assertEqual(payload["rows"], 2)
        self.assertTrue(calls["refresh"])
        self.assertEqual(calls["series_id"].cache_key, "feature_engine/nasdaq/equity/AAPL/1d/research_default_v1_ema50_atr14_adx14_bb20x2")
        self.assertIn("refreshed_feature", observed["columns"])
        self.assertEqual(payload["featureCaches"], {"AAPL": {"hit": False}})

    def test_multi_market_research_event_backtest_preview_runs_symbols_through_one_portfolio(self):
        from serve import signal_preview

        frames = {
            "AAPL": pd.DataFrame(
                {
                    "Open": [99.0, 100.0, 104.0],
                    "High": [101.0, 106.0, 108.0],
                    "Low": [98.0, 99.0, 103.0],
                    "Close": [100.0, 105.0, 107.0],
                    "Volume": [1000.0, 1200.0, 1300.0],
                },
                index=pd.date_range("2026-06-01", periods=3, freq="D", tz="UTC"),
            ),
            "MSFT": pd.DataFrame(
                {
                    "Open": [299.0, 300.0, 306.0],
                    "High": [301.0, 307.0, 309.0],
                    "Low": [298.0, 299.0, 305.0],
                    "Close": [300.0, 306.0, 308.0],
                    "Volume": [900.0, 1000.0, 1100.0],
                },
                index=pd.date_range("2026-06-01", periods=3, freq="D", tz="UTC"),
            ),
        }
        market_records = [
            {
                "symbol": "AAPL",
                "base": "AAPL",
                "quote": "USD",
                "exchange": "nasdaq",
                "market_type": "equity",
                "tick_size": 0.01,
                "lot_size": 0.001,
                "correlation_group": "mega_cap",
                "supports_short": False,
                "supports_leverage": False,
            },
            {
                "symbol": "MSFT",
                "base": "MSFT",
                "quote": "USD",
                "exchange": "nasdaq",
                "market_type": "equity",
                "tick_size": 0.01,
                "lot_size": 0.001,
                "correlation_group": "mega_cap",
                "supports_short": False,
                "supports_leverage": False,
            },
        ]
        regime_payload = {"default": {"trend_ema_length": 50}}

        def load_ohlcv(timeframe, market):
            return frames[market.asset.symbol]

        def build_features(frame, market, regime_profile):
            return frame.assign(feature_symbol=market.asset.symbol)

        def generate_signals(features, symbol, market, regime_profile):
            if len(features) != 2:
                return []
            close = float(features["Close"].iloc[-1])
            return [
                Signal(
                    module="research_breakout",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=80.0,
                    entry_reason="research breakout",
                    invalidation="close below stop",
                    preferred_stop=close - 5.0,
                    preferred_target=close + 1.0,
                    confidence=0.8,
                    required_data=("ohlcv:1d",),
                )
            ]

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            market_path = root / "markets.json"
            regime_path = root / "regime_profiles.json"
            market_path.write_text(json.dumps({"markets": market_records}), encoding="utf-8")
            regime_path.write_text(json.dumps(regime_payload), encoding="utf-8")
            original_market_path = signal_preview._MARKET_CATALOG_PATH
            original_regime_path = signal_preview._REGIME_PROFILE_PATH
            try:
                signal_preview._MARKET_CATALOG_PATH = market_path
                signal_preview._REGIME_PROFILE_PATH = regime_path
                payload = signal_preview.get_signal_research_event_backtest_preview(
                    timeframe="1d",
                    symbol=["AAPL", "MSFT"],
                    exchange=["nasdaq", "nasdaq"],
                    market_type=["equity", "equity"],
                    equity=20_000.0,
                    load_ohlcv=load_ohlcv,
                    build_features=build_features,
                    generate_signals=generate_signals,
                )
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path
                signal_preview._REGIME_PROFILE_PATH = original_regime_path

        self.assertEqual(payload["symbols"], ["AAPL", "MSFT"])
        self.assertEqual(payload["rows"], 6)
        self.assertEqual(payload["stepCount"], 6)
        self.assertEqual(payload["signalCount"], 2)
        self.assertEqual(payload["orderCount"], 4)
        self.assertEqual(payload["tradeCount"], 2)
        self.assertEqual(sorted(payload["markets"]), ["AAPL", "MSFT"])
        self.assertEqual(payload["markets"]["AAPL"]["marketType"], "equity")
        self.assertEqual(payload["orderStatusCounts"]["filled"], 2)
        self.assertEqual(payload["orderStatusCounts"]["submitted"], 0)
        self.assertEqual(payload["orderLifecycleByCorrelationGroup"]["mega_cap"]["totalOrderCount"], 2)
        self.assertEqual(payload["orderLifecycleByCorrelationGroup"]["mega_cap"]["filledCount"], 2)
        self.assertAlmostEqual(payload["orderLifecycleByCorrelationGroup"]["mega_cap"]["fillRate"], 1.0)
        self.assertEqual(payload["orderLifecycleByExchange"]["nasdaq"]["totalOrderCount"], 2)
        self.assertEqual(payload["orderLifecycleByExchange"]["nasdaq"]["filledCount"], 2)
        self.assertAlmostEqual(payload["orderLifecycleByExchange"]["nasdaq"]["fillRate"], 1.0)
        self.assertEqual(payload["orderLifecycleByMarketType"]["equity"]["totalOrderCount"], 2)
        self.assertEqual(payload["orderLifecycleByMarketType"]["equity"]["filledCount"], 2)
        self.assertAlmostEqual(payload["orderLifecycleByMarketType"]["equity"]["fillRate"], 1.0)
        self.assertEqual(payload["regimeProfiles"]["MSFT"]["trendEmaLength"], 50)
        self.assertIn("AAPL", payload["latestRegimes"])
        self.assertIn("MSFT", payload["latestRegimes"])
        self.assertEqual(payload["featureCaches"], {"AAPL": None, "MSFT": None})
        self.assertIn(payload["latestRegimes"]["AAPL"]["value"], [0, 1, 2, 3, 4])
        self.assertIn(payload["latestRegimes"]["MSFT"]["value"], [0, 1, 2, 3, 4])
        self.assertEqual(payload["orders"][0]["symbol"], "AAPL")
        self.assertEqual(payload["orders"][1]["symbol"], "MSFT")
        self.assertEqual(len(payload["equityCurve"]), 6)
        self.assertEqual(len(payload["exposureCurve"]), 6)
        two_position_exposure = payload["exposureCurve"][3]
        mega_cap_exposure = two_position_exposure["groupExposure"]["mega_cap"]
        symbol_exposure = two_position_exposure["symbolExposure"]
        layer_exposure = two_position_exposure["layerExposure"]
        module_exposure = two_position_exposure["moduleExposure"]
        exchange_exposure = two_position_exposure["exchangeExposure"]
        market_type_exposure = two_position_exposure["marketTypeExposure"]
        self.assertEqual(mega_cap_exposure["positionCount"], 2)
        self.assertAlmostEqual(mega_cap_exposure["openRisk"], two_position_exposure["openRisk"])
        self.assertEqual(symbol_exposure["AAPL"]["positionCount"], 1)
        self.assertEqual(symbol_exposure["MSFT"]["positionCount"], 1)
        self.assertGreater(symbol_exposure["AAPL"]["grossNotional"], 0.0)
        self.assertGreater(symbol_exposure["MSFT"]["grossNotional"], 0.0)
        self.assertEqual(layer_exposure["tactical"]["positionCount"], 2)
        self.assertAlmostEqual(layer_exposure["tactical"]["openRisk"], two_position_exposure["openRisk"])
        self.assertEqual(module_exposure["research_breakout"]["positionCount"], 2)
        self.assertAlmostEqual(module_exposure["research_breakout"]["openRisk"], two_position_exposure["openRisk"])
        self.assertEqual(exchange_exposure["nasdaq"]["positionCount"], 2)
        self.assertAlmostEqual(exchange_exposure["nasdaq"]["openRisk"], two_position_exposure["openRisk"])
        self.assertEqual(market_type_exposure["equity"]["positionCount"], 2)
        self.assertAlmostEqual(market_type_exposure["equity"]["openRisk"], two_position_exposure["openRisk"])
        self.assertEqual(payload["exposureSummary"]["maxPositionCount"], 2)
        self.assertGreater(payload["exposureSummary"]["maxGrossNotional"], 0.0)
        self.assertAlmostEqual(
            payload["exposureSummary"]["maxGroupOpenRisk"],
            two_position_exposure["openRisk"],
        )
        self.assertEqual(payload["exposureSummary"]["maxGroupGrossNotionalGroup"], "mega_cap")
        self.assertEqual(payload["exposureSummary"]["maxGroupOpenRiskGroup"], "mega_cap")
        self.assertAlmostEqual(
            payload["exposureSummary"]["maxExchangeOpenRisk"],
            two_position_exposure["openRisk"],
        )
        self.assertEqual(payload["exposureSummary"]["maxExchangeGrossNotionalExchange"], "nasdaq")
        self.assertEqual(payload["exposureSummary"]["maxExchangeOpenRiskExchange"], "nasdaq")
        self.assertAlmostEqual(
            payload["exposureSummary"]["maxMarketTypeOpenRisk"],
            two_position_exposure["openRisk"],
        )
        self.assertEqual(payload["exposureSummary"]["maxMarketTypeGrossNotionalMarketType"], "equity")
        self.assertEqual(payload["exposureSummary"]["maxMarketTypeOpenRiskMarketType"], "equity")
        self.assertIn(
            payload["exposureSummary"]["maxSymbolGrossNotionalSymbol"],
            {"AAPL", "MSFT"},
        )
        self.assertIn(
            payload["exposureSummary"]["maxSymbolOpenRiskSymbol"],
            {"AAPL", "MSFT"},
        )
        self.assertEqual(payload["exposureSummary"]["maxLayerGrossNotionalLayer"], "tactical")
        self.assertEqual(payload["exposureSummary"]["maxLayerOpenRiskLayer"], "tactical")
        self.assertEqual(payload["exposureSummary"]["maxModuleGrossNotionalModule"], "research_breakout")
        self.assertEqual(payload["exposureSummary"]["maxModuleOpenRiskModule"], "research_breakout")
        self.assertEqual(payload["exposureCurve"][-1]["positionCount"], 0)
        self.assertIn("AAPL", payload["attribution"]["bySymbol"])
        self.assertIn("MSFT", payload["attribution"]["bySymbol"])
        self.assertEqual(payload["attribution"]["byExchange"]["nasdaq"]["tradeCount"], 2)
        self.assertEqual(payload["attribution"]["byMarketType"]["equity"]["tradeCount"], 2)
        self.assertEqual(payload["attribution"]["byCorrelationGroup"]["mega_cap"]["tradeCount"], 2)

    def test_research_preview_bars_load_from_configured_non_btc_csv_source(self):
        from serve import signal_preview

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

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            csv_path = root / "data" / "aapl_1d.csv"
            csv_path.parent.mkdir()
            pd.DataFrame([
                {
                    "timestamp": "2026-06-01T00:00:00Z",
                    "open": 199.0,
                    "high": 203.0,
                    "low": 198.0,
                    "close": 202.0,
                    "volume": 1000.0,
                },
                {
                    "timestamp": "2026-06-02T00:00:00Z",
                    "open": 202.0,
                    "high": 206.0,
                    "low": 201.0,
                    "close": 205.0,
                    "volume": 1200.0,
                },
            ]).to_csv(csv_path, index=False)
            market_path = root / "markets.json"
            data_source_path = root / "research_data_sources.json"
            market_path.write_text(json.dumps({"markets": market_records}), encoding="utf-8")
            data_source_path.write_text(json.dumps({
                "connectors": [
                    {
                        "name": "research_csv",
                        "type": "csv",
                        "files_by_symbol": {"AAPL": "data/aapl_1d.csv"},
                    }
                ],
                "routes": [
                    {
                        "symbol": "AAPL",
                        "exchange": "nasdaq",
                        "market_type": "equity",
                        "timeframe": "1d",
                        "source": "research_csv",
                        "limit": 1,
                    }
                ],
            }), encoding="utf-8")

            original_market_path = signal_preview._MARKET_CATALOG_PATH
            original_data_source_path = signal_preview._RESEARCH_DATA_SOURCE_PATH
            original_root = signal_preview._PROJECT_ROOT
            try:
                signal_preview._MARKET_CATALOG_PATH = market_path
                signal_preview._RESEARCH_DATA_SOURCE_PATH = data_source_path
                signal_preview._PROJECT_ROOT = root
                market = signal_preview.resolve_market_spec("AAPL", exchange="nasdaq", market_type="equity")
                bars = signal_preview.load_research_preview_bars("1d", market)
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path
                signal_preview._RESEARCH_DATA_SOURCE_PATH = original_data_source_path
                signal_preview._PROJECT_ROOT = original_root

        self.assertEqual(len(bars), 1)
        self.assertEqual(float(bars.iloc[0]["Close"]), 205.0)
        self.assertEqual(str(bars.index.tz), "UTC")

    def test_research_preview_bars_use_generic_bar_store_cache_boundary(self):
        from serve import signal_preview

        expected = pd.DataFrame(
            {
                "Open": [202.0],
                "High": [206.0],
                "Low": [201.0],
                "Close": [205.0],
                "Volume": [1200.0],
            },
            index=pd.to_datetime(["2026-06-02T00:00:00Z"], utc=True),
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
        calls = {}

        class FakeBarStore:
            def __init__(self, root):
                calls["parquet_store_root"] = Path(root)

        class FakeSQLiteBarStore:
            def __init__(self, root):
                calls["sqlite_store_root"] = Path(root)

        def fake_fetch_bars_with_cache(**kwargs):
            calls.update(kwargs)
            return expected

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            market_path = root / "markets.json"
            data_source_path = root / "research_data_sources.json"
            market_path.write_text(json.dumps({"markets": market_records}), encoding="utf-8")
            data_source_path.write_text(json.dumps({
                "connectors": [
                    {
                        "name": "research_csv",
                        "type": "csv",
                        "files_by_symbol": {"AAPL": "data/aapl_1d.csv"},
                    }
                ],
                "routes": [
                    {
                        "symbol": "AAPL",
                        "exchange": "nasdaq",
                        "market_type": "equity",
                        "timeframe": "1d",
                        "source": "research_csv",
                        "store_type": "sqlite",
                        "limit": 1,
                    }
                ],
            }), encoding="utf-8")

            original_market_path = signal_preview._MARKET_CATALOG_PATH
            original_data_source_path = signal_preview._RESEARCH_DATA_SOURCE_PATH
            original_root = signal_preview._PROJECT_ROOT
            original_fetch = signal_preview.fetch_bars_with_cache
            original_store = signal_preview.ParquetBarStore
            original_sqlite_store = signal_preview.SQLiteBarStore
            try:
                signal_preview._MARKET_CATALOG_PATH = market_path
                signal_preview._RESEARCH_DATA_SOURCE_PATH = data_source_path
                signal_preview._PROJECT_ROOT = root
                signal_preview.fetch_bars_with_cache = fake_fetch_bars_with_cache
                signal_preview.ParquetBarStore = FakeBarStore
                signal_preview.SQLiteBarStore = FakeSQLiteBarStore
                market = signal_preview.resolve_market_spec("AAPL", exchange="nasdaq", market_type="equity")
                bars = signal_preview.load_research_preview_bars("1d", market)
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path
                signal_preview._RESEARCH_DATA_SOURCE_PATH = original_data_source_path
                signal_preview._PROJECT_ROOT = original_root
                signal_preview.fetch_bars_with_cache = original_fetch
                signal_preview.ParquetBarStore = original_store
                signal_preview.SQLiteBarStore = original_sqlite_store

        self.assertIs(bars, expected)
        self.assertEqual(calls["source"], "research_csv")
        self.assertEqual(calls["market"].market_key, "nasdaq:equity:AAPL")
        self.assertEqual(calls["timeframe"], "1d")
        self.assertEqual(calls["limit"], 1)
        self.assertFalse(calls["refresh"])
        self.assertNotIn("parquet_store_root", calls)
        self.assertEqual(calls["sqlite_store_root"], root / "data" / "research_bars")

    def test_research_preview_bars_filter_intraday_rows_to_market_session(self):
        from serve import signal_preview

        fetched = pd.DataFrame(
            {
                "Open": [199.0, 202.0, 205.0],
                "High": [203.0, 206.0, 207.0],
                "Low": [198.0, 201.0, 204.0],
                "Close": [202.0, 205.0, 206.0],
                "Volume": [1000.0, 1200.0, 800.0],
            },
            index=pd.to_datetime(
                [
                    "2026-06-12T14:00:00Z",
                    "2026-06-12T21:00:00Z",
                    "2026-06-13T14:00:00Z",
                ],
                utc=True,
            ),
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
            "session_timezone": "America/New_York",
            "session_open": "09:30",
            "session_close": "16:00",
            "trading_days": ["mon", "tue", "wed", "thu", "fri"],
            "supports_short": False,
            "supports_leverage": False,
        }]

        class FakeBarStore:
            def __init__(self, root):
                pass

        def fake_fetch_bars_with_cache(**kwargs):
            return fetched

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            market_path = root / "markets.json"
            data_source_path = root / "research_data_sources.json"
            market_path.write_text(json.dumps({"markets": market_records}), encoding="utf-8")
            data_source_path.write_text(json.dumps({
                "connectors": [
                    {
                        "name": "research_csv",
                        "type": "csv",
                        "files_by_symbol": {"AAPL": "data/aapl_1h.csv"},
                    }
                ],
                "routes": [
                    {
                        "symbol": "AAPL",
                        "exchange": "nasdaq",
                        "market_type": "equity",
                        "timeframe": "1h",
                        "source": "research_csv",
                    }
                ],
            }), encoding="utf-8")

            original_market_path = signal_preview._MARKET_CATALOG_PATH
            original_data_source_path = signal_preview._RESEARCH_DATA_SOURCE_PATH
            original_root = signal_preview._PROJECT_ROOT
            original_fetch = signal_preview.fetch_bars_with_cache
            original_store = signal_preview.ParquetBarStore
            try:
                signal_preview._MARKET_CATALOG_PATH = market_path
                signal_preview._RESEARCH_DATA_SOURCE_PATH = data_source_path
                signal_preview._PROJECT_ROOT = root
                signal_preview.fetch_bars_with_cache = fake_fetch_bars_with_cache
                signal_preview.ParquetBarStore = FakeBarStore
                market = signal_preview.resolve_market_spec("AAPL", exchange="nasdaq", market_type="equity")
                bars = signal_preview.load_research_preview_bars("1h", market)
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path
                signal_preview._RESEARCH_DATA_SOURCE_PATH = original_data_source_path
                signal_preview._PROJECT_ROOT = original_root
                signal_preview.fetch_bars_with_cache = original_fetch
                signal_preview.ParquetBarStore = original_store

        self.assertEqual(list(bars.index), [pd.Timestamp("2026-06-12T14:00:00Z")])
        self.assertEqual(float(bars.iloc[0]["Close"]), 202.0)

    def test_research_preview_bars_pass_configured_date_window_to_cache_boundary(self):
        from serve import signal_preview

        expected = pd.DataFrame(
            {
                "Open": [202.0],
                "High": [206.0],
                "Low": [201.0],
                "Close": [205.0],
                "Volume": [1200.0],
            },
            index=pd.date_range("2026-06-02", periods=1, freq="D", tz="UTC"),
        )
        market_records = [{
            "symbol": "AAPL",
            "base": "AAPL",
            "quote": "USD",
            "exchange": "nasdaq",
            "market_type": "equity",
            "tick_size": 0.01,
            "lot_size": 0.001,
            "supports_short": False,
            "supports_leverage": False,
        }]
        calls = {}

        class FakeBarStore:
            def __init__(self, root):
                calls["store_root"] = Path(root)

        def fake_fetch_bars_with_cache(**kwargs):
            calls.update(kwargs)
            return expected

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            market_path = root / "markets.json"
            data_source_path = root / "research_data_sources.json"
            market_path.write_text(json.dumps({"markets": market_records}), encoding="utf-8")
            data_source_path.write_text(json.dumps({
                "connectors": [
                    {
                        "name": "research_csv",
                        "type": "csv",
                        "files_by_symbol": {"AAPL": "data/aapl_1d.csv"},
                    }
                ],
                "routes": [
                    {
                        "symbol": "AAPL",
                        "exchange": "nasdaq",
                        "market_type": "equity",
                        "timeframe": "1d",
                        "source": "research_csv",
                        "start": "2026-06-01T00:00:00Z",
                        "end": "2026-06-30T00:00:00Z",
                    }
                ],
            }), encoding="utf-8")

            original_market_path = signal_preview._MARKET_CATALOG_PATH
            original_data_source_path = signal_preview._RESEARCH_DATA_SOURCE_PATH
            original_root = signal_preview._PROJECT_ROOT
            original_fetch = signal_preview.fetch_bars_with_cache
            original_store = signal_preview.ParquetBarStore
            try:
                signal_preview._MARKET_CATALOG_PATH = market_path
                signal_preview._RESEARCH_DATA_SOURCE_PATH = data_source_path
                signal_preview._PROJECT_ROOT = root
                signal_preview.fetch_bars_with_cache = fake_fetch_bars_with_cache
                signal_preview.ParquetBarStore = FakeBarStore
                market = signal_preview.resolve_market_spec("AAPL", exchange="nasdaq", market_type="equity")
                bars = signal_preview.load_research_preview_bars("1d", market)
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path
                signal_preview._RESEARCH_DATA_SOURCE_PATH = original_data_source_path
                signal_preview._PROJECT_ROOT = original_root
                signal_preview.fetch_bars_with_cache = original_fetch
                signal_preview.ParquetBarStore = original_store

        self.assertIs(bars, expected)
        self.assertEqual(calls["start"], pd.Timestamp("2026-06-01T00:00:00Z"))
        self.assertEqual(calls["end"], pd.Timestamp("2026-06-30T00:00:00Z"))

    def test_research_preview_bars_treat_naive_configured_date_window_as_utc(self):
        from serve import signal_preview

        expected = pd.DataFrame(
            {
                "Open": [202.0],
                "High": [206.0],
                "Low": [201.0],
                "Close": [205.0],
                "Volume": [1200.0],
            },
            index=pd.date_range("2026-06-02", periods=1, freq="D", tz="UTC"),
        )
        market_records = [{
            "symbol": "AAPL",
            "base": "AAPL",
            "quote": "USD",
            "exchange": "nasdaq",
            "market_type": "equity",
            "tick_size": 0.01,
            "lot_size": 0.001,
            "supports_short": False,
            "supports_leverage": False,
        }]
        calls = {}

        class FakeBarStore:
            def __init__(self, root):
                pass

        def fake_fetch_bars_with_cache(**kwargs):
            calls.update(kwargs)
            return expected

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            market_path = root / "markets.json"
            data_source_path = root / "research_data_sources.json"
            market_path.write_text(json.dumps({"markets": market_records}), encoding="utf-8")
            data_source_path.write_text(json.dumps({
                "connectors": [
                    {
                        "name": "research_csv",
                        "type": "csv",
                        "files_by_symbol": {"AAPL": "data/aapl_1d.csv"},
                    }
                ],
                "routes": [
                    {
                        "symbol": "AAPL",
                        "exchange": "nasdaq",
                        "market_type": "equity",
                        "timeframe": "1d",
                        "source": "research_csv",
                        "start": "2026-06-01",
                        "end": "2026-06-30",
                    }
                ],
            }), encoding="utf-8")

            original_market_path = signal_preview._MARKET_CATALOG_PATH
            original_data_source_path = signal_preview._RESEARCH_DATA_SOURCE_PATH
            original_root = signal_preview._PROJECT_ROOT
            original_fetch = signal_preview.fetch_bars_with_cache
            original_store = signal_preview.ParquetBarStore
            try:
                signal_preview._MARKET_CATALOG_PATH = market_path
                signal_preview._RESEARCH_DATA_SOURCE_PATH = data_source_path
                signal_preview._PROJECT_ROOT = root
                signal_preview.fetch_bars_with_cache = fake_fetch_bars_with_cache
                signal_preview.ParquetBarStore = FakeBarStore
                market = signal_preview.resolve_market_spec("AAPL", exchange="nasdaq", market_type="equity")
                signal_preview.load_research_preview_bars("1d", market)
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path
                signal_preview._RESEARCH_DATA_SOURCE_PATH = original_data_source_path
                signal_preview._PROJECT_ROOT = original_root
                signal_preview.fetch_bars_with_cache = original_fetch
                signal_preview.ParquetBarStore = original_store

        self.assertEqual(calls["start"], pd.Timestamp("2026-06-01T00:00:00Z"))
        self.assertEqual(calls["end"], pd.Timestamp("2026-06-30T00:00:00Z"))

    def test_research_preview_bars_can_refresh_generic_bar_store_cache_boundary(self):
        from serve import signal_preview

        expected = pd.DataFrame(
            {
                "Open": [202.0],
                "High": [206.0],
                "Low": [201.0],
                "Close": [205.0],
                "Volume": [1200.0],
            },
            index=pd.date_range("2026-06-02", periods=1, freq="D", tz="UTC"),
        )
        market_records = [{
            "symbol": "AAPL",
            "base": "AAPL",
            "quote": "USD",
            "exchange": "nasdaq",
            "market_type": "equity",
            "tick_size": 0.01,
            "lot_size": 0.001,
            "supports_short": False,
            "supports_leverage": False,
        }]
        calls = {}

        class FakeBarStore:
            def __init__(self, root):
                self.root = Path(root)
                calls["store_root"] = self.root

        def fake_fetch_bars_with_cache(**kwargs):
            calls.update(kwargs)
            return expected

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            market_path = root / "markets.json"
            data_source_path = root / "research_data_sources.json"
            market_path.write_text(json.dumps({"markets": market_records}), encoding="utf-8")
            data_source_path.write_text(json.dumps({
                "connectors": [
                    {
                        "name": "research_csv",
                        "type": "csv",
                        "files_by_symbol": {"AAPL": "data/aapl_1d.csv"},
                    }
                ],
                "routes": [
                    {
                        "symbol": "AAPL",
                        "exchange": "nasdaq",
                        "market_type": "equity",
                        "timeframe": "1d",
                        "source": "research_csv",
                    }
                ],
            }), encoding="utf-8")
            original_market_path = signal_preview._MARKET_CATALOG_PATH
            original_data_source_path = signal_preview._RESEARCH_DATA_SOURCE_PATH
            original_root = signal_preview._PROJECT_ROOT
            original_fetch = signal_preview.fetch_bars_with_cache
            original_store = signal_preview.ParquetBarStore
            try:
                signal_preview._MARKET_CATALOG_PATH = market_path
                signal_preview._RESEARCH_DATA_SOURCE_PATH = data_source_path
                signal_preview._PROJECT_ROOT = root
                signal_preview.fetch_bars_with_cache = fake_fetch_bars_with_cache
                signal_preview.ParquetBarStore = FakeBarStore
                market = signal_preview.resolve_market_spec("AAPL", exchange="nasdaq", market_type="equity")
                bars = signal_preview.load_research_preview_bars("1d", market, refresh=True)
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path
                signal_preview._RESEARCH_DATA_SOURCE_PATH = original_data_source_path
                signal_preview._PROJECT_ROOT = original_root
                signal_preview.fetch_bars_with_cache = original_fetch
                signal_preview.ParquetBarStore = original_store

        self.assertIs(bars, expected)
        self.assertTrue(calls["refresh"])
        self.assertEqual(calls["store_root"], root / "data" / "research_bars")

    def test_default_research_feature_builder_loads_configured_derivative_features(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.regimes import RegimeProfile
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0],
                "High": [102.0, 103.0, 104.0],
                "Low": [99.0, 100.0, 101.0],
                "Close": [101.0, 102.0, 103.0],
                "Volume": [1000.0, 1100.0, 1200.0],
            },
            index=pd.to_datetime(
                ["2026-06-01T00:00:00Z", "2026-06-01T01:00:00Z", "2026-06-01T02:00:00Z"],
                utc=True,
            ),
        )
        derivatives = pd.DataFrame(
            {
                "funding_rate": [0.0001, 0.0002],
                "open_interest": [10000.0, 11000.0],
            },
            index=pd.to_datetime(["2026-06-01T00:00:00Z", "2026-06-01T02:00:00Z"], utc=True),
        )
        market = MarketSpec(
            asset=AssetSpec(symbol="ETH/USDT", base="ETH", quote="USDT"),
            exchange="binance",
            market_type="swap",
            supports_short=True,
            supports_leverage=True,
        )
        calls = {}

        class FakeFeatureStore:
            def __init__(self, root):
                calls["feature_store_root"] = Path(root)

            def write(self, series_id, features):
                calls["feature_series_id"] = series_id
                calls["feature_columns"] = list(features.columns)
                return Path("features.parquet")

        class FakeDerivativeStore:
            def __init__(self, root):
                calls["parquet_derivative_store_root"] = Path(root)

        class FakeSQLiteDerivativeStore:
            def __init__(self, root):
                calls["sqlite_derivative_store_root"] = Path(root)

        def fake_fetch_derivatives_with_cache(**kwargs):
            calls["derivative_kwargs"] = kwargs
            return derivatives

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_source_path = root / "research_data_sources.json"
            data_source_path.write_text(json.dumps({
                "connectors": [
                    {
                        "name": "exchange_ccxt",
                        "type": "ccxt",
                    }
                ],
                "routes": [
                    {
                        "symbol": "ETH/USDT",
                        "exchange": "binance",
                        "market_type": "swap",
                        "timeframe": "1h",
                        "source": "exchange_ccxt",
                        "data_type": "derivatives",
                        "store_type": "sqlite",
                        "funding_limit": 500,
                        "open_interest_timeframe": "4h",
                        "open_interest_limit": 600,
                        "start": "2026-06-01T00:00:00Z",
                        "end": "2026-06-01T02:00:00Z",
                    }
                ],
            }), encoding="utf-8")

            original_root = signal_preview._PROJECT_ROOT
            original_data_source_path = signal_preview._RESEARCH_DATA_SOURCE_PATH
            original_feature_store = signal_preview.ParquetFeatureStore
            original_derivative_store = signal_preview.ParquetDerivativeStore
            original_sqlite_derivative_store = signal_preview.SQLiteDerivativeStore
            original_fetch_derivatives = signal_preview.fetch_derivatives_with_cache
            try:
                signal_preview._PROJECT_ROOT = root
                signal_preview._RESEARCH_DATA_SOURCE_PATH = data_source_path
                signal_preview.ParquetFeatureStore = FakeFeatureStore
                signal_preview.ParquetDerivativeStore = FakeDerivativeStore
                signal_preview.SQLiteDerivativeStore = FakeSQLiteDerivativeStore
                signal_preview.fetch_derivatives_with_cache = fake_fetch_derivatives_with_cache
                features = signal_preview._default_research_feature_builder(
                    bars,
                    market,
                    RegimeProfile(trend_ema_length=3),
                    timeframe="1h",
                    refresh=True,
                )
            finally:
                signal_preview._PROJECT_ROOT = original_root
                signal_preview._RESEARCH_DATA_SOURCE_PATH = original_data_source_path
                signal_preview.ParquetFeatureStore = original_feature_store
                signal_preview.ParquetDerivativeStore = original_derivative_store
                signal_preview.SQLiteDerivativeStore = original_sqlite_derivative_store
                signal_preview.fetch_derivatives_with_cache = original_fetch_derivatives

        self.assertEqual(float(features.iloc[-1]["funding_rate"]), 0.0002)
        self.assertEqual(float(features.iloc[-1]["open_interest"]), 11000.0)
        self.assertIn("funding_zscore_90", features.columns)
        self.assertIn("open_interest_change_6", features.columns)
        self.assertEqual(calls["derivative_kwargs"]["source"], "exchange_ccxt")
        self.assertEqual(calls["derivative_kwargs"]["market"].market_key, "binance:swap:ETH/USDT")
        self.assertEqual(calls["derivative_kwargs"]["funding_limit"], 500)
        self.assertEqual(calls["derivative_kwargs"]["open_interest_timeframe"], "4h")
        self.assertEqual(calls["derivative_kwargs"]["open_interest_limit"], 600)
        self.assertEqual(calls["derivative_kwargs"]["start"], pd.Timestamp("2026-06-01T00:00:00Z"))
        self.assertEqual(calls["derivative_kwargs"]["end"], pd.Timestamp("2026-06-01T02:00:00Z"))
        self.assertTrue(calls["derivative_kwargs"]["refresh"])
        self.assertNotIn("parquet_derivative_store_root", calls)
        self.assertEqual(calls["sqlite_derivative_store_root"], root / "data" / "research_derivatives")
        self.assertEqual(calls["feature_store_root"], root / "data" / "research_features")
        self.assertTrue(calls["feature_series_id"].feature_set.endswith("_derivatives"))

    def test_default_research_feature_builder_loads_configured_order_book_features(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.regimes import RegimeProfile
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0],
                "High": [102.0, 103.0, 104.0],
                "Low": [99.0, 100.0, 101.0],
                "Close": [101.0, 102.0, 103.0],
                "Volume": [1000.0, 1100.0, 1200.0],
            },
            index=pd.to_datetime(
                ["2026-06-01T00:00:00Z", "2026-06-01T01:00:00Z", "2026-06-01T02:00:00Z"],
                utc=True,
            ),
        )
        snapshots = pd.DataFrame(
            {
                "bid_price_1": [100.0, 102.0],
                "bid_size_1": [2.0, 4.0],
                "bid_price_2": [99.5, 101.5],
                "bid_size_2": [3.0, 1.0],
                "ask_price_1": [101.0, 103.0],
                "ask_size_1": [1.0, 2.0],
                "ask_price_2": [101.5, 103.5],
                "ask_size_2": [1.0, 1.0],
            },
            index=pd.to_datetime(["2026-06-01T00:00:00Z", "2026-06-01T02:00:00Z"], utc=True),
        )
        market = MarketSpec(
            asset=AssetSpec(symbol="ETH/USDT", base="ETH", quote="USDT"),
            exchange="binance",
            market_type="swap",
            supports_short=True,
            supports_leverage=True,
        )
        calls = {}

        class FakeFeatureStore:
            def __init__(self, root):
                calls["feature_store_root"] = Path(root)

            def write(self, series_id, features):
                calls["feature_series_id"] = series_id
                calls["feature_columns"] = list(features.columns)
                return Path("features.parquet")

        class FakeOrderBookStore:
            def __init__(self, root):
                calls["parquet_order_book_store_root"] = Path(root)

        class FakeSQLiteOrderBookStore:
            def __init__(self, root):
                calls["sqlite_order_book_store_root"] = Path(root)

        def fake_fetch_order_book_snapshots_with_cache(**kwargs):
            calls["order_book_kwargs"] = kwargs
            return snapshots

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_source_path = root / "research_data_sources.json"
            data_source_path.write_text(json.dumps({
                "connectors": [
                    {
                        "name": "exchange_ccxt",
                        "type": "ccxt",
                    }
                ],
                "routes": [
                    {
                        "symbol": "ETH/USDT",
                        "exchange": "binance",
                        "market_type": "swap",
                        "timeframe": "1h",
                        "source": "exchange_ccxt",
                        "data_type": "order_book",
                        "store_type": "sqlite",
                        "depth": 2,
                        "sample_interval": "snapshot",
                        "limit": 7,
                    }
                ],
            }), encoding="utf-8")

            original_root = signal_preview._PROJECT_ROOT
            original_data_source_path = signal_preview._RESEARCH_DATA_SOURCE_PATH
            original_feature_store = signal_preview.ParquetFeatureStore
            original_order_book_store = signal_preview.ParquetOrderBookStore
            original_sqlite_order_book_store = signal_preview.SQLiteOrderBookStore
            original_fetch_order_book = signal_preview.fetch_order_book_snapshots_with_cache
            try:
                signal_preview._PROJECT_ROOT = root
                signal_preview._RESEARCH_DATA_SOURCE_PATH = data_source_path
                signal_preview.ParquetFeatureStore = FakeFeatureStore
                signal_preview.ParquetOrderBookStore = FakeOrderBookStore
                signal_preview.SQLiteOrderBookStore = FakeSQLiteOrderBookStore
                signal_preview.fetch_order_book_snapshots_with_cache = fake_fetch_order_book_snapshots_with_cache
                features = signal_preview._default_research_feature_builder(
                    bars,
                    market,
                    RegimeProfile(trend_ema_length=3),
                    timeframe="1h",
                    refresh=True,
                )
            finally:
                signal_preview._PROJECT_ROOT = original_root
                signal_preview._RESEARCH_DATA_SOURCE_PATH = original_data_source_path
                signal_preview.ParquetFeatureStore = original_feature_store
                signal_preview.ParquetOrderBookStore = original_order_book_store
                signal_preview.SQLiteOrderBookStore = original_sqlite_order_book_store
                signal_preview.fetch_order_book_snapshots_with_cache = original_fetch_order_book

        self.assertEqual(float(features.iloc[-1]["order_book_spread"]), 1.0)
        self.assertEqual(float(features.iloc[-1]["order_book_mid"]), 102.5)
        self.assertEqual(float(features.iloc[-1]["order_book_bid_size_sum_2"]), 5.0)
        self.assertEqual(float(features.iloc[-1]["order_book_ask_size_sum_2"]), 3.0)
        self.assertEqual(float(features.iloc[-1]["order_book_imbalance_2"]), 0.25)
        self.assertEqual(calls["order_book_kwargs"]["source"], "exchange_ccxt")
        self.assertEqual(calls["order_book_kwargs"]["market"].market_key, "binance:swap:ETH/USDT")
        self.assertEqual(calls["order_book_kwargs"]["depth"], 2)
        self.assertEqual(calls["order_book_kwargs"]["sample_interval"], "snapshot")
        self.assertEqual(calls["order_book_kwargs"]["limit"], 7)
        self.assertTrue(calls["order_book_kwargs"]["refresh"])
        self.assertNotIn("parquet_order_book_store_root", calls)
        self.assertEqual(calls["sqlite_order_book_store_root"], root / "data" / "research_order_books")
        self.assertEqual(calls["feature_store_root"], root / "data" / "research_features")
        self.assertTrue(calls["feature_series_id"].feature_set.endswith("_order_book_d2"))

    def test_default_research_feature_builder_loads_configured_external_metric_features(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.regimes import RegimeProfile
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0],
                "High": [102.0, 103.0, 104.0],
                "Low": [99.0, 100.0, 101.0],
                "Close": [101.0, 102.0, 103.0],
                "Volume": [1000.0, 1100.0, 1200.0],
            },
            index=pd.to_datetime(
                ["2026-06-01T00:00:00Z", "2026-06-01T01:00:00Z", "2026-06-01T02:00:00Z"],
                utc=True,
            ),
        )
        metrics = pd.DataFrame(
            {
                "bullish_ratio": [0.45, 0.62, 0.99],
                "risk_score": [12.0, 35.0, 99.0],
            },
            index=pd.to_datetime(
                ["2026-06-01T00:00:00Z", "2026-06-01T02:00:00Z", "2026-06-01T03:00:00Z"],
                utc=True,
            ),
        )
        macro_metrics = pd.DataFrame(
            {"liquidity": [1.5, 1.8]},
            index=pd.to_datetime(["2026-06-01T00:00:00Z", "2026-06-01T01:00:00Z"], utc=True),
        )
        market = MarketSpec(
            asset=AssetSpec(symbol="ETH/USDT", base="ETH", quote="USDT"),
            exchange="binance",
            market_type="swap",
            supports_short=True,
            supports_leverage=True,
        )
        calls = {}

        class FakeFeatureStore:
            def __init__(self, root):
                calls["feature_store_root"] = Path(root)

            def write(self, series_id, features):
                calls["feature_series_id"] = series_id
                calls["feature_columns"] = list(features.columns)
                return Path("features.parquet")

        class FakeExternalMetricStore:
            def __init__(self, root):
                calls["parquet_external_metric_store_root"] = Path(root)

            def read(self, series_id):
                calls.setdefault("parquet_external_metric_series_ids", []).append(series_id)
                return metrics

        class FakeSQLiteExternalMetricStore:
            def __init__(self, root):
                calls["sqlite_external_metric_store_root"] = Path(root)

            def read(self, series_id):
                calls.setdefault("sqlite_external_metric_series_ids", []).append(series_id)
                return macro_metrics

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            data_source_path = root / "research_data_sources.json"
            data_source_path.write_text(json.dumps({
                "routes": [
                    {
                        "symbol": "ETH/USDT",
                        "exchange": "binance",
                        "market_type": "swap",
                        "timeframe": "1h",
                        "source": "valuescan_store",
                        "data_type": "external_metrics",
                        "provider": "valuescan",
                        "dataset": "ai_tracking",
                        "prefix": "valuescan",
                        "columns": ["bullish_ratio", "risk_score"],
                        "start": "2026-06-01T00:00:00Z",
                        "end": "2026-06-01T01:00:00Z",
                    },
                    {
                        "symbol": "ETH/USDT",
                        "exchange": "binance",
                        "market_type": "swap",
                        "timeframe": "1h",
                        "source": "macro_store",
                        "data_type": "external_metrics",
                        "store_type": "sqlite",
                        "provider": "macro",
                        "dataset": "liquidity",
                        "prefix": "macro",
                        "columns": ["liquidity"],
                    }
                ],
            }), encoding="utf-8")

            original_root = signal_preview._PROJECT_ROOT
            original_data_source_path = signal_preview._RESEARCH_DATA_SOURCE_PATH
            original_feature_store = signal_preview.ParquetFeatureStore
            original_external_store = signal_preview.ParquetExternalMetricStore
            original_sqlite_external_store = signal_preview.SQLiteExternalMetricStore
            try:
                signal_preview._PROJECT_ROOT = root
                signal_preview._RESEARCH_DATA_SOURCE_PATH = data_source_path
                signal_preview.ParquetFeatureStore = FakeFeatureStore
                signal_preview.ParquetExternalMetricStore = FakeExternalMetricStore
                signal_preview.SQLiteExternalMetricStore = FakeSQLiteExternalMetricStore
                features = signal_preview._default_research_feature_builder(
                    bars,
                    market,
                    RegimeProfile(trend_ema_length=3),
                    timeframe="1h",
                    refresh=True,
                )
            finally:
                signal_preview._PROJECT_ROOT = original_root
                signal_preview._RESEARCH_DATA_SOURCE_PATH = original_data_source_path
                signal_preview.ParquetFeatureStore = original_feature_store
                signal_preview.ParquetExternalMetricStore = original_external_store
                signal_preview.SQLiteExternalMetricStore = original_sqlite_external_store

        self.assertEqual(float(features.iloc[-1]["valuescan_bullish_ratio"]), 0.45)
        self.assertEqual(float(features.iloc[-1]["valuescan_risk_score"]), 12.0)
        self.assertEqual(float(features.iloc[-1]["macro_liquidity"]), 1.8)
        self.assertEqual(calls["parquet_external_metric_store_root"], root / "data" / "research_external_metrics")
        self.assertEqual(calls["sqlite_external_metric_store_root"], root / "data" / "research_external_metrics")
        self.assertEqual(
            [series_id.cache_key for series_id in calls["parquet_external_metric_series_ids"]],
            [
                "valuescan_store/valuescan/ETH_USDT/1h/ai_tracking",
            ],
        )
        self.assertEqual(
            [series_id.cache_key for series_id in calls["sqlite_external_metric_series_ids"]],
            [
                "macro_store/macro/ETH_USDT/1h/liquidity",
            ],
        )
        self.assertEqual(calls["feature_store_root"], root / "data" / "research_features")
        self.assertIn("valuescan_bullish_ratio", calls["feature_columns"])
        self.assertIn("macro_liquidity", calls["feature_columns"])
        self.assertTrue(
            calls["feature_series_id"].feature_set.endswith("_external_valuescan_ai_tracking_macro_liquidity")
        )

    def test_default_research_feature_builder_falls_back_when_derivatives_are_unavailable(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.regimes import RegimeProfile
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0],
                "High": [102.0, 103.0, 104.0],
                "Low": [99.0, 100.0, 101.0],
                "Close": [101.0, 102.0, 103.0],
                "Volume": [1000.0, 1100.0, 1200.0],
            },
            index=pd.date_range("2026-06-01", periods=3, freq="h", tz="UTC"),
        )
        market = MarketSpec(
            asset=AssetSpec(symbol="ETH/USDT", base="ETH", quote="USDT"),
            exchange="binance",
            market_type="swap",
            supports_short=True,
            supports_leverage=True,
        )
        calls = {}

        class FakeFeatureStore:
            def __init__(self, root):
                pass

            def write(self, series_id, features):
                calls["feature_series_id"] = series_id
                calls["feature_columns"] = list(features.columns)
                return Path("features.parquet")

        def broken_derivatives_loader(timeframe, market, *, refresh=False):
            calls["loader_args"] = (timeframe, market, refresh)
            raise NotImplementedError("derivative data unavailable")

        original_loader = signal_preview.load_research_preview_derivatives
        original_feature_store = signal_preview.ParquetFeatureStore
        try:
            signal_preview.load_research_preview_derivatives = broken_derivatives_loader
            signal_preview.ParquetFeatureStore = FakeFeatureStore
            features = signal_preview._default_research_feature_builder(
                bars,
                market,
                RegimeProfile(trend_ema_length=3),
                timeframe="1h",
                refresh=True,
            )
        finally:
            signal_preview.load_research_preview_derivatives = original_loader
            signal_preview.ParquetFeatureStore = original_feature_store

        self.assertEqual(calls["loader_args"][0], "1h")
        self.assertEqual(calls["loader_args"][1].market_key, "binance:swap:ETH/USDT")
        self.assertTrue(calls["loader_args"][2])
        self.assertIn("ema3", features.columns)
        self.assertNotIn("funding_rate", features.columns)
        self.assertNotIn("open_interest", features.columns)
        self.assertFalse(calls["feature_series_id"].feature_set.endswith("_derivatives"))

    def test_generic_research_preview_defaults_to_direct_compute_breakout_signal_module(self):
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [94.0, 98.0, 101.0, 104.0],
                "High": [100.0, 102.0, 105.0, 107.0],
                "Low": [90.0, 92.0, 95.0, 103.0],
                "Close": [95.0, 101.0, 104.0, 106.0],
                "Volume": [100.0, 110.0, 120.0, 130.0],
            },
            index=pd.date_range("2026-06-01", periods=4, freq="D", tz="UTC"),
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

        with TemporaryDirectory() as tmpdir:
            market_path = Path(tmpdir) / "markets.json"
            market_path.write_text(json.dumps({"markets": market_records}), encoding="utf-8")
            original_market_path = signal_preview._MARKET_CATALOG_PATH
            try:
                signal_preview._MARKET_CATALOG_PATH = market_path
                payload = signal_preview.get_signal_research_preview(
                    timeframe="1d",
                    symbol="AAPL",
                    exchange="nasdaq",
                    market_type="equity",
                    equity=10_000.0,
                    load_ohlcv=lambda timeframe, market: bars,
                )
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path

        self.assertEqual(payload["signalCount"], 1)
        self.assertEqual(payload["signals"][0]["module"], "breakout")
        self.assertEqual(payload["signals"][0]["direction"], "long")
        self.assertEqual(payload["signals"][0]["preferred_stop"], 90.0)
        self.assertEqual(payload["signals"][0]["preferred_target"], 138.0)
        self.assertEqual(payload["riskDecisionCount"], 1)
        self.assertTrue(payload["riskDecisions"][0]["allowed"])
        self.assertEqual(payload["orderCount"], 1)
        self.assertEqual(payload["orders"][0]["action"], "open")

    def test_generic_research_preview_defaults_to_direct_compute_pullback_signal_module(self):
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [100.0, 104.0, 103.0, 105.0],
                "High": [101.0, 106.0, 104.0, 107.0],
                "Low": [99.0, 104.0, 100.0, 105.0],
                "Close": [100.0, 105.0, 102.0, 106.0],
                "Volume": [100.0, 120.0, 140.0, 160.0],
            },
            index=pd.date_range("2026-06-01", periods=4, freq="D", tz="UTC"),
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

        with TemporaryDirectory() as tmpdir:
            market_path = Path(tmpdir) / "markets.json"
            market_path.write_text(json.dumps({"markets": market_records}), encoding="utf-8")
            original_market_path = signal_preview._MARKET_CATALOG_PATH
            try:
                signal_preview._MARKET_CATALOG_PATH = market_path
                payload = signal_preview.get_signal_research_preview(
                    timeframe="1d",
                    symbol="AAPL",
                    exchange="nasdaq",
                    market_type="equity",
                    equity=10_000.0,
                    load_ohlcv=lambda timeframe, market: bars,
                )
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path

        self.assertEqual(payload["signalCount"], 1)
        self.assertEqual(payload["signals"][0]["module"], "pullback")
        self.assertEqual(payload["signals"][0]["direction"], "long")
        self.assertEqual(payload["signals"][0]["preferred_stop"], 100.0)
        self.assertEqual(payload["signals"][0]["preferred_target"], 118.0)
        self.assertEqual(payload["riskDecisionCount"], 1)
        self.assertTrue(payload["riskDecisions"][0]["allowed"])
        self.assertEqual(payload["orderCount"], 1)
        self.assertEqual(payload["orders"][0]["action"], "open")

    def test_generic_research_preview_uses_configured_signal_module_set(self):
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [100.0, 104.0, 103.0, 105.0],
                "High": [101.0, 106.0, 104.0, 107.0],
                "Low": [99.0, 104.0, 100.0, 105.0],
                "Close": [100.0, 105.0, 102.0, 106.0],
                "Volume": [100.0, 120.0, 140.0, 160.0],
            },
            index=pd.date_range("2026-06-01", periods=4, freq="D", tz="UTC"),
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
        signal_config = {
            "module_sets": [
                {
                    "name": "equity_pullback_only",
                    "modules": [
                        {
                            "type": "pullback",
                            "params": {
                                "module": "configured_pullback",
                                "ema_length": 3,
                                "allow_short": False,
                            },
                        }
                    ],
                }
            ],
            "routes": [
                {
                    "symbol": "AAPL",
                    "exchange": "nasdaq",
                    "market_type": "equity",
                    "timeframe": "1d",
                    "module_set": "equity_pullback_only",
                }
            ],
        }

        with TemporaryDirectory() as tmpdir:
            market_path = Path(tmpdir) / "markets.json"
            signal_path = Path(tmpdir) / "research_signal_modules.json"
            market_path.write_text(json.dumps({"markets": market_records}), encoding="utf-8")
            signal_path.write_text(json.dumps(signal_config), encoding="utf-8")
            original_market_path = signal_preview._MARKET_CATALOG_PATH
            original_signal_path = signal_preview._RESEARCH_SIGNAL_MODULE_PATH
            try:
                signal_preview._MARKET_CATALOG_PATH = market_path
                signal_preview._RESEARCH_SIGNAL_MODULE_PATH = signal_path
                payload = signal_preview.get_signal_research_preview(
                    timeframe="1d",
                    symbol="AAPL",
                    exchange="nasdaq",
                    market_type="equity",
                    equity=10_000.0,
                    load_ohlcv=lambda timeframe, market: bars,
                    build_features=lambda frame, market, regime_profile: frame,
                )
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path
                signal_preview._RESEARCH_SIGNAL_MODULE_PATH = original_signal_path

        self.assertEqual(payload["signalCount"], 1)
        self.assertEqual(payload["signals"][0]["module"], "configured_pullback")
        self.assertEqual(payload["signals"][0]["required_data"], ["ohlcv:1d"])

    def test_generic_research_preview_defaults_to_direct_compute_mean_reversion_signal_module(self):
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [110.0, 100.0, 95.0, 94.0],
                "High": [111.0, 101.0, 96.0, 96.0],
                "Low": [90.0, 99.0, 94.0, 93.0],
                "Close": [110.0, 100.0, 95.0, 95.5],
                "Volume": [100.0, 120.0, 140.0, 160.0],
            },
            index=pd.date_range("2026-06-01", periods=4, freq="D", tz="UTC"),
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

        with TemporaryDirectory() as tmpdir:
            market_path = Path(tmpdir) / "markets.json"
            market_path.write_text(json.dumps({"markets": market_records}), encoding="utf-8")
            original_market_path = signal_preview._MARKET_CATALOG_PATH
            try:
                signal_preview._MARKET_CATALOG_PATH = market_path
                payload = signal_preview.get_signal_research_preview(
                    timeframe="1d",
                    symbol="AAPL",
                    exchange="nasdaq",
                    market_type="equity",
                    equity=10_000.0,
                    load_ohlcv=lambda timeframe, market: bars,
                )
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path

        self.assertEqual(payload["signalCount"], 1)
        self.assertEqual(payload["signals"][0]["module"], "meanrev")
        self.assertEqual(payload["signals"][0]["direction"], "long")
        self.assertEqual(payload["signals"][0]["preferred_stop"], 93.0)
        self.assertAlmostEqual(payload["signals"][0]["preferred_target"], 101.66666666666667)
        self.assertEqual(payload["riskDecisionCount"], 1)
        self.assertTrue(payload["riskDecisions"][0]["allowed"])
        self.assertEqual(payload["orderCount"], 1)
        self.assertEqual(payload["orders"][0]["action"], "open")

    def test_generic_research_preview_defaults_to_direct_compute_sweep_reversal_signal_module(self):
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [119.0, 110.0, 100.0, 99.0],
                "High": [121.0, 112.0, 102.0, 101.0],
                "Low": [118.0, 108.0, 99.0, 98.5],
                "Close": [120.0, 110.0, 100.0, 99.5],
                "Volume": [100.0, 120.0, 140.0, 160.0],
            },
            index=pd.date_range("2026-06-01", periods=4, freq="D", tz="UTC"),
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

        with TemporaryDirectory() as tmpdir:
            market_path = Path(tmpdir) / "markets.json"
            market_path.write_text(json.dumps({"markets": market_records}), encoding="utf-8")
            original_market_path = signal_preview._MARKET_CATALOG_PATH
            try:
                signal_preview._MARKET_CATALOG_PATH = market_path
                payload = signal_preview.get_signal_research_preview(
                    timeframe="1d",
                    symbol="AAPL",
                    exchange="nasdaq",
                    market_type="equity",
                    equity=10_000.0,
                    load_ohlcv=lambda timeframe, market: bars,
                )
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path

        self.assertEqual(payload["signalCount"], 1)
        self.assertEqual(payload["signals"][0]["module"], "sweep_reversal")
        self.assertEqual(payload["signals"][0]["direction"], "long")
        self.assertEqual(payload["signals"][0]["preferred_stop"], 98.5)
        self.assertEqual(payload["signals"][0]["preferred_target"], 121.0)
        self.assertEqual(payload["riskDecisionCount"], 1)
        self.assertTrue(payload["riskDecisions"][0]["allowed"])
        self.assertEqual(payload["orderCount"], 1)
        self.assertEqual(payload["orders"][0]["action"], "open")

    def test_generic_research_preview_defaults_to_direct_compute_crash_short_signal_module(self):
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [110.0, 105.0, 100.0, 99.0],
                "High": [112.0, 106.0, 101.0, 100.0],
                "Low": [80.0, 104.0, 99.0, 93.0],
                "Close": [110.0, 105.0, 100.0, 94.0],
                "Volume": [100.0, 110.0, 120.0, 300.0],
            },
            index=pd.date_range("2026-06-01", periods=4, freq="D", tz="UTC"),
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
            "supports_short": True,
            "supports_leverage": False,
        }]

        with TemporaryDirectory() as tmpdir:
            market_path = Path(tmpdir) / "markets.json"
            market_path.write_text(json.dumps({"markets": market_records}), encoding="utf-8")
            original_market_path = signal_preview._MARKET_CATALOG_PATH
            try:
                signal_preview._MARKET_CATALOG_PATH = market_path
                payload = signal_preview.get_signal_research_preview(
                    timeframe="1d",
                    symbol="AAPL",
                    exchange="nasdaq",
                    market_type="equity",
                    equity=10_000.0,
                    load_ohlcv=lambda timeframe, market: bars,
                )
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path

        self.assertEqual(payload["signalCount"], 1)
        self.assertEqual(payload["signals"][0]["module"], "crash_short")
        self.assertEqual(payload["signals"][0]["direction"], "short")
        self.assertEqual(payload["signals"][0]["preferred_stop"], 101.0)
        self.assertEqual(payload["signals"][0]["preferred_target"], 80.0)
        self.assertEqual(payload["riskDecisionCount"], 1)
        self.assertTrue(payload["riskDecisions"][0]["allowed"])
        self.assertEqual(payload["orderCount"], 1)
        self.assertEqual(payload["orders"][0]["action"], "open")

    def test_generic_research_preview_defaults_to_direct_compute_failed_bounce_signal_module(self):
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [109.0, 107.0, 105.0, 106.0, 102.0],
                "High": [111.0, 109.0, 108.0, 110.5, 102.5],
                "Low": [108.0, 95.0, 104.0, 102.0, 100.0],
                "Close": [110.0, 108.0, 106.0, 103.0, 100.5],
                "Volume": [100.0, 110.0, 120.0, 130.0, 150.0],
            },
            index=pd.date_range("2026-06-01", periods=5, freq="D", tz="UTC"),
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
            "supports_short": True,
            "supports_leverage": False,
        }]

        with TemporaryDirectory() as tmpdir:
            market_path = Path(tmpdir) / "markets.json"
            market_path.write_text(json.dumps({"markets": market_records}), encoding="utf-8")
            original_market_path = signal_preview._MARKET_CATALOG_PATH
            try:
                signal_preview._MARKET_CATALOG_PATH = market_path
                payload = signal_preview.get_signal_research_preview(
                    timeframe="1d",
                    symbol="AAPL",
                    exchange="nasdaq",
                    market_type="equity",
                    equity=10_000.0,
                    load_ohlcv=lambda timeframe, market: bars,
                )
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path

        self.assertEqual(payload["signalCount"], 1)
        self.assertEqual(payload["signals"][0]["module"], "failed_bounce")
        self.assertEqual(payload["signals"][0]["direction"], "short")
        self.assertEqual(payload["signals"][0]["preferred_stop"], 110.5)
        self.assertEqual(payload["signals"][0]["preferred_target"], 95.0)
        self.assertEqual(payload["riskDecisionCount"], 1)
        self.assertTrue(payload["riskDecisions"][0]["allowed"])
        self.assertEqual(payload["orderCount"], 1)
        self.assertEqual(payload["orders"][0]["action"], "open")

    def test_generic_research_preview_defaults_to_direct_compute_bull_trap_signal_module(self):
        from serve import signal_preview

        bars = pd.DataFrame(
            {
                "Open": [109.0, 107.0, 105.0, 106.0, 104.0],
                "High": [111.0, 109.0, 108.0, 113.0, 106.0],
                "Low": [108.0, 95.0, 104.0, 100.0, 100.5],
                "Close": [110.0, 108.0, 106.0, 103.0, 101.5],
                "Volume": [100.0, 110.0, 120.0, 260.0, 150.0],
            },
            index=pd.date_range("2026-06-01", periods=5, freq="D", tz="UTC"),
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
            "supports_short": True,
            "supports_leverage": False,
        }]

        with TemporaryDirectory() as tmpdir:
            market_path = Path(tmpdir) / "markets.json"
            market_path.write_text(json.dumps({"markets": market_records}), encoding="utf-8")
            original_market_path = signal_preview._MARKET_CATALOG_PATH
            try:
                signal_preview._MARKET_CATALOG_PATH = market_path
                payload = signal_preview.get_signal_research_preview(
                    timeframe="1d",
                    symbol="AAPL",
                    exchange="nasdaq",
                    market_type="equity",
                    equity=10_000.0,
                    load_ohlcv=lambda timeframe, market: bars,
                )
            finally:
                signal_preview._MARKET_CATALOG_PATH = original_market_path

        self.assertEqual(payload["signalCount"], 1)
        self.assertEqual(payload["signals"][0]["module"], "bull_trap")
        self.assertEqual(payload["signals"][0]["direction"], "short")
        self.assertEqual(payload["signals"][0]["preferred_stop"], 113.0)
        self.assertEqual(payload["signals"][0]["preferred_target"], 95.0)
        self.assertEqual(payload["riskDecisionCount"], 1)
        self.assertTrue(payload["riskDecisions"][0]["allowed"])
        self.assertEqual(payload["orderCount"], 1)
        self.assertEqual(payload["orders"][0]["action"], "open")

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
        self.assertEqual(payload["orders"][0]["action"], "open")
        self.assertEqual(payload["orders"][0]["module"], "breakout")
        self.assertEqual(payload["filledOrderCount"], 1)
        self.assertEqual(payload["filledOrders"][0]["action"], "open")
        self.assertEqual(payload["filledOrders"][0]["status"], "filled")
        self.assertEqual(payload["orderStatusCounts"]["filled"], 1)
        self.assertEqual(payload["orderStatusCounts"]["submitted"], 0)
        self.assertEqual(payload["trades"][0]["module"], "breakout")
        self.assertEqual(payload["trades"][0]["exit_reason"], "target")
        self.assertEqual(payload["trades"][0]["entry_time"], "2024-01-01T04:00:00+00:00")
        self.assertEqual(payload["trades"][0]["exit_time"], "2024-01-01T12:00:00+00:00")
        self.assertEqual(payload["trades"][0]["entry_bar_index"], 1)
        self.assertEqual(payload["trades"][0]["exit_bar_index"], 3)
        self.assertEqual(payload["trades"][0]["holding_bars"], 2)
        self.assertAlmostEqual(payload["trades"][0]["gross_pnl"], 400.0)
        self.assertAlmostEqual(payload["summary"]["finalEquity"], 10_400.0)
        self.assertAlmostEqual(payload["summary"]["totalReturnPct"], 0.04)
        self.assertAlmostEqual(payload["summary"]["finalUnrealizedPnl"], 0.0)
        self.assertAlmostEqual(payload["summary"]["maxDrawdownPct"], 0.0)
        self.assertAlmostEqual(payload["summary"]["maxDrawdownAmount"], 0.0)
        self.assertIsNone(payload["summary"]["returnToMaxDrawdown"])
        self.assertEqual(payload["summary"]["maxDrawdownDurationBars"], 0)
        self.assertEqual(payload["summary"]["drawdownPointCount"], 0)
        self.assertEqual(payload["summary"]["timeInDrawdownPct"], 0.0)
        self.assertEqual(payload["summary"]["eventReturnCount"], len(payload["equityCurve"]))
        self.assertGreaterEqual(payload["summary"]["bestEventReturnPct"], 0.0)
        self.assertLessEqual(payload["summary"]["worstEventReturnPct"], payload["summary"]["bestEventReturnPct"])
        self.assertGreaterEqual(payload["summary"]["positiveEventReturnCount"], 0)
        self.assertGreaterEqual(payload["summary"]["negativeEventReturnCount"], 0)
        self.assertGreaterEqual(payload["summary"]["eventReturnWinRate"], 0.0)
        self.assertGreaterEqual(payload["summary"]["maxConsecutivePositiveEventReturns"], 0)
        self.assertGreaterEqual(payload["summary"]["maxConsecutiveNegativeEventReturns"], 0)
        self.assertGreaterEqual(payload["summary"]["averagePositiveEventReturnPct"], 0.0)
        self.assertGreaterEqual(payload["summary"]["averageNegativeEventReturnPct"], 0.0)
        self.assertIsNone(payload["summary"]["eventReturnPayoffRatio"])
        self.assertIsNone(payload["summary"]["eventReturnProfitFactor"])
        self.assertGreaterEqual(payload["summary"]["eventReturnVolatilityPct"], 0.0)
        self.assertIn("eventReturnRiskRatio", payload["summary"])
        self.assertEqual(payload["summary"]["eventReturnDownsideVolatilityPct"], 0.0)
        self.assertIsNone(payload["summary"]["eventReturnSortinoRatio"])
        self.assertEqual(payload["summary"]["tradeCount"], 1)
        self.assertAlmostEqual(payload["summary"]["winRate"], 1.0)
        self.assertAlmostEqual(payload["summary"]["averageTradeNetPnl"], 400.0)
        self.assertAlmostEqual(payload["summary"]["averageHoldingBars"], 2.0)
        self.assertAlmostEqual(payload["summary"]["grossProfit"], 400.0)
        self.assertAlmostEqual(payload["summary"]["grossLoss"], 0.0)
        self.assertIsNone(payload["summary"]["profitFactor"])
        self.assertAlmostEqual(payload["summary"]["averageWinNetPnl"], 400.0)
        self.assertIsNone(payload["summary"]["averageLossNetPnl"])
        self.assertIsNone(payload["summary"]["payoffRatio"])
        self.assertAlmostEqual(payload["summary"]["realizedTradeNotional"], 8_800.0)
        self.assertAlmostEqual(payload["summary"]["realizedTurnoverRatio"], 0.88)
        self.assertEqual(payload["attribution"]["bySymbol"]["BTC/USDT"]["tradeCount"], 1)
        self.assertAlmostEqual(payload["attribution"]["bySymbol"]["BTC/USDT"]["averageHoldingBars"], 2.0)
        self.assertAlmostEqual(payload["attribution"]["bySymbol"]["BTC/USDT"]["realizedTradeNotional"], 8_800.0)
        self.assertAlmostEqual(payload["attribution"]["bySymbol"]["BTC/USDT"]["grossProfit"], 400.0)
        self.assertAlmostEqual(payload["attribution"]["bySymbol"]["BTC/USDT"]["grossLoss"], 0.0)
        self.assertIsNone(payload["attribution"]["bySymbol"]["BTC/USDT"]["profitFactor"])
        self.assertAlmostEqual(payload["attribution"]["bySymbol"]["BTC/USDT"]["averageWinNetPnl"], 400.0)
        self.assertIsNone(payload["attribution"]["bySymbol"]["BTC/USDT"]["averageLossNetPnl"])
        self.assertIsNone(payload["attribution"]["bySymbol"]["BTC/USDT"]["payoffRatio"])
        self.assertEqual(payload["attribution"]["byDirection"]["long"]["tradeCount"], 1)
        self.assertAlmostEqual(payload["attribution"]["byDirection"]["long"]["averageHoldingBars"], 2.0)
        self.assertAlmostEqual(payload["attribution"]["byDirection"]["long"]["realizedTradeNotional"], 8_800.0)
        self.assertEqual(payload["attribution"]["byExitReason"]["target"]["tradeCount"], 1)
        self.assertAlmostEqual(payload["attribution"]["byExitReason"]["target"]["averageHoldingBars"], 2.0)
        self.assertAlmostEqual(payload["attribution"]["byExitReason"]["target"]["realizedTradeNotional"], 8_800.0)
        self.assertEqual(payload["equityCurve"][-1]["equity"], 10_400.0)
        self.assertEqual(payload["equityCurve"][-1]["equityPeak"], 10_400.0)
        self.assertGreaterEqual(payload["equityCurve"][-1]["returnPct"], 0.0)
        self.assertEqual(payload["equityCurve"][-1]["drawdownAmount"], 0.0)
        self.assertEqual(payload["equityCurve"][-1]["drawdownPct"], 0.0)
        self.assertEqual(payload["equityCurve"][-1]["drawdownDurationBars"], 0)
        self.assertEqual(len(payload["exposureCurve"]), 4)
        open_exposure = payload["exposureCurve"][1]
        self.assertEqual(open_exposure["symbol"], "BTC/USDT")
        self.assertEqual(open_exposure["positionCount"], 1)
        self.assertAlmostEqual(open_exposure["longNotional"], 4_200.0)
        self.assertAlmostEqual(open_exposure["shortNotional"], 0.0)
        self.assertAlmostEqual(open_exposure["grossNotional"], 4_200.0)
        self.assertAlmostEqual(open_exposure["netNotional"], 4_200.0)
        self.assertAlmostEqual(open_exposure["openRisk"], 200.0)
        self.assertEqual(payload["exposureCurve"][-1]["positionCount"], 0)

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

    def test_migration_comparison_exposes_platform_risk_audit_summary(self):
        from serve.signal_preview import get_btc_migration_comparison_preview

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
        risk_audits = [
            {
                "bar_index": 5,
                "module": "breakout",
                "symbol": "BTC/USDT",
                "direction": "long",
                "parity_status": "matched",
                "would_block_if_enforced": False,
                "risk_amount_delta": 0.0,
            },
            {
                "bar_index": 6,
                "module": "core_long",
                "symbol": "BTC/USDT",
                "direction": "long",
                "parity_status": "engine_blocked",
                "would_block_if_enforced": True,
                "risk_amount_delta": -200.0,
            },
        ]

        payload = get_btc_migration_comparison_preview(
            timeframe="4h",
            symbol="BTC/USDT",
            equity=10_000.0,
            load_ohlcv=lambda _: bars,
            build_features=lambda frame: frame,
            generate_signals=lambda features, symbol: [],
            load_trade_log=lambda: pd.DataFrame(),
            load_legacy_summary=lambda: {},
            load_risk_audits=lambda: risk_audits,
        )

        self.assertEqual(payload["riskAudit"]["auditCount"], 2)
        self.assertEqual(payload["riskAudit"]["wouldBlockIfEnforcedCount"], 1)
        self.assertEqual(payload["riskAudit"]["mismatchCount"], 1)
        self.assertEqual(payload["riskAudit"]["parityStatusCounts"]["matched"], 1)
        self.assertEqual(payload["riskAudit"]["parityStatusCounts"]["engine_blocked"], 1)
        self.assertEqual(payload["riskAudit"]["audits"][1]["module"], "core_long")
        self.assertTrue(payload["riskAudit"]["audits"][1]["would_block_if_enforced"])

    def test_migration_comparison_exposes_platform_pipeline_audit_summary(self):
        from quant_btc.risk_model import build_btc_legacy_entry_risk_decision
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner
        from quant_platform.signals import Direction, Signal
        from serve.signal_preview import get_btc_migration_comparison_preview

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
        signal = Signal(
            module="breakout",
            symbol="BTC/USDT",
            direction=Direction.LONG,
            score=88.0,
            entry_reason="legacy breakout",
            invalidation="legacy stop",
        )
        decision = build_btc_legacy_entry_risk_decision(
            signal=signal,
            equity=10_000.0,
            entry_price=100.0,
            stop_price=90.0,
            target_price=120.0,
            size_fraction=0.20,
        )
        result = SignalPipeline(
            signal_runner=SignalModuleRunner([]),
            risk_engine=RiskEngine(RiskLimits()),
            portfolio_engine=PortfolioEngine(layer_by_module={"breakout": "tactical"}),
        ).run_decisions([decision], account=AccountState(equity=10_000.0))

        payload = get_btc_migration_comparison_preview(
            timeframe="4h",
            symbol="BTC/USDT",
            equity=10_000.0,
            load_ohlcv=lambda _: bars,
            build_features=lambda frame: frame,
            generate_signals=lambda features, symbol: [],
            load_trade_log=lambda: pd.DataFrame(),
            load_legacy_summary=lambda: {},
            load_risk_audits=lambda: [],
            load_pipeline_audits=lambda: [result],
        )

        self.assertEqual(payload["pipelineAudit"]["auditCount"], 1)
        self.assertEqual(payload["pipelineAudit"]["signalCount"], 1)
        self.assertEqual(payload["pipelineAudit"]["riskDecisionCount"], 1)
        self.assertEqual(payload["pipelineAudit"]["orderCount"], 1)
        self.assertEqual(payload["pipelineAudit"]["audits"][0]["signals"][0]["module"], "breakout")
        self.assertEqual(payload["pipelineAudit"]["audits"][0]["orders"][0]["action"], "open")
        self.assertEqual(payload["pipelineAudit"]["audits"][0]["riskDiagnostics"]["portfolio"]["used"], 200.0)

    def test_migration_comparison_summarizes_pipeline_to_event_order_parity(self):
        from quant_btc.risk_model import build_btc_legacy_entry_risk_decision
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner
        from quant_platform.signals import Direction, Signal
        from serve.signal_preview import get_btc_migration_comparison_preview

        bars = pd.DataFrame(
            {
                "Open": [99.0, 100.0],
                "High": [101.0, 106.0],
                "Low": [98.0, 99.0],
                "Close": [100.0, 105.0],
                "Volume": [10.0, 12.0],
            },
            index=pd.date_range("2024-01-01", periods=2, freq="4h", tz="UTC"),
        )
        signal = Signal(
            module="breakout",
            symbol="BTC/USDT",
            direction=Direction.LONG,
            score=88.0,
            entry_reason="legacy breakout",
            invalidation="legacy stop",
            preferred_stop=90.0,
            preferred_target=110.0,
        )
        decision = build_btc_legacy_entry_risk_decision(
            signal=signal,
            equity=10_000.0,
            entry_price=100.0,
            stop_price=90.0,
            target_price=110.0,
            size_fraction=0.20,
        )
        pipeline_result = SignalPipeline(
            signal_runner=SignalModuleRunner([]),
            risk_engine=RiskEngine(RiskLimits()),
            portfolio_engine=PortfolioEngine(layer_by_module={"breakout": "tactical"}),
        ).run_decisions([decision], account=AccountState(equity=10_000.0))

        def generate_signals(features, symbol):
            if len(features) != 1:
                return []
            return [signal]

        payload = get_btc_migration_comparison_preview(
            timeframe="4h",
            symbol="BTC/USDT",
            equity=10_000.0,
            load_ohlcv=lambda _: bars,
            build_features=lambda frame: frame,
            generate_signals=generate_signals,
            load_trade_log=lambda: pd.DataFrame(),
            load_legacy_summary=lambda: {},
            load_risk_audits=lambda: [
                {
                    "bar_index": 1,
                    "module": "breakout",
                    "symbol": "BTC/USDT",
                    "direction": "long",
                    "parity_status": "matched",
                    "would_block_if_enforced": False,
                    "risk_amount_delta": 0.0,
                }
            ],
            load_pipeline_audits=lambda: [pipeline_result],
        )

        self.assertEqual(payload["orderParity"]["legacyOrderCount"], 1)
        self.assertEqual(payload["orderParity"]["eventOrderCount"], 1)
        self.assertEqual(payload["orderParity"]["matchedCount"], 1)
        self.assertEqual(payload["orderParity"]["mismatchCount"], 0)
        self.assertEqual(payload["orderParity"]["missingFromEvent"], [])
        self.assertEqual(payload["orderParity"]["extraInEvent"], [])
        self.assertEqual(
            payload["orderParity"]["byModule"]["breakout"],
            {
                "legacyOrderCount": 1,
                "eventOrderCount": 1,
                "matchedCount": 1,
                "mismatchCount": 0,
            },
        )
        self.assertEqual(payload["migrationReadiness"]["readyCount"], 1)
        self.assertTrue(
            payload["migrationReadiness"]["byModule"]["breakout"]["readyToMigrate"]
        )
        self.assertEqual(
            payload["migrationReadiness"]["byModule"]["breakout"]["status"], "ready"
        )
        self.assertEqual(
            payload["migrationReadiness"]["byModule"]["breakout"]["reasons"], []
        )

    def test_migration_comparison_blocks_readiness_when_risk_or_order_parity_fails(self):
        from serve.signal_preview import get_btc_migration_comparison_preview

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
        pipeline_audit = {
            "signalCount": 1,
            "riskDecisionCount": 1,
            "orderCount": 1,
            "signals": [{"module": "core_long"}],
            "riskDecisions": [
                {"allowed": True, "signal": {"module": "core_long"}}
            ],
            "orders": [
                {
                    "action": "open",
                    "symbol": "BTC/USDT",
                    "layer": "core",
                    "module": "core_long",
                    "direction": "long",
                    "quantity": 1.0,
                    "entry_price": 100.0,
                    "stop_price": 90.0,
                    "target_price": 120.0,
                }
            ],
            "riskDiagnostics": {},
        }
        risk_audits = [
            {
                "bar_index": 1,
                "module": "core_long",
                "symbol": "BTC/USDT",
                "direction": "long",
                "parity_status": "engine_blocked",
                "would_block_if_enforced": True,
                "risk_amount_delta": -200.0,
            }
        ]

        payload = get_btc_migration_comparison_preview(
            timeframe="4h",
            symbol="BTC/USDT",
            equity=10_000.0,
            load_ohlcv=lambda _: bars,
            build_features=lambda frame: frame,
            generate_signals=lambda features, symbol: [],
            load_trade_log=lambda: pd.DataFrame(),
            load_legacy_summary=lambda: {},
            load_risk_audits=lambda: risk_audits,
            load_pipeline_audits=lambda: [pipeline_audit],
        )

        readiness = payload["migrationReadiness"]["byModule"]["core_long"]
        self.assertFalse(readiness["readyToMigrate"])
        self.assertEqual(readiness["status"], "blocked")
        self.assertIn("risk_parity_mismatch", readiness["reasons"])
        self.assertIn("platform_would_block", readiness["reasons"])
        self.assertIn("order_parity_mismatch", readiness["reasons"])

    def test_load_btc_legacy_risk_audits_reads_strategy_audits_from_backtest(self):
        from serve.signal_preview import load_btc_legacy_risk_audits

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
        calls = []

        class Audit:
            def to_dict(self):
                return {
                    "module": "breakout",
                    "parity_status": "matched",
                    "would_block_if_enforced": False,
                }

        class Strategy:
            _platform_risk_audits = [Audit()]

        def run_legacy_backtest(features, cfg, *, strategy_name, risk_cfg):
            calls.append({
                "features": features,
                "initial_cash": cfg.initial_cash,
                "strategy_name": strategy_name,
                "risk_cfg": risk_cfg,
            })
            return {"_strategy": Strategy()}, object()

        audits = load_btc_legacy_risk_audits(
            timeframe="4h",
            symbol="BTC/USDT",
            equity=25_000.0,
            load_ohlcv=lambda _: bars,
            build_features=lambda frame: frame.assign(prepared=True),
            run_legacy_backtest=run_legacy_backtest,
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["initial_cash"], 25_000.0)
        self.assertEqual(calls[0]["strategy_name"], "dual")
        self.assertIn("prepared", calls[0]["features"].columns)
        self.assertIsNotNone(calls[0]["risk_cfg"])
        self.assertEqual(audits[0].to_dict()["module"], "breakout")

    def test_migration_comparison_loads_default_legacy_risk_audits(self):
        from serve import signal_preview

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
        calls = []

        def load_ohlcv(timeframe):
            return bars

        def load_btc_legacy_risk_audits(**kwargs):
            calls.append(kwargs)
            return [
                {
                    "module": "breakout",
                    "parity_status": "matched",
                    "would_block_if_enforced": False,
                }
            ]

        original_loader = signal_preview.load_btc_legacy_risk_audits
        try:
            signal_preview.load_btc_legacy_risk_audits = load_btc_legacy_risk_audits
            payload = signal_preview.get_btc_migration_comparison_preview(
                timeframe="4h",
                symbol="BTC/USDT",
                equity=25_000.0,
                load_ohlcv=load_ohlcv,
                build_features=lambda frame: frame,
                generate_signals=lambda features, symbol: [],
                load_trade_log=lambda: pd.DataFrame(),
                load_legacy_summary=lambda: {},
            )
        finally:
            signal_preview.load_btc_legacy_risk_audits = original_loader

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["timeframe"], "4h")
        self.assertEqual(calls[0]["symbol"], "BTC/USDT")
        self.assertEqual(calls[0]["equity"], 25_000.0)
        self.assertIs(calls[0]["load_ohlcv"], load_ohlcv)
        self.assertEqual(payload["riskAudit"]["auditCount"], 1)
        self.assertEqual(payload["riskAudit"]["parityStatusCounts"]["matched"], 1)


if __name__ == "__main__":
    unittest.main()
