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

    def test_default_signal_module_registry_builds_runner_from_config_records(self):
        from quant_platform.signal_modules import default_signal_module_registry
        from quant_platform.signals import Direction

        features = pd.DataFrame(
            {
                "Open": [94.0, 98.0, 101.0, 104.0],
                "High": [100.0, 102.0, 105.0, 107.0],
                "Low": [90.0, 92.0, 95.0, 103.0],
                "Close": [95.0, 101.0, 104.0, 106.0],
                "Volume": [100.0, 110.0, 120.0, 130.0],
            },
            index=pd.date_range("2026-06-01", periods=4, freq="D", tz="UTC"),
        )
        runner = default_signal_module_registry().build_runner([
            {
                "type": "breakout",
                "params": {
                    "module": "daily_breakout",
                    "lookback": 3,
                    "timeframe": "1d",
                    "allow_short": False,
                },
            },
            {
                "type": "pullback",
                "params": {
                    "module": "daily_pullback",
                    "ema_length": 3,
                    "timeframe": "1d",
                    "allow_short": False,
                },
            },
        ])

        signals = runner.generate(features, symbol="AAPL")

        self.assertEqual([signal.module for signal in signals], ["daily_breakout"])
        self.assertEqual(signals[0].direction, Direction.LONG)
        self.assertEqual(signals[0].required_data, ("ohlcv:1d",))

    def test_breakout_signal_module_computes_current_long_signal_from_ohlcv(self):
        from quant_platform import BreakoutSignalConfig, BreakoutSignalModule
        from quant_platform.signals import Direction

        features = pd.DataFrame(
            {
                "Open": [94.0, 98.0, 101.0, 104.0],
                "High": [100.0, 102.0, 105.0, 107.0],
                "Low": [90.0, 92.0, 95.0, 103.0],
                "Close": [95.0, 101.0, 104.0, 106.0],
                "Volume": [100.0, 110.0, 120.0, 130.0],
            },
            index=pd.date_range("2026-06-01", periods=4, freq="D", tz="UTC"),
        )

        signals = BreakoutSignalModule(
            BreakoutSignalConfig(lookback=3, timeframe="1d", risk_reward=2.0)
        ).generate(features, symbol="AAPL")

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.module, "breakout")
        self.assertEqual(signal.symbol, "AAPL")
        self.assertEqual(signal.direction, Direction.LONG)
        self.assertEqual(signal.preferred_stop, 90.0)
        self.assertEqual(signal.preferred_target, 138.0)
        self.assertEqual(signal.required_data, ("ohlcv:1d",))
        self.assertGreater(signal.score, 70.0)
        self.assertGreater(signal.confidence, 0.70)
        self.assertNotIn("breakout_long", features.columns)

    def test_breakout_signal_module_returns_no_signal_without_current_breakout(self):
        from quant_platform.signal_modules import BreakoutSignalConfig, BreakoutSignalModule

        features = pd.DataFrame(
            {
                "Open": [94.0, 98.0, 101.0, 104.0],
                "High": [100.0, 102.0, 105.0, 107.0],
                "Low": [90.0, 92.0, 95.0, 103.0],
                "Close": [95.0, 101.0, 104.0, 104.5],
                "Volume": [100.0, 110.0, 120.0, 130.0],
            },
            index=pd.date_range("2026-06-01", periods=4, freq="D", tz="UTC"),
        )

        signals = BreakoutSignalModule(BreakoutSignalConfig(lookback=3, timeframe="1d")).generate(
            features,
            symbol="AAPL",
        )

        self.assertEqual(signals, [])

    def test_pullback_signal_module_computes_current_long_signal_from_ohlcv(self):
        from quant_platform import PullbackSignalConfig, PullbackSignalModule
        from quant_platform.signals import Direction

        features = pd.DataFrame(
            {
                "Open": [100.0, 104.0, 103.0, 105.0],
                "High": [101.0, 106.0, 104.0, 107.0],
                "Low": [99.0, 104.0, 100.0, 105.0],
                "Close": [100.0, 105.0, 102.0, 106.0],
                "Volume": [100.0, 120.0, 140.0, 160.0],
            },
            index=pd.date_range("2026-06-01", periods=4, freq="D", tz="UTC"),
        )

        signals = PullbackSignalModule(
            PullbackSignalConfig(ema_length=3, timeframe="1d", risk_reward=2.0)
        ).generate(features, symbol="AAPL")

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.module, "pullback")
        self.assertEqual(signal.symbol, "AAPL")
        self.assertEqual(signal.direction, Direction.LONG)
        self.assertEqual(signal.preferred_stop, 100.0)
        self.assertEqual(signal.preferred_target, 118.0)
        self.assertEqual(signal.required_data, ("ohlcv:1d",))
        self.assertGreater(signal.score, 68.0)
        self.assertGreater(signal.confidence, 0.68)
        self.assertNotIn("ema3", features.columns)

    def test_pullback_signal_module_computes_current_short_signal_from_ohlcv(self):
        from quant_platform import PullbackSignalConfig, PullbackSignalModule
        from quant_platform.signals import Direction

        features = pd.DataFrame(
            {
                "Open": [110.0, 106.0, 107.0, 105.0],
                "High": [111.0, 106.0, 110.0, 105.0],
                "Low": [109.0, 104.0, 107.0, 103.0],
                "Close": [110.0, 105.0, 108.0, 104.0],
                "Volume": [100.0, 120.0, 140.0, 160.0],
            },
            index=pd.date_range("2026-06-01", periods=4, freq="D", tz="UTC"),
        )

        signals = PullbackSignalModule(
            PullbackSignalConfig(ema_length=3, timeframe="1d", risk_reward=2.0)
        ).generate(features, symbol="BTC/USDT")

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.direction, Direction.SHORT)
        self.assertEqual(signal.preferred_stop, 110.0)
        self.assertEqual(signal.preferred_target, 92.0)
        self.assertEqual(signal.required_data, ("ohlcv:1d",))

    def test_pullback_signal_module_returns_no_signal_without_prior_pullback(self):
        from quant_platform.signal_modules import PullbackSignalConfig, PullbackSignalModule

        features = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 103.0, 105.0],
                "High": [101.0, 103.0, 105.0, 107.0],
                "Low": [99.0, 100.0, 102.0, 104.0],
                "Close": [100.0, 102.0, 104.0, 106.0],
                "Volume": [100.0, 120.0, 140.0, 160.0],
            },
            index=pd.date_range("2026-06-01", periods=4, freq="D", tz="UTC"),
        )

        signals = PullbackSignalModule(PullbackSignalConfig(ema_length=3, timeframe="1d")).generate(
            features,
            symbol="AAPL",
        )

        self.assertEqual(signals, [])

    def test_mean_reversion_signal_module_computes_current_long_signal_from_ohlcv(self):
        from quant_platform import MeanReversionSignalConfig, MeanReversionSignalModule
        from quant_platform.signals import Direction

        features = pd.DataFrame(
            {
                "Open": [110.0, 100.0, 95.0, 94.0],
                "High": [111.0, 101.0, 96.0, 96.0],
                "Low": [109.0, 99.0, 94.0, 93.0],
                "Close": [110.0, 100.0, 95.0, 95.5],
                "Volume": [100.0, 120.0, 140.0, 160.0],
            },
            index=pd.date_range("2026-06-01", periods=4, freq="D", tz="UTC"),
        )

        signals = MeanReversionSignalModule(
            MeanReversionSignalConfig(lookback=3, std_mult=1.0, timeframe="1d")
        ).generate(features, symbol="AAPL")

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.module, "meanrev")
        self.assertEqual(signal.symbol, "AAPL")
        self.assertEqual(signal.direction, Direction.LONG)
        self.assertEqual(signal.preferred_stop, 93.0)
        self.assertAlmostEqual(signal.preferred_target, 101.66666666666667)
        self.assertEqual(signal.required_data, ("ohlcv:1d",))
        self.assertGreater(signal.score, 65.0)
        self.assertGreater(signal.confidence, 0.65)
        self.assertNotIn("meanrev_long", features.columns)

    def test_mean_reversion_signal_module_computes_current_short_signal_from_ohlcv(self):
        from quant_platform import MeanReversionSignalConfig, MeanReversionSignalModule
        from quant_platform.signals import Direction

        features = pd.DataFrame(
            {
                "Open": [90.0, 100.0, 105.0, 106.0],
                "High": [91.0, 101.0, 106.0, 107.0],
                "Low": [89.0, 99.0, 104.0, 105.0],
                "Close": [90.0, 100.0, 105.0, 105.5],
                "Volume": [100.0, 120.0, 140.0, 160.0],
            },
            index=pd.date_range("2026-06-01", periods=4, freq="D", tz="UTC"),
        )

        signals = MeanReversionSignalModule(
            MeanReversionSignalConfig(lookback=3, std_mult=1.0, timeframe="1d")
        ).generate(features, symbol="BTC/USDT")

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.direction, Direction.SHORT)
        self.assertEqual(signal.preferred_stop, 107.0)
        self.assertAlmostEqual(signal.preferred_target, 98.33333333333333)
        self.assertEqual(signal.required_data, ("ohlcv:1d",))

    def test_mean_reversion_signal_module_returns_no_signal_without_band_reclaim(self):
        from quant_platform.signal_modules import MeanReversionSignalConfig, MeanReversionSignalModule

        features = pd.DataFrame(
            {
                "Open": [110.0, 100.0, 95.0, 96.0],
                "High": [111.0, 101.0, 96.0, 97.0],
                "Low": [109.0, 99.0, 94.0, 95.0],
                "Close": [110.0, 100.0, 95.0, 96.0],
                "Volume": [100.0, 120.0, 140.0, 160.0],
            },
            index=pd.date_range("2026-06-01", periods=4, freq="D", tz="UTC"),
        )

        signals = MeanReversionSignalModule(
            MeanReversionSignalConfig(lookback=3, std_mult=1.0, timeframe="1d")
        ).generate(features, symbol="AAPL")

        self.assertEqual(signals, [])

    def test_sweep_reversal_signal_module_computes_current_long_signal_from_ohlcv(self):
        from quant_platform import SweepReversalSignalConfig, SweepReversalSignalModule
        from quant_platform.signals import Direction

        features = pd.DataFrame(
            {
                "Open": [119.0, 110.0, 100.0, 99.0],
                "High": [121.0, 112.0, 102.0, 101.0],
                "Low": [118.0, 108.0, 99.0, 98.5],
                "Close": [120.0, 110.0, 100.0, 99.5],
                "Volume": [100.0, 120.0, 140.0, 160.0],
            },
            index=pd.date_range("2026-06-01", periods=4, freq="D", tz="UTC"),
        )

        signals = SweepReversalSignalModule(
            SweepReversalSignalConfig(lookback=3, timeframe="1d")
        ).generate(features, symbol="AAPL")

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.module, "sweep_reversal")
        self.assertEqual(signal.symbol, "AAPL")
        self.assertEqual(signal.direction, Direction.LONG)
        self.assertEqual(signal.preferred_stop, 98.5)
        self.assertEqual(signal.preferred_target, 121.0)
        self.assertEqual(signal.required_data, ("ohlcv:1d",))
        self.assertGreater(signal.score, 66.0)
        self.assertGreater(signal.confidence, 0.66)
        self.assertNotIn("_sweep_signal_long", features.columns)

    def test_sweep_reversal_signal_module_computes_current_short_signal_from_ohlcv(self):
        from quant_platform import SweepReversalSignalConfig, SweepReversalSignalModule
        from quant_platform.signals import Direction

        features = pd.DataFrame(
            {
                "Open": [90.0, 100.0, 102.0, 102.5],
                "High": [91.0, 101.0, 102.0, 103.5],
                "Low": [89.0, 99.0, 100.0, 101.0],
                "Close": [90.0, 100.0, 101.0, 101.5],
                "Volume": [100.0, 120.0, 140.0, 160.0],
            },
            index=pd.date_range("2026-06-01", periods=4, freq="D", tz="UTC"),
        )

        signals = SweepReversalSignalModule(
            SweepReversalSignalConfig(lookback=3, timeframe="1d")
        ).generate(features, symbol="BTC/USDT")

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.direction, Direction.SHORT)
        self.assertEqual(signal.preferred_stop, 103.5)
        self.assertEqual(signal.preferred_target, 89.0)
        self.assertEqual(signal.required_data, ("ohlcv:1d",))

    def test_sweep_reversal_signal_module_returns_no_signal_without_reclaim(self):
        from quant_platform.signal_modules import SweepReversalSignalConfig, SweepReversalSignalModule

        features = pd.DataFrame(
            {
                "Open": [119.0, 110.0, 100.0, 99.0],
                "High": [121.0, 112.0, 102.0, 100.0],
                "Low": [118.0, 108.0, 99.0, 98.5],
                "Close": [120.0, 110.0, 100.0, 98.8],
                "Volume": [100.0, 120.0, 140.0, 160.0],
            },
            index=pd.date_range("2026-06-01", periods=4, freq="D", tz="UTC"),
        )

        signals = SweepReversalSignalModule(
            SweepReversalSignalConfig(lookback=3, timeframe="1d")
        ).generate(features, symbol="AAPL")

        self.assertEqual(signals, [])

    def test_crash_short_signal_module_computes_current_short_signal_from_ohlcv(self):
        from quant_platform import CrashShortSignalConfig, CrashShortSignalModule
        from quant_platform.signals import Direction

        features = pd.DataFrame(
            {
                "Open": [110.0, 105.0, 100.0, 99.0],
                "High": [112.0, 106.0, 101.0, 100.0],
                "Low": [80.0, 104.0, 99.0, 93.0],
                "Close": [110.0, 105.0, 100.0, 94.0],
                "Volume": [100.0, 110.0, 120.0, 300.0],
            },
            index=pd.date_range("2026-06-01", periods=4, freq="D", tz="UTC"),
        )

        signals = CrashShortSignalModule(
            CrashShortSignalConfig(lookback=3, timeframe="1d", min_drop_pct=0.05, volume_multiplier=2.0)
        ).generate(features, symbol="BTC/USDT")

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.module, "crash_short")
        self.assertEqual(signal.symbol, "BTC/USDT")
        self.assertEqual(signal.direction, Direction.SHORT)
        self.assertEqual(signal.preferred_stop, 101.0)
        self.assertEqual(signal.preferred_target, 80.0)
        self.assertEqual(signal.required_data, ("ohlcv:1d",))
        self.assertGreater(signal.score, 72.0)
        self.assertGreater(signal.confidence, 0.72)
        self.assertNotIn("_crash_short_signal", features.columns)

    def test_crash_short_signal_module_returns_no_signal_without_volume_confirmation(self):
        from quant_platform.signal_modules import CrashShortSignalConfig, CrashShortSignalModule

        features = pd.DataFrame(
            {
                "Open": [110.0, 105.0, 100.0, 99.0],
                "High": [112.0, 106.0, 101.0, 100.0],
                "Low": [80.0, 104.0, 99.0, 93.0],
                "Close": [110.0, 105.0, 100.0, 94.0],
                "Volume": [100.0, 110.0, 120.0, 150.0],
            },
            index=pd.date_range("2026-06-01", periods=4, freq="D", tz="UTC"),
        )

        signals = CrashShortSignalModule(
            CrashShortSignalConfig(lookback=3, timeframe="1d", min_drop_pct=0.05, volume_multiplier=2.0)
        ).generate(features, symbol="BTC/USDT")

        self.assertEqual(signals, [])

    def test_failed_bounce_signal_module_computes_current_short_signal_from_ohlcv(self):
        from quant_platform import FailedBounceSignalConfig, FailedBounceSignalModule
        from quant_platform.signals import Direction

        features = pd.DataFrame(
            {
                "Open": [109.0, 107.0, 105.0, 106.0, 102.0],
                "High": [111.0, 109.0, 108.0, 110.5, 102.5],
                "Low": [108.0, 95.0, 104.0, 102.0, 100.0],
                "Close": [110.0, 108.0, 106.0, 103.0, 100.5],
                "Volume": [100.0, 110.0, 120.0, 130.0, 150.0],
            },
            index=pd.date_range("2026-06-01", periods=5, freq="D", tz="UTC"),
        )

        signals = FailedBounceSignalModule(
            FailedBounceSignalConfig(lookback=3, timeframe="1d")
        ).generate(features, symbol="BTC/USDT")

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.module, "failed_bounce")
        self.assertEqual(signal.symbol, "BTC/USDT")
        self.assertEqual(signal.direction, Direction.SHORT)
        self.assertEqual(signal.preferred_stop, 110.5)
        self.assertEqual(signal.preferred_target, 95.0)
        self.assertEqual(signal.required_data, ("ohlcv:1d",))
        self.assertGreater(signal.score, 69.0)
        self.assertGreater(signal.confidence, 0.69)
        self.assertNotIn("_failed_bounce_gate", features.columns)

    def test_failed_bounce_signal_module_returns_no_signal_without_breakdown(self):
        from quant_platform.signal_modules import FailedBounceSignalConfig, FailedBounceSignalModule

        features = pd.DataFrame(
            {
                "Open": [109.0, 107.0, 105.0, 106.0, 103.0],
                "High": [111.0, 109.0, 108.0, 110.5, 104.0],
                "Low": [108.0, 95.0, 104.0, 102.0, 101.5],
                "Close": [110.0, 108.0, 106.0, 103.0, 102.5],
                "Volume": [100.0, 110.0, 120.0, 130.0, 150.0],
            },
            index=pd.date_range("2026-06-01", periods=5, freq="D", tz="UTC"),
        )

        signals = FailedBounceSignalModule(
            FailedBounceSignalConfig(lookback=3, timeframe="1d")
        ).generate(features, symbol="BTC/USDT")

        self.assertEqual(signals, [])

    def test_bull_trap_signal_module_computes_current_short_signal_from_ohlcv(self):
        from quant_platform import BullTrapSignalConfig, BullTrapSignalModule
        from quant_platform.signals import Direction

        features = pd.DataFrame(
            {
                "Open": [109.0, 107.0, 105.0, 106.0, 104.0],
                "High": [111.0, 109.0, 108.0, 113.0, 106.0],
                "Low": [108.0, 95.0, 104.0, 100.0, 100.5],
                "Close": [110.0, 108.0, 106.0, 103.0, 101.5],
                "Volume": [100.0, 110.0, 120.0, 260.0, 150.0],
            },
            index=pd.date_range("2026-06-01", periods=5, freq="D", tz="UTC"),
        )

        signals = BullTrapSignalModule(
            BullTrapSignalConfig(lookback=3, timeframe="1d", volume_multiplier=1.5)
        ).generate(features, symbol="BTC/USDT")

        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual(signal.module, "bull_trap")
        self.assertEqual(signal.symbol, "BTC/USDT")
        self.assertEqual(signal.direction, Direction.SHORT)
        self.assertEqual(signal.preferred_stop, 113.0)
        self.assertEqual(signal.preferred_target, 95.0)
        self.assertEqual(signal.required_data, ("ohlcv:1d",))
        self.assertGreater(signal.score, 70.0)
        self.assertGreater(signal.confidence, 0.70)
        self.assertNotIn("_bull_trap_signal", features.columns)

    def test_bull_trap_signal_module_returns_no_signal_without_breakout_volume(self):
        from quant_platform.signal_modules import BullTrapSignalConfig, BullTrapSignalModule

        features = pd.DataFrame(
            {
                "Open": [109.0, 107.0, 105.0, 106.0, 104.0],
                "High": [111.0, 109.0, 108.0, 113.0, 106.0],
                "Low": [108.0, 95.0, 104.0, 100.0, 100.5],
                "Close": [110.0, 108.0, 106.0, 103.0, 101.5],
                "Volume": [100.0, 110.0, 120.0, 130.0, 150.0],
            },
            index=pd.date_range("2026-06-01", periods=5, freq="D", tz="UTC"),
        )

        signals = BullTrapSignalModule(
            BullTrapSignalConfig(lookback=3, timeframe="1d", volume_multiplier=1.5)
        ).generate(features, symbol="BTC/USDT")

        self.assertEqual(signals, [])

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

    def test_btc_base_entry_signal_selects_standard_signal_with_legacy_gate_rules(self):
        from quant_btc.signal_modules import select_btc_base_entry_signal
        from quant_platform.signals import Direction

        row = pd.Series(
            {
                "score_pullback_long": 80.0,
                "score_pullback_short": 82.0,
                "_btc_long_stop": 95.0,
                "_btc_short_stop": 106.0,
                "_btc_long_target": 115.0,
                "_btc_short_target": 88.0,
            }
        )

        signal = select_btc_base_entry_signal(
            row,
            symbol="BTC/USDT",
            module="pullback",
            long_column="score_pullback_long",
            short_column="score_pullback_short",
            regime=1,
            daily_ema_dir=1,
            weekly_ema_dir=0,
            allow_long=True,
            allow_short=True,
            score_threshold=75.0,
            long_stop_column="_btc_long_stop",
            short_stop_column="_btc_short_stop",
            long_target_column="_btc_long_target",
            short_target_column="_btc_short_target",
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.module, "pullback")
        self.assertEqual(signal.symbol, "BTC/USDT")
        self.assertEqual(signal.direction, Direction.LONG)
        self.assertEqual(signal.score, 80.0)
        self.assertEqual(signal.preferred_stop, 95.0)
        self.assertEqual(signal.preferred_target, 115.0)
        self.assertEqual(signal.confidence, 0.80)

        high_risk_signal = select_btc_base_entry_signal(
            row,
            symbol="BTC/USDT",
            module="pullback",
            long_column="score_pullback_long",
            short_column="score_pullback_short",
            regime=4,
            daily_ema_dir=1,
            weekly_ema_dir=0,
            allow_long=True,
            allow_short=True,
            score_threshold=75.0,
        )

        self.assertIsNone(high_risk_signal)

    def test_btc_tactical_signal_selects_strong_bull_retest_as_standard_signal(self):
        from quant_btc.signal_modules import select_btc_tactical_signal
        from quant_platform.signals import Direction

        row = pd.Series(
            {
                "Close": 120.0,
                "_d_ema_169": 100.0,
                "score_breakout_retest_long": 72.0,
                "score_pullback_struct_long": 95.0,
                "score_sweep_reversal_long": 95.0,
                "score_meanrev_range_long": 95.0,
                "_sweep_signal_long": True,
                "rsi_14": 55.0,
                "_late_chase": False,
                "_bull_guard": False,
            }
        )

        signal = select_btc_tactical_signal(
            row,
            symbol="BTC/USDT",
            regime=1,
            daily_ema_dir=1,
            weekly_ema_dir=1,
            core_active=False,
            bear_core_active=False,
            short_rsi_floor=35.0,
            mtf_higher_low=False,
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.module, "breakout_retest")
        self.assertEqual(signal.direction, Direction.LONG)
        self.assertEqual(signal.score, 72.0)
        self.assertEqual(signal.required_data, ("ohlcv:4h", "features:btc_compat"))

    def test_btc_tactical_signal_selects_strong_bear_crash_short_as_standard_signal(self):
        from quant_btc.signal_modules import select_btc_tactical_signal
        from quant_platform.signals import Direction

        row = pd.Series(
            {
                "Close": 80.0,
                "_d_ema_169": 100.0,
                "score_crash_short": 78.0,
                "rsi_14": 42.0,
                "_late_chase": False,
                "_bull_guard": False,
            }
        )

        signal = select_btc_tactical_signal(
            row,
            symbol="BTC/USDT",
            regime=2,
            daily_ema_dir=-1,
            weekly_ema_dir=-1,
            core_active=False,
            bear_core_active=False,
            short_rsi_floor=35.0,
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.module, "crash")
        self.assertEqual(signal.direction, Direction.SHORT)
        self.assertEqual(signal.score, 78.0)
        self.assertGreater(signal.confidence, 0.77)

    def test_btc_core_entry_signal_selects_standard_core_long_signal(self):
        from quant_btc.signal_modules import select_btc_core_entry_signal
        from quant_platform.signals import Direction

        signal = select_btc_core_entry_signal(symbol="BTC/USDT", regime=1)

        self.assertIsNotNone(signal)
        self.assertEqual(signal.module, "core_long")
        self.assertEqual(signal.symbol, "BTC/USDT")
        self.assertEqual(signal.direction, Direction.LONG)
        self.assertEqual(signal.score, 100.0)
        self.assertEqual(signal.confidence, 1.0)
        self.assertEqual(signal.required_data, ("ohlcv:4h", "regime:btc_compat"))

        self.assertIsNone(select_btc_core_entry_signal(symbol="BTC/USDT", regime=0))

    def test_btc_core_add_signal_selects_standard_pullback_add_signal(self):
        from quant_btc.signal_modules import select_btc_core_add_signal
        from quant_platform.signals import Direction

        row = pd.Series({"pullback_long": True, "score_pullback_long": 78.0})

        signal = select_btc_core_add_signal(row, symbol="BTC/USDT")

        self.assertIsNotNone(signal)
        self.assertEqual(signal.module, "core_add")
        self.assertEqual(signal.direction, Direction.LONG)
        self.assertEqual(signal.score, 78.0)
        self.assertEqual(signal.entry_reason, "core_add BTC compatibility entry")
        self.assertIsNone(select_btc_core_add_signal(pd.Series({"pullback_long": False}), symbol="BTC/USDT"))

    def test_btc_bear_core_probe_signal_selects_standard_probe_signal(self):
        from quant_btc.signal_modules import select_btc_bear_core_probe_signal
        from quant_platform.signals import Direction

        row = pd.Series(
            {
                "_double_top_signal": True,
                "_top_exhaustion_score": 71.0,
                "_bull_guard": False,
            }
        )

        signal = select_btc_bear_core_probe_signal(
            row,
            symbol="BTC/USDT",
            core_active=False,
            bear_core_active=False,
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.module, "bear_core_probe")
        self.assertEqual(signal.direction, Direction.SHORT)
        self.assertEqual(signal.score, 71.0)
        self.assertEqual(signal.required_data, ("ohlcv:4h", "features:btc_compat"))
        self.assertIsNone(
            select_btc_bear_core_probe_signal(
                row,
                symbol="BTC/USDT",
                core_active=True,
                bear_core_active=False,
            )
        )
        self.assertIsNone(
            select_btc_bear_core_probe_signal(
                pd.Series({"_double_top_signal": True, "_top_exhaustion_score": 69.0}),
                symbol="BTC/USDT",
                core_active=False,
                bear_core_active=False,
            )
        )

    def test_btc_bear_core_confirm_add_signal_selects_standard_signal(self):
        from quant_btc.signal_modules import select_btc_bear_core_confirm_add_signal
        from quant_platform.signals import Direction

        row = pd.Series(
            {
                "Close": 90.0,
                "_d_ema_dir": -1.0,
                "_w_ema_dir": 0.0,
                "_w_ema_169": 100.0,
            }
        )

        signal = select_btc_bear_core_confirm_add_signal(
            row,
            symbol="BTC/USDT",
            bar_index=20,
            entry_bar=10,
            active=True,
            stage=1,
            probe_peak_r=1.2,
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.module, "bear_core_confirm")
        self.assertEqual(signal.direction, Direction.SHORT)
        self.assertEqual(signal.score, 80.0)
        self.assertEqual(signal.required_data, ("ohlcv:4h", "features:btc_compat"))

        blocked = select_btc_bear_core_confirm_add_signal(
            row,
            symbol="BTC/USDT",
            bar_index=10,
            entry_bar=10,
            active=True,
            stage=1,
            probe_peak_r=1.2,
        )
        self.assertIsNone(blocked)

    def test_btc_bear_core_acceleration_add_signal_selects_standard_signal(self):
        from quant_btc.signal_modules import select_btc_bear_core_acceleration_add_signal
        from quant_platform.signals import Direction

        row = pd.Series(
            {
                "_d_ema_dir": -1.0,
                "_adx_signal": 23.0,
                "_plus_di": 12.0,
                "_minus_di": 18.0,
            }
        )

        signal = select_btc_bear_core_acceleration_add_signal(
            row,
            symbol="BTC/USDT",
            bar_index=30,
            last_trade_bar=20,
            active=True,
            stage=2,
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.module, "bear_core_acceleration")
        self.assertEqual(signal.direction, Direction.SHORT)
        self.assertEqual(signal.score, 85.0)
        self.assertEqual(signal.required_data, ("ohlcv:4h", "features:btc_compat"))

        blocked = select_btc_bear_core_acceleration_add_signal(
            pd.Series(
                {
                    "_d_ema_dir": -1.0,
                    "_adx_signal": 21.0,
                    "_plus_di": 12.0,
                    "_minus_di": 18.0,
                }
            ),
            symbol="BTC/USDT",
            bar_index=30,
            last_trade_bar=20,
            active=True,
            stage=2,
        )
        self.assertIsNone(blocked)

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
