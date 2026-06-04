import unittest

import pandas as pd


def sample_regime_bars() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=12, freq="4h", tz="UTC")
    close = pd.Series([100, 101, 102, 103, 104, 105, 98, 97, 96, 100, 100.1, 100.2], index=index, dtype=float)
    return pd.DataFrame(
        {
            "Open": close.shift(1).fillna(close.iloc[0]),
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": 1000.0,
        },
        index=index,
    )


class RegimeModelTest(unittest.TestCase):
    def test_regime_model_classifies_from_profile_thresholds_without_mutating_input(self):
        from quant_platform.regimes import RegimeLabel, RegimeModel, RegimeProfile

        bars = sample_regime_bars()
        model = RegimeModel(
            RegimeProfile(
                trend_ema_length=3,
                daily_rule="4h",
                weekly_rule="8h",
                adx_period=3,
                bb_period=3,
                bb_std_mult=2.0,
                regime_lookback=4,
                compression_bb_pct=0.40,
                compression_atr_pct=0.40,
                high_vol_atr_pct=0.75,
                high_vol_large_candle_mult=10.0,
                adx_ranging_threshold=100.0,
            )
        )

        result = model.classify(bars)

        for col in [
            "_d_ema_dir",
            "_w_ema_dir",
            "_d_ema_3",
            "_w_ema_3",
            "_bb_width_pct",
            "_atr_pct",
            "_adx",
            "_regime",
        ]:
            self.assertIn(col, result.columns)
        self.assertNotIn("_regime", bars.columns)
        self.assertTrue(result["_regime"].isin([label.value for label in RegimeLabel]).all())

    def test_regime_priority_keeps_high_risk_above_trend(self):
        from quant_platform.regimes import RegimeLabel, RegimeModel, RegimeProfile

        bars = sample_regime_bars()
        model = RegimeModel(
            RegimeProfile(
                trend_ema_length=3,
                daily_rule="4h",
                weekly_rule="8h",
                adx_period=3,
                regime_lookback=4,
                high_vol_atr_pct=0.0,
            )
        )

        result = model.classify(bars)

        self.assertEqual(int(result["_regime"].iloc[-1]), RegimeLabel.HIGH_RISK.value)

    def test_regime_profile_registry_selects_asset_specific_profile(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.regimes import RegimeProfile, RegimeProfileRegistry

        default = RegimeProfile(trend_ema_length=169)
        btc_profile = RegimeProfile(trend_ema_length=55)
        equity_profile = RegimeProfile(trend_ema_length=200, daily_rule="1D", weekly_rule="1W")
        registry = RegimeProfileRegistry(default_profile=default)
        registry.register("BTC/USDT", btc_profile)
        registry.register_market(exchange="nasdaq", market_type="equity", profile=equity_profile)

        btc_market = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
        )
        equity_market = MarketSpec(
            asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
        )
        fallback_market = MarketSpec(
            asset=AssetSpec(symbol="ETH/USDT", base="ETH", quote="USDT"),
            exchange="binance",
            market_type="swap",
        )

        self.assertIs(registry.profile_for(btc_market), btc_profile)
        self.assertIs(registry.profile_for(equity_market), equity_profile)
        self.assertIs(registry.profile_for(fallback_market), default)

    def test_regime_profile_registry_loads_json_config_for_non_btc_markets(self):
        import json
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.regimes import load_regime_profile_registry_json

        payload = {
            "default": {"trend_ema_length": 169},
            "profiles": [
                {
                    "exchange": "nasdaq",
                    "market_type": "equity",
                    "trend_ema_length": 50,
                    "daily_rule": "1D",
                    "weekly_rule": "1W-FRI",
                    "ema_slope_threshold": 0.0005,
                    "high_vol_atr_pct": 0.85,
                }
            ],
        }
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "regime_profiles.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            registry = load_regime_profile_registry_json(path)

        equity_market = MarketSpec(
            asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
        )
        crypto_market = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
        )

        equity_profile = registry.profile_for(equity_market)
        self.assertEqual(equity_profile.trend_ema_length, 50)
        self.assertEqual(equity_profile.weekly_rule, "1W-FRI")
        self.assertEqual(equity_profile.ema_slope_threshold, 0.0005)
        self.assertEqual(equity_profile.high_vol_atr_pct, 0.85)
        self.assertEqual(registry.profile_for(crypto_market).trend_ema_length, 169)

    def test_btc_regime_model_builder_preserves_strategy_columns(self):
        from quant_btc.config import RiskConfig
        from quant_btc.regime_model import build_btc_regime_model

        bars = sample_regime_bars()
        result = build_btc_regime_model(RiskConfig()).classify(bars)

        for col in ["_d_ema_dir", "_w_ema_dir", "_d_ema_169", "_w_ema_169", "_regime"]:
            self.assertIn(col, result.columns)

    def test_btc_regime_entry_gate_matches_strategy_modes(self):
        from quant_btc.regime_model import btc_regime_entry_gate

        self.assertEqual(
            btc_regime_entry_gate(regime=1, d_dir=-1, w_dir=-1, mode="default"),
            (True, True),
        )
        self.assertEqual(
            btc_regime_entry_gate(regime=0, d_dir=1, w_dir=1, mode="default"),
            (True, False),
        )
        self.assertEqual(
            btc_regime_entry_gate(regime=3, d_dir=0, w_dir=1, mode="breakout"),
            (True, False),
        )
        self.assertEqual(
            btc_regime_entry_gate(regime=2, d_dir=1, w_dir=0, mode="breakout"),
            (False, True),
        )
        self.assertEqual(
            btc_regime_entry_gate(regime=0, d_dir=1, w_dir=1, mode="meanrev"),
            (True, True),
        )
        self.assertEqual(
            btc_regime_entry_gate(regime=4, d_dir=0, w_dir=0, mode="meanrev"),
            (False, False),
        )

    def test_btc_strategy_regime_gate_methods_delegate_to_compatibility_helper(self):
        from quant_btc.strategy import ATRHTFStopStrategy, BreakoutStrategy, MeanRevStrategy

        self.assertEqual(
            ATRHTFStopStrategy.__new__(ATRHTFStopStrategy)._regime_entry_gate(0, 1, 1),
            (True, False),
        )
        self.assertEqual(
            BreakoutStrategy.__new__(BreakoutStrategy)._regime_entry_gate(3, 0, 1),
            (True, False),
        )
        self.assertEqual(
            MeanRevStrategy.__new__(MeanRevStrategy)._regime_entry_gate(0, -1, -1),
            (True, True),
        )


if __name__ == "__main__":
    unittest.main()
