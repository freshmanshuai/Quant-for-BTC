import unittest


class BtcPortfolioModelTest(unittest.TestCase):
    def test_base_entry_plan_preserves_risk_reward_size_and_state_rules(self):
        from quant_btc.portfolio_model import btc_base_entry_plan

        self.assertIsNone(
            btc_base_entry_plan(
                is_long=True,
                entry_price=100.0,
                stop_price=100.0,
                target_price=130.0,
                size=1.0,
                use_fixed_tp=True,
                min_reward_risk=2.0,
                min_size=0.001,
                entry_atr=5.0,
                entry_bar=12,
            )
        )
        self.assertIsNone(
            btc_base_entry_plan(
                is_long=True,
                entry_price=100.0,
                stop_price=90.0,
                target_price=None,
                size=1.0,
                use_fixed_tp=True,
                min_reward_risk=2.0,
                min_size=0.001,
                entry_atr=5.0,
                entry_bar=12,
            )
        )
        self.assertIsNone(
            btc_base_entry_plan(
                is_long=False,
                entry_price=100.0,
                stop_price=110.0,
                target_price=85.0,
                size=1.0,
                use_fixed_tp=True,
                min_reward_risk=2.0,
                min_size=0.001,
                entry_atr=5.0,
                entry_bar=12,
            )
        )
        self.assertIsNone(
            btc_base_entry_plan(
                is_long=True,
                entry_price=100.0,
                stop_price=90.0,
                target_price=130.0,
                size=0.0009,
                use_fixed_tp=True,
                min_reward_risk=2.0,
                min_size=0.001,
                entry_atr=5.0,
                entry_bar=12,
            )
        )

        long_plan = btc_base_entry_plan(
            is_long=True,
            entry_price=100.0,
            stop_price=90.0,
            target_price=120.0,
            size=0.25,
            use_fixed_tp=True,
            min_reward_risk=2.0,
            min_size=0.001,
            entry_atr=5.0,
            entry_bar=12,
        )
        self.assertIsNotNone(long_plan)
        self.assertEqual(long_plan.initial_risk, 10.0)
        self.assertEqual(long_plan.trailing_stop, 90.0)
        self.assertEqual(long_plan.extreme_since_entry, 100.0)
        self.assertEqual(long_plan.entry_atr, 5.0)
        self.assertEqual(long_plan.entry_bar, 12)
        self.assertEqual(long_plan.last_trade_bar, 12)
        self.assertFalse(long_plan.partial_done)

        breakout_plan = btc_base_entry_plan(
            is_long=False,
            entry_price=100.0,
            stop_price=110.0,
            target_price=None,
            size=0.25,
            use_fixed_tp=False,
            min_reward_risk=2.0,
            min_size=0.001,
            entry_atr=5.0,
            entry_bar=12,
        )
        self.assertIsNotNone(breakout_plan)
        self.assertIsNone(breakout_plan.target_price)

    def test_bear_core_v_reversal_exit_preserves_peak_snapback_and_trend_rules(self):
        from quant_btc.portfolio_model import btc_bear_core_v_reversal_exit

        self.assertFalse(
            btc_bear_core_v_reversal_exit(
                entry_price=100.0,
                stop_price=100.0,
                close=90.0,
                peak_r=3.0,
                bars_held=6,
                daily_ema_dir=1,
                regime=1,
            )
        )
        self.assertFalse(
            btc_bear_core_v_reversal_exit(
                entry_price=100.0,
                stop_price=110.0,
                close=82.0,
                peak_r=3.0,
                bars_held=6,
                daily_ema_dir=1,
                regime=1,
            )
        )
        self.assertFalse(
            btc_bear_core_v_reversal_exit(
                entry_price=100.0,
                stop_price=110.0,
                close=96.0,
                peak_r=1.99,
                bars_held=6,
                daily_ema_dir=1,
                regime=1,
            )
        )
        self.assertFalse(
            btc_bear_core_v_reversal_exit(
                entry_price=100.0,
                stop_price=110.0,
                close=96.0,
                peak_r=3.0,
                bars_held=13,
                daily_ema_dir=1,
                regime=1,
            )
        )
        self.assertFalse(
            btc_bear_core_v_reversal_exit(
                entry_price=100.0,
                stop_price=110.0,
                close=96.0,
                peak_r=3.0,
                bars_held=6,
                daily_ema_dir=-1,
                regime=2,
            )
        )
        self.assertTrue(
            btc_bear_core_v_reversal_exit(
                entry_price=100.0,
                stop_price=110.0,
                close=96.0,
                peak_r=3.0,
                bars_held=6,
                daily_ema_dir=0,
                regime=2,
            )
        )
        self.assertTrue(
            btc_bear_core_v_reversal_exit(
                entry_price=100.0,
                stop_price=110.0,
                close=96.0,
                peak_r=3.0,
                bars_held=6,
                daily_ema_dir=-1,
                regime=1,
            )
        )

    def test_bear_core_waterfall_runner_exit_preserves_stage_lock_and_risk_rules(self):
        from quant_btc.portfolio_model import btc_bear_core_waterfall_runner_exit

        self.assertFalse(
            btc_bear_core_waterfall_runner_exit(
                stage=2,
                entry_price=100.0,
                stop_price=110.0,
                close=94.0,
                lock_r=1.5,
            )
        )
        self.assertFalse(
            btc_bear_core_waterfall_runner_exit(
                stage=99,
                entry_price=100.0,
                stop_price=100.0,
                close=94.0,
                lock_r=1.5,
            )
        )
        self.assertFalse(
            btc_bear_core_waterfall_runner_exit(
                stage=99,
                entry_price=100.0,
                stop_price=110.0,
                close=92.5,
                lock_r=1.5,
            )
        )
        self.assertTrue(
            btc_bear_core_waterfall_runner_exit(
                stage=99,
                entry_price=100.0,
                stop_price=110.0,
                close=93.0,
                lock_r=1.5,
            )
        )

    def test_bear_core_trend_exit_plan_preserves_layer_close_and_state_cleanup(self):
        from quant_btc.portfolio_model import btc_bear_core_trend_exit_plan

        plan = btc_bear_core_trend_exit_plan(
            bear_core_active=False,
            exit_signal=True,
            bear_core_size=0.30,
            tactical_size=0.12,
            days_above_dema=2,
        )
        self.assertFalse(plan.should_exit)
        self.assertEqual(plan.layer_size, 0.0)
        self.assertFalse(plan.bear_core_active)
        self.assertEqual(plan.bear_core_size, 0.30)
        self.assertEqual(plan.tactical_size, 0.12)
        self.assertEqual(plan.days_above_dema, 2)

        plan = btc_bear_core_trend_exit_plan(
            bear_core_active=True,
            exit_signal=False,
            bear_core_size=0.30,
            tactical_size=0.12,
            days_above_dema=2,
        )
        self.assertFalse(plan.should_exit)
        self.assertEqual(plan.layer_size, 0.0)
        self.assertTrue(plan.bear_core_active)
        self.assertEqual(plan.bear_core_size, 0.30)
        self.assertEqual(plan.tactical_size, 0.12)
        self.assertEqual(plan.days_above_dema, 2)

        plan = btc_bear_core_trend_exit_plan(
            bear_core_active=True,
            exit_signal=True,
            bear_core_size=0.30,
            tactical_size=0.12,
            days_above_dema=2,
        )
        self.assertTrue(plan.should_exit)
        self.assertEqual(plan.layer_size, 0.30)
        self.assertFalse(plan.bear_core_active)
        self.assertEqual(plan.bear_core_size, 0.0)
        self.assertEqual(plan.tactical_size, 0.0)
        self.assertEqual(plan.days_above_dema, 0)

    def test_bear_core_giveback_exit_plan_preserves_layer_close_and_state_cleanup(self):
        from quant_btc.portfolio_model import btc_bear_core_giveback_exit_plan

        plan = btc_bear_core_giveback_exit_plan(
            bear_core_active=False,
            giveback_exit=True,
            bear_core_size=0.30,
        )
        self.assertFalse(plan.should_exit)
        self.assertEqual(plan.layer_size, 0.0)
        self.assertFalse(plan.bear_core_active)
        self.assertEqual(plan.bear_core_size, 0.30)

        plan = btc_bear_core_giveback_exit_plan(
            bear_core_active=True,
            giveback_exit=False,
            bear_core_size=0.30,
        )
        self.assertFalse(plan.should_exit)
        self.assertEqual(plan.layer_size, 0.0)
        self.assertTrue(plan.bear_core_active)
        self.assertEqual(plan.bear_core_size, 0.30)

        plan = btc_bear_core_giveback_exit_plan(
            bear_core_active=True,
            giveback_exit=True,
            bear_core_size=0.30,
        )
        self.assertTrue(plan.should_exit)
        self.assertEqual(plan.layer_size, 0.30)
        self.assertFalse(plan.bear_core_active)
        self.assertEqual(plan.bear_core_size, 0.0)

    def test_bear_core_v_reversal_exit_plan_preserves_layer_close_and_state_cleanup(self):
        from quant_btc.portfolio_model import btc_bear_core_v_reversal_exit_plan

        plan = btc_bear_core_v_reversal_exit_plan(
            bear_core_active=False,
            v_reversal_exit=True,
            bear_core_size=0.30,
            waterfall_triggered=True,
            days_above_dema=2,
        )
        self.assertFalse(plan.should_exit)
        self.assertEqual(plan.layer_size, 0.0)
        self.assertFalse(plan.bear_core_active)
        self.assertEqual(plan.bear_core_size, 0.30)
        self.assertTrue(plan.waterfall_triggered)
        self.assertEqual(plan.days_above_dema, 2)

        plan = btc_bear_core_v_reversal_exit_plan(
            bear_core_active=True,
            v_reversal_exit=False,
            bear_core_size=0.30,
            waterfall_triggered=True,
            days_above_dema=2,
        )
        self.assertFalse(plan.should_exit)
        self.assertEqual(plan.layer_size, 0.0)
        self.assertTrue(plan.bear_core_active)
        self.assertEqual(plan.bear_core_size, 0.30)
        self.assertTrue(plan.waterfall_triggered)
        self.assertEqual(plan.days_above_dema, 2)

        plan = btc_bear_core_v_reversal_exit_plan(
            bear_core_active=True,
            v_reversal_exit=True,
            bear_core_size=0.30,
            waterfall_triggered=True,
            days_above_dema=2,
        )
        self.assertTrue(plan.should_exit)
        self.assertEqual(plan.layer_size, 0.30)
        self.assertFalse(plan.bear_core_active)
        self.assertEqual(plan.bear_core_size, 0.0)
        self.assertFalse(plan.waterfall_triggered)
        self.assertEqual(plan.days_above_dema, 0)

    def test_bear_core_waterfall_runner_exit_plan_preserves_layer_close_and_state_cleanup(self):
        from quant_btc.portfolio_model import btc_bear_core_waterfall_runner_exit_plan

        plan = btc_bear_core_waterfall_runner_exit_plan(
            bear_core_active=False,
            runner_exit=True,
            bear_core_size=0.30,
            tactical_size=0.12,
            waterfall_triggered=True,
            days_above_dema=2,
        )
        self.assertFalse(plan.should_exit)
        self.assertEqual(plan.layer_size, 0.0)
        self.assertFalse(plan.bear_core_active)
        self.assertEqual(plan.bear_core_size, 0.30)
        self.assertEqual(plan.tactical_size, 0.12)
        self.assertTrue(plan.waterfall_triggered)
        self.assertEqual(plan.days_above_dema, 2)

        plan = btc_bear_core_waterfall_runner_exit_plan(
            bear_core_active=True,
            runner_exit=False,
            bear_core_size=0.30,
            tactical_size=0.12,
            waterfall_triggered=True,
            days_above_dema=2,
        )
        self.assertFalse(plan.should_exit)
        self.assertEqual(plan.layer_size, 0.0)
        self.assertTrue(plan.bear_core_active)
        self.assertEqual(plan.bear_core_size, 0.30)
        self.assertEqual(plan.tactical_size, 0.12)
        self.assertTrue(plan.waterfall_triggered)
        self.assertEqual(plan.days_above_dema, 2)

        plan = btc_bear_core_waterfall_runner_exit_plan(
            bear_core_active=True,
            runner_exit=True,
            bear_core_size=0.30,
            tactical_size=0.12,
            waterfall_triggered=True,
            days_above_dema=2,
        )
        self.assertTrue(plan.should_exit)
        self.assertEqual(plan.layer_size, 0.30)
        self.assertFalse(plan.bear_core_active)
        self.assertEqual(plan.bear_core_size, 0.0)
        self.assertEqual(plan.tactical_size, 0.0)
        self.assertFalse(plan.waterfall_triggered)
        self.assertEqual(plan.days_above_dema, 0)

    def test_flash_crash_dip_buy_plan_preserves_legacy_tactical_state(self):
        from quant_btc.portfolio_model import btc_flash_crash_dip_buy_plan

        self.assertFalse(
            btc_flash_crash_dip_buy_plan(
                flash_crash_active=False,
                core_active=True,
                tactical_direction=0,
                entry_price=100.0,
                bar_index=42,
            ).should_enter
        )
        self.assertFalse(
            btc_flash_crash_dip_buy_plan(
                flash_crash_active=True,
                core_active=False,
                tactical_direction=0,
                entry_price=100.0,
                bar_index=42,
            ).should_enter
        )
        self.assertFalse(
            btc_flash_crash_dip_buy_plan(
                flash_crash_active=True,
                core_active=True,
                tactical_direction=1,
                entry_price=100.0,
                bar_index=42,
            ).should_enter
        )

        plan = btc_flash_crash_dip_buy_plan(
            flash_crash_active=True,
            core_active=True,
            tactical_direction=0,
            entry_price=100.0,
            bar_index=42,
        )
        self.assertTrue(plan.should_enter)
        self.assertTrue(plan.is_long)
        self.assertEqual(plan.direction, 1)
        self.assertEqual(plan.module, "dip_buy")
        self.assertEqual(plan.order_tag, "dip_buy_long")
        self.assertEqual(plan.entry_price, 100.0)
        self.assertEqual(plan.stop_price, 92.0)
        self.assertEqual(plan.target_price, 108.0)
        self.assertEqual(plan.size, 0.10)
        self.assertEqual(plan.entry_bar, 42)
        self.assertEqual(plan.last_trade_bar, 42)

    def test_core_entry_plan_preserves_legacy_state_and_order_tag(self):
        from quant_btc.portfolio_model import btc_core_entry_plan

        plan = btc_core_entry_plan(
            core_active=True,
            entry_signal=True,
            entry_price=100.0,
            core_size=0.40,
            equity=120000.0,
            bar_index=88,
        )
        self.assertFalse(plan.should_enter)
        self.assertTrue(plan.core_active)
        self.assertEqual(plan.core_size, 0.40)
        self.assertEqual(plan.last_trade_bar, -10**9)

        plan = btc_core_entry_plan(
            core_active=False,
            entry_signal=False,
            entry_price=100.0,
            core_size=0.40,
            equity=120000.0,
            bar_index=88,
        )
        self.assertFalse(plan.should_enter)
        self.assertFalse(plan.core_active)
        self.assertEqual(plan.core_size, 0.0)
        self.assertEqual(plan.last_trade_bar, -10**9)

        plan = btc_core_entry_plan(
            core_active=False,
            entry_signal=True,
            entry_price=100.0,
            core_size=0.40,
            equity=120000.0,
            bar_index=88,
        )
        self.assertTrue(plan.should_enter)
        self.assertTrue(plan.core_active)
        self.assertTrue(plan.is_long)
        self.assertEqual(plan.order_tag, "core_long")
        self.assertEqual(plan.entry_price, 100.0)
        self.assertEqual(plan.highest_close, 100.0)
        self.assertEqual(plan.core_size, 0.40)
        self.assertEqual(plan.days_below_dema, 0)
        self.assertEqual(plan.equity_snapshot, 120000.0)
        self.assertEqual(plan.last_trade_bar, 88)

    def test_base_entry_direction_preserves_gate_threshold_and_conflict_rules(self):
        from quant_btc.portfolio_model import btc_base_entry_direction

        self.assertIsNone(
            btc_base_entry_direction(
                regime=4,
                daily_ema_dir=1,
                weekly_ema_dir=1,
                allow_long=True,
                allow_short=True,
                long_score=100.0,
                short_score=100.0,
                score_threshold=70,
            )
        )
        self.assertTrue(
            btc_base_entry_direction(
                regime=1,
                daily_ema_dir=0,
                weekly_ema_dir=0,
                allow_long=True,
                allow_short=True,
                long_score=70.0,
                short_score=69.99,
                score_threshold=70,
            )
        )
        self.assertFalse(
            btc_base_entry_direction(
                regime=2,
                daily_ema_dir=0,
                weekly_ema_dir=0,
                allow_long=True,
                allow_short=True,
                long_score=69.99,
                short_score=70.0,
                score_threshold=70,
            )
        )
        self.assertIsNone(
            btc_base_entry_direction(
                regime=1,
                daily_ema_dir=1,
                weekly_ema_dir=1,
                allow_long=False,
                allow_short=True,
                long_score=100.0,
                short_score=50.0,
                score_threshold=70,
            )
        )
        self.assertTrue(
            btc_base_entry_direction(
                regime=1,
                daily_ema_dir=1,
                weekly_ema_dir=0,
                allow_long=True,
                allow_short=True,
                long_score=80.0,
                short_score=80.0,
                score_threshold=70,
            )
        )
        self.assertFalse(
            btc_base_entry_direction(
                regime=2,
                daily_ema_dir=-1,
                weekly_ema_dir=0,
                allow_long=True,
                allow_short=True,
                long_score=80.0,
                short_score=80.0,
                score_threshold=70,
            )
        )
        self.assertIsNone(
            btc_base_entry_direction(
                regime=0,
                daily_ema_dir=0,
                weekly_ema_dir=0,
                allow_long=True,
                allow_short=True,
                long_score=80.0,
                short_score=80.0,
                score_threshold=70,
            )
        )

    def test_base_invalidation_preserves_no_profit_atr_and_htf_rules(self):
        from quant_btc.portfolio_model import btc_base_invalidation

        self.assertTrue(
            btc_base_invalidation(
                is_long=True,
                bars_held=84,
                max_bars_no_profit=84,
                close=99.0,
                entry_price=100.0,
                entry_atr=10.0,
                current_atr=20.0,
                volatility_spike_atr_mult=3.0,
                daily_ema_dir=1,
                weekly_ema_dir=1,
            )
        )
        self.assertTrue(
            btc_base_invalidation(
                is_long=False,
                bars_held=84,
                max_bars_no_profit=84,
                close=101.0,
                entry_price=100.0,
                entry_atr=10.0,
                current_atr=20.0,
                volatility_spike_atr_mult=3.0,
                daily_ema_dir=-1,
                weekly_ema_dir=-1,
            )
        )
        self.assertFalse(
            btc_base_invalidation(
                is_long=True,
                bars_held=83,
                max_bars_no_profit=84,
                close=99.0,
                entry_price=100.0,
                entry_atr=10.0,
                current_atr=20.0,
                volatility_spike_atr_mult=3.0,
                daily_ema_dir=1,
                weekly_ema_dir=1,
            )
        )
        self.assertFalse(
            btc_base_invalidation(
                is_long=True,
                bars_held=84,
                max_bars_no_profit=84,
                close=101.0,
                entry_price=100.0,
                entry_atr=10.0,
                current_atr=20.0,
                volatility_spike_atr_mult=3.0,
                daily_ema_dir=1,
                weekly_ema_dir=1,
            )
        )
        self.assertTrue(
            btc_base_invalidation(
                is_long=True,
                bars_held=1,
                max_bars_no_profit=84,
                close=110.0,
                entry_price=100.0,
                entry_atr=10.0,
                current_atr=31.0,
                volatility_spike_atr_mult=3.0,
                daily_ema_dir=1,
                weekly_ema_dir=1,
            )
        )
        self.assertFalse(
            btc_base_invalidation(
                is_long=True,
                bars_held=1,
                max_bars_no_profit=84,
                close=110.0,
                entry_price=100.0,
                entry_atr=0.0,
                current_atr=999.0,
                volatility_spike_atr_mult=3.0,
                daily_ema_dir=1,
                weekly_ema_dir=1,
            )
        )
        self.assertTrue(
            btc_base_invalidation(
                is_long=True,
                bars_held=1,
                max_bars_no_profit=84,
                close=110.0,
                entry_price=100.0,
                entry_atr=10.0,
                current_atr=20.0,
                volatility_spike_atr_mult=3.0,
                daily_ema_dir=-1,
                weekly_ema_dir=-1,
            )
        )
        self.assertTrue(
            btc_base_invalidation(
                is_long=False,
                bars_held=1,
                max_bars_no_profit=84,
                close=90.0,
                entry_price=100.0,
                entry_atr=10.0,
                current_atr=20.0,
                volatility_spike_atr_mult=3.0,
                daily_ema_dir=1,
                weekly_ema_dir=1,
            )
        )
        self.assertFalse(
            btc_base_invalidation(
                is_long=False,
                bars_held=1,
                max_bars_no_profit=84,
                close=90.0,
                entry_price=100.0,
                entry_atr=10.0,
                current_atr=20.0,
                volatility_spike_atr_mult=3.0,
                daily_ema_dir=1,
                weekly_ema_dir=0,
            )
        )

    def test_base_trailing_stop_preserves_breakeven_activation_and_hit_rules(self):
        from quant_btc.config import RiskConfig
        from quant_btc.portfolio_model import btc_base_trailing_stop_hit, btc_base_trailing_stop_update

        risk_cfg = RiskConfig(
            trailing_breakeven_r=1.5,
            trailing_activate_r=3.0,
            trailing_distance_atr=1.5,
            breakout_trail_mult=3.0,
        )

        self.assertEqual(
            btc_base_trailing_stop_update(
                is_long=True,
                close=110.0,
                high=118.0,
                low=104.0,
                atr=4.0,
                entry_price=100.0,
                initial_risk=10.0,
                previous_extreme=105.0,
                trailing_stop=90.0,
                breakout_mode=False,
                effective_breakeven_r=risk_cfg.trailing_breakeven_r,
                risk_cfg=risk_cfg,
            ),
            (118.0, 90.0),
        )
        self.assertEqual(
            btc_base_trailing_stop_update(
                is_long=True,
                close=115.0,
                high=116.0,
                low=110.0,
                atr=4.0,
                entry_price=100.0,
                initial_risk=10.0,
                previous_extreme=105.0,
                trailing_stop=90.0,
                breakout_mode=False,
                effective_breakeven_r=risk_cfg.trailing_breakeven_r,
                risk_cfg=risk_cfg,
            ),
            (116.0, 100.0),
        )
        self.assertEqual(
            btc_base_trailing_stop_update(
                is_long=True,
                close=132.0,
                high=140.0,
                low=129.0,
                atr=4.0,
                entry_price=100.0,
                initial_risk=10.0,
                previous_extreme=116.0,
                trailing_stop=100.0,
                breakout_mode=False,
                effective_breakeven_r=risk_cfg.trailing_breakeven_r,
                risk_cfg=risk_cfg,
            ),
            (140.0, 134.0),
        )
        self.assertEqual(
            btc_base_trailing_stop_update(
                is_long=False,
                close=85.0,
                high=90.0,
                low=84.0,
                atr=4.0,
                entry_price=100.0,
                initial_risk=10.0,
                previous_extreme=95.0,
                trailing_stop=110.0,
                breakout_mode=False,
                effective_breakeven_r=risk_cfg.trailing_breakeven_r,
                risk_cfg=risk_cfg,
            ),
            (84.0, 100.0),
        )
        self.assertEqual(
            btc_base_trailing_stop_update(
                is_long=False,
                close=68.0,
                high=72.0,
                low=60.0,
                atr=4.0,
                entry_price=100.0,
                initial_risk=10.0,
                previous_extreme=84.0,
                trailing_stop=100.0,
                breakout_mode=True,
                effective_breakeven_r=risk_cfg.trailing_breakeven_r,
                risk_cfg=risk_cfg,
            ),
            (60.0, 72.0),
        )
        self.assertEqual(
            btc_base_trailing_stop_update(
                is_long=True,
                close=150.0,
                high=120.0,
                low=100.0,
                atr=4.0,
                entry_price=100.0,
                initial_risk=0.0,
                previous_extreme=110.0,
                trailing_stop=90.0,
                breakout_mode=False,
                effective_breakeven_r=risk_cfg.trailing_breakeven_r,
                risk_cfg=risk_cfg,
            ),
            (120.0, 90.0),
        )

        self.assertTrue(btc_base_trailing_stop_hit(is_long=True, low=99.0, high=120.0, trailing_stop=100.0))
        self.assertFalse(btc_base_trailing_stop_hit(is_long=True, low=101.0, high=120.0, trailing_stop=100.0))
        self.assertTrue(btc_base_trailing_stop_hit(is_long=False, low=80.0, high=101.0, trailing_stop=100.0))
        self.assertFalse(btc_base_trailing_stop_hit(is_long=False, low=80.0, high=99.0, trailing_stop=100.0))

    def test_htf_stop_target_preserves_swing_cap_and_invalid_stop_rules(self):
        from quant_btc.config import RiskConfig
        from quant_btc.portfolio_model import btc_htf_stop_target

        risk_cfg = RiskConfig(htf_sl_cap_pct=0.10)

        self.assertEqual(
            btc_htf_stop_target(
                is_long=True,
                entry=100.0,
                daily_high=130.0,
                daily_low=70.0,
                risk_cfg=risk_cfg,
            ),
            (90.0, 120.0),
        )
        self.assertEqual(
            btc_htf_stop_target(
                is_long=True,
                entry=100.0,
                daily_high=130.0,
                daily_low=95.0,
                risk_cfg=risk_cfg,
            ),
            (95.0, 110.0),
        )
        self.assertIsNone(
            btc_htf_stop_target(
                is_long=True,
                entry=100.0,
                daily_high=130.0,
                daily_low=101.0,
                risk_cfg=risk_cfg,
            )
        )
        self.assertEqual(
            btc_htf_stop_target(
                is_long=False,
                entry=100.0,
                daily_high=130.0,
                daily_low=70.0,
                risk_cfg=risk_cfg,
            ),
            (110.00000000000001, 79.99999999999997),
        )
        self.assertEqual(
            btc_htf_stop_target(
                is_long=False,
                entry=100.0,
                daily_high=105.0,
                daily_low=70.0,
                risk_cfg=risk_cfg,
            ),
            (105.0, 90.0),
        )
        self.assertIsNone(
            btc_htf_stop_target(
                is_long=False,
                entry=100.0,
                daily_high=99.0,
                daily_low=70.0,
                risk_cfg=risk_cfg,
            )
        )

    def test_atr_htf_stop_target_preserves_regime_multipliers_caps_and_invalid_rules(self):
        from quant_btc.config import RiskConfig
        from quant_btc.portfolio_model import btc_atr_htf_stop_target

        risk_cfg = RiskConfig(
            regime_bull_sl_mult=2.5,
            regime_bull_tp_mult=5.0,
            regime_bear_sl_mult=2.0,
            regime_bear_tp_mult=4.0,
            regime_ranging_sl_mult=1.5,
            regime_ranging_tp_mult=3.0,
            regime_compression_sl_mult=1.0,
            regime_compression_tp_mult=2.0,
        )

        self.assertEqual(
            btc_atr_htf_stop_target(
                is_long=True,
                entry=100.0,
                atr=4.0,
                daily_high=130.0,
                daily_low=95.0,
                regime=1,
                risk_cfg=risk_cfg,
            ),
            (95.0, 120.0),
        )
        self.assertEqual(
            btc_atr_htf_stop_target(
                is_long=False,
                entry=100.0,
                atr=4.0,
                daily_high=105.0,
                daily_low=80.0,
                regime=2,
                risk_cfg=risk_cfg,
            ),
            (105.0, 84.0),
        )
        self.assertEqual(
            btc_atr_htf_stop_target(
                is_long=True,
                entry=100.0,
                atr=4.0,
                daily_high=130.0,
                daily_low=80.0,
                regime=3,
                risk_cfg=risk_cfg,
            ),
            (96.0, 108.0),
        )
        self.assertEqual(
            btc_atr_htf_stop_target(
                is_long=False,
                entry=100.0,
                atr=4.0,
                daily_high=130.0,
                daily_low=80.0,
                regime=0,
                risk_cfg=risk_cfg,
            ),
            (106.0, 88.0),
        )
        self.assertIsNone(
            btc_atr_htf_stop_target(
                is_long=True,
                entry=100.0,
                atr=4.0,
                daily_high=130.0,
                daily_low=101.0,
                regime=1,
                risk_cfg=risk_cfg,
            )
        )
        self.assertIsNone(
            btc_atr_htf_stop_target(
                is_long=False,
                entry=100.0,
                atr=4.0,
                daily_high=99.0,
                daily_low=80.0,
                regime=2,
                risk_cfg=risk_cfg,
            )
        )

    def test_breakout_stop_target_preserves_sl_only_caps_and_invalid_rules(self):
        from quant_btc.config import RiskConfig
        from quant_btc.portfolio_model import btc_breakout_stop_target

        risk_cfg = RiskConfig(breakout_sl_atr_mult=2.5, short_sl_atr_mult=1.8)

        self.assertEqual(
            btc_breakout_stop_target(
                is_long=True,
                entry=100.0,
                atr=4.0,
                daily_high=130.0,
                daily_low=95.0,
                risk_cfg=risk_cfg,
            ),
            (95.0, None),
        )
        self.assertEqual(
            btc_breakout_stop_target(
                is_long=True,
                entry=100.0,
                atr=4.0,
                daily_high=130.0,
                daily_low=80.0,
                risk_cfg=risk_cfg,
            ),
            (90.0, None),
        )
        self.assertIsNone(
            btc_breakout_stop_target(
                is_long=True,
                entry=100.0,
                atr=4.0,
                daily_high=130.0,
                daily_low=101.0,
                risk_cfg=risk_cfg,
            )
        )
        self.assertEqual(
            btc_breakout_stop_target(
                is_long=False,
                entry=100.0,
                atr=4.0,
                daily_high=105.0,
                daily_low=80.0,
                risk_cfg=risk_cfg,
            ),
            (105.0, None),
        )
        self.assertEqual(
            btc_breakout_stop_target(
                is_long=False,
                entry=100.0,
                atr=4.0,
                daily_high=130.0,
                daily_low=80.0,
                risk_cfg=risk_cfg,
            ),
            (107.2, None),
        )
        self.assertIsNone(
            btc_breakout_stop_target(
                is_long=False,
                entry=100.0,
                atr=4.0,
                daily_high=99.0,
                daily_low=80.0,
                risk_cfg=risk_cfg,
            )
        )

    def test_meanrev_stop_target_preserves_midpoint_ema_cap_and_invalid_rules(self):
        from quant_btc.config import RiskConfig
        from quant_btc.portfolio_model import btc_meanrev_stop_target

        risk_cfg = RiskConfig(mean_rev_sl_mult=1.0, mean_rev_tp_mult=2.0)

        self.assertEqual(
            btc_meanrev_stop_target(
                is_long=True,
                entry=100.0,
                atr=4.0,
                bb_upper=116.0,
                bb_lower=104.0,
                ema55=106.0,
                risk_cfg=risk_cfg,
            ),
            (96.0, 106.0),
        )
        self.assertEqual(
            btc_meanrev_stop_target(
                is_long=True,
                entry=100.0,
                atr=4.0,
                bb_upper=130.0,
                bb_lower=110.0,
                ema55=112.0,
                risk_cfg=risk_cfg,
            ),
            (96.0, 108.0),
        )
        self.assertEqual(
            btc_meanrev_stop_target(
                is_long=True,
                entry=100.0,
                atr=4.0,
                bb_upper=100.0,
                bb_lower=90.0,
                ema55=105.0,
                risk_cfg=risk_cfg,
            ),
            (96.0, 105.0),
        )
        self.assertIsNone(
            btc_meanrev_stop_target(
                is_long=True,
                entry=100.0,
                atr=4.0,
                bb_upper=100.0,
                bb_lower=90.0,
                ema55=99.0,
                risk_cfg=risk_cfg,
            )
        )
        self.assertEqual(
            btc_meanrev_stop_target(
                is_long=False,
                entry=100.0,
                atr=4.0,
                bb_upper=92.0,
                bb_lower=88.0,
                ema55=94.0,
                risk_cfg=risk_cfg,
            ),
            (104.0, 94.0),
        )
        self.assertEqual(
            btc_meanrev_stop_target(
                is_long=False,
                entry=100.0,
                atr=4.0,
                bb_upper=82.0,
                bb_lower=78.0,
                ema55=88.0,
                risk_cfg=risk_cfg,
            ),
            (104.0, 92.0),
        )
        self.assertEqual(
            btc_meanrev_stop_target(
                is_long=False,
                entry=100.0,
                atr=4.0,
                bb_upper=110.0,
                bb_lower=100.0,
                ema55=95.0,
                risk_cfg=risk_cfg,
            ),
            (104.0, 95.0),
        )
        self.assertIsNone(
            btc_meanrev_stop_target(
                is_long=False,
                entry=100.0,
                atr=4.0,
                bb_upper=110.0,
                bb_lower=100.0,
                ema55=101.0,
                risk_cfg=risk_cfg,
            )
        )

    def test_base_partial_tp_and_time_stop_preserve_legacy_r_multiple_rules(self):
        from quant_btc.portfolio_model import btc_base_partial_tp, btc_base_time_stop

        self.assertFalse(
            btc_base_partial_tp(
                enabled=False,
                partial_done=False,
                is_long=True,
                entry_price=100.0,
                initial_risk=10.0,
                close=120.0,
                partial_tp_r=1.0,
            )
        )
        self.assertFalse(
            btc_base_partial_tp(
                enabled=True,
                partial_done=True,
                is_long=True,
                entry_price=100.0,
                initial_risk=10.0,
                close=120.0,
                partial_tp_r=1.0,
            )
        )
        self.assertFalse(
            btc_base_partial_tp(
                enabled=True,
                partial_done=False,
                is_long=True,
                entry_price=100.0,
                initial_risk=0.0,
                close=120.0,
                partial_tp_r=1.0,
            )
        )
        self.assertTrue(
            btc_base_partial_tp(
                enabled=True,
                partial_done=False,
                is_long=True,
                entry_price=100.0,
                initial_risk=10.0,
                close=110.0,
                partial_tp_r=1.0,
            )
        )
        self.assertTrue(
            btc_base_partial_tp(
                enabled=True,
                partial_done=False,
                is_long=False,
                entry_price=100.0,
                initial_risk=10.0,
                close=90.0,
                partial_tp_r=1.0,
            )
        )
        self.assertFalse(
            btc_base_partial_tp(
                enabled=True,
                partial_done=False,
                is_long=False,
                entry_price=100.0,
                initial_risk=10.0,
                close=95.0,
                partial_tp_r=1.0,
            )
        )

        self.assertFalse(
            btc_base_time_stop(
                enabled=False,
                is_long=True,
                bars_held=99,
                time_stop_bars=10,
                entry_price=100.0,
                initial_risk=10.0,
                close=90.0,
                min_profit_r=0.0,
            )
        )
        self.assertFalse(
            btc_base_time_stop(
                enabled=True,
                is_long=True,
                bars_held=9,
                time_stop_bars=10,
                entry_price=100.0,
                initial_risk=10.0,
                close=90.0,
                min_profit_r=0.0,
            )
        )
        self.assertFalse(
            btc_base_time_stop(
                enabled=True,
                is_long=True,
                bars_held=10,
                time_stop_bars=10,
                entry_price=100.0,
                initial_risk=0.0,
                close=90.0,
                min_profit_r=0.0,
            )
        )
        self.assertTrue(
            btc_base_time_stop(
                enabled=True,
                is_long=True,
                bars_held=10,
                time_stop_bars=10,
                entry_price=100.0,
                initial_risk=10.0,
                close=99.0,
                min_profit_r=0.0,
            )
        )
        self.assertTrue(
            btc_base_time_stop(
                enabled=True,
                is_long=False,
                bars_held=10,
                time_stop_bars=10,
                entry_price=100.0,
                initial_risk=10.0,
                close=101.0,
                min_profit_r=0.0,
            )
        )
        self.assertFalse(
            btc_base_time_stop(
                enabled=True,
                is_long=False,
                bars_held=10,
                time_stop_bars=10,
                entry_price=100.0,
                initial_risk=10.0,
                close=90.0,
                min_profit_r=0.0,
            )
        )

    def test_breakout_extra_exit_preserves_donchian_and_ema_confirm_rules(self):
        from quant_btc.portfolio_model import btc_breakout_extra_exit

        self.assertTrue(
            btc_breakout_extra_exit(
                is_long=True,
                close=89.0,
                dc20_low=90.0,
                dc20_high=120.0,
                ema144=100.0,
                prev_close=105.0,
                prev_ema144=100.0,
            )
        )
        self.assertTrue(
            btc_breakout_extra_exit(
                is_long=True,
                close=99.0,
                dc20_low=90.0,
                dc20_high=120.0,
                ema144=100.0,
                prev_close=98.0,
                prev_ema144=99.0,
            )
        )
        self.assertFalse(
            btc_breakout_extra_exit(
                is_long=True,
                close=99.0,
                dc20_low=90.0,
                dc20_high=120.0,
                ema144=100.0,
                prev_close=101.0,
                prev_ema144=99.0,
            )
        )

        self.assertTrue(
            btc_breakout_extra_exit(
                is_long=False,
                close=121.0,
                dc20_low=90.0,
                dc20_high=120.0,
                ema144=100.0,
                prev_close=95.0,
                prev_ema144=100.0,
            )
        )
        self.assertTrue(
            btc_breakout_extra_exit(
                is_long=False,
                close=101.0,
                dc20_low=90.0,
                dc20_high=120.0,
                ema144=100.0,
                prev_close=102.0,
                prev_ema144=101.0,
            )
        )
        self.assertFalse(
            btc_breakout_extra_exit(
                is_long=False,
                close=101.0,
                dc20_low=90.0,
                dc20_high=120.0,
                ema144=100.0,
                prev_close=99.0,
                prev_ema144=101.0,
            )
        )

    def test_short_extra_exit_preserves_module_specific_donchian_rules(self):
        from quant_btc.portfolio_model import btc_short_extra_exit

        self.assertTrue(
            btc_short_extra_exit(
                module="crash",
                close=101.0,
                dc10_high=100.0,
                dc20_low=90.0,
            )
        )
        self.assertFalse(
            btc_short_extra_exit(
                module="crash",
                close=100.0,
                dc10_high=100.0,
                dc20_low=90.0,
            )
        )
        for module in ("pullback", "failed_bounce", "bull_trap"):
            self.assertTrue(
                btc_short_extra_exit(
                    module=module,
                    close=89.5,
                    dc10_high=100.0,
                    dc20_low=90.0,
                )
            )
            self.assertFalse(
                btc_short_extra_exit(
                    module=module,
                    close=90.5,
                    dc10_high=100.0,
                    dc20_low=90.0,
                )
            )
        self.assertFalse(
            btc_short_extra_exit(
                module="meanrev_range",
                close=80.0,
                dc10_high=100.0,
                dc20_low=90.0,
            )
        )

    def test_bear_core_probe_and_confirm_signals_preserve_legacy_conditions(self):
        from quant_btc.portfolio_model import (
            btc_bear_core_confirm_signal,
            btc_bear_core_probe_signal,
        )

        self.assertTrue(
            btc_bear_core_probe_signal(
                core_active=False,
                bear_core_active=False,
                close=90.0,
                daily_ema_dir=-1,
                daily_ema=100.0,
                daily_swing_low_20=95.0,
            )
        )
        self.assertFalse(
            btc_bear_core_probe_signal(
                core_active=True,
                bear_core_active=False,
                close=90.0,
                daily_ema_dir=-1,
                daily_ema=100.0,
                daily_swing_low_20=95.0,
            )
        )
        self.assertFalse(
            btc_bear_core_probe_signal(
                core_active=False,
                bear_core_active=True,
                close=90.0,
                daily_ema_dir=-1,
                daily_ema=100.0,
                daily_swing_low_20=95.0,
            )
        )
        self.assertFalse(
            btc_bear_core_probe_signal(
                core_active=False,
                bear_core_active=False,
                close=96.0,
                daily_ema_dir=-1,
                daily_ema=100.0,
                daily_swing_low_20=95.0,
            )
        )
        self.assertFalse(
            btc_bear_core_probe_signal(
                core_active=False,
                bear_core_active=False,
                close=90.0,
                daily_ema_dir=0,
                daily_ema=100.0,
                daily_swing_low_20=95.0,
            )
        )

        self.assertTrue(
            btc_bear_core_confirm_signal(
                probe_active=True,
                close=90.0,
                daily_ema_dir=-1,
                daily_ema=100.0,
                weekly_ema=110.0,
                weekly_ema_dir=0,
            )
        )
        self.assertFalse(
            btc_bear_core_confirm_signal(
                probe_active=False,
                close=90.0,
                daily_ema_dir=-1,
                daily_ema=100.0,
                weekly_ema=110.0,
                weekly_ema_dir=0,
            )
        )
        self.assertFalse(
            btc_bear_core_confirm_signal(
                probe_active=True,
                close=105.0,
                daily_ema_dir=-1,
                daily_ema=100.0,
                weekly_ema=110.0,
                weekly_ema_dir=0,
            )
        )
        self.assertFalse(
            btc_bear_core_confirm_signal(
                probe_active=True,
                close=90.0,
                daily_ema_dir=-1,
                daily_ema=100.0,
                weekly_ema=110.0,
                weekly_ema_dir=1,
            )
        )

    def test_tactical_sl_tp_preserves_regime_adaptive_stop_target_rules(self):
        from quant_btc.config import RiskConfig
        from quant_btc.portfolio_model import btc_tactical_sl_tp

        cfg = RiskConfig()

        plan = btc_tactical_sl_tp(
            is_long=True,
            entry=100.0,
            atr=4.0,
            daily_high=130.0,
            daily_low=92.0,
            regime=1,
            risk_cfg=cfg,
        )
        self.assertIsNotNone(plan)
        self.assertAlmostEqual(plan[0], 92.0)
        self.assertAlmostEqual(plan[1], 120.0)

        plan = btc_tactical_sl_tp(
            is_long=False,
            entry=100.0,
            atr=4.0,
            daily_high=106.0,
            daily_low=70.0,
            regime=2,
            risk_cfg=cfg,
        )
        self.assertIsNotNone(plan)
        self.assertAlmostEqual(plan[0], 106.0)
        self.assertAlmostEqual(plan[1], 80.0)

        plan = btc_tactical_sl_tp(
            is_long=True,
            entry=100.0,
            atr=4.0,
            daily_high=130.0,
            daily_low=0.0,
            regime=3,
            risk_cfg=cfg,
        )
        self.assertIsNotNone(plan)
        self.assertAlmostEqual(plan[0], 94.0)
        self.assertAlmostEqual(plan[1], 112.0)

        plan = btc_tactical_sl_tp(
            is_long=False,
            entry=100.0,
            atr=4.0,
            daily_high=200.0,
            daily_low=70.0,
            regime=0,
            risk_cfg=cfg,
        )
        self.assertIsNotNone(plan)
        self.assertAlmostEqual(plan[0], 108.0)
        self.assertAlmostEqual(plan[1], 84.0)

        self.assertIsNone(
            btc_tactical_sl_tp(
                is_long=True,
                entry=100.0,
                atr=4.0,
                daily_high=130.0,
                daily_low=101.0,
                regime=1,
                risk_cfg=cfg,
            )
        )
        self.assertIsNone(
            btc_tactical_sl_tp(
                is_long=False,
                entry=100.0,
                atr=4.0,
                daily_high=99.0,
                daily_low=70.0,
                regime=2,
                risk_cfg=cfg,
            )
        )

    def test_short_partial_tp_plan_preserves_module_tiers_and_state(self):
        from quant_btc.config import RiskConfig
        from quant_btc.portfolio_model import btc_short_partial_tp_plan

        cfg = RiskConfig()

        plan = btc_short_partial_tp_plan(
            module="crash",
            entry_price=100.0,
            stop_price=110.0,
            close=90.0,
            tp1_done=False,
            tp2_done=False,
            risk_cfg=cfg,
        )
        self.assertTrue(plan.should_take_profit)
        self.assertTrue(plan.tp1_done)
        self.assertFalse(plan.tp2_done)
        self.assertAlmostEqual(plan.portion, cfg.short_crash_tp1_pct)

        plan = btc_short_partial_tp_plan(
            module="crash",
            entry_price=100.0,
            stop_price=110.0,
            close=80.0,
            tp1_done=True,
            tp2_done=False,
            risk_cfg=cfg,
        )
        self.assertTrue(plan.should_take_profit)
        self.assertTrue(plan.tp1_done)
        self.assertTrue(plan.tp2_done)
        self.assertAlmostEqual(plan.portion, cfg.short_crash_tp2_pct)

        plan = btc_short_partial_tp_plan(
            module="failed_bounce",
            entry_price=100.0,
            stop_price=110.0,
            close=100.0 - cfg.fb_tp1_r * 10.0,
            tp1_done=False,
            tp2_done=False,
            risk_cfg=cfg,
        )
        self.assertTrue(plan.should_take_profit)
        self.assertTrue(plan.tp1_done)
        self.assertFalse(plan.tp2_done)
        self.assertAlmostEqual(plan.portion, cfg.fb_tp1_pct)

        plan = btc_short_partial_tp_plan(
            module="pullback",
            entry_price=100.0,
            stop_price=110.0,
            close=100.0 - cfg.fb_tp2_r * 10.0,
            tp1_done=True,
            tp2_done=False,
            risk_cfg=cfg,
        )
        self.assertTrue(plan.should_take_profit)
        self.assertTrue(plan.tp1_done)
        self.assertTrue(plan.tp2_done)
        self.assertAlmostEqual(plan.portion, cfg.fb_tp2_pct)

        plan = btc_short_partial_tp_plan(
            module="bear_core",
            entry_price=100.0,
            stop_price=110.0,
            close=100.0 - cfg.bear_core_tp1_r * 10.0,
            tp1_done=False,
            tp2_done=False,
            risk_cfg=cfg,
        )
        self.assertTrue(plan.should_take_profit)
        self.assertTrue(plan.tp1_done)
        self.assertFalse(plan.tp2_done)
        self.assertAlmostEqual(plan.portion, cfg.bear_core_tp1_pct)

        plan = btc_short_partial_tp_plan(
            module="unknown",
            entry_price=100.0,
            stop_price=110.0,
            close=50.0,
            tp1_done=False,
            tp2_done=False,
            risk_cfg=cfg,
        )
        self.assertFalse(plan.should_take_profit)
        self.assertFalse(plan.tp1_done)
        self.assertFalse(plan.tp2_done)
        self.assertAlmostEqual(plan.portion, 0.0)

        plan = btc_short_partial_tp_plan(
            module="crash",
            entry_price=100.0,
            stop_price=100.0,
            close=50.0,
            tp1_done=False,
            tp2_done=False,
            risk_cfg=cfg,
        )
        self.assertFalse(plan.should_take_profit)
        self.assertFalse(plan.tp1_done)
        self.assertFalse(plan.tp2_done)
        self.assertAlmostEqual(plan.portion, 0.0)

    def test_tactical_exit_close_plan_preserves_partial_vs_full_close_branch(self):
        from quant_btc.portfolio_model import btc_tactical_exit_close_plan

        plan = btc_tactical_exit_close_plan(total_position_size=1.0, tactical_size=0.25)
        self.assertEqual(plan.action, "portion")
        self.assertAlmostEqual(plan.portion, 0.25)

        plan = btc_tactical_exit_close_plan(total_position_size=0.5, tactical_size=1.0)
        self.assertEqual(plan.action, "portion")
        self.assertAlmostEqual(plan.portion, 1.0)

        plan = btc_tactical_exit_close_plan(total_position_size=0.001, tactical_size=0.25)
        self.assertEqual(plan.action, "all")
        self.assertAlmostEqual(plan.portion, 0.0)

        plan = btc_tactical_exit_close_plan(total_position_size=1.0, tactical_size=0.001)
        self.assertEqual(plan.action, "all")
        self.assertAlmostEqual(plan.portion, 0.0)

    def test_tactical_exit_cleanup_plan_preserves_legacy_tactical_resets(self):
        from quant_btc.portfolio_model import btc_tactical_exit_cleanup_plan

        plan = btc_tactical_exit_cleanup_plan(
            should_exit=False,
            tactical_direction=-1,
            tactical_size=0.12,
        )
        self.assertFalse(plan.should_cleanup)
        self.assertEqual(plan.tactical_direction, -1)
        self.assertEqual(plan.tactical_size, 0.12)

        plan = btc_tactical_exit_cleanup_plan(
            should_exit=True,
            tactical_direction=-1,
            tactical_size=0.12,
        )
        self.assertTrue(plan.should_cleanup)
        self.assertEqual(plan.tactical_direction, 0)
        self.assertEqual(plan.tactical_size, 0.0)

    def test_layer_close_portion_preserves_legacy_thresholds_and_cap(self):
        from quant_btc.portfolio_model import btc_layer_close_portion

        self.assertEqual(btc_layer_close_portion(layer_size=0.0, total_position_size=1.0), 0.0)
        self.assertEqual(btc_layer_close_portion(layer_size=0.2, total_position_size=0.00009), 0.0)
        self.assertAlmostEqual(
            btc_layer_close_portion(layer_size=0.2, total_position_size=1.0),
            0.2,
        )
        self.assertAlmostEqual(
            btc_layer_close_portion(layer_size=1.5, total_position_size=1.0),
            1.0,
        )
        self.assertAlmostEqual(
            btc_layer_close_portion(layer_size=0.25, total_position_size=-0.5),
            0.5,
        )

    def test_external_close_cleanup_plan_preserves_legacy_core_and_tactical_resets(self):
        from quant_btc.portfolio_model import btc_external_close_cleanup_plan

        plan = btc_external_close_cleanup_plan(
            has_position=True,
            core_active=True,
            core_size=0.40,
            tactical_direction=-1,
            tactical_size=0.12,
        )
        self.assertFalse(plan.should_record_trade)
        self.assertTrue(plan.core_active)
        self.assertEqual(plan.core_size, 0.40)
        self.assertEqual(plan.tactical_direction, -1)
        self.assertEqual(plan.tactical_size, 0.12)

        plan = btc_external_close_cleanup_plan(
            has_position=False,
            core_active=False,
            core_size=0.0,
            tactical_direction=0,
            tactical_size=0.0,
        )
        self.assertFalse(plan.should_record_trade)
        self.assertFalse(plan.core_active)
        self.assertEqual(plan.core_size, 0.0)
        self.assertEqual(plan.tactical_direction, 0)
        self.assertEqual(plan.tactical_size, 0.0)

        plan = btc_external_close_cleanup_plan(
            has_position=False,
            core_active=True,
            core_size=0.40,
            tactical_direction=-1,
            tactical_size=0.12,
        )
        self.assertTrue(plan.should_record_trade)
        self.assertFalse(plan.core_active)
        self.assertEqual(plan.core_size, 0.0)
        self.assertEqual(plan.tactical_direction, 0)
        self.assertEqual(plan.tactical_size, 0.0)

    def test_core_exit_plan_preserves_layer_close_and_state_cleanup(self):
        from quant_btc.portfolio_model import btc_core_exit_plan

        plan = btc_core_exit_plan(
            core_active=False,
            exit_signal=True,
            core_size=0.40,
        )
        self.assertFalse(plan.should_exit)
        self.assertEqual(plan.layer_size, 0.0)
        self.assertFalse(plan.core_active)
        self.assertEqual(plan.core_size, 0.40)

        plan = btc_core_exit_plan(
            core_active=True,
            exit_signal=False,
            core_size=0.40,
        )
        self.assertFalse(plan.should_exit)
        self.assertEqual(plan.layer_size, 0.0)
        self.assertTrue(plan.core_active)
        self.assertEqual(plan.core_size, 0.40)

        plan = btc_core_exit_plan(
            core_active=True,
            exit_signal=True,
            core_size=0.40,
        )
        self.assertTrue(plan.should_exit)
        self.assertEqual(plan.layer_size, 0.40)
        self.assertFalse(plan.core_active)
        self.assertEqual(plan.core_size, 0.0)

    def test_tactical_entry_plan_preserves_rr_gate_and_legacy_state_defaults(self):
        from quant_btc.portfolio_model import btc_tactical_entry_plan

        self.assertFalse(
            btc_tactical_entry_plan(
                long_signal=False,
                short_signal=False,
                module="none",
                entry=100.0,
                stop=95.0,
                target=112.0,
                position_size=0.2,
                bar_index=10,
            ).should_enter
        )

        self.assertFalse(
            btc_tactical_entry_plan(
                long_signal=True,
                short_signal=False,
                module="pullback",
                entry=100.0,
                stop=95.0,
                target=108.0,
                position_size=0.2,
                bar_index=10,
            ).should_enter
        )

        plan = btc_tactical_entry_plan(
            long_signal=True,
            short_signal=False,
            module="pullback",
            entry=100.0,
            stop=95.0,
            target=112.0,
            position_size=0.2,
            bar_index=10,
        )
        self.assertTrue(plan.should_enter)
        self.assertTrue(plan.is_long)
        self.assertEqual(plan.direction, 1)
        self.assertEqual(plan.module, "pullback")
        self.assertEqual(plan.order_tag, "pullback_long")
        self.assertAlmostEqual(plan.entry_price, 100.0)
        self.assertAlmostEqual(plan.stop_price, 95.0)
        self.assertAlmostEqual(plan.target_price, 112.0)
        self.assertAlmostEqual(plan.size, 0.2)
        self.assertEqual(plan.entry_bar, 10)
        self.assertAlmostEqual(plan.extreme, 100.0)
        self.assertFalse(plan.tp1_done)
        self.assertFalse(plan.tp2_done)
        self.assertFalse(plan.short_reached_1r)
        self.assertAlmostEqual(plan.short_peak_r, 0.0)
        self.assertAlmostEqual(plan.short_giveback_peak_r, -999.0)
        self.assertEqual(plan.last_trade_bar, 10)

        plan = btc_tactical_entry_plan(
            long_signal=True,
            short_signal=True,
            module="crash",
            entry=100.0,
            stop=105.0,
            target=88.0,
            position_size=0.15,
            bar_index=12,
        )
        self.assertTrue(plan.should_enter)
        self.assertFalse(plan.is_long)
        self.assertEqual(plan.direction, -1)
        self.assertEqual(plan.order_tag, "crash_short")

    def test_tactical_hard_exit_preserves_stop_and_target_hits(self):
        from quant_btc.portfolio_model import btc_tactical_hard_exit

        self.assertTrue(
            btc_tactical_hard_exit(
                is_long=True,
                high=106.0,
                low=98.0,
                stop_price=98.0,
                target_price=110.0,
            )
        )
        self.assertTrue(
            btc_tactical_hard_exit(
                is_long=True,
                high=111.0,
                low=101.0,
                stop_price=98.0,
                target_price=110.0,
            )
        )
        self.assertTrue(
            btc_tactical_hard_exit(
                is_long=False,
                high=103.0,
                low=96.0,
                stop_price=103.0,
                target_price=90.0,
            )
        )
        self.assertTrue(
            btc_tactical_hard_exit(
                is_long=False,
                high=99.0,
                low=89.0,
                stop_price=103.0,
                target_price=90.0,
            )
        )
        self.assertFalse(
            btc_tactical_hard_exit(
                is_long=True,
                high=109.0,
                low=99.0,
                stop_price=98.0,
                target_price=110.0,
            )
        )

    def test_tactical_trailing_stop_preserves_extreme_stop_and_exit_state(self):
        from quant_btc.config import RiskConfig
        from quant_btc.portfolio_model import btc_tactical_trailing_stop

        risk_cfg = RiskConfig(trailing_distance_atr=1.5)

        self.assertEqual(
            btc_tactical_trailing_stop(
                is_long=True,
                price=101.0,
                high=105.0,
                low=103.0,
                atr=2.0,
                previous_extreme=102.0,
                stop_price=98.0,
                risk_cfg=risk_cfg,
            ),
            (False, 105.0, 102.0),
        )

        self.assertEqual(
            btc_tactical_trailing_stop(
                is_long=True,
                price=101.0,
                high=103.0,
                low=102.0,
                atr=2.0,
                previous_extreme=102.0,
                stop_price=101.0,
                risk_cfg=risk_cfg,
            ),
            (False, 103.0, 101.0),
        )

        self.assertEqual(
            btc_tactical_trailing_stop(
                is_long=False,
                price=99.0,
                high=98.0,
                low=94.0,
                atr=2.0,
                previous_extreme=97.0,
                stop_price=103.0,
                risk_cfg=risk_cfg,
            ),
            (True, 94.0, 97.0),
        )

        self.assertEqual(
            btc_tactical_trailing_stop(
                is_long=False,
                price=99.0,
                high=100.0,
                low=96.0,
                atr=2.0,
                previous_extreme=97.0,
                stop_price=98.0,
                risk_cfg=risk_cfg,
            ),
            (True, 96.0, 98.0),
        )

    def test_bear_probe_peak_r_preserves_max_profit_state(self):
        from quant_btc.portfolio_model import btc_bear_probe_peak_r

        self.assertAlmostEqual(
            btc_bear_probe_peak_r(
                entry_price=100.0,
                stop_price=110.0,
                low=85.0,
                previous_peak_r=1.0,
            ),
            1.5,
        )

        self.assertAlmostEqual(
            btc_bear_probe_peak_r(
                entry_price=100.0,
                stop_price=110.0,
                low=95.0,
                previous_peak_r=1.0,
            ),
            1.0,
        )

        self.assertAlmostEqual(
            btc_bear_probe_peak_r(
                entry_price=100.0,
                stop_price=100.0,
                low=90.0,
                previous_peak_r=1.25,
            ),
            1.25,
        )

    def test_flash_crash_state_preserves_activation_recovery_and_timeout(self):
        from quant_btc.portfolio_model import btc_flash_crash_state

        self.assertEqual(
            btc_flash_crash_state(
                bar_index=20,
                close=94.0,
                high_lookback=100.0,
                atr_now=2.0,
                atr_sma20=1.0,
                flash_crash_active=False,
                flash_crash_bar=-10**9,
            ),
            (True, 20),
        )

        self.assertEqual(
            btc_flash_crash_state(
                bar_index=21,
                close=94.0,
                high_lookback=100.0,
                atr_now=1.7,
                atr_sma20=1.0,
                flash_crash_active=False,
                flash_crash_bar=-10**9,
            ),
            (False, -10**9),
        )

        self.assertEqual(
            btc_flash_crash_state(
                bar_index=22,
                close=98.0,
                high_lookback=100.0,
                atr_now=1.0,
                atr_sma20=1.0,
                flash_crash_active=True,
                flash_crash_bar=20,
            ),
            (False, 20),
        )

        self.assertEqual(
            btc_flash_crash_state(
                bar_index=33,
                close=90.0,
                high_lookback=100.0,
                atr_now=1.0,
                atr_sma20=1.0,
                flash_crash_active=True,
                flash_crash_bar=21,
            ),
            (True, 21),
        )

        self.assertEqual(
            btc_flash_crash_state(
                bar_index=34,
                close=90.0,
                high_lookback=100.0,
                atr_now=1.0,
                atr_sma20=1.0,
                flash_crash_active=True,
                flash_crash_bar=20,
            ),
            (False, 20),
        )

    def test_short_time_stop_preserves_timeout_and_reached_1r_state(self):
        from quant_btc.config import RiskConfig
        from quant_btc.portfolio_model import btc_short_time_stop

        risk_cfg = RiskConfig(short_crash_timeout=8, fb_timeout=15, short_bulltrap_timeout=6)

        self.assertEqual(
            btc_short_time_stop(
                module="bear_core",
                bars_held=100,
                entry_price=100.0,
                stop_price=110.0,
                close=80.0,
                short_reached_1r=False,
                risk_cfg=risk_cfg,
            ),
            (False, False),
        )

        self.assertEqual(
            btc_short_time_stop(
                module="crash",
                bars_held=7,
                entry_price=100.0,
                stop_price=110.0,
                close=95.0,
                short_reached_1r=False,
                risk_cfg=risk_cfg,
            ),
            (False, False),
        )

        self.assertEqual(
            btc_short_time_stop(
                module="crash",
                bars_held=8,
                entry_price=100.0,
                stop_price=110.0,
                close=95.0,
                short_reached_1r=False,
                risk_cfg=risk_cfg,
            ),
            (True, False),
        )

        self.assertEqual(
            btc_short_time_stop(
                module="failed_bounce",
                bars_held=3,
                entry_price=100.0,
                stop_price=110.0,
                close=89.0,
                short_reached_1r=False,
                risk_cfg=risk_cfg,
            ),
            (False, True),
        )

        self.assertEqual(
            btc_short_time_stop(
                module="failed_bounce",
                bars_held=4,
                entry_price=100.0,
                stop_price=110.0,
                close=92.0,
                short_reached_1r=True,
                risk_cfg=risk_cfg,
            ),
            (True, True),
        )

    def test_core_add_plan_preserves_legacy_size_and_loaded_state(self):
        from quant_btc.config import RiskConfig
        from quant_btc.portfolio_model import btc_core_add_plan

        risk_cfg = RiskConfig(core_allocation=0.55, risk_core_alloc=0.40)

        plan = btc_core_add_plan(
            core_active=True,
            core_fully_loaded=False,
            core_add_signal=True,
            core_size=0.40,
            max_position_frac=0.90,
            risk_cfg=risk_cfg,
        )
        self.assertTrue(plan[0])
        self.assertAlmostEqual(plan[1], 0.135)
        self.assertAlmostEqual(plan[2], 0.40)
        self.assertTrue(plan[3])

        self.assertEqual(
            btc_core_add_plan(
                core_active=True,
                core_fully_loaded=True,
                core_add_signal=True,
                core_size=0.40,
                max_position_frac=0.90,
                risk_cfg=risk_cfg,
            ),
            (False, 0.0, 0.40, True),
        )

        self.assertEqual(
            btc_core_add_plan(
                core_active=True,
                core_fully_loaded=False,
                core_add_signal=True,
                core_size=0.55,
                max_position_frac=0.90,
                risk_cfg=risk_cfg,
            ),
            (False, 0.0, 0.55, False),
        )

    def test_core_add_state_plan_preserves_legacy_state_update(self):
        from quant_btc.portfolio_model import btc_core_add_state_plan

        no_update = btc_core_add_state_plan(
            should_core_add=False,
            new_core_size=0.40,
            new_core_fully_loaded=True,
            core_size=0.25,
            core_fully_loaded=False,
        )
        self.assertFalse(no_update.should_update)
        self.assertEqual(no_update.core_size, 0.25)
        self.assertFalse(no_update.core_fully_loaded)

        update = btc_core_add_state_plan(
            should_core_add=True,
            new_core_size=0.40,
            new_core_fully_loaded=True,
            core_size=0.25,
            core_fully_loaded=False,
        )
        self.assertTrue(update.should_update)
        self.assertEqual(update.core_size, 0.40)
        self.assertTrue(update.core_fully_loaded)

    def test_bear_core_confirm_and_acceleration_add_plans_preserve_group_exposure(self):
        from quant_btc.config import RiskConfig
        from quant_btc.portfolio_model import (
            btc_bear_core_acceleration_add_plan,
            btc_bear_core_confirm_add_plan,
        )

        risk_cfg = RiskConfig(bear_core_full_pct=0.40)

        plan = btc_bear_core_confirm_add_plan(
            bar_index=20,
            entry_bar=10,
            active=True,
            stage=1,
            probe_peak_r=1.2,
            daily_ema_dir=-1,
            weekly_ema_dir=0,
            close=90.0,
            weekly_ema=100.0,
            current_size=0.14,
            group_exposure=0.14,
            group_max_exposure=0.50,
            risk_cfg=risk_cfg,
        )
        self.assertTrue(plan[0])
        self.assertAlmostEqual(plan[1], 0.12)
        self.assertAlmostEqual(plan[2], 0.26)
        self.assertAlmostEqual(plan[3], 0.26)
        self.assertEqual(plan[4], 2)

        self.assertEqual(
            btc_bear_core_confirm_add_plan(
                bar_index=20,
                entry_bar=10,
                active=True,
                stage=1,
                probe_peak_r=1.2,
                daily_ema_dir=-1,
                weekly_ema_dir=1,
                close=90.0,
                weekly_ema=100.0,
                current_size=0.14,
                group_exposure=0.14,
                group_max_exposure=0.50,
                risk_cfg=risk_cfg,
            ),
            (False, 0.0, 0.14, 0.14, 1),
        )

        plan = btc_bear_core_acceleration_add_plan(
            bar_index=30,
            last_trade_bar=20,
            active=True,
            stage=2,
            daily_ema_dir=-1,
            adx=23.0,
            plus_di=12.0,
            minus_di=18.0,
            current_size=0.26,
            group_exposure=0.26,
            group_max_exposure=0.35,
            risk_cfg=risk_cfg,
        )
        self.assertTrue(plan[0])
        self.assertAlmostEqual(plan[1], 0.09)
        self.assertAlmostEqual(plan[2], 0.35)
        self.assertAlmostEqual(plan[3], 0.35)
        self.assertEqual(plan[4], 3)

        self.assertEqual(
            btc_bear_core_acceleration_add_plan(
                bar_index=30,
                last_trade_bar=20,
                active=True,
                stage=2,
                daily_ema_dir=-1,
                adx=21.0,
                plus_di=12.0,
                minus_di=18.0,
                current_size=0.26,
                group_exposure=0.26,
                group_max_exposure=0.35,
                risk_cfg=risk_cfg,
            ),
            (False, 0.0, 0.26, 0.26, 2),
        )

    def test_bear_core_confirm_add_state_plan_preserves_legacy_state_updates(self):
        from quant_btc.portfolio_model import btc_bear_core_confirm_add_state_plan

        plan = btc_bear_core_confirm_add_state_plan(
            should_confirm_add=False,
            bar_index=20,
            target_size=0.26,
            group_exposure=0.26,
            stage=2,
            bear_core_size=0.14,
            bear_group_exposure=0.14,
            bear_core_stage=1,
            last_trade_bar=10,
        )
        self.assertFalse(plan.should_update)
        self.assertEqual(plan.bear_core_size, 0.14)
        self.assertEqual(plan.bear_group_exposure, 0.14)
        self.assertEqual(plan.bear_core_stage, 1)
        self.assertEqual(plan.last_trade_bar, 10)

        plan = btc_bear_core_confirm_add_state_plan(
            should_confirm_add=True,
            bar_index=20,
            target_size=0.26,
            group_exposure=0.26,
            stage=2,
            bear_core_size=0.14,
            bear_group_exposure=0.14,
            bear_core_stage=1,
            last_trade_bar=10,
        )
        self.assertTrue(plan.should_update)
        self.assertEqual(plan.bear_core_size, 0.26)
        self.assertEqual(plan.bear_group_exposure, 0.26)
        self.assertEqual(plan.bear_core_stage, 2)
        self.assertEqual(plan.last_trade_bar, 20)

    def test_bear_core_acceleration_add_state_plan_preserves_legacy_state_updates(self):
        from quant_btc.portfolio_model import btc_bear_core_acceleration_add_state_plan

        plan = btc_bear_core_acceleration_add_state_plan(
            should_accel_add=False,
            target_size=0.35,
            group_exposure=0.35,
            stage=3,
            bear_core_size=0.26,
            bear_group_exposure=0.26,
            bear_core_stage=2,
        )
        self.assertFalse(plan.should_update)
        self.assertEqual(plan.bear_core_size, 0.26)
        self.assertEqual(plan.bear_group_exposure, 0.26)
        self.assertEqual(plan.bear_core_stage, 2)

        plan = btc_bear_core_acceleration_add_state_plan(
            should_accel_add=True,
            target_size=0.35,
            group_exposure=0.35,
            stage=3,
            bear_core_size=0.26,
            bear_group_exposure=0.26,
            bear_core_stage=2,
        )
        self.assertTrue(plan.should_update)
        self.assertEqual(plan.bear_core_size, 0.35)
        self.assertEqual(plan.bear_group_exposure, 0.35)
        self.assertEqual(plan.bear_core_stage, 3)

    def test_bear_core_probe_plan_preserves_group_gate_and_initial_exposure(self):
        from quant_btc.config import RiskConfig
        from quant_btc.portfolio_model import btc_bear_core_probe_plan

        risk_cfg = RiskConfig(bear_core_full_pct=0.40)

        plan = btc_bear_core_probe_plan(
            bar_index=110,
            core_active=False,
            bear_core_active=False,
            top_score=80.0,
            double_top_signal=True,
            bull_guard=False,
            group_entry_bar=100,
            group_id=2,
            group_exposure=0.30,
            risk_cfg=risk_cfg,
        )
        self.assertEqual(plan, (False, True, 0.0, 2, 0.30, 100, 0.0))

        plan = btc_bear_core_probe_plan(
            bar_index=140,
            core_active=False,
            bear_core_active=False,
            top_score=80.0,
            double_top_signal=True,
            bull_guard=True,
            group_entry_bar=100,
            group_id=2,
            group_exposure=0.30,
            risk_cfg=risk_cfg,
        )
        self.assertEqual(plan, (False, False, 0.0, 2, 0.30, 100, 0.0))

        plan = btc_bear_core_probe_plan(
            bar_index=140,
            core_active=False,
            bear_core_active=False,
            top_score=80.0,
            double_top_signal=True,
            bull_guard=False,
            group_entry_bar=100,
            group_id=2,
            group_exposure=0.30,
            risk_cfg=risk_cfg,
        )
        self.assertEqual((plan[0], plan[1], plan[3], plan[5]), (True, False, 3, 140))
        self.assertAlmostEqual(plan[2], 0.14)
        self.assertAlmostEqual(plan[4], 0.14)
        self.assertAlmostEqual(plan[6], 0.0)

        plan = btc_bear_core_probe_plan(
            bar_index=140,
            core_active=True,
            bear_core_active=False,
            top_score=80.0,
            double_top_signal=True,
            bull_guard=False,
            group_entry_bar=100,
            group_id=2,
            group_exposure=0.30,
            risk_cfg=risk_cfg,
        )
        self.assertEqual(plan, (False, False, 0.0, 2, 0.30, 100, 0.0))

    def test_bear_core_probe_entry_state_plan_preserves_legacy_entry_state(self):
        from quant_btc.portfolio_model import btc_bear_core_probe_entry_state_plan

        plan = btc_bear_core_probe_entry_state_plan(
            should_probe=False,
            entry_price=100.0,
            bar_index=140,
            equity=120000.0,
            probe_size=0.14,
            group_id=3,
            group_exposure=0.14,
            group_entry_bar=140,
            group_peak_r=0.0,
            bear_core_active=True,
            bear_core_stage=2,
            bear_core_entry_price=95.0,
            bear_core_entry_bar=100,
            bear_core_size=0.26,
            bear_group_id=2,
            bear_group_exposure=0.30,
            bear_group_entry_bar=100,
            bear_group_peak_r=1.2,
            days_above_dema=3,
            equity_snapshot=110000.0,
        )
        self.assertFalse(plan.should_enter)
        self.assertTrue(plan.bear_core_active)
        self.assertEqual(plan.bear_core_stage, 2)
        self.assertEqual(plan.bear_core_entry_price, 95.0)
        self.assertEqual(plan.bear_core_entry_bar, 100)
        self.assertEqual(plan.bear_core_size, 0.26)
        self.assertEqual(plan.bear_group_id, 2)
        self.assertEqual(plan.bear_group_exposure, 0.30)
        self.assertEqual(plan.bear_group_entry_bar, 100)
        self.assertEqual(plan.bear_group_peak_r, 1.2)
        self.assertEqual(plan.days_above_dema, 3)
        self.assertEqual(plan.equity_snapshot, 110000.0)

        plan = btc_bear_core_probe_entry_state_plan(
            should_probe=True,
            entry_price=100.0,
            bar_index=140,
            equity=120000.0,
            probe_size=0.14,
            group_id=3,
            group_exposure=0.14,
            group_entry_bar=140,
            group_peak_r=0.0,
            bear_core_active=False,
            bear_core_stage=0,
            bear_core_entry_price=0.0,
            bear_core_entry_bar=-10**9,
            bear_core_size=0.0,
            bear_group_id=2,
            bear_group_exposure=0.30,
            bear_group_entry_bar=100,
            bear_group_peak_r=1.2,
            days_above_dema=3,
            equity_snapshot=110000.0,
        )
        self.assertTrue(plan.should_enter)
        self.assertTrue(plan.bear_core_active)
        self.assertEqual(plan.bear_core_stage, 1)
        self.assertEqual(plan.bear_core_entry_price, 100.0)
        self.assertEqual(plan.bear_core_entry_bar, 140)
        self.assertEqual(plan.bear_probe_peak_r, 0.0)
        self.assertEqual(plan.short_giveback_peak_r, -999.0)
        self.assertEqual(plan.bear_core_size, 0.14)
        self.assertEqual(plan.bear_group_id, 3)
        self.assertEqual(plan.bear_group_exposure, 0.14)
        self.assertEqual(plan.bear_group_entry_bar, 140)
        self.assertEqual(plan.bear_group_peak_r, 0.0)
        self.assertEqual(plan.days_above_dema, 0)
        self.assertEqual(plan.equity_snapshot, 120000.0)
        self.assertEqual(plan.last_trade_bar, 140)

    def test_bear_core_waterfall_guard_returns_action_without_side_effects(self):
        from quant_btc.portfolio_model import btc_bear_core_waterfall_guard

        self.assertEqual(
            btc_bear_core_waterfall_guard(
                stage=0,
                entry_price=100.0,
                low=80.0,
                atr_4h=4.0,
                bars_since_entry=3,
                daily_ema_dir=0,
            ),
            (False, 0.0, 0.0, 0),
        )
        self.assertEqual(
            btc_bear_core_waterfall_guard(
                stage=1,
                entry_price=100.0,
                low=80.0,
                atr_4h=0.0,
                bars_since_entry=3,
                daily_ema_dir=0,
            ),
            (False, 0.0, 0.0, 1),
        )
        self.assertEqual(
            btc_bear_core_waterfall_guard(
                stage=1,
                entry_price=100.0,
                low=85.0,
                atr_4h=4.0,
                bars_since_entry=6,
                daily_ema_dir=0,
            ),
            (True, 0.70, 1.5, 99),
        )
        self.assertEqual(
            btc_bear_core_waterfall_guard(
                stage=2,
                entry_price=100.0,
                low=75.0,
                atr_4h=4.0,
                bars_since_entry=10,
                daily_ema_dir=-1,
            ),
            (True, 0.80, 2.0, 99),
        )
        self.assertEqual(
            btc_bear_core_waterfall_guard(
                stage=2,
                entry_price=100.0,
                low=85.0,
                atr_4h=4.0,
                bars_since_entry=7,
                daily_ema_dir=-1,
            ),
            (False, 0.0, 0.0, 2),
        )

    def test_short_giveback_guard_preserves_peak_state_and_legacy_thresholds(self):
        from quant_btc.portfolio_model import btc_short_giveback_guard

        should_exit, peak = btc_short_giveback_guard(
            entry_price=100.0,
            stop_price=110.0,
            low=85.0,
            close=96.0,
            previous_peak_r=-999.0,
        )
        self.assertFalse(should_exit)
        self.assertAlmostEqual(peak, 1.5)

        should_exit, peak = btc_short_giveback_guard(
            entry_price=100.0,
            stop_price=110.0,
            low=85.0,
            close=96.0,
            previous_peak_r=2.0,
        )
        self.assertTrue(should_exit)
        self.assertAlmostEqual(peak, 2.0)

        should_exit, peak = btc_short_giveback_guard(
            entry_price=100.0,
            stop_price=110.0,
            low=80.0,
            close=91.0,
            previous_peak_r=3.0,
        )
        self.assertTrue(should_exit)
        self.assertAlmostEqual(peak, 3.0)

        should_exit, peak = btc_short_giveback_guard(
            entry_price=100.0,
            stop_price=110.0,
            low=70.0,
            close=81.0,
            previous_peak_r=5.0,
        )
        self.assertTrue(should_exit)
        self.assertAlmostEqual(peak, 5.0)

        should_exit, peak = btc_short_giveback_guard(
            entry_price=100.0,
            stop_price=100.0,
            low=90.0,
            close=95.0,
            previous_peak_r=1.0,
        )
        self.assertFalse(should_exit)
        self.assertAlmostEqual(peak, 1.0)

    def test_bear_core_rules_preserve_stop_and_trend_exit_state(self):
        from quant_btc.config import RiskConfig
        from quant_btc.portfolio_model import btc_bear_core_exit_signal, btc_bear_core_stop

        risk_cfg = RiskConfig(bear_core_sl_daily_atr=3.0, bear_core_exit_days_above_ema=2)

        self.assertAlmostEqual(
            btc_bear_core_stop(entry_price=100.0, atr_4h=2.0, risk_cfg=risk_cfg),
            109.0,
        )

        exit_now, last_day, days_above = btc_bear_core_exit_signal(
            bear_core_active=False,
            entry_price=100.0,
            close=130.0,
            atr_4h=2.0,
            daily_ema_dir=1,
            daily_ema=100.0,
            day_id=10,
            last_day=9,
            days_above_dema=1,
            risk_cfg=risk_cfg,
        )
        self.assertFalse(exit_now)
        self.assertEqual(last_day, 9)
        self.assertEqual(days_above, 1)

        exit_now, last_day, days_above = btc_bear_core_exit_signal(
            bear_core_active=True,
            entry_price=100.0,
            close=95.0,
            atr_4h=2.0,
            daily_ema_dir=1,
            daily_ema=100.0,
            day_id=10,
            last_day=9,
            days_above_dema=0,
            risk_cfg=risk_cfg,
        )
        self.assertTrue(exit_now)
        self.assertEqual(last_day, 9)
        self.assertEqual(days_above, 0)

        exit_now, last_day, days_above = btc_bear_core_exit_signal(
            bear_core_active=True,
            entry_price=100.0,
            close=105.0,
            atr_4h=2.0,
            daily_ema_dir=-1,
            daily_ema=100.0,
            day_id=10,
            last_day=9,
            days_above_dema=1,
            risk_cfg=risk_cfg,
        )
        self.assertTrue(exit_now)
        self.assertEqual(last_day, 10)
        self.assertEqual(days_above, 2)

        exit_now, last_day, days_above = btc_bear_core_exit_signal(
            bear_core_active=True,
            entry_price=100.0,
            close=110.0,
            atr_4h=2.0,
            daily_ema_dir=-1,
            daily_ema=120.0,
            day_id=11,
            last_day=10,
            days_above_dema=0,
            risk_cfg=risk_cfg,
        )
        self.assertTrue(exit_now)
        self.assertEqual(last_day, 11)
        self.assertEqual(days_above, 0)

    def test_core_long_rules_preserve_entry_exit_add_and_trailing_state(self):
        from quant_btc.config import RiskConfig
        from quant_btc.portfolio_model import (
            btc_core_add_signal,
            btc_core_entry_signal,
            btc_core_exit_signal,
            btc_core_trail_stop_hit,
        )

        risk_cfg = RiskConfig(core_exit_days_below_ema=2, core_sl_daily_atr_mult=3.0)

        self.assertTrue(btc_core_entry_signal(regime=1))
        self.assertFalse(btc_core_entry_signal(regime=0))
        self.assertTrue(btc_core_add_signal(pullback_long=True))

        exit_now, last_day, days_below = btc_core_exit_signal(
            weekly_ema_dir=1,
            close=95.0,
            daily_ema=100.0,
            day_id=10,
            last_day=9,
            days_below_dema=1,
            risk_cfg=risk_cfg,
        )
        self.assertTrue(exit_now)
        self.assertEqual(last_day, 10)
        self.assertEqual(days_below, 2)

        exit_now, last_day, days_below = btc_core_exit_signal(
            weekly_ema_dir=1,
            close=105.0,
            daily_ema=100.0,
            day_id=11,
            last_day=10,
            days_below_dema=2,
            risk_cfg=risk_cfg,
        )
        self.assertFalse(exit_now)
        self.assertEqual(last_day, 11)
        self.assertEqual(days_below, 0)

        exit_now, last_day, days_below = btc_core_exit_signal(
            weekly_ema_dir=-1,
            close=105.0,
            daily_ema=100.0,
            day_id=12,
            last_day=11,
            days_below_dema=0,
            risk_cfg=risk_cfg,
        )
        self.assertTrue(exit_now)
        self.assertEqual(last_day, 11)
        self.assertEqual(days_below, 0)

        stop_hit, highest_close = btc_core_trail_stop_hit(
            core_active=True,
            highest_close=110.0,
            close=100.0,
            atr=4.0,
            risk_cfg=risk_cfg,
        )
        self.assertFalse(stop_hit)
        self.assertEqual(highest_close, 110.0)

        stop_hit, highest_close = btc_core_trail_stop_hit(
            core_active=True,
            highest_close=110.0,
            close=97.0,
            atr=4.0,
            risk_cfg=risk_cfg,
        )
        self.assertTrue(stop_hit)
        self.assertEqual(highest_close, 110.0)

        stop_hit, highest_close = btc_core_trail_stop_hit(
            core_active=False,
            highest_close=110.0,
            close=120.0,
            atr=4.0,
            risk_cfg=risk_cfg,
        )
        self.assertFalse(stop_hit)
        self.assertEqual(highest_close, 110.0)


if __name__ == "__main__":
    unittest.main()
