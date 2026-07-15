import unittest
from pathlib import Path

import pandas as pd


def sample_bars() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=40, freq="4h", tz="UTC")
    close = pd.Series(range(100, 140), index=index, dtype=float)
    return pd.DataFrame(
        {
            "Open": close - 0.5,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": close * 10,
        },
        index=index,
    )


class FeatureEngineTest(unittest.TestCase):
    def test_feature_engine_applies_registered_modules_in_order_without_mutating_input(self):
        from quant_platform.features import FeatureEngine

        calls = []

        class AddOne:
            name = "add_one"

            def apply(self, bars):
                calls.append(self.name)
                out = bars.copy()
                out["one"] = 1
                return out

        class AddTwo:
            name = "add_two"

            def apply(self, bars):
                calls.append(self.name)
                out = bars.copy()
                out["two"] = out["one"] + 1
                return out

        bars = sample_bars()
        result = FeatureEngine([AddOne(), AddTwo()]).run(bars)

        self.assertEqual(calls, ["add_one", "add_two"])
        self.assertEqual(int(result["two"].iloc[-1]), 2)
        self.assertNotIn("one", bars.columns)

    def test_default_feature_module_registry_builds_engine_from_config_records(self):
        from quant_platform.features import default_feature_module_registry

        bars = sample_bars().iloc[:8]
        registry = default_feature_module_registry()
        engine = registry.build_engine([
            {
                "type": "technical_indicators",
                "params": {
                    "ema_lengths": [3],
                    "macd_fast": 3,
                    "macd_slow": 6,
                    "macd_signal": 2,
                    "rsi_period": 4,
                },
            },
            {"type": "donchian", "params": {"channel_periods": {"short": 3}}},
            {"type": "volume", "params": {"lookback": 3, "zscore_column": "vol_z"}},
            {"type": "price_action"},
        ])

        result = engine.run(bars)

        for column in ["ema3", "macd_hist", "rsi_4", "short_high_3", "vol_z", "_lower_shadow"]:
            self.assertIn(column, result.columns)
        self.assertNotIn("ema3", bars.columns)

    def test_feature_engine_cache_helper_persists_output_without_mutating_input(self):
        from quant_platform.data import FeatureSeriesId
        from quant_platform.features import FeatureEngine, run_feature_engine_with_cache

        class AddFeature:
            name = "add_feature"

            def apply(self, bars):
                out = bars.copy()
                out["feature_value"] = out["Close"] * 2
                return out

        class FakeStore:
            def __init__(self):
                self.calls = []

            def write(self, series_id, features):
                self.calls.append((series_id, features.copy()))
                return Path("features/api/binance/swap/BTC_USDT/4h/test.parquet")

        bars = sample_bars().iloc[:3]
        series_id = FeatureSeriesId("BTC/USDT", "binance", "swap", "4h", "feature_engine", "test")
        store = FakeStore()

        result = run_feature_engine_with_cache(FeatureEngine([AddFeature()]), bars, series_id=series_id, store=store)

        self.assertIn("feature_value", result.features.columns)
        self.assertNotIn("feature_value", bars.columns)
        self.assertEqual(store.calls[0][0], series_id)
        self.assertIn("feature_value", store.calls[0][1].columns)
        self.assertEqual(result.cache["cacheKey"], series_id.cache_key)
        self.assertEqual(result.cache["path"], str(Path("features/api/binance/swap/BTC_USDT/4h/test.parquet")))
        self.assertEqual(result.cache["rows"], 3)

    def test_feature_engine_cache_helper_reads_cached_features_without_recomputing(self):
        from quant_platform.data import FeatureSeriesId
        from quant_platform.features import FeatureEngine, run_feature_engine_with_cache

        class ExplodingModule:
            name = "exploding"

            def apply(self, bars):
                raise AssertionError("feature engine should not run on cache hit")

        class FakeStore:
            def __init__(self, cached):
                self.cached = cached
                self.read_calls = []
                self.write_calls = []

            def read(self, series_id):
                self.read_calls.append(series_id)
                return self.cached

            def write(self, series_id, features):
                self.write_calls.append((series_id, features.copy()))
                return Path("features/feature_engine/nasdaq/equity/AAPL/1d/research_default_v1.parquet")

        bars = sample_bars().iloc[:3]
        cached = bars.assign(cached_feature=[1.0, 2.0, 3.0])
        series_id = FeatureSeriesId("AAPL", "nasdaq", "equity", "1d", "feature_engine", "research_default_v1")
        store = FakeStore(cached)

        result = run_feature_engine_with_cache(FeatureEngine([ExplodingModule()]), bars, series_id=series_id, store=store)

        self.assertEqual(store.read_calls, [series_id])
        self.assertEqual(store.write_calls, [])
        self.assertIs(result.features, cached)
        self.assertEqual(result.cache["cacheKey"], series_id.cache_key)
        self.assertTrue(result.cache["hit"])
        self.assertEqual(result.cache["rows"], 3)
        self.assertIn("cached_feature", result.cache["columns"])

    def test_technical_indicator_module_adds_reusable_base_columns(self):
        from quant_platform.features import TechnicalIndicatorConfig, TechnicalIndicatorModule

        bars = sample_bars()
        module = TechnicalIndicatorModule(
            TechnicalIndicatorConfig(
                ema_lengths=(3, 5),
                macd_fast=3,
                macd_slow=6,
                macd_signal=2,
                rsi_period=4,
                htf_ema_rules={"d_ema": "1D"},
                htf_ema_length=5,
            )
        )

        result = module.apply(bars)

        for col in ["ema3", "ema5", "macd", "macd_signal", "macd_hist", "d_ema", "rsi_4"]:
            self.assertIn(col, result.columns)
        self.assertAlmostEqual(
            float(result["macd_hist"].iloc[-1]),
            float(result["macd"].iloc[-1] - result["macd_signal"].iloc[-1]),
        )
        self.assertEqual(str(result.index.tz), "UTC")
        self.assertNotIn("ema3", bars.columns)

    def test_btc_feature_engine_builder_runs_platform_engine_for_base_indicators(self):
        from quant_btc.config import BacktestConfig
        from quant_btc.feature_engine import build_btc_feature_engine

        calls = {"engine": 0}
        real_builder = build_btc_feature_engine

        class SpyEngine:
            def __init__(self, wrapped):
                self.wrapped = wrapped

            def run(self, bars):
                calls["engine"] += 1
                return self.wrapped.run(bars)

        def spy_builder(cfg):
            return SpyEngine(real_builder(cfg))

        result = spy_builder(BacktestConfig()).run(sample_bars())

        self.assertEqual(calls["engine"], 1)
        self.assertIn("ema55", result.columns)
        self.assertIn("macd_hist", result.columns)
        self.assertIn("rsi_14", result.columns)

    def test_btc_feature_engine_cache_wrapper_uses_deterministic_feature_series_id(self):
        from quant_btc.config import BacktestConfig
        from quant_btc.feature_engine import build_cached_btc_features

        class FakeStore:
            def __init__(self):
                self.series_id = None

            def write(self, series_id, features):
                self.series_id = series_id
                self.rows = len(features)
                return Path("features/feature_engine/binance/swap/BTC_USDT/4h/btc_compat_v1.parquet")

        store = FakeStore()

        result = build_cached_btc_features(
            sample_bars(),
            BacktestConfig(),
            symbol="BTC/USDT",
            exchange="binance",
            market_type="swap",
            timeframe="4h",
            store=store,
        )

        self.assertIn("ema55", result.features.columns)
        self.assertEqual(store.series_id.cache_key, "feature_engine/binance/swap/BTC_USDT/4h/btc_compat_v1")
        self.assertEqual(result.cache["rows"], store.rows)

    def test_market_feature_modules_add_structure_volatility_volume_and_price_action_columns(self):
        from quant_platform.features import (
            BollingerFeatureModule,
            BollingerConfig,
            DonchianFeatureModule,
            DonchianConfig,
            PriceActionFeatureModule,
            VolatilityFeatureModule,
            VolatilityConfig,
            VolumeFeatureModule,
            VolumeConfig,
        )

        bars = sample_bars()
        result = DonchianFeatureModule(DonchianConfig(channel_periods={"roll": 5})).apply(bars)
        result = VolumeFeatureModule(VolumeConfig(lookback=5)).apply(result)
        result = VolatilityFeatureModule(VolatilityConfig(period=4, percentile_lookback=8)).apply(result)
        result = BollingerFeatureModule(BollingerConfig(period=5, std_mult=2.0)).apply(result)
        result = PriceActionFeatureModule().apply(result)

        for col in [
            "roll_high_5",
            "roll_low_5",
            "vol_sma_5",
            "vol_std_5",
            "vol_zscore_5",
            "_atr_4",
            "_atr_pct_4",
            "_adx_4",
            "bb_upper_5",
            "bb_lower_5",
            "_lower_shadow",
            "_upper_shadow",
        ]:
            self.assertIn(col, result.columns)
        self.assertGreater(float(result["_atr_4"].iloc[-1]), 0)
        self.assertGreaterEqual(float(result["_atr_pct_4"].iloc[-1]), 0)
        self.assertLessEqual(float(result["_atr_pct_4"].iloc[-1]), 1)
        self.assertNotIn("roll_high_5", bars.columns)

    def test_volume_feature_module_derives_turnover_features_when_available(self):
        from quant_platform.features import VolumeConfig, VolumeFeatureModule

        bars = sample_bars().assign(Turnover=lambda frame: frame["Close"] * frame["Volume"])

        result = VolumeFeatureModule(VolumeConfig(lookback=5)).apply(bars)

        self.assertIn("turnover_sma_5", result.columns)
        self.assertIn("turnover_std_5", result.columns)
        self.assertIn("turnover_zscore_5", result.columns)
        self.assertAlmostEqual(float(result["turnover_sma_5"].iloc[-1]), float(bars["Turnover"].tail(5).mean()))
        self.assertNotIn("turnover_sma_5", bars.columns)

    def test_volatility_feature_module_can_use_distinct_atr_and_adx_periods(self):
        from quant_platform.features import VolatilityConfig, VolatilityFeatureModule

        bars = sample_bars()
        result = VolatilityFeatureModule(
            VolatilityConfig(period=10, adx_period=21, percentile_lookback=30)
        ).apply(bars)

        self.assertIn("_atr_10", result.columns)
        self.assertIn("_atr_pct_10", result.columns)
        self.assertIn("_adx_21", result.columns)
        self.assertNotIn("_adx_10", result.columns)
        self.assertGreater(float(result["_atr_10"].iloc[-1]), 0)
        self.assertGreaterEqual(float(result["_atr_pct_10"].iloc[-1]), 0)
        self.assertLessEqual(float(result["_atr_pct_10"].iloc[-1]), 1)

    def test_btc_feature_engine_produces_prepare_features_market_columns(self):
        from quant_btc.config import BacktestConfig
        from quant_btc.feature_engine import build_btc_feature_engine

        result = build_btc_feature_engine(BacktestConfig()).run(sample_bars())

        for col in [
            "roll_high_55",
            "roll_low_55",
            "mr_dc20_high",
            "mr_dc20_low",
            "vol_sma_50",
            "vol_std_50",
            "vol_zscore",
            "_atr_signal",
            "_atr_pct_signal",
            "_adx_signal",
            "bb_upper",
            "bb_lower",
            "_upper_shadow",
            "_lower_shadow",
        ]:
            self.assertIn(col, result.columns)

    def test_derivatives_feature_module_aligns_funding_and_open_interest_features(self):
        from quant_platform.features import DerivativesFeatureConfig, DerivativesFeatureModule

        bars = sample_bars().iloc[:12]
        derivatives = pd.DataFrame(
            {
                "funding_rate": [0.0001, 0.0002, 0.0005],
                "open_interest": [1000.0, 1100.0, 1210.0],
            },
            index=bars.index[[0, 4, 8]],
        )

        result = DerivativesFeatureModule(
            derivatives,
            DerivativesFeatureConfig(funding_zscore_lookback=3, open_interest_change_periods=4),
        ).apply(bars)

        for col in [
            "funding_rate",
            "open_interest",
            "funding_zscore_3",
            "open_interest_change_4",
            "derivative_price_change_4",
        ]:
            self.assertIn(col, result.columns)
        self.assertEqual(float(result["funding_rate"].iloc[5]), 0.0002)
        self.assertAlmostEqual(float(result["open_interest_change_4"].iloc[8]), 0.1)
        self.assertNotIn("funding_rate", bars.columns)

    def test_order_book_feature_module_aligns_spread_and_depth_features(self):
        from quant_platform.features import OrderBookFeatureConfig, OrderBookFeatureModule

        bars = sample_bars().iloc[:6]
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
            index=bars.index[[0, 4]],
        )

        result = OrderBookFeatureModule(
            snapshots,
            OrderBookFeatureConfig(depth=2, prefix="book"),
        ).apply(bars)

        for col in [
            "book_best_bid",
            "book_best_ask",
            "book_spread",
            "book_mid",
            "book_relative_spread",
            "book_bid_size_sum_2",
            "book_ask_size_sum_2",
            "book_imbalance_2",
        ]:
            self.assertIn(col, result.columns)
        self.assertEqual(float(result["book_best_bid"].iloc[3]), 100.0)
        self.assertEqual(float(result["book_best_bid"].iloc[5]), 102.0)
        self.assertEqual(float(result["book_spread"].iloc[5]), 1.0)
        self.assertEqual(float(result["book_mid"].iloc[5]), 102.5)
        self.assertAlmostEqual(float(result["book_relative_spread"].iloc[5]), 1.0 / 102.5)
        self.assertEqual(float(result["book_bid_size_sum_2"].iloc[5]), 5.0)
        self.assertEqual(float(result["book_ask_size_sum_2"].iloc[5]), 3.0)
        self.assertEqual(float(result["book_imbalance_2"].iloc[5]), 0.25)
        self.assertNotIn("book_spread", bars.columns)

    def test_external_metric_feature_module_aligns_valuescan_style_metrics(self):
        from quant_platform.features import ExternalMetricFeatureConfig, ExternalMetricFeatureModule

        bars = sample_bars().iloc[:8]
        metrics = pd.DataFrame(
            {
                "bullish_ratio": [0.45, 0.62],
                "bearish_ratio": [0.30, 0.18],
                "risk_score": [12, 35],
                "note": ["neutral", "risk rising"],
            },
            index=bars.index[[0, 4]],
        )

        result = ExternalMetricFeatureModule(
            metrics,
            ExternalMetricFeatureConfig(
                prefix="valuescan",
                columns=("bullish_ratio", "bearish_ratio", "risk_score"),
            ),
        ).apply(bars)

        for col in [
            "valuescan_bullish_ratio",
            "valuescan_bearish_ratio",
            "valuescan_risk_score",
        ]:
            self.assertIn(col, result.columns)
        self.assertEqual(float(result["valuescan_bullish_ratio"].iloc[3]), 0.45)
        self.assertEqual(float(result["valuescan_bullish_ratio"].iloc[5]), 0.62)
        self.assertEqual(float(result["valuescan_risk_score"].iloc[5]), 35.0)
        self.assertNotIn("valuescan_bullish_ratio", bars.columns)


if __name__ == "__main__":
    unittest.main()
