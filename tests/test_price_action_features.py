import unittest

import numpy as np
import pandas as pd

from quant_btc.price_action import PriceActionConfig, add_continuous_price_action_features
from quant_btc.retained_strategy import RetainedStrategyConfig, prepare_retained_features
from quant_platform.features import atr


class ContinuousPriceActionFeatureTest(unittest.TestCase):
    @staticmethod
    def _bars(periods: int = 180) -> pd.DataFrame:
        index = pd.date_range("2025-01-01", periods=periods, freq="4h", tz="UTC")
        phase = np.arange(periods, dtype=float)
        close = 100.0 + 0.08 * phase + 2.0 * np.sin(phase / 7.0)
        open_price = np.r_[close[0], close[:-1]] * (1.0 + 0.0005 * np.cos(phase))
        high = np.maximum(open_price, close) + 1.0 + 0.1 * np.sin(phase / 3.0)
        low = np.minimum(open_price, close) - 1.0 - 0.1 * np.cos(phase / 4.0)
        return pd.DataFrame(
            {
                "Open": open_price,
                "High": high,
                "Low": low,
                "Close": close,
                "Volume": 1_000.0 + phase,
            },
            index=index,
        )

    @staticmethod
    def _config() -> PriceActionConfig:
        return PriceActionConfig(
            structure_short=12,
            structure_long=36,
            level_lookback=18,
            level_decay=6.0,
            level_bandwidth_atr=1.5,
            jump_window=12,
        )

    def test_features_are_prefix_invariant(self):
        bars = self._bars()
        prefix_length = 120
        prefix_bars = bars.iloc[:prefix_length]
        prefix = add_continuous_price_action_features(
            prefix_bars,
            atr_values=atr(
                prefix_bars["High"], prefix_bars["Low"], prefix_bars["Close"], 14
            ),
            config=self._config(),
        )

        mutated = bars.copy()
        mutated.iloc[prefix_length:, mutated.columns.get_indexer(["Open", "Close"])] *= 10.0
        mutated.iloc[prefix_length:, mutated.columns.get_indexer(["High"])] *= 20.0
        mutated.iloc[prefix_length:, mutated.columns.get_indexer(["Low"])] *= 0.1
        full = add_continuous_price_action_features(
            mutated,
            atr_values=atr(mutated["High"], mutated["Low"], mutated["Close"], 14),
            config=self._config(),
        )

        feature_columns = [column for column in prefix if column.startswith("_")]
        pd.testing.assert_frame_equal(prefix[feature_columns], full.iloc[:prefix_length][feature_columns])

    def test_ablation_computes_only_requested_family(self):
        bars = self._bars(80)
        values = atr(bars["High"], bars["Low"], bars["Close"], 14)
        result = add_continuous_price_action_features(
            bars,
            atr_values=values,
            config=self._config(),
            families=("support_resistance",),
        )

        self.assertIn("_level_balance", result)
        self.assertIn("_level_density", result)
        self.assertNotIn("_structure_score", result)
        self.assertNotIn("_jump_risk", result)

    def test_empty_family_selection_computes_no_candidates(self):
        bars = self._bars(80)
        result = add_continuous_price_action_features(
            bars,
            atr_values=atr(bars["High"], bars["Low"], bars["Close"], 14),
            config=self._config(),
            families=(),
        )

        self.assertFalse(any(column.startswith("_") for column in result.columns))

    def test_feature_ranges_are_bounded(self):
        bars = self._bars()
        result = add_continuous_price_action_features(
            bars,
            atr_values=atr(bars["High"], bars["Low"], bars["Close"], 14),
            config=self._config(),
        )

        for column in ("_structure_score", "_level_balance"):
            values = result[column].dropna()
            self.assertTrue(values.between(-1.0, 1.0).all())
        self.assertTrue(result["_jump_risk"].dropna().between(0.0, 1.0).all())

    def test_production_baseline_does_not_compute_candidate_families(self):
        result = prepare_retained_features(self._bars(), config=RetainedStrategyConfig())

        candidate_columns = {
            "_ema_strength",
            "_structure_score",
            "_level_balance",
            "_jump_risk",
        }
        self.assertTrue(candidate_columns.isdisjoint(result.columns))


if __name__ == "__main__":
    unittest.main()
