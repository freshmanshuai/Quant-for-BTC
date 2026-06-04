import unittest
from unittest.mock import patch

import pandas as pd


class BtcDerivativeBonusTest(unittest.TestCase):
    def test_compute_derivative_bonus_consumes_platform_derivative_features(self):
        from quant_btc import strategy

        index = pd.date_range("2024-01-01", periods=30, freq="4h", tz="UTC")
        df = pd.DataFrame(
            {
                "Open": [100.0] * 30,
                "High": [101.0] * 30,
                "Low": [99.0] * 30,
                "Close": [100.0] * 30,
                "Volume": [1000.0] * 30,
            },
            index=index,
        )
        derivatives = pd.DataFrame(
            {"funding_rate": [0.0001], "open_interest": [1000.0]},
            index=[index[0]],
        )
        calls = {"module": 0}

        class FakeDerivativesFeatureModule:
            def __init__(self, deriv_df, config):
                calls["module"] += 1
                calls["deriv_df"] = deriv_df
                calls["config"] = config

            def apply(self, bars):
                out = bars.copy()
                out["funding_zscore_90"] = 0.0
                out["open_interest_change_6"] = 0.0
                out["derivative_price_change_6"] = 0.0
                out.loc[index[-1], "funding_zscore_90"] = 2.0
                out.loc[index[-1], "open_interest_change_6"] = 0.06
                return out

        with patch("quant_btc.strategy.DerivativesFeatureModule", FakeDerivativesFeatureModule):
            bonus = strategy.compute_derivative_bonus(df, derivatives)

        self.assertEqual(calls["module"], 1)
        self.assertIs(calls["deriv_df"], derivatives)
        self.assertEqual(calls["config"].funding_zscore_lookback, 90)
        self.assertEqual(calls["config"].open_interest_change_periods, 6)
        self.assertEqual(float(bonus.iloc[-1]), 10.0)
        self.assertEqual(float(df["_short_deriv_bonus"].iloc[-1]), 10.0)
        self.assertEqual(float(df["_perp_crowding_long_bonus"].iloc[-1]), 0.0)


if __name__ == "__main__":
    unittest.main()
