import unittest

import numpy as np
import pandas as pd

from quant_btc.simple_ml import (
    ATR_FEATURE,
    EMA_FEATURE,
    RSI_FEATURE,
    TARGET_COLUMN,
    VOLUME_FEATURE,
    SimpleMLConfig,
    build_simple_ml_features,
    pooled_walk_forward_ridge,
    positions_from_prediction,
    simulate_open_boundary_strategy,
)


def _bars(periods: int = 400, *, start: str = "2024-01-01") -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq="15min", tz="UTC")
    close = pd.Series(100.0 + np.arange(periods) * 0.01, index=index)
    return pd.DataFrame(
        {
            "Open": close - 0.005,
            "High": close + 0.05,
            "Low": close - 0.05,
            "Close": close,
            "Volume": 100.0 + np.sin(np.arange(periods)),
        },
        index=index,
    )


class SimpleMLTests(unittest.TestCase):
    def test_feature_prefix_is_unchanged_when_future_rows_are_appended(self):
        bars = _bars()
        prefix = build_simple_ml_features(bars.iloc[:250])
        full = build_simple_ml_features(bars)
        columns = [EMA_FEATURE, RSI_FEATURE, VOLUME_FEATURE, ATR_FEATURE]
        pd.testing.assert_frame_equal(prefix[columns], full.loc[prefix.index, columns])

    def test_forward_label_matches_next_open_execution_horizon(self):
        bars = _bars(40)
        config = SimpleMLConfig(prediction_horizon_bars=4)
        features = build_simple_ml_features(bars, config)
        expected = bars["Open"].iloc[5] / bars["Open"].iloc[1] - 1.0
        self.assertAlmostEqual(float(features[TARGET_COLUMN].iloc[0]), float(expected))

    def test_walk_forward_prediction_does_not_use_later_prices(self):
        config = SimpleMLConfig(
            prediction_horizon_bars=4,
            minimum_training_rows_per_asset=50,
        )
        original = _bars(2_000)
        changed = original.copy()
        changed.loc[changed.index >= "2024-01-18", "Close"] *= 3.0
        changed.loc[changed.index >= "2024-01-18", ["Open", "High", "Low"]] *= 3.0
        original_features = build_simple_ml_features(original, config)
        changed_features = build_simple_ml_features(changed, config)
        kwargs = {
            "feature_columns": (EMA_FEATURE, RSI_FEATURE),
            "prediction_start": "2024-01-15",
            "prediction_end": "2024-01-16",
            "config": config,
        }
        left = pooled_walk_forward_ridge({"BTC": original_features}, **kwargs)
        right = pooled_walk_forward_ridge({"BTC": changed_features}, **kwargs)
        pd.testing.assert_series_equal(
            left.predictions["BTC"].loc["2024-01-15":"2024-01-16"],
            right.predictions["BTC"].loc["2024-01-15":"2024-01-16"],
        )

    def test_prediction_threshold_creates_neutral_zone(self):
        prediction = pd.Series([-0.002, -0.001, 0.0, 0.001, 0.002])
        position = positions_from_prediction(prediction, 0.0014)
        self.assertEqual(position.tolist(), [-1.0, -1.0, 0.0, 0.0, 1.0])

    def test_close_signal_executes_on_next_open(self):
        bars = _bars(3)
        bars.loc[:, "Open"] = [100.0, 110.0, 121.0]
        bars.loc[:, "Close"] = [105.0, 115.0, 121.0]
        target = pd.Series([1.0, 1.0, 0.0], index=bars.index)
        metrics = simulate_open_boundary_strategy(
            bars,
            target,
            start=bars.index[0],
            end=bars.index[-1],
            fee_rate_per_fill=0.0,
            slippage_bps_per_fill=0.0,
        )
        # The first bar's 100 -> 110 move occurs before the signal can fill.
        self.assertAlmostEqual(metrics["total_return_pct"], 10.0)


if __name__ == "__main__":
    unittest.main()
