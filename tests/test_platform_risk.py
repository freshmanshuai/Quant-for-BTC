import unittest

from quant_platform.signals import Direction, Signal


class RiskEngineTest(unittest.TestCase):
    def _signal(self, **overrides):
        data = {
            "module": "breakout",
            "symbol": "BTC/USDT",
            "direction": Direction.LONG,
            "score": 82.0,
            "entry_reason": "breakout",
            "invalidation": "stop loss",
            "preferred_stop": 95.0,
            "preferred_target": 120.0,
            "confidence": 0.8,
        }
        data.update(overrides)
        return Signal(**data)

    def test_sizes_order_from_signal_stop_distance_and_caps_notional(self):
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits

        engine = RiskEngine(RiskLimits(
            risk_per_trade=0.02,
            max_position_fraction=0.50,
            max_leverage=3.0,
        ))
        decision = engine.evaluate(
            self._signal(preferred_stop=98.0),
            AccountState(equity=10_000.0),
            entry_price=100.0,
        )

        self.assertTrue(decision.allowed)
        self.assertAlmostEqual(decision.risk_amount, 100.0)
        self.assertAlmostEqual(decision.quantity, 50.0)
        self.assertAlmostEqual(decision.notional, 5_000.0)
        self.assertEqual(decision.reason, "allowed")

    def test_market_spec_blocks_unsupported_shorts_and_leverage(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits

        spot_market = MarketSpec(
            asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
            supports_short=False,
            supports_leverage=False,
        )
        engine = RiskEngine(
            RiskLimits(
                risk_per_trade=0.50,
                max_position_fraction=2.0,
                max_leverage=3.0,
                portfolio_risk_budget=1.0,
            ),
            markets_by_symbol={"AAPL": spot_market},
        )

        short = engine.evaluate(
            self._signal(symbol="AAPL", direction=Direction.SHORT, preferred_stop=105.0),
            AccountState(equity=10_000.0),
            entry_price=100.0,
        )
        long = engine.evaluate(
            self._signal(symbol="AAPL", preferred_stop=99.0),
            AccountState(equity=10_000.0),
            entry_price=100.0,
        )

        self.assertFalse(short.allowed)
        self.assertEqual(short.reason, "short_not_supported")
        self.assertTrue(long.allowed)
        self.assertAlmostEqual(long.notional, 10_000.0)

    def test_blocks_when_portfolio_risk_budget_is_exhausted(self):
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits

        engine = RiskEngine(RiskLimits(
            risk_per_trade=0.02,
            portfolio_risk_budget=0.05,
        ))
        decision = engine.evaluate(
            self._signal(),
            AccountState(equity=10_000.0),
            entry_price=100.0,
            open_risk=450.0,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "portfolio_risk_budget_exhausted")
        self.assertEqual(decision.quantity, 0.0)

    def test_blocks_when_correlation_group_risk_budget_is_exhausted(self):
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits

        engine = RiskEngine(RiskLimits(
            risk_per_trade=0.02,
            portfolio_risk_budget=0.20,
            max_correlation_group_risk=0.05,
            correlation_groups={"BTC/USDT": "crypto_beta", "ETH/USDT": "crypto_beta"},
        ))
        decision = engine.evaluate(
            self._signal(symbol="ETH/USDT"),
            AccountState(equity=10_000.0),
            entry_price=100.0,
            open_risk=100.0,
            open_group_risk={"crypto_beta": 450.0},
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "correlation_group_risk_budget_exhausted")

    def test_unmapped_symbols_skip_correlation_group_gate(self):
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits

        engine = RiskEngine(RiskLimits(
            risk_per_trade=0.02,
            portfolio_risk_budget=0.20,
            max_correlation_group_risk=0.05,
            correlation_groups={"BTC/USDT": "crypto_beta"},
        ))
        decision = engine.evaluate(
            self._signal(symbol="SOL/USDT"),
            AccountState(equity=10_000.0),
            entry_price=100.0,
            open_group_risk={"crypto_beta": 500.0},
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "allowed")

    def test_blocks_when_symbol_risk_budget_is_exhausted(self):
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits

        engine = RiskEngine(RiskLimits(
            risk_per_trade=0.02,
            portfolio_risk_budget=0.20,
            max_symbol_risk=0.05,
        ))
        decision = engine.evaluate(
            self._signal(symbol="BTC/USDT"),
            AccountState(equity=10_000.0),
            entry_price=100.0,
            open_symbol_risk={"BTC/USDT": 450.0},
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "symbol_risk_budget_exhausted")

    def test_blocks_when_module_risk_budget_is_exhausted(self):
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits

        engine = RiskEngine(RiskLimits(
            risk_per_trade=0.02,
            portfolio_risk_budget=0.20,
            max_module_risk=0.05,
        ))
        decision = engine.evaluate(
            self._signal(module="breakout", symbol="ETH/USDT"),
            AccountState(equity=10_000.0),
            entry_price=100.0,
            open_module_risk={"breakout": 450.0},
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "module_risk_budget_exhausted")

    def test_blocks_during_daily_or_weekly_circuit_breaker(self):
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits

        engine = RiskEngine(RiskLimits(daily_drawdown_limit=0.075, weekly_drawdown_limit=0.10))

        daily = engine.evaluate(
            self._signal(),
            AccountState(equity=10_000.0, daily_drawdown_pct=0.08),
            entry_price=100.0,
        )
        weekly = engine.evaluate(
            self._signal(),
            AccountState(equity=10_000.0, weekly_drawdown_pct=0.11),
            entry_price=100.0,
        )

        self.assertFalse(daily.allowed)
        self.assertEqual(daily.reason, "daily_drawdown_limit")
        self.assertFalse(weekly.allowed)
        self.assertEqual(weekly.reason, "weekly_drawdown_limit")

    def test_reduces_size_after_consecutive_losses_and_pauses_after_limit(self):
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits, RiskState

        state = RiskState()
        limits = RiskLimits(
            risk_per_trade=0.02,
            consecutive_loss_limit=2,
            reduced_size_multiplier=0.5,
            max_consecutive_losses=3,
            pause_bars=5,
        )
        engine = RiskEngine(limits, state=state)
        state.record_trade(-10.0, bar_index=3, limits=limits)
        state.record_trade(-20.0, bar_index=4, limits=limits)

        reduced = engine.evaluate(self._signal(), AccountState(equity=10_000.0), entry_price=100.0, bar_index=5)
        self.assertTrue(reduced.allowed)
        self.assertAlmostEqual(reduced.risk_amount, 100.0)

        state.record_trade(-30.0, bar_index=5, limits=limits)
        paused = engine.evaluate(self._signal(), AccountState(equity=10_000.0), entry_price=100.0, bar_index=6)
        resumed = engine.evaluate(self._signal(), AccountState(equity=10_000.0), entry_price=100.0, bar_index=10)

        self.assertFalse(paused.allowed)
        self.assertEqual(paused.reason, "paused_after_consecutive_losses")
        self.assertTrue(resumed.allowed)

    def test_blocks_flat_signals_and_signals_without_stop(self):
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits

        engine = RiskEngine(RiskLimits())
        account = AccountState(equity=10_000.0)

        flat = engine.evaluate(self._signal(direction=Direction.FLAT), account, entry_price=100.0)
        no_stop = engine.evaluate(self._signal(preferred_stop=None), account, entry_price=100.0)

        self.assertFalse(flat.allowed)
        self.assertEqual(flat.reason, "flat_signal")
        self.assertFalse(no_stop.allowed)
        self.assertEqual(no_stop.reason, "missing_stop")


if __name__ == "__main__":
    unittest.main()
