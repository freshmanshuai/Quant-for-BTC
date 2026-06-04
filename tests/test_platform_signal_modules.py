import unittest

import pandas as pd


class SignalModuleTest(unittest.TestCase):
    def test_column_signal_module_emits_standard_signals_from_feature_columns(self):
        from quant_platform.signal_modules import ColumnSignalConfig, ColumnSignalModule
        from quant_platform.signals import Direction

        features = pd.DataFrame(
            {
                "breakout_long": [False, True],
                "score_breakout_long": [10.0, 82.5],
                "breakout_short": [True, False],
                "score_breakout_short": [61.0, 20.0],
                "long_stop": [95.0, 99.0],
                "short_stop": [101.0, 110.0],
                "long_target": [110.0, 115.0],
                "short_target": [90.0, 100.0],
                "Close": [100.0, 105.0],
                "_atr_signal": [2.0, 3.0],
            },
            index=pd.date_range("2024-01-01", periods=2, freq="4h", tz="UTC"),
        )
        module = ColumnSignalModule(
            ColumnSignalConfig(
                module="breakout",
                long_column="breakout_long",
                short_column="breakout_short",
                long_score_column="score_breakout_long",
                short_score_column="score_breakout_short",
                long_stop_column="long_stop",
                short_stop_column="short_stop",
                long_target_column="long_target",
                short_target_column="short_target",
                entry_reason="Donchian breakout",
                invalidation="Close back inside channel",
                required_data=("ohlcv:4h", "features:donchian"),
            )
        )

        signals = module.generate(features, symbol="BTC/USDT")

        self.assertEqual(len(signals), 2)
        self.assertEqual(signals[0].direction, Direction.SHORT)
        self.assertEqual(signals[0].score, 61.0)
        self.assertEqual(signals[1].direction, Direction.LONG)
        self.assertEqual(signals[1].module, "breakout")
        self.assertEqual(signals[1].required_data, ("ohlcv:4h", "features:donchian"))
        self.assertEqual(signals[0].preferred_stop, 101.0)
        self.assertEqual(signals[1].preferred_stop, 99.0)
        self.assertEqual(signals[1].preferred_target, 115.0)

    def test_signal_module_runner_combines_modules_in_order(self):
        from quant_platform.signal_modules import ColumnSignalConfig, ColumnSignalModule, SignalModuleRunner

        features = pd.DataFrame(
            {
                "a_long": [True],
                "a_score": [70.0],
                "b_short": [True],
                "b_score": [80.0],
            },
            index=pd.date_range("2024-01-01", periods=1, freq="4h", tz="UTC"),
        )
        runner = SignalModuleRunner([
            ColumnSignalModule(ColumnSignalConfig("a", long_column="a_long", long_score_column="a_score")),
            ColumnSignalModule(ColumnSignalConfig("b", short_column="b_short", short_score_column="b_score")),
        ])

        signals = runner.generate(features, symbol="BTC/USDT")

        self.assertEqual([signal.module for signal in signals], ["a", "b"])

    def test_btc_signal_modules_map_existing_feature_columns(self):
        from quant_btc.signal_modules import build_btc_signal_modules

        names = [module.name for module in build_btc_signal_modules()]

        self.assertEqual(names, [
            "breakout",
            "pullback",
            "meanrev",
            "sweep_reversal",
            "crash_short",
            "failed_bounce",
            "bull_trap",
        ])

    def test_btc_mtf_confirmation_helpers_preserve_legacy_15m_rules(self):
        from quant_btc.signal_modules import (
            btc_mtf_higher_low_formed,
            btc_mtf_no_new_extreme,
            btc_mtf_sweep_reclaim,
        )

        sweep_bars = pd.DataFrame(
            {
                "High": [101.0, 102.0, 101.0, 100.5],
                "Low": [99.0, 98.5, 100.1, 100.2],
                "Close": [99.5, 100.5, 100.3, 100.4],
            }
        )
        self.assertTrue(btc_mtf_sweep_reclaim(sweep_bars, is_long=True, key_level=100.0))

        short_sweep_bars = pd.DataFrame(
            {
                "High": [99.0, 101.5, 99.8, 99.5],
                "Low": [98.0, 98.5, 98.8, 98.7],
                "Close": [100.5, 99.5, 99.7, 99.6],
            }
        )
        self.assertTrue(btc_mtf_sweep_reclaim(short_sweep_bars, is_long=False, key_level=100.0))
        self.assertFalse(btc_mtf_sweep_reclaim(sweep_bars.iloc[:2], is_long=True, key_level=100.0))

        no_new_low = pd.DataFrame({"Low": [9.0, 8.0, 8.0, 8.5], "High": [10.0, 11.0, 10.5, 10.0]})
        new_low = pd.DataFrame({"Low": [9.0, 8.0, 7.9, 8.5], "High": [10.0, 11.0, 10.5, 10.0]})
        no_new_high = pd.DataFrame({"Low": [9.0, 8.0, 8.0, 8.5], "High": [10.0, 11.0, 11.0, 10.0]})
        new_high = pd.DataFrame({"Low": [9.0, 8.0, 8.0, 8.5], "High": [10.0, 11.0, 12.0, 10.0]})
        self.assertTrue(btc_mtf_no_new_extreme(no_new_low, is_long=True))
        self.assertFalse(btc_mtf_no_new_extreme(new_low, is_long=True))
        self.assertTrue(btc_mtf_no_new_extreme(no_new_high, is_long=False))
        self.assertFalse(btc_mtf_no_new_extreme(new_high, is_long=False))
        self.assertFalse(btc_mtf_no_new_extreme(no_new_low.iloc[:3], is_long=True))

        higher_low_bars = pd.DataFrame({"Low": [9.0, 4.0, 8.0, 7.0, 6.0, 7.0, 8.0, 9.0]})
        lower_low_bars = pd.DataFrame({"Low": [9.0, 7.0, 8.0, 6.0, 4.0, 7.0, 8.0, 9.0]})
        self.assertTrue(btc_mtf_higher_low_formed(higher_low_bars))
        self.assertFalse(btc_mtf_higher_low_formed(lower_low_bars))
        self.assertFalse(btc_mtf_higher_low_formed(higher_low_bars.iloc[:5]))

    def test_btc_signal_modules_emit_short_extension_signals_from_existing_columns(self):
        from quant_btc.signal_modules import build_btc_signal_modules
        from quant_platform.signal_modules import SignalModuleRunner
        from quant_platform.signals import Direction

        features = pd.DataFrame(
            {
                "breakout_long": [False],
                "breakout_short": [False],
                "pullback_long": [False],
                "pullback_short": [False],
                "meanrev_long": [False],
                "meanrev_short": [False],
                "_sweep_signal_long": [True],
                "_sweep_signal_short": [False],
                "_crash_short_signal": [True],
                "_failed_bounce_gate": [True],
                "_bull_trap_signal": [True],
                "score_breakout_long": [0.0],
                "score_breakout_short": [0.0],
                "score_pullback_long": [0.0],
                "score_pullback_short": [0.0],
                "score_meanrev_long": [0.0],
                "score_meanrev_short": [0.0],
                "score_sweep_reversal_long": [72.0],
                "score_sweep_reversal_short": [0.0],
                "score_crash_short": [81.0],
                "score_failed_bounce_short": [76.0],
                "score_bull_trap_short": [79.0],
                "_btc_long_stop": [95.0],
                "_btc_short_stop": [105.0],
                "_btc_long_target": [110.0],
                "_btc_short_target": [90.0],
            },
            index=pd.date_range("2024-01-01", periods=1, freq="4h", tz="UTC"),
        )

        signals = SignalModuleRunner(build_btc_signal_modules()).generate(features, symbol="BTC/USDT")

        self.assertEqual(
            [signal.module for signal in signals],
            ["sweep_reversal", "crash_short", "failed_bounce", "bull_trap"],
        )
        self.assertEqual(signals[0].direction, Direction.LONG)
        self.assertEqual(signals[0].score, 72.0)
        self.assertEqual(signals[1].direction, Direction.SHORT)
        self.assertEqual(signals[1].score, 81.0)
        self.assertEqual(signals[2].direction, Direction.SHORT)
        self.assertEqual(signals[2].score, 76.0)
        self.assertEqual(signals[3].direction, Direction.SHORT)
        self.assertEqual(signals[3].score, 79.0)
        self.assertEqual(signals[0].preferred_stop, 95.0)
        self.assertEqual(signals[1].preferred_stop, 105.0)
        self.assertEqual(signals[1].preferred_target, 90.0)

    def test_btc_preferred_exit_columns_use_atr_without_mutating_input(self):
        from quant_btc.signal_modules import add_btc_preferred_exit_columns

        features = pd.DataFrame(
            {
                "Close": [100.0, 120.0],
                "_atr_signal": [5.0, 10.0],
            },
            index=pd.date_range("2024-01-01", periods=2, freq="4h", tz="UTC"),
        )

        result = add_btc_preferred_exit_columns(features)

        self.assertEqual(result["_btc_long_stop"].tolist(), [90.0, 100.0])
        self.assertEqual(result["_btc_long_target"].tolist(), [120.0, 160.0])
        self.assertEqual(result["_btc_short_stop"].tolist(), [110.0, 140.0])
        self.assertEqual(result["_btc_short_target"].tolist(), [80.0, 80.0])
        self.assertNotIn("_btc_long_stop", features.columns)

    def test_btc_standard_signal_preview_generates_serializable_signals(self):
        from quant_btc.signal_modules import generate_btc_standard_signals

        features = pd.DataFrame(
            {
                "breakout_long": [True],
                "breakout_short": [False],
                "pullback_long": [False],
                "pullback_short": [False],
                "meanrev_long": [False],
                "meanrev_short": [False],
                "_sweep_signal_long": [False],
                "_sweep_signal_short": [False],
                "_crash_short_signal": [False],
                "_failed_bounce_gate": [False],
                "_bull_trap_signal": [False],
                "score_breakout_long": [88.0],
                "score_breakout_short": [0.0],
                "score_pullback_long": [0.0],
                "score_pullback_short": [0.0],
                "score_meanrev_long": [0.0],
                "score_meanrev_short": [0.0],
                "score_sweep_reversal_long": [0.0],
                "score_sweep_reversal_short": [0.0],
                "score_crash_short": [0.0],
                "score_failed_bounce_short": [0.0],
                "score_bull_trap_short": [0.0],
                "Close": [100.0],
                "_atr_signal": [5.0],
            },
            index=pd.date_range("2024-01-01", periods=1, freq="4h", tz="UTC"),
        )

        signals = generate_btc_standard_signals(features, symbol="BTC/USDT")

        self.assertEqual(len(signals), 1)
        payload = signals[0].to_dict()
        self.assertEqual(payload["module"], "breakout")
        self.assertEqual(payload["direction"], "long")
        self.assertEqual(payload["score"], 88.0)
        self.assertEqual(payload["preferred_stop"], 90.0)
        self.assertEqual(payload["preferred_target"], 120.0)

    def test_btc_score_signal_columns_generate_crash_gate_without_mutating_input(self):
        from quant_btc.signal_modules import add_btc_score_signal_columns

        features = pd.DataFrame(
            {
                "score_crash_short": [74.0, 80.0, 90.0],
                "_late_chase": [False, False, True],
            },
            index=pd.date_range("2024-01-01", periods=3, freq="4h", tz="UTC"),
        )

        result = add_btc_score_signal_columns(features)

        self.assertEqual(result["_crash_short_signal"].tolist(), [False, True, False])
        self.assertNotIn("_crash_short_signal", features.columns)

    def test_btc_module_score_columns_generate_all_standard_module_scores_without_mutating_input(self):
        from quant_btc.signal_modules import add_btc_module_score_columns

        index = pd.date_range("2024-01-01", periods=8, freq="4h", tz="UTC")
        features = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0, 103.0, 102.0, 101.0, 100.0, 99.0],
                "High": [102.0, 103.0, 104.0, 105.0, 104.0, 103.0, 102.0, 101.0],
                "Low": [99.0, 100.0, 101.0, 102.0, 100.0, 99.0, 98.0, 97.0],
                "Close": [101.0, 102.0, 103.0, 102.0, 101.0, 100.0, 99.0, 98.0],
                "Volume": [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0],
                "d_ema": [100.0, 100.4, 100.8, 101.0, 100.9, 100.7, 100.4, 100.1],
                "w_ema": [99.0, 99.2, 99.4, 99.6, 99.5, 99.4, 99.2, 99.0],
                "ema55": [100.0, 100.5, 101.0, 101.3, 101.2, 101.0, 100.8, 100.5],
                "ema69": [100.0, 100.4, 100.8, 101.0, 101.0, 100.8, 100.6, 100.3],
                "ema144": [99.0, 99.5, 100.0, 100.5, 100.7, 100.6, 100.4, 100.2],
                "ema169": [99.0, 99.4, 99.8, 100.2, 100.4, 100.3, 100.1, 99.9],
                "_atr_signal": [2.0] * 8,
                "_adx_signal": [18.0, 19.0, 20.0, 23.0, 24.0, 25.0, 26.0, 27.0],
                "rsi_14": [45.0, 48.0, 52.0, 55.0, 50.0, 45.0, 40.0, 35.0],
                "macd_hist": [-0.2, -0.1, 0.1, 0.2, 0.1, 0.0, -0.1, -0.2],
                "vol_zscore": [0.0, 0.2, 0.5, 1.0, 1.2, 1.5, 1.8, 2.0],
                "roll_high_55": [103.0, 104.0, 105.0, 106.0, 106.0, 105.0, 104.0, 103.0],
                "roll_low_55": [98.0, 98.0, 99.0, 100.0, 99.0, 98.0, 97.0, 96.0],
                "mr_dc20_high": [102.0, 103.0, 104.0, 105.0, 104.0, 103.0, 102.0, 101.0],
                "mr_dc20_low": [99.0, 100.0, 101.0, 102.0, 100.0, 99.0, 98.0, 97.0],
                "bb_upper": [103.0, 104.0, 105.0, 106.0, 105.0, 104.0, 103.0, 102.0],
                "bb_lower": [98.0, 99.0, 100.0, 101.0, 99.0, 98.0, 97.0, 96.0],
                "_lower_shadow": [0.2, 0.2, 0.2, 0.2, 0.5, 0.5, 0.4, 0.4],
                "_upper_shadow": [0.2, 0.2, 0.2, 0.2, 0.4, 0.5, 0.5, 0.5],
                "breakout_long": [False, False, True, True, False, False, False, False],
                "breakout_short": [False, False, False, False, False, True, True, True],
                "pullback_long": [False, True, True, False, False, False, False, False],
                "pullback_short": [False, False, False, False, True, True, False, False],
                "meanrev_long": [False, False, False, False, True, False, False, False],
                "meanrev_short": [False, False, False, True, False, False, False, False],
            },
            index=index,
        )

        result = add_btc_module_score_columns(features)

        for column in [
            "score_breakout_long",
            "score_breakout_short",
            "score_pullback_long",
            "score_pullback_short",
            "score_meanrev_long",
            "score_meanrev_short",
            "score_sweep_reversal_long",
            "score_sweep_reversal_short",
            "score_crash_short",
            "score_failed_bounce_short",
            "score_bull_trap_short",
            "_crash_short_signal",
            "_failed_bounce_gate",
            "_bull_trap_signal",
        ]:
            self.assertIn(column, result.columns)
        self.assertNotIn("score_breakout_long", features.columns)

    def test_btc_crash_score_columns_generate_score_di_columns_and_gate(self):
        from quant_btc.signal_modules import add_btc_crash_score_columns

        features = pd.DataFrame(
            {
                "Open": [100.0, 100.0, 100.0, 100.0],
                "High": [101.0, 102.0, 101.0, 100.0],
                "Low": [99.0, 100.0, 98.0, 97.0],
                "Close": [100.0, 99.0, 100.0, 97.5],
                "_adx_signal": [20.0, 21.0, 24.0, 30.0],
                "rsi_14": [45.0, 42.0, 40.0, 35.0],
                "vol_zscore": [0.0, 0.5, 1.0, 2.0],
            },
            index=pd.date_range("2024-01-01", periods=4, freq="4h", tz="UTC"),
        )
        market_short = pd.Series([30.0, 30.0, 30.0, 30.0], index=features.index)
        risk_score = pd.Series([20.0, 20.0, 20.0, 20.0], index=features.index)
        adx_rising = pd.Series([False, False, True, True], index=features.index)

        result = add_btc_crash_score_columns(features, market_short, risk_score, adx_rising)

        self.assertIn("_plus_di", result.columns)
        self.assertIn("_minus_di", result.columns)
        self.assertEqual(result["_late_chase"].tolist(), [False, False, False, False])
        self.assertGreaterEqual(result["score_crash_short"].iloc[-1], 75.0)
        self.assertTrue(result["_crash_short_signal"].iloc[-1])
        self.assertNotIn("score_crash_short", features.columns)

    def test_btc_sweep_signal_columns_generate_reclaim_gates_without_mutating_input(self):
        from quant_btc.signal_modules import add_btc_sweep_signal_columns

        features = pd.DataFrame(
            {
                "Open": [100.0, 100.0, 100.0],
                "High": [104.0, 105.0, 112.0],
                "Low": [98.0, 94.0, 99.0],
                "Close": [101.0, 99.0, 106.0],
                "mr_dc20_low": [96.0, 96.0, 96.0],
                "mr_dc20_high": [108.0, 108.0, 108.0],
                "bb_lower": [95.0, 95.0, 95.0],
                "bb_upper": [109.0, 109.0, 109.0],
            },
            index=pd.date_range("2024-01-01", periods=3, freq="4h", tz="UTC"),
        )

        result = add_btc_sweep_signal_columns(features)

        self.assertEqual(result["_sweep_signal_long"].tolist(), [False, True, False])
        self.assertEqual(result["_sweep_signal_short"].tolist(), [False, False, True])
        self.assertNotIn("_sweep_signal_long", features.columns)

    def test_btc_sweep_score_columns_generate_scores_and_gates(self):
        from quant_btc.signal_modules import add_btc_sweep_score_columns

        features = pd.DataFrame(
            {
                "Open": [100.0, 100.0, 100.0],
                "High": [104.0, 105.0, 112.0],
                "Low": [98.0, 94.0, 99.0],
                "Close": [101.0, 99.0, 106.0],
                "mr_dc20_low": [96.0, 96.0, 96.0],
                "mr_dc20_high": [108.0, 108.0, 108.0],
                "bb_lower": [95.0, 95.0, 95.0],
                "bb_upper": [109.0, 109.0, 109.0],
                "_atr_signal": [4.0, 4.0, 4.0],
            },
            index=pd.date_range("2024-01-01", periods=3, freq="4h", tz="UTC"),
        )
        market_long = pd.Series([20.0, 20.0, 20.0], index=features.index)
        market_short = pd.Series([10.0, 10.0, 10.0], index=features.index)
        momentum_long = pd.Series([5.0, 5.0, 5.0], index=features.index)
        momentum_short = pd.Series([6.0, 6.0, 6.0], index=features.index)
        risk_score = pd.Series([4.0, 4.0, 4.0], index=features.index)

        result = add_btc_sweep_score_columns(
            features,
            market_long,
            market_short,
            momentum_long,
            momentum_short,
            risk_score,
        )

        self.assertEqual(result["_sweep_signal_long"].tolist(), [False, True, False])
        self.assertEqual(result["_sweep_signal_short"].tolist(), [False, False, True])
        self.assertAlmostEqual(result["score_sweep_reversal_long"].iloc[1], 41.33333333333333)
        self.assertAlmostEqual(result["score_sweep_reversal_short"].iloc[2], 31.0)
        self.assertNotIn("score_sweep_reversal_long", features.columns)

    def test_btc_short_extension_signal_columns_generate_failed_bounce_and_bull_trap_gates(self):
        from quant_btc.signal_modules import add_btc_short_extension_signal_columns

        features = pd.DataFrame(
            {
                "Open": [100.0, 100.0, 105.0],
                "High": [101.0, 105.0, 108.0],
                "Low": [99.0, 100.0, 98.0],
                "Close": [100.0, 104.0, 99.0],
                "ema55": [99.0, 100.0, 99.0],
                "ema69": [99.0, 100.0, 100.0],
                "ema144": [101.0, 105.0, 105.0],
                "ema169": [101.0, 105.0, 105.0],
                "bb_lower": [95.0, 95.0, 95.0],
                "bb_upper": [104.0, 104.0, 104.0],
                "roll_high_55": [102.0, 103.0, 104.0],
                "_atr_signal": [4.0, 4.0, 4.0],
                "_upper_shadow": [0.1, 0.2, 0.5],
                "rsi_14": [50.0, 56.0, 52.0],
                "macd_hist": [0.05, 0.10, 0.08],
                "vol_zscore": [0.0, 1.0, 0.0],
            },
            index=pd.date_range("2024-01-01", periods=3, freq="4h", tz="UTC"),
        )

        result = add_btc_short_extension_signal_columns(features)

        self.assertEqual(result["_failed_bounce_gate"].tolist(), [False, False, True])
        self.assertEqual(result["_bull_trap_signal"].tolist(), [False, False, True])
        self.assertNotIn("_failed_bounce_gate", features.columns)

    def test_btc_short_extension_score_columns_generate_scores_and_gates(self):
        from quant_btc.signal_modules import add_btc_short_extension_score_columns

        features = pd.DataFrame(
            {
                "Open": [100.0, 100.0, 105.0],
                "High": [101.0, 105.0, 108.0],
                "Low": [99.0, 100.0, 98.0],
                "Close": [100.0, 104.0, 99.0],
                "ema55": [99.0, 100.0, 99.0],
                "ema69": [99.0, 100.0, 100.0],
                "ema144": [101.0, 105.0, 105.0],
                "ema169": [101.0, 105.0, 105.0],
                "bb_lower": [95.0, 95.0, 95.0],
                "bb_upper": [104.0, 104.0, 104.0],
                "roll_high_55": [102.0, 103.0, 104.0],
                "_atr_signal": [4.0, 4.0, 4.0],
                "_adx_signal": [20.0, 21.0, 25.0],
                "_upper_shadow": [0.1, 0.2, 0.5],
                "rsi_14": [50.0, 56.0, 52.0],
                "macd_hist": [0.05, 0.10, 0.08],
                "vol_zscore": [0.0, 1.0, 0.0],
            },
            index=pd.date_range("2024-01-01", periods=3, freq="4h", tz="UTC"),
        )
        market_short = pd.Series([20.0, 20.0, 20.0], index=features.index)
        risk_score = pd.Series([10.0, 10.0, 10.0], index=features.index)
        adx_rising = pd.Series([False, False, True], index=features.index)

        result = add_btc_short_extension_score_columns(features, market_short, risk_score, adx_rising)

        self.assertEqual(result["_failed_bounce_gate"].tolist(), [False, False, True])
        self.assertEqual(result["_bull_trap_signal"].tolist(), [False, False, True])
        self.assertEqual(result["score_failed_bounce_short"].iloc[-1], 80.0)
        self.assertEqual(result["score_bull_trap_short"].iloc[-1], 70.0)
        self.assertNotIn("score_failed_bounce_short", features.columns)

    def test_btc_signal_predicate_columns_are_generated_from_features(self):
        from quant_btc.signal_modules import add_btc_signal_predicate_columns

        features = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 99.0, 95.0],
                "High": [101.0, 104.0, 100.0, 96.0],
                "Low": [99.0, 100.0, 94.0, 90.0],
                "Close": [100.0, 103.0, 95.0, 92.0],
                "Volume": [100.0, 150.0, 160.0, 170.0],
                "ema55": [99.0, 100.0, 96.0, 93.0],
                "ema69": [99.0, 100.0, 96.0, 93.0],
                "ema144": [101.0, 102.0, 98.0, 95.0],
                "ema169": [101.0, 102.0, 98.0, 95.0],
                "macd_hist": [0.0, 0.1, -0.1, -0.2],
                "rsi_14": [45.0, 46.0, 66.0, 67.0],
                "roll_high_55": [101.0, 102.0, 103.0, 104.0],
                "roll_low_55": [99.0, 98.0, 94.0, 90.0],
                "vol_sma_50": [100.0, 100.0, 100.0, 100.0],
                "vol_zscore": [0.0, 1.0, 1.0, 1.0],
                "_adx_signal": [30.0, 30.0, 10.0, 10.0],
                "_atr_pct_signal": [0.5, 0.5, 0.2, 0.2],
                "bb_lower": [98.0, 99.0, 96.0, 93.0],
                "bb_upper": [102.0, 104.0, 100.0, 96.0],
                "mr_dc20_low": [99.0, 98.0, 94.0, 90.0],
                "mr_dc20_high": [101.0, 104.0, 100.0, 96.0],
                "_lower_shadow": [0.2, 0.2, 0.5, 0.4],
                "_upper_shadow": [0.2, 0.2, 0.2, 0.5],
            },
            index=pd.date_range("2024-01-01", periods=4, freq="4h", tz="UTC"),
        )

        result = add_btc_signal_predicate_columns(features)

        for col in ["breakout_long", "breakout_short", "pullback_long", "pullback_short", "meanrev_long", "meanrev_short"]:
            self.assertIn(col, result.columns)
        self.assertNotIn("breakout_long", features.columns)


if __name__ == "__main__":
    unittest.main()
