import tempfile
import unittest
from pathlib import Path

import pandas as pd


class FeatureStoreTest(unittest.TestCase):
    def test_feature_series_id_builds_deterministic_cache_key(self):
        from quant_platform.data import DerivativeSeriesId, ExternalMetricSeriesId, FeatureSeriesId

        series_id = FeatureSeriesId(
            symbol="BTC/USDT",
            exchange="binance",
            market_type="swap",
            timeframe="4h",
            source="feature_engine",
            feature_set="btc_base_v1",
        )

        self.assertEqual(
            series_id.cache_key,
            "feature_engine/binance/swap/BTC_USDT/4h/btc_base_v1",
        )

        derivative_id = DerivativeSeriesId("BTC/USDT", "binance", "swap", "4h", "ccxt")
        self.assertEqual(derivative_id.cache_key, "ccxt/binance/swap/BTC_USDT/4h/derivatives")

        external_id = ExternalMetricSeriesId("BTC/USDT", "valuescan", "ai_social_sentiment", "4h", "api")
        self.assertEqual(external_id.cache_key, "api/valuescan/BTC_USDT/4h/ai_social_sentiment")

    def test_parquet_feature_store_builds_deterministic_path(self):
        from quant_platform.data import FeatureSeriesId
        from quant_platform.stores import ParquetFeatureStore

        store = ParquetFeatureStore(Path("features"))
        series_id = FeatureSeriesId("BTC/USDT", "binance", "swap", "4h", "feature_engine", "btc_base_v1")

        self.assertEqual(
            store.path_for(series_id),
            Path("features") / "feature_engine" / "binance" / "swap" / "BTC_USDT" / "4h" / "btc_base_v1.parquet",
        )

    def test_parquet_feature_store_round_trip_or_reports_missing_engine(self):
        from quant_platform.data import FeatureSeriesId
        from quant_platform.stores import MissingStorageDependency, ParquetFeatureStore

        features = pd.DataFrame(
            {"ema55": [101.0], "rsi_14": [52.5], "funding_rate": [0.0001]},
            index=pd.to_datetime([1700000000000], unit="ms", utc=True),
        )
        series_id = FeatureSeriesId("BTC/USDT", "binance", "swap", "4h", "feature_engine", "btc_base_v1")

        with tempfile.TemporaryDirectory() as tmp:
            store = ParquetFeatureStore(Path(tmp))
            try:
                store.write(series_id, features)
            except MissingStorageDependency as exc:
                self.assertIn("pyarrow", str(exc))
                return

            loaded = store.read(series_id)
            self.assertEqual(float(loaded.iloc[0]["ema55"]), 101.0)
            self.assertEqual(float(loaded.iloc[0]["funding_rate"]), 0.0001)
            self.assertEqual(str(loaded.index.tz), "UTC")

    def test_sqlite_feature_store_builds_deterministic_path(self):
        from quant_platform.data import FeatureSeriesId
        from quant_platform.stores import SQLiteFeatureStore

        store = SQLiteFeatureStore(Path("features_sqlite"))
        series_id = FeatureSeriesId("BTC/USDT", "binance", "swap", "4h", "feature_engine", "btc/base/v1")

        self.assertEqual(
            store.path_for(series_id),
            Path("features_sqlite")
            / "feature_engine"
            / "binance"
            / "swap"
            / "BTC_USDT"
            / "4h"
            / "btc_base_v1.sqlite",
        )

    def test_sqlite_feature_store_round_trip_preserves_columns_and_utc_index(self):
        from quant_platform.data import FeatureSeriesId
        from quant_platform.stores import SQLiteFeatureStore

        features = pd.DataFrame(
            {
                "ema55": [101.0, 102.0],
                "rsi_14": [52.5, 53.5],
                "funding_rate": [0.0001, 0.0002],
            },
            index=pd.to_datetime([1700000000000, 1700003600000], unit="ms", utc=True),
        )
        series_id = FeatureSeriesId("BTC/USDT", "binance", "swap", "4h", "feature_engine", "btc_base_v1")

        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteFeatureStore(Path(tmp))
            path = store.write(series_id, features)
            loaded = store.read(series_id)

        self.assertEqual(path.name, "btc_base_v1.sqlite")
        self.assertEqual(list(loaded.columns), ["ema55", "rsi_14", "funding_rate"])
        self.assertEqual(len(loaded), 2)
        self.assertEqual(float(loaded.iloc[-1]["rsi_14"]), 53.5)
        self.assertEqual(float(loaded.iloc[-1]["funding_rate"]), 0.0002)
        self.assertEqual(str(loaded.index.tz), "UTC")

    def test_parquet_external_metric_store_builds_deterministic_path(self):
        from quant_platform.data import ExternalMetricSeriesId
        from quant_platform.stores import ParquetExternalMetricStore

        store = ParquetExternalMetricStore(Path("external_metrics"))
        series_id = ExternalMetricSeriesId("BTC/USDT", "valuescan", "ai_tracking", "4h", "api")

        self.assertEqual(
            store.path_for(series_id),
            Path("external_metrics") / "api" / "valuescan" / "BTC_USDT" / "4h" / "ai_tracking.parquet",
        )

    def test_parquet_external_metric_store_round_trip_or_reports_missing_engine(self):
        from quant_platform.data import ExternalMetricSeriesId
        from quant_platform.stores import MissingStorageDependency, ParquetExternalMetricStore

        metrics = pd.DataFrame(
            {"bullish_ratio": [0.45], "risk_score": [58.0]},
            index=pd.to_datetime([1775734240000], unit="ms", utc=True),
        )
        series_id = ExternalMetricSeriesId("BTC/USDT", "valuescan", "ai_tracking", "4h", "api")

        with tempfile.TemporaryDirectory() as tmp:
            store = ParquetExternalMetricStore(Path(tmp))
            try:
                store.write(series_id, metrics)
            except MissingStorageDependency as exc:
                self.assertIn("pyarrow", str(exc))
                return

            loaded = store.read(series_id)
            self.assertEqual(float(loaded.iloc[0]["bullish_ratio"]), 0.45)
            self.assertEqual(float(loaded.iloc[0]["risk_score"]), 58.0)
            self.assertEqual(str(loaded.index.tz), "UTC")

    def test_sqlite_external_metric_store_builds_deterministic_path(self):
        from quant_platform.data import ExternalMetricSeriesId
        from quant_platform.stores import SQLiteExternalMetricStore

        store = SQLiteExternalMetricStore(Path("external_sqlite"))
        series_id = ExternalMetricSeriesId("BTC/USDT", "valuescan", "ai/tracking", "4h", "api")

        self.assertEqual(
            store.path_for(series_id),
            Path("external_sqlite") / "api" / "valuescan" / "BTC_USDT" / "4h" / "ai_tracking.sqlite",
        )

    def test_sqlite_external_metric_store_round_trip_preserves_columns_and_utc_index(self):
        from quant_platform.data import ExternalMetricSeriesId
        from quant_platform.stores import SQLiteExternalMetricStore

        metrics = pd.DataFrame(
            {
                "bullish_ratio": [0.45, 0.47],
                "risk_score": [58.0, 55.0],
                "social_sentiment": [0.12, 0.18],
            },
            index=pd.to_datetime([1775734240000, 1775737840000], unit="ms", utc=True),
        )
        series_id = ExternalMetricSeriesId("BTC/USDT", "valuescan", "ai_tracking", "1h", "api")

        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteExternalMetricStore(Path(tmp))
            path = store.write(series_id, metrics)
            loaded = store.read(series_id)

        self.assertEqual(path.name, "ai_tracking.sqlite")
        self.assertEqual(list(loaded.columns), ["bullish_ratio", "risk_score", "social_sentiment"])
        self.assertEqual(len(loaded), 2)
        self.assertEqual(float(loaded.iloc[-1]["risk_score"]), 55.0)
        self.assertEqual(float(loaded.iloc[-1]["social_sentiment"]), 0.18)
        self.assertEqual(str(loaded.index.tz), "UTC")

    def test_parquet_derivative_store_builds_deterministic_path(self):
        from quant_platform.data import DerivativeSeriesId
        from quant_platform.stores import ParquetDerivativeStore

        store = ParquetDerivativeStore(Path("derivatives"))
        series_id = DerivativeSeriesId("BTC/USDT", "binance", "swap", "4h", "ccxt")

        self.assertEqual(
            store.path_for(series_id),
            Path("derivatives") / "ccxt" / "binance" / "swap" / "BTC_USDT" / "4h.parquet",
        )

    def test_sqlite_derivative_store_builds_deterministic_path(self):
        from quant_platform.data import DerivativeSeriesId
        from quant_platform.stores import SQLiteDerivativeStore

        store = SQLiteDerivativeStore(Path("derivatives_sqlite"))
        series_id = DerivativeSeriesId("BTC/USDT", "binance", "swap", "4h", "ccxt")

        self.assertEqual(
            store.path_for(series_id),
            Path("derivatives_sqlite") / "ccxt" / "binance" / "swap" / "BTC_USDT" / "4h.sqlite",
        )

    def test_sqlite_derivative_store_round_trip_preserves_columns_and_utc_index(self):
        from quant_platform.data import DerivativeSeriesId
        from quant_platform.stores import SQLiteDerivativeStore

        derivatives = pd.DataFrame(
            {
                "funding_rate": [0.0001, 0.0002],
                "open_interest": [1000.0, 1100.0],
            },
            index=pd.to_datetime([1700000000000, 1700003600000], unit="ms", utc=True),
        )
        series_id = DerivativeSeriesId("BTC/USDT", "binance", "swap", "1h", "ccxt")

        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteDerivativeStore(Path(tmp))
            path = store.write(series_id, derivatives)
            loaded = store.read(series_id)

        self.assertEqual(path.name, "1h.sqlite")
        self.assertEqual(list(loaded.columns), ["funding_rate", "open_interest"])
        self.assertEqual(len(loaded), 2)
        self.assertEqual(float(loaded.iloc[-1]["funding_rate"]), 0.0002)
        self.assertEqual(float(loaded.iloc[-1]["open_interest"]), 1100.0)
        self.assertEqual(str(loaded.index.tz), "UTC")


if __name__ == "__main__":
    unittest.main()
