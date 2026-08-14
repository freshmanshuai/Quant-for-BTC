import unittest

import numpy as np
import pandas as pd
import torch

from quant_btc.lstm_model import (
    FULL_FEATURES,
    RESISTANCE_DISTANCE_FEATURE,
    SUPPORT_DISTANCE_FEATURE,
    LSTMConfig,
    MediumLSTM,
    build_lstm_features,
)
from quant_platform.features import atr


def _bars(periods: int = 500) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=periods, freq="15min", tz="UTC")
    close = pd.Series(100.0 + np.arange(periods) * 0.01, index=index)
    return pd.DataFrame(
        {
            "Open": close - 0.005,
            "High": close + 0.10,
            "Low": close - 0.10,
            "Close": close,
            "Volume": 100.0 + np.sin(np.arange(periods)),
        },
        index=index,
    )


class LSTMModelTests(unittest.TestCase):
    def test_medium_network_is_two_layer_unidirectional(self):
        model = MediumLSTM(len(FULL_FEATURES))
        self.assertEqual(model.lstm.num_layers, 2)
        self.assertEqual(model.lstm.hidden_size, 64)
        self.assertFalse(model.lstm.bidirectional)
        output = model(torch.zeros(3, 96, len(FULL_FEATURES)))
        self.assertEqual(tuple(output.shape), (3,))

    def test_features_are_prefix_invariant(self):
        bars = _bars()
        prefix = build_lstm_features(bars.iloc[:350])
        full = build_lstm_features(bars)
        pd.testing.assert_frame_equal(prefix[list(FULL_FEATURES)], full.loc[prefix.index, list(FULL_FEATURES)])

    def test_support_and_resistance_ignore_current_extremes_as_levels(self):
        config = LSTMConfig(level_lookback=20)
        bars = _bars(100)
        changed = bars.copy()
        changed.iloc[-1, changed.columns.get_loc("High")] = 10_000.0
        changed.iloc[-1, changed.columns.get_loc("Low")] = 1.0
        changed_features = build_lstm_features(changed, config)
        prior = bars.iloc[-21:-1]
        atr_value = float(
            atr(changed["High"], changed["Low"], changed["Close"], 14).iloc[-1]
        )
        close = float(changed["Close"].iloc[-1])
        expected_support = np.clip((close - float(prior["Low"].min())) / atr_value, -10, 10)
        expected_resistance = np.clip(
            (float(prior["High"].max()) - close) / atr_value, -10, 10
        )
        self.assertAlmostEqual(
            float(changed_features[SUPPORT_DISTANCE_FEATURE].iloc[-1]),
            float(expected_support),
        )
        self.assertAlmostEqual(
            float(changed_features[RESISTANCE_DISTANCE_FEATURE].iloc[-1]),
            float(expected_resistance),
        )


if __name__ == "__main__":
    unittest.main()
