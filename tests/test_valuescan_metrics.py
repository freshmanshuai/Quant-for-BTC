import unittest
from pathlib import Path
from unittest.mock import Mock

import pandas as pd


class ValuescanMetricsTest(unittest.TestCase):
    def test_overview_payload_converts_to_timestamped_external_metric_frame(self):
        from serve.valuescan_metrics import valuescan_overview_to_metric_frame

        payload = {
            "updatedAt": 1775734240000,
            "token": {"symbol": "BTC"},
            "socialSentiment": {
                "bullishRatio": 0.45,
                "neutralRatio": 0.35,
                "bearishRatio": 0.20,
            },
            "priceMarket": [
                {"date": 1775734240000, "priceMarketType": 1},
                {"date": 1775720000000, "priceMarketType": 2},
            ],
            "supportResistance": [
                {"price": "70000", "denseArea": 1},
                {"price": "68000", "denseArea": 2},
            ],
            "marketAnalysis": [
                {"uniqueId": "m1", "ts": 1775734240000, "content": "analysis"},
            ],
        }

        frame = valuescan_overview_to_metric_frame(payload)

        self.assertEqual(str(frame.index.tz), "UTC")
        self.assertEqual(frame.index[0].value // 1_000_000, 1775734240000)
        self.assertEqual(float(frame.iloc[0]["bullish_ratio"]), 0.45)
        self.assertEqual(float(frame.iloc[0]["bearish_ratio"]), 0.20)
        self.assertEqual(float(frame.iloc[0]["price_market_type"]), 1.0)
        self.assertEqual(float(frame.iloc[0]["dense_area_count"]), 2.0)
        self.assertEqual(float(frame.iloc[0]["support_price_mean"]), 69000.0)
        self.assertEqual(float(frame.iloc[0]["market_analysis_count"]), 1.0)

    def test_lists_payload_converts_symbol_scores_to_external_metric_frame(self):
        from serve.valuescan_metrics import valuescan_lists_to_metric_frame

        payload = {
            "updatedAt": 1775734240000,
            "opportunities": [{"symbol": "BTC", "score": 66, "grade": 2}],
            "risks": [{"symbol": "BTC", "score": 58, "grade": 1}],
            "funds": [{"symbol": "BTC", "tradeType": 2, "score": 73}],
            "messages": {
                "opportunities": [{"symbol": "BTC", "scoring": 65, "updateTime": 1775734240000}],
                "risks": [{"symbol": "BTC", "scoring": 55, "updateTime": 1775734240000}],
                "funds": [{"symbol": "BTC", "tradeType": 2, "updateTime": 1775734240000}],
            },
        }

        frame = valuescan_lists_to_metric_frame(payload, symbol="BTC")

        self.assertEqual(str(frame.index.tz), "UTC")
        self.assertEqual(float(frame.iloc[0]["opportunity_score"]), 66.0)
        self.assertEqual(float(frame.iloc[0]["opportunity_grade"]), 2.0)
        self.assertEqual(float(frame.iloc[0]["risk_score"]), 58.0)
        self.assertEqual(float(frame.iloc[0]["risk_grade"]), 1.0)
        self.assertEqual(float(frame.iloc[0]["funds_score"]), 73.0)
        self.assertEqual(float(frame.iloc[0]["funds_trade_type"]), 2.0)
        self.assertEqual(float(frame.iloc[0]["opportunity_message_score"]), 65.0)
        self.assertEqual(float(frame.iloc[0]["risk_message_score"]), 55.0)

    def test_valuescan_payloads_align_to_bars_as_research_external_features(self):
        from serve.valuescan_metrics import build_valuescan_external_feature_frame

        bars = pd.DataFrame(
            {
                "Open": [99.0, 100.0, 101.0],
                "High": [101.0, 102.0, 103.0],
                "Low": [98.0, 99.0, 100.0],
                "Close": [100.0, 101.0, 102.0],
                "Volume": [10.0, 11.0, 12.0],
            },
            index=pd.date_range("2026-06-03", periods=3, freq="4h", tz="UTC"),
        )
        timestamp_ms = int(bars.index[1].timestamp() * 1000)
        overview = {
            "updatedAt": timestamp_ms,
            "socialSentiment": {"bullishRatio": 0.55, "neutralRatio": 0.25, "bearishRatio": 0.20},
            "priceMarket": [{"date": timestamp_ms, "priceMarketType": 1}],
            "supportResistance": [{"price": "70000", "denseArea": 1}],
        }
        lists = {
            "updatedAt": timestamp_ms,
            "opportunities": [{"symbol": "BTC", "score": 66, "grade": 2}],
            "risks": [{"symbol": "BTC", "score": 44, "grade": 1}],
            "funds": [{"symbol": "BTC", "tradeType": 2, "score": 73}],
            "messages": {},
        }

        features = build_valuescan_external_feature_frame(bars, overview_payload=overview, lists_payload=lists, symbol="BTC")

        self.assertEqual(list(features.index), list(bars.index))
        self.assertNotIn("valuescan_bullish_ratio", bars.columns)
        self.assertEqual(float(features["valuescan_bullish_ratio"].iloc[0]), 0.0)
        self.assertEqual(float(features["valuescan_bullish_ratio"].iloc[1]), 0.55)
        self.assertEqual(float(features["valuescan_bullish_ratio"].iloc[2]), 0.55)
        self.assertEqual(float(features["valuescan_opportunity_score"].iloc[2]), 66.0)
        self.assertEqual(float(features["valuescan_funds_score"].iloc[2]), 73.0)

    def test_valuescan_feature_preview_payload_returns_recent_prefixed_features(self):
        from serve.valuescan_metrics import valuescan_feature_preview_payload

        bars = pd.DataFrame(
            {
                "Open": [99.0, 100.0, 101.0],
                "High": [101.0, 102.0, 103.0],
                "Low": [98.0, 99.0, 100.0],
                "Close": [100.0, 101.0, 102.0],
                "Volume": [10.0, 11.0, 12.0],
            },
            index=pd.date_range("2026-06-03", periods=3, freq="4h", tz="UTC"),
        )
        timestamp_ms = int(bars.index[1].timestamp() * 1000)
        overview = {
            "updatedAt": timestamp_ms,
            "socialSentiment": {"bullishRatio": 0.55, "neutralRatio": 0.25, "bearishRatio": 0.20},
            "priceMarket": [{"date": timestamp_ms, "priceMarketType": 1}],
        }
        lists = {
            "updatedAt": timestamp_ms,
            "opportunities": [{"symbol": "BTC", "score": 66, "grade": 2}],
            "risks": [{"symbol": "BTC", "score": 44, "grade": 1}],
            "funds": [{"symbol": "BTC", "tradeType": 2, "score": 73}],
            "messages": {},
        }

        payload = valuescan_feature_preview_payload(
            bars,
            overview_payload=overview,
            lists_payload=lists,
            symbol="BTC",
            limit=2,
        )

        self.assertEqual(payload["symbol"], "BTC")
        self.assertEqual(payload["rows"], 3)
        self.assertIn("valuescan_bullish_ratio", payload["columns"])
        self.assertEqual(len(payload["features"]), 2)
        self.assertEqual(float(payload["features"][0]["valuescan_bullish_ratio"]), 0.55)
        self.assertEqual(float(payload["features"][1]["valuescan_opportunity_score"]), 66.0)

    def test_valuescan_metric_payload_can_be_cached_without_changing_feature_preview(self):
        from quant_platform.data import ExternalMetricSeriesId
        from serve.valuescan_metrics import cache_valuescan_external_metrics, valuescan_feature_preview_payload

        overview = {
            "updatedAt": 1775734240000,
            "socialSentiment": {"bullishRatio": 0.45, "neutralRatio": 0.35, "bearishRatio": 0.20},
            "priceMarket": [{"date": 1775734240000, "priceMarketType": 1}],
        }
        lists = {
            "updatedAt": 1775734240000,
            "opportunities": [{"symbol": "BTC", "score": 66, "grade": 2}],
            "risks": [{"symbol": "BTC", "score": 44, "grade": 1}],
            "funds": [{"symbol": "BTC", "tradeType": 2, "score": 73}],
            "messages": {},
        }
        series_id = ExternalMetricSeriesId("BTC/USDT", "valuescan", "ai_tracking", "4h", "api")
        store = Mock()
        store.write.return_value = Path("external_metrics/api/valuescan/BTC_USDT/4h/ai_tracking.parquet")

        cache = cache_valuescan_external_metrics(
            overview_payload=overview,
            lists_payload=lists,
            symbol="BTC",
            series_id=series_id,
            store=store,
        )
        payload = valuescan_feature_preview_payload(
            pd.DataFrame(
                {
                    "Open": [99.0],
                    "High": [101.0],
                    "Low": [98.0],
                    "Close": [100.0],
                    "Volume": [10.0],
                },
                index=pd.to_datetime([1775734240000], unit="ms", utc=True),
            ),
            overview_payload=overview,
            lists_payload=lists,
            symbol="BTC",
            limit=1,
        )

        store.write.assert_called_once()
        written_series_id, written_metrics = store.write.call_args.args
        self.assertEqual(written_series_id, series_id)
        self.assertIn("bullish_ratio", written_metrics.columns)
        self.assertIn("opportunity_score", written_metrics.columns)
        self.assertEqual(cache["cacheKey"], series_id.cache_key)
        self.assertEqual(cache["path"], str(store.write.return_value))
        self.assertEqual(cache["rows"], 1)
        self.assertEqual(payload["featureCount"], len(payload["columns"]))


if __name__ == "__main__":
    unittest.main()
