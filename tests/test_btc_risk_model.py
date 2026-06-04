import unittest


class BtcRiskModelTest(unittest.TestCase):
    def test_dual_layer_regime_size_multiplier_preserves_weak_bull_half_size(self):
        from quant_btc.risk_model import btc_dual_layer_regime_size_multiplier

        self.assertAlmostEqual(
            btc_dual_layer_regime_size_multiplier(
                regime=3,
                daily_ema_dir=1,
                weekly_ema_dir=0,
            ),
            0.5,
        )
        self.assertAlmostEqual(
            btc_dual_layer_regime_size_multiplier(
                regime=1,
                daily_ema_dir=1,
                weekly_ema_dir=1,
            ),
            1.0,
        )
        self.assertAlmostEqual(
            btc_dual_layer_regime_size_multiplier(
                regime=0,
                daily_ema_dir=1,
                weekly_ema_dir=1,
            ),
            1.0,
        )
        self.assertAlmostEqual(
            btc_dual_layer_regime_size_multiplier(
                regime=2,
                daily_ema_dir=1,
                weekly_ema_dir=1,
            ),
            1.0,
        )
        self.assertAlmostEqual(
            btc_dual_layer_regime_size_multiplier(
                regime=4,
                daily_ema_dir=1,
                weekly_ema_dir=1,
            ),
            1.0,
        )
        self.assertAlmostEqual(
            btc_dual_layer_regime_size_multiplier(
                regime=3,
                daily_ema_dir=-1,
                weekly_ema_dir=1,
            ),
            1.0,
        )

    def test_base_position_size_preserves_legacy_risk_adjustments(self):
        from quant_btc.config import RiskConfig
        from quant_btc.risk_model import calculate_btc_base_position_size

        risk_cfg = RiskConfig(
            risk_per_trade=0.02,
            max_position_frac=0.8,
            consecutive_loss_limit=2,
            reduced_size_mult=0.5,
            risk_bear_short_mult=0.6,
        )

        self.assertAlmostEqual(
            calculate_btc_base_position_size(
                entry=100.0,
                stop=95.0,
                risk_per_trade=0.02,
                consecutive_losses=0,
                daily_ema_dir=1,
                weekly_ema_dir=1,
                risk_cfg=risk_cfg,
            ),
            0.4,
        )
        self.assertAlmostEqual(
            calculate_btc_base_position_size(
                entry=100.0,
                stop=95.0,
                risk_per_trade=0.02,
                consecutive_losses=2,
                daily_ema_dir=1,
                weekly_ema_dir=-1,
                risk_cfg=risk_cfg,
            ),
            0.1,
        )
        self.assertAlmostEqual(
            calculate_btc_base_position_size(
                entry=100.0,
                stop=105.0,
                risk_per_trade=0.02,
                consecutive_losses=0,
                daily_ema_dir=-1,
                weekly_ema_dir=-1,
                risk_cfg=risk_cfg,
            ),
            0.24,
        )
        self.assertAlmostEqual(
            calculate_btc_base_position_size(
                entry=100.0,
                stop=99.0,
                risk_per_trade=0.02,
                consecutive_losses=0,
                daily_ema_dir=1,
                weekly_ema_dir=1,
                risk_cfg=risk_cfg,
            ),
            0.8,
        )
        self.assertEqual(
            calculate_btc_base_position_size(
                entry=100.0,
                stop=99.999,
                risk_per_trade=0.02,
                consecutive_losses=0,
                daily_ema_dir=1,
                weekly_ema_dir=1,
                risk_cfg=risk_cfg,
            ),
            0.0,
        )

    def test_tactical_position_size_uses_module_risk_and_short_discount(self):
        from quant_btc.config import RiskConfig
        from quant_btc.risk_model import calculate_btc_tactical_position_size

        risk_cfg = RiskConfig(
            risk_breakout=0.0065,
            risk_pullback=0.0050,
            risk_meanrev=0.0025,
            risk_per_trade=0.02,
            risk_bear_short_mult=0.6,
        )

        self.assertAlmostEqual(
            calculate_btc_tactical_position_size(
                module="breakout_retest",
                is_long=True,
                entry=100.0,
                stop=99.0,
                risk_cfg=risk_cfg,
            ),
            0.65,
        )
        self.assertAlmostEqual(
            calculate_btc_tactical_position_size(
                module="failed_bounce",
                is_long=False,
                entry=100.0,
                stop=102.0,
                risk_cfg=risk_cfg,
            ),
            0.15,
        )
        self.assertAlmostEqual(
            calculate_btc_tactical_position_size(
                module="meanrev_range",
                is_long=True,
                entry=100.0,
                stop=50.0,
                risk_cfg=risk_cfg,
            ),
            0.005,
        )
        self.assertAlmostEqual(
            calculate_btc_tactical_position_size(
                module="unknown_module",
                is_long=True,
                entry=100.0,
                stop=99.0,
                risk_cfg=risk_cfg,
            ),
            0.99,
        )


if __name__ == "__main__":
    unittest.main()
