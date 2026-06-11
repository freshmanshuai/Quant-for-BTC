import tempfile
import unittest
import json
from pathlib import Path

from quant_platform.signal_modules import (
    BreakoutSignalConfig,
    BullTrapSignalConfig,
    CrashShortSignalConfig,
    FailedBounceSignalConfig,
    MeanReversionSignalConfig,
    PullbackSignalConfig,
    SweepReversalSignalConfig,
)


class PineGeneratorTest(unittest.TestCase):
    def test_generates_breakout_pine_from_signal_module_config(self):
        from quant_platform.pine import generate_signal_module_pine

        source = generate_signal_module_pine(
            [
                BreakoutSignalConfig(
                    module="donchian_alpha",
                    lookback=55,
                    timeframe="240",
                    risk_reward=3.0,
                    score_floor=76.0,
                    score_breakout_scale=500.0,
                    allow_long=True,
                    allow_short=False,
                )
            ],
            title="Research Signals",
            layer="tactical",
        )

        self.assertIn('indicator("Research Signals", overlay=true)', source)
        self.assertIn("donchian_alpha_lookback = input.int(55", source)
        self.assertIn("donchian_alpha_riskReward = input.float(3.0", source)
        self.assertIn("donchian_alpha_scoreFloor = input.float(76.0", source)
        self.assertIn("donchian_alpha_scoreBreakoutScale = input.float(500.0", source)
        self.assertIn('donchian_alpha_high = request.security(syminfo.tickerid, "240", high)', source)
        self.assertIn("donchian_alpha_channelHigh = ta.highest(donchian_alpha_high[1], donchian_alpha_lookback)", source)
        self.assertIn("donchian_alpha_longSignal = donchian_alpha_close > donchian_alpha_channelHigh", source)
        self.assertIn("donchian_alpha_shortSignal = false", source)
        self.assertIn('"signal_key,bar_time,entry_price,stop_price,target_price,score"', source)
        self.assertIn('str.format("{0}|tactical|donchian_alpha|long", syminfo.ticker)', source)

    def test_generates_pullback_pine_from_signal_module_config(self):
        from quant_platform.pine import generate_signal_module_pine

        source = generate_signal_module_pine(
            [
                PullbackSignalConfig(
                    module="ema_retest",
                    ema_length=34,
                    timeframe="60",
                    pullback_tolerance_pct=0.015,
                    stop_lookback=4,
                    risk_reward=2.5,
                    score_floor=69.0,
                    score_resume_scale=250.0,
                    allow_long=False,
                    allow_short=True,
                )
            ],
            title="Pullback Signals",
            layer="core",
        )

        self.assertIn("ema_retest_emaLength = input.int(34", source)
        self.assertIn("ema_retest_pullbackTolerancePct = input.float(0.015", source)
        self.assertIn("ema_retest_stopLookback = input.int(4", source)
        self.assertIn("ema_retest_riskReward = input.float(2.5", source)
        self.assertIn("ema_retest_scoreResumeScale = input.float(250.0", source)
        self.assertIn('ema_retest_close = request.security(syminfo.tickerid, "60", close)', source)
        self.assertIn("ema_retest_ema = ta.ema(ema_retest_close, ema_retest_emaLength)", source)
        self.assertIn("ema_retest_longSignal = false", source)
        self.assertIn(
            "ema_retest_shortSignal = ema_retest_previousHigh >= ema_retest_previousEma * (1.0 - ema_retest_pullbackTolerancePct)",
            source,
        )
        self.assertIn("ema_retest_shortStop = ta.highest(ema_retest_high, ema_retest_stopLookback + 1)", source)
        self.assertIn('str.format("{0}|core|ema_retest|short", syminfo.ticker)', source)

    def test_generates_mean_reversion_pine_from_signal_module_config(self):
        from quant_platform.pine import generate_signal_module_pine

        source = generate_signal_module_pine(
            [
                MeanReversionSignalConfig(
                    module="bb_reclaim",
                    lookback=31,
                    std_mult=1.7,
                    timeframe="D",
                    stop_lookback=5,
                    score_floor=64.0,
                    score_deviation_scale=420.0,
                    allow_long=True,
                    allow_short=False,
                )
            ],
            title="Mean Reversion Signals",
            layer="tactical",
        )

        self.assertIn("bb_reclaim_lookback = input.int(31", source)
        self.assertIn("bb_reclaim_stdMult = input.float(1.7", source)
        self.assertIn("bb_reclaim_stopLookback = input.int(5", source)
        self.assertIn("bb_reclaim_scoreFloor = input.float(64.0", source)
        self.assertIn("bb_reclaim_scoreDeviationScale = input.float(420.0", source)
        self.assertIn('bb_reclaim_close = request.security(syminfo.tickerid, "D", close)', source)
        self.assertIn("bb_reclaim_mid = ta.sma(bb_reclaim_close[1], bb_reclaim_lookback)", source)
        self.assertIn("bb_reclaim_std = ta.stdev(bb_reclaim_close[1], bb_reclaim_lookback, false)", source)
        self.assertIn("bb_reclaim_lower = bb_reclaim_mid - bb_reclaim_stdMult * bb_reclaim_std", source)
        self.assertIn("bb_reclaim_longSignal = bb_reclaim_low < bb_reclaim_lower and bb_reclaim_lower < bb_reclaim_close and bb_reclaim_close < bb_reclaim_mid and bb_reclaim_longStop < bb_reclaim_close", source)
        self.assertIn("bb_reclaim_shortSignal = false", source)
        self.assertIn('str.format("{0}|tactical|bb_reclaim|long", syminfo.ticker)', source)

    def test_generates_sweep_reversal_pine_from_signal_module_config(self):
        from quant_platform.pine import generate_signal_module_pine

        source = generate_signal_module_pine(
            [
                SweepReversalSignalConfig(
                    module="range_sweep",
                    lookback=18,
                    timeframe="120",
                    score_floor=67.0,
                    score_sweep_scale=850.0,
                    allow_long=False,
                    allow_short=True,
                )
            ],
            title="Sweep Signals",
            layer="tactical",
        )

        self.assertIn("range_sweep_lookback = input.int(18", source)
        self.assertIn("range_sweep_scoreFloor = input.float(67.0", source)
        self.assertIn("range_sweep_scoreSweepScale = input.float(850.0", source)
        self.assertIn('range_sweep_high = request.security(syminfo.tickerid, "120", high)', source)
        self.assertIn("range_sweep_support = ta.lowest(range_sweep_low[1], range_sweep_lookback)", source)
        self.assertIn("range_sweep_resistance = ta.highest(range_sweep_high[1], range_sweep_lookback)", source)
        self.assertIn("range_sweep_longSignal = false", source)
        self.assertIn(
            "range_sweep_shortSignal = range_sweep_high > range_sweep_resistance and range_sweep_resistance > range_sweep_close and range_sweep_close > range_sweep_support",
            source,
        )
        self.assertIn("range_sweep_shortStop = range_sweep_high", source)
        self.assertIn("range_sweep_shortTarget = range_sweep_support", source)
        self.assertIn('str.format("{0}|tactical|range_sweep|short", syminfo.ticker)', source)

    def test_generates_crash_short_pine_from_signal_module_config(self):
        from quant_platform.pine import generate_signal_module_pine

        source = generate_signal_module_pine(
            [
                CrashShortSignalConfig(
                    module="panic_short",
                    lookback=24,
                    timeframe="15",
                    min_drop_pct=0.035,
                    volume_multiplier=2.4,
                    stop_lookback=3,
                    risk_reward=1.8,
                    score_floor=73.0,
                    score_drop_scale=410.0,
                    score_volume_scale=12.5,
                )
            ],
            title="Crash Short Signals",
            layer="tactical",
        )

        self.assertIn("panic_short_lookback = input.int(24", source)
        self.assertIn("panic_short_minDropPct = input.float(0.035", source)
        self.assertIn("panic_short_volumeMultiplier = input.float(2.4", source)
        self.assertIn("panic_short_stopLookback = input.int(3", source)
        self.assertIn("panic_short_riskReward = input.float(1.8", source)
        self.assertIn("panic_short_scoreDropScale = input.float(410.0", source)
        self.assertIn("panic_short_scoreVolumeScale = input.float(12.5", source)
        self.assertIn('panic_short_open = request.security(syminfo.tickerid, "15", open)', source)
        self.assertIn('panic_short_volume = request.security(syminfo.tickerid, "15", volume)', source)
        self.assertIn("panic_short_previousClose = panic_short_close[1]", source)
        self.assertIn("panic_short_avgVolume = ta.sma(panic_short_volume[1], panic_short_lookback)", source)
        self.assertIn("panic_short_stop = ta.highest(panic_short_high, panic_short_stopLookback + 1)", source)
        self.assertIn("panic_short_target = panic_short_close - panic_short_riskReward * math.abs(panic_short_stop - panic_short_close)", source)
        self.assertIn(
            "panic_short_shortSignal = panic_short_dropPct >= panic_short_minDropPct and panic_short_volumeRatio >= panic_short_volumeMultiplier and panic_short_close < panic_short_open and panic_short_close < panic_short_previousClose and panic_short_stop > panic_short_close",
            source,
        )
        self.assertIn('str.format("{0}|tactical|panic_short|short", syminfo.ticker)', source)

    def test_generates_failed_bounce_pine_from_signal_module_config(self):
        from quant_platform.pine import generate_signal_module_pine

        source = generate_signal_module_pine(
            [
                FailedBounceSignalConfig(
                    module="failed_rally",
                    lookback=22,
                    timeframe="30",
                    resistance_tolerance_pct=0.018,
                    min_upper_wick_pct=0.42,
                    score_floor=71.0,
                    score_rejection_scale=360.0,
                    score_wick_scale=16.0,
                )
            ],
            title="Failed Bounce Signals",
            layer="tactical",
        )

        self.assertIn("failed_rally_lookback = input.int(22", source)
        self.assertIn("failed_rally_resistanceTolerancePct = input.float(0.018", source)
        self.assertIn("failed_rally_minUpperWickPct = input.float(0.42", source)
        self.assertIn("failed_rally_scoreRejectionScale = input.float(360.0", source)
        self.assertIn("failed_rally_scoreWickScale = input.float(16.0", source)
        self.assertIn('failed_rally_open = request.security(syminfo.tickerid, "30", open)', source)
        self.assertIn("failed_rally_resistance = ta.highest(failed_rally_high[2], failed_rally_lookback)", source)
        self.assertIn("failed_rally_support = ta.lowest(failed_rally_low[2], failed_rally_lookback)", source)
        self.assertIn("failed_rally_setupHigh = failed_rally_high[1]", source)
        self.assertIn("failed_rally_upperWick = failed_rally_setupRange <= 0.0 ? 0.0 : math.max(0.0, (failed_rally_setupHigh - failed_rally_setupBodyTop) / failed_rally_setupRange)", source)
        self.assertIn("failed_rally_stop = math.max(failed_rally_setupHigh, failed_rally_high)", source)
        self.assertIn("failed_rally_target = failed_rally_support", source)
        self.assertIn(
            "failed_rally_shortSignal = failed_rally_resistance > 0.0 and failed_rally_support < failed_rally_close and failed_rally_setupHigh >= failed_rally_resistance * (1.0 - failed_rally_resistanceTolerancePct)",
            source,
        )
        self.assertIn('str.format("{0}|tactical|failed_rally|short", syminfo.ticker)', source)

    def test_generates_bull_trap_pine_from_signal_module_config(self):
        from quant_platform.pine import generate_signal_module_pine

        source = generate_signal_module_pine(
            [
                BullTrapSignalConfig(
                    module="bull_trap_short",
                    lookback=26,
                    timeframe="45",
                    volume_multiplier=1.8,
                    weak_close_threshold=0.38,
                    score_floor=74.0,
                    score_breakout_scale=330.0,
                    score_rejection_scale=280.0,
                    score_volume_scale=11.0,
                )
            ],
            title="Bull Trap Signals",
            layer="tactical",
        )

        self.assertIn("bull_trap_short_lookback = input.int(26", source)
        self.assertIn("bull_trap_short_volumeMultiplier = input.float(1.8", source)
        self.assertIn("bull_trap_short_weakCloseThreshold = input.float(0.38", source)
        self.assertIn("bull_trap_short_scoreBreakoutScale = input.float(330.0", source)
        self.assertIn("bull_trap_short_scoreRejectionScale = input.float(280.0", source)
        self.assertIn("bull_trap_short_scoreVolumeScale = input.float(11.0", source)
        self.assertIn('bull_trap_short_volume = request.security(syminfo.tickerid, "45", volume)', source)
        self.assertIn("bull_trap_short_resistance = ta.highest(bull_trap_short_high[2], bull_trap_short_lookback)", source)
        self.assertIn("bull_trap_short_support = ta.lowest(bull_trap_short_low[2], bull_trap_short_lookback)", source)
        self.assertIn("bull_trap_short_setupHigh = bull_trap_short_high[1]", source)
        self.assertIn("bull_trap_short_avgVolume = ta.sma(bull_trap_short_volume[2], bull_trap_short_lookback)", source)
        self.assertIn("bull_trap_short_closePosition = bull_trap_short_currentRange <= 0.0 ? 0.5 : (bull_trap_short_close - bull_trap_short_low) / bull_trap_short_currentRange", source)
        self.assertIn("bull_trap_short_stop = math.max(bull_trap_short_setupHigh, bull_trap_short_high)", source)
        self.assertIn("bull_trap_short_target = bull_trap_short_support", source)
        self.assertIn(
            "bull_trap_short_shortSignal = bull_trap_short_resistance > 0.0 and bull_trap_short_avgVolume > 0.0 and bull_trap_short_support < bull_trap_short_close and bull_trap_short_setupHigh > bull_trap_short_resistance",
            source,
        )
        self.assertIn('str.format("{0}|tactical|bull_trap_short|short", syminfo.ticker)', source)

    def test_write_generated_pine_script_creates_parent_directory(self):
        from quant_platform.pine import generate_signal_module_pine, write_pine_script

        source = generate_signal_module_pine([BreakoutSignalConfig(module="breakout")])
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "generated" / "signals.pine"

            write_pine_script(target, source)

            self.assertEqual(target.read_text(encoding="utf-8"), source)

    def test_writes_generated_pine_parity_example_artifacts(self):
        from quant_platform.delivery import compare_pine_golden_vector_files, load_pine_golden_vectors_json
        from quant_platform.pine import write_signal_module_pine_parity_example

        with tempfile.TemporaryDirectory() as tmp:
            artifacts = write_signal_module_pine_parity_example(Path(tmp) / "pine_parity")

            self.assertEqual(
                set(artifacts),
                {"pine_script", "expected_vectors", "observed_template"},
            )
            source = artifacts["pine_script"].read_text(encoding="utf-8")
            vectors = load_pine_golden_vectors_json(artifacts["expected_vectors"])
            issues = compare_pine_golden_vector_files(
                artifacts["expected_vectors"],
                artifacts["observed_template"],
                tolerance=0.01,
            )

        self.assertIn('indicator("Generated Signal Module Parity Example", overlay=true)', source)
        self.assertIn("// breakout", source)
        self.assertIn("// pullback", source)
        self.assertIn("// meanrev", source)
        self.assertIn("// sweep_reversal", source)
        self.assertIn("// crash_short", source)
        self.assertIn("// failed_bounce", source)
        self.assertIn("// bull_trap", source)
        self.assertEqual(
            sorted(vector.signal_key for vector in vectors),
            [
                "AAPL|tactical|breakout|long",
                "AAPL|tactical|bull_trap|short",
                "AAPL|tactical|crash_short|short",
                "AAPL|tactical|failed_bounce|short",
                "AAPL|tactical|meanrev|long",
                "AAPL|tactical|pullback|long",
                "AAPL|tactical|sweep_reversal|long",
            ],
        )
        self.assertEqual(issues, [])

    def test_writes_pine_parity_example_from_signal_module_config_file(self):
        from quant_platform.delivery import load_pine_golden_vectors_json
        from quant_platform.pine import write_signal_module_pine_parity_example

        signal_config = {
            "default_module_set": "pine_subset",
            "module_sets": [
                {
                    "name": "pine_subset",
                    "modules": [
                        {
                            "type": "breakout",
                            "params": {
                                "module": "configured_breakout",
                                "lookback": 3,
                                "allow_short": False,
                            },
                        },
                        {
                            "type": "pullback",
                            "params": {
                                "module": "configured_pullback",
                                "ema_length": 3,
                                "allow_short": False,
                            },
                        },
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "research_signal_modules.json"
            config_path.write_text(json.dumps(signal_config), encoding="utf-8")

            artifacts = write_signal_module_pine_parity_example(
                Path(tmp) / "pine_parity",
                config_path=config_path,
                timeframe="1D",
            )

            source = artifacts["pine_script"].read_text(encoding="utf-8")
            vectors = load_pine_golden_vectors_json(artifacts["expected_vectors"])

        self.assertIn("// configured_breakout", source)
        self.assertIn("// configured_pullback", source)
        self.assertIn('configured_breakout_high = request.security(syminfo.tickerid, "1D", high)', source)
        self.assertIn("configured_pullback_emaLength = input.int(3", source)
        self.assertNotIn("// meanrev", source)
        self.assertNotIn("// crash_short", source)
        self.assertEqual(
            sorted(vector.signal_key for vector in vectors),
            [
                "AAPL|tactical|configured_breakout|long",
                "AAPL|tactical|configured_pullback|long",
            ],
        )


if __name__ == "__main__":
    unittest.main()
