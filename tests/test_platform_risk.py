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

    def test_signal_confidence_only_scales_risk_when_explicitly_enabled(self):
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits

        common = {
            "risk_per_trade": 0.01,
            "max_position_fraction": 1.0,
            "max_leverage": 1.0,
            "portfolio_risk_budget": 1.0,
        }
        signal = self._signal(preferred_stop=95.0, confidence=0.5)
        account = AccountState(equity=10_000.0)

        default = RiskEngine(RiskLimits(**common)).evaluate(signal, account, entry_price=100.0)
        scaled = RiskEngine(RiskLimits(**common, use_signal_confidence=True)).evaluate(
            signal, account, entry_price=100.0
        )

        self.assertAlmostEqual(default.risk_amount, 100.0)
        self.assertAlmostEqual(scaled.risk_amount, 50.0)
        self.assertAlmostEqual(scaled.quantity, default.quantity / 2.0)

    def test_non_finite_signal_confidence_fails_closed(self):
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits

        decision = RiskEngine(
            RiskLimits(use_signal_confidence=True, portfolio_risk_budget=1.0)
        ).evaluate(
            self._signal(confidence=float("nan")),
            AccountState(equity=10_000.0),
            entry_price=100.0,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "zero_quantity")

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

    def test_market_spec_max_leverage_caps_leveraged_notional(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits

        swap_market = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
            supports_short=True,
            supports_leverage=True,
            max_leverage=1.5,
        )
        engine = RiskEngine(
            RiskLimits(
                risk_per_trade=0.50,
                max_position_fraction=1.0,
                max_leverage=3.0,
                portfolio_risk_budget=1.0,
            ),
            markets_by_symbol={"BTC/USDT": swap_market},
        )

        decision = engine.evaluate(
            self._signal(preferred_stop=99.0),
            AccountState(equity=10_000.0),
            entry_price=100.0,
        )

        self.assertTrue(decision.allowed)
        self.assertAlmostEqual(decision.notional, 15_000.0)
        self.assertAlmostEqual(decision.quantity, 150.0)
        self.assertAlmostEqual(decision.risk_amount, 150.0)

    def test_market_spec_contract_multiplier_scales_quantity_and_unit_risk(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits

        futures_market = MarketSpec(
            asset=AssetSpec(symbol="ES", base="ES", quote="USD"),
            exchange="cme",
            market_type="future",
            contract_multiplier=100.0,
            supports_short=True,
            supports_leverage=True,
        )
        engine = RiskEngine(
            RiskLimits(
                risk_per_trade=0.02,
                max_position_fraction=1.0,
                max_leverage=1.0,
                portfolio_risk_budget=1.0,
            ),
            markets_by_symbol={"ES": futures_market},
        )

        decision = engine.evaluate(
            self._signal(symbol="ES", preferred_stop=9.0),
            AccountState(equity=10_000.0),
            entry_price=10.0,
        )

        self.assertTrue(decision.allowed)
        self.assertAlmostEqual(decision.max_loss_per_unit, 100.0)
        self.assertAlmostEqual(decision.quantity, 2.0)
        self.assertAlmostEqual(decision.notional, 2_000.0)
        self.assertAlmostEqual(decision.risk_amount, 200.0)

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

    def test_caps_total_notional_to_available_initial_margin(self):
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits

        engine = RiskEngine(RiskLimits(
            risk_per_trade=0.50,
            max_position_fraction=1.0,
            max_leverage=2.0,
            enforce_initial_margin=True,
            portfolio_risk_budget=1.0,
        ))
        resized = engine.evaluate(
            self._signal(preferred_stop=99.0),
            AccountState(equity=10_000.0),
            entry_price=100.0,
            open_notional=15_000.0,
        )
        blocked = engine.evaluate(
            self._signal(preferred_stop=99.0),
            AccountState(equity=10_000.0),
            entry_price=100.0,
            open_notional=20_000.0,
        )

        self.assertTrue(resized.allowed)
        self.assertAlmostEqual(resized.notional, 5_000.0)
        self.assertAlmostEqual(resized.quantity, 50.0)
        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.reason, "initial_margin_exhausted")

    def test_budget_gates_use_capped_candidate_risk(self):
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits

        engine = RiskEngine(RiskLimits(
            risk_per_trade=0.02,
            max_position_fraction=0.10,
            max_leverage=1.0,
            portfolio_risk_budget=0.10,
            max_symbol_risk=0.10,
            max_module_risk=0.10,
            max_correlation_group_risk=0.10,
            correlation_groups={"BTC/USDT": "crypto_beta"},
        ))
        decision = engine.evaluate(
            self._signal(preferred_stop=95.0),
            AccountState(equity=10_000.0),
            entry_price=100.0,
            open_risk=950.0,
            open_symbol_risk={"BTC/USDT": 950.0},
            open_module_risk={"breakout": 950.0},
            open_group_risk={"crypto_beta": 950.0},
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "allowed")
        self.assertAlmostEqual(decision.notional, 1_000.0)
        self.assertAlmostEqual(decision.risk_amount, 50.0)

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

    def test_market_spec_correlation_group_feeds_risk_budget_gate(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits

        market = MarketSpec(
            asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
            correlation_group="us_equity_beta",
        )
        engine = RiskEngine(
            RiskLimits(
                risk_per_trade=0.02,
                portfolio_risk_budget=0.20,
                max_correlation_group_risk=0.05,
            ),
            markets_by_symbol={"AAPL": market},
        )

        decision = engine.evaluate(
            self._signal(symbol="AAPL"),
            AccountState(equity=10_000.0),
            entry_price=100.0,
            open_group_risk={"us_equity_beta": 450.0},
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "correlation_group_risk_budget_exhausted")

    def test_market_spec_exchange_feeds_risk_budget_gate(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits

        market = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
        )
        engine = RiskEngine(
            RiskLimits(
                risk_per_trade=0.02,
                portfolio_risk_budget=0.20,
                max_exchange_risk=0.05,
            ),
            markets_by_symbol={"BTC/USDT": market},
        )

        decision = engine.evaluate(
            self._signal(symbol="BTC/USDT"),
            AccountState(equity=10_000.0),
            entry_price=100.0,
            open_exchange_risk={"binance": 450.0},
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "exchange_risk_budget_exhausted")

    def test_market_spec_market_type_feeds_risk_budget_gate(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits

        market = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
        )
        engine = RiskEngine(
            RiskLimits(
                risk_per_trade=0.02,
                portfolio_risk_budget=0.20,
                max_market_type_risk=0.05,
            ),
            markets_by_symbol={"BTC/USDT": market},
        )

        decision = engine.evaluate(
            self._signal(symbol="BTC/USDT"),
            AccountState(equity=10_000.0),
            entry_price=100.0,
            open_market_type_risk={"swap": 450.0},
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "market_type_risk_budget_exhausted")

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

    def test_budget_diagnostics_report_portfolio_symbol_module_and_group_usage(self):
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits

        engine = RiskEngine(RiskLimits(
            risk_per_trade=0.02,
            portfolio_risk_budget=0.10,
            max_symbol_risk=0.05,
            max_module_risk=0.04,
            max_correlation_group_risk=0.06,
            max_exchange_risk=0.07,
            max_market_type_risk=0.08,
            correlation_groups={"BTC/USDT": "crypto_beta", "ETH/USDT": "crypto_beta"},
        ))

        diagnostics = engine.budget_diagnostics(
            AccountState(equity=10_000.0),
            open_risk=300.0,
            open_symbol_risk={"BTC/USDT": 200.0, "ETH/USDT": 100.0},
            open_module_risk={"breakout": 200.0, "pullback": 100.0},
            open_group_risk={"crypto_beta": 300.0},
            open_exchange_risk={"binance": 200.0, "okx": 100.0},
            open_market_type_risk={"swap": 300.0},
        )

        self.assertEqual(diagnostics.portfolio.used, 300.0)
        self.assertEqual(diagnostics.portfolio.budget, 1_000.0)
        self.assertEqual(diagnostics.portfolio.remaining, 700.0)
        self.assertEqual(diagnostics.portfolio.utilization, 0.3)
        self.assertEqual(diagnostics.symbols["BTC/USDT"].budget, 500.0)
        self.assertEqual(diagnostics.symbols["BTC/USDT"].remaining, 300.0)
        self.assertEqual(diagnostics.modules["breakout"].budget, 400.0)
        self.assertEqual(diagnostics.correlation_groups["crypto_beta"].budget, 600.0)
        self.assertEqual(diagnostics.correlation_groups["crypto_beta"].utilization, 0.5)
        self.assertEqual(diagnostics.exchanges["binance"].used, 200.0)
        self.assertAlmostEqual(diagnostics.exchanges["binance"].budget, 700.0)
        self.assertEqual(diagnostics.exchanges["okx"].used, 100.0)
        self.assertEqual(diagnostics.market_types["swap"].used, 300.0)
        self.assertEqual(diagnostics.market_types["swap"].budget, 800.0)
        self.assertEqual(diagnostics.to_dict()["exchanges"]["okx"]["used"], 100.0)
        self.assertEqual(diagnostics.to_dict()["market_types"]["swap"]["used"], 300.0)
        self.assertEqual(diagnostics.target_risk_amount, 200.0)
        self.assertFalse(diagnostics.paused)

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

    def test_blocks_when_portfolio_max_drawdown_limit_is_reached(self):
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits, RiskState

        engine = RiskEngine(
            RiskLimits(max_drawdown_pct=0.10),
            state=RiskState(equity_peak=12_000.0),
        )

        decision = engine.evaluate(
            self._signal(),
            AccountState(equity=10_700.0),
            entry_price=100.0,
        )
        diagnostics = engine.budget_diagnostics(AccountState(equity=10_700.0)).to_dict()

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "max_drawdown_limit")
        self.assertAlmostEqual(diagnostics["drawdown"]["equityPeak"], 12_000.0)
        self.assertAlmostEqual(diagnostics["drawdown"]["currentPct"], 1300.0 / 12_000.0)
        self.assertAlmostEqual(diagnostics["drawdown"]["limitPct"], 0.10)
        self.assertTrue(diagnostics["drawdown"]["breached"])

    def test_max_drawdown_gate_tracks_equity_peak_from_evaluations(self):
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits

        engine = RiskEngine(RiskLimits(max_drawdown_pct=0.10))

        first = engine.evaluate(
            self._signal(),
            AccountState(equity=12_000.0),
            entry_price=100.0,
        )
        blocked = engine.evaluate(
            self._signal(),
            AccountState(equity=10_700.0),
            entry_price=100.0,
        )
        diagnostics = engine.budget_diagnostics(AccountState(equity=10_700.0)).to_dict()

        self.assertTrue(first.allowed)
        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.reason, "max_drawdown_limit")
        self.assertAlmostEqual(diagnostics["drawdown"]["equityPeak"], 12_000.0)
        self.assertAlmostEqual(diagnostics["drawdown"]["currentPct"], 1300.0 / 12_000.0)

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
