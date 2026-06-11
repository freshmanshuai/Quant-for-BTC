import unittest

import pandas as pd


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

    def test_legacy_entry_risk_decision_preserves_fractional_size_audit(self):
        from quant_btc.risk_model import build_btc_legacy_entry_risk_decision
        from quant_platform.signals import Direction, Signal

        signal = Signal(
            module="breakout",
            symbol="BTC/USDT",
            direction=Direction.LONG,
            score=82.0,
            entry_reason="legacy breakout",
            invalidation="legacy stop",
        )

        decision = build_btc_legacy_entry_risk_decision(
            signal=signal,
            equity=100_000.0,
            entry_price=100.0,
            stop_price=90.0,
            target_price=125.0,
            size_fraction=0.25,
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "legacy_compat_audit")
        self.assertEqual(decision.signal.preferred_stop, 90.0)
        self.assertEqual(decision.signal.preferred_target, 125.0)
        self.assertEqual(decision.entry_price, 100.0)
        self.assertEqual(decision.stop_price, 90.0)
        self.assertEqual(decision.quantity, 250.0)
        self.assertEqual(decision.notional, 25_000.0)
        self.assertEqual(decision.max_loss_per_unit, 10.0)
        self.assertEqual(decision.risk_amount, 2_500.0)

    def test_legacy_entry_risk_engine_decision_matches_fractional_size_for_audit(self):
        from quant_btc.risk_model import build_btc_legacy_entry_risk_engine_decision
        from quant_platform.signals import Direction, Signal

        signal = Signal(
            module="breakout",
            symbol="BTC/USDT",
            direction=Direction.LONG,
            score=82.0,
            entry_reason="legacy breakout",
            invalidation="legacy stop",
        )

        decision = build_btc_legacy_entry_risk_engine_decision(
            signal=signal,
            equity=100_000.0,
            entry_price=100.0,
            stop_price=90.0,
            target_price=125.0,
            size_fraction=0.25,
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "allowed")
        self.assertEqual(decision.signal.preferred_stop, 90.0)
        self.assertEqual(decision.signal.preferred_target, 125.0)
        self.assertEqual(decision.entry_price, 100.0)
        self.assertEqual(decision.stop_price, 90.0)
        self.assertEqual(decision.quantity, 250.0)
        self.assertEqual(decision.notional, 25_000.0)
        self.assertEqual(decision.max_loss_per_unit, 10.0)
        self.assertEqual(decision.risk_amount, 2_500.0)

    def test_legacy_entry_risk_audit_serializes_risk_engine_parity(self):
        from quant_btc.risk_model import (
            build_btc_legacy_entry_risk_audit,
            build_btc_legacy_entry_risk_decision,
            build_btc_legacy_entry_risk_engine_decision,
        )
        from quant_platform.signals import Direction, Signal

        signal = Signal(
            module="breakout",
            symbol="BTC/USDT",
            direction=Direction.LONG,
            score=82.0,
            entry_reason="legacy breakout",
            invalidation="legacy stop",
        )
        legacy_decision = build_btc_legacy_entry_risk_decision(
            signal=signal,
            equity=100_000.0,
            entry_price=100.0,
            stop_price=90.0,
            target_price=125.0,
            size_fraction=0.25,
        )
        engine_decision = build_btc_legacy_entry_risk_engine_decision(
            signal=signal,
            equity=100_000.0,
            entry_price=100.0,
            stop_price=90.0,
            target_price=125.0,
            size_fraction=0.25,
        )

        audit = build_btc_legacy_entry_risk_audit(
            legacy_decision=legacy_decision,
            engine_decision=engine_decision,
            enforcement_enabled=False,
            bar_index=42,
        ).to_dict()

        self.assertEqual(audit["bar_index"], 42)
        self.assertEqual(audit["module"], "breakout")
        self.assertEqual(audit["symbol"], "BTC/USDT")
        self.assertEqual(audit["direction"], "long")
        self.assertEqual(audit["parity_status"], "matched")
        self.assertTrue(audit["allowed_match"])
        self.assertTrue(audit["quantity_match"])
        self.assertTrue(audit["notional_match"])
        self.assertTrue(audit["risk_amount_match"])
        self.assertFalse(audit["would_block"])
        self.assertFalse(audit["would_block_if_enforced"])
        self.assertEqual(audit["legacy_reason"], "legacy_compat_audit")
        self.assertEqual(audit["engine_reason"], "allowed")
        self.assertEqual(audit["legacy_notional"], 25_000.0)
        self.assertEqual(audit["engine_notional"], 25_000.0)
        self.assertEqual(audit["risk_amount_delta"], 0.0)

    def test_legacy_entry_risk_decision_flows_to_portfolio_engine_order_plan(self):
        from quant_btc.risk_model import build_btc_legacy_entry_risk_decision
        from quant_platform.portfolio import OrderAction, PortfolioEngine
        from quant_platform.signals import Direction, Signal

        signal = Signal(
            module="breakout_retest",
            symbol="BTC/USDT",
            direction=Direction.LONG,
            score=80.0,
            entry_reason="legacy tactical",
            invalidation="legacy exit",
        )
        decision = build_btc_legacy_entry_risk_decision(
            signal=signal,
            equity=50_000.0,
            entry_price=100.0,
            stop_price=92.0,
            target_price=116.0,
            size_fraction=0.10,
        )

        order = PortfolioEngine(layer_by_module={"breakout_retest": "tactical"}).apply([decision]).orders[0]

        self.assertEqual(order.action, OrderAction.OPEN)
        self.assertEqual(order.layer, "tactical")
        self.assertEqual(order.symbol, "BTC/USDT")
        self.assertEqual(order.quantity, 50.0)
        self.assertEqual(order.entry_price, 100.0)
        self.assertEqual(order.stop_price, 92.0)
        self.assertEqual(order.target_price, 116.0)

    def test_legacy_entry_risk_decision_flows_through_signal_pipeline_decision_bridge(self):
        from quant_btc.risk_model import build_btc_legacy_entry_risk_decision
        from quant_platform.delivery import InMemoryDeliveryChannel
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner
        from quant_platform.signals import Direction, Signal

        signal = Signal(
            module="breakout_retest",
            symbol="BTC/USDT",
            direction=Direction.LONG,
            score=80.0,
            entry_reason="legacy tactical",
            invalidation="legacy exit",
        )
        decision = build_btc_legacy_entry_risk_decision(
            signal=signal,
            equity=50_000.0,
            entry_price=100.0,
            stop_price=92.0,
            target_price=116.0,
            size_fraction=0.10,
        )
        delivery = InMemoryDeliveryChannel("dashboard")
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([]),
            risk_engine=RiskEngine(RiskLimits(portfolio_risk_budget=0.20)),
            portfolio_engine=PortfolioEngine(layer_by_module={"breakout_retest": "tactical"}),
            delivery_channels=(delivery,),
        )

        result = pipeline.run_decisions([decision], account=AccountState(equity=50_000.0))
        order = result.portfolio_plan.orders[0]

        self.assertEqual(result.signals, [decision.signal])
        self.assertEqual(result.risk_decisions, [decision])
        self.assertEqual(order.action, OrderAction.OPEN)
        self.assertEqual(order.layer, "tactical")
        self.assertEqual(order.quantity, 50.0)
        self.assertEqual(order.entry_price, 100.0)
        self.assertEqual(order.stop_price, 92.0)
        self.assertEqual(order.target_price, 116.0)
        self.assertEqual(len(delivery.messages), 1)
        self.assertEqual(result.risk_diagnostics.portfolio.used, 400.0)

    def test_base_strategy_entry_records_platform_risk_decision_audit(self):
        from quant_btc.strategy import ATRHTFStopStrategy

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        strategy = object.__new__(ATRHTFStopStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "_regime": [1],
                "_d_ema_dir": [1],
                "_w_ema_dir": [1],
                "_atr": [5.0],
                "long_entry": [True],
                "short_entry": [False],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = None
        strategy.equity = 100_000.0
        strategy._had_position = False
        strategy._pause_until_bar = -1
        strategy._last_trade_bar = -10**9
        strategy._update_circuit_breaker = lambda: None
        strategy._calc_sl_tp = lambda is_long, regime: (90.0, 120.0)
        strategy._calc_position_size = lambda entry, sl: 0.25
        orders = []
        strategy.buy = lambda **kwargs: orders.append(("buy", kwargs))
        strategy.sell = lambda **kwargs: orders.append(("sell", kwargs))

        strategy.next()

        self.assertEqual(orders, [("buy", {"size": 0.25, "sl": 90.0, "tp": 120.0})])
        decision = strategy._last_platform_risk_decision
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.signal.module, "legacy_zone")
        self.assertEqual(decision.entry_price, 100.0)
        self.assertEqual(decision.stop_price, 90.0)
        self.assertEqual(decision.signal.preferred_target, 120.0)
        self.assertEqual(decision.quantity, 250.0)
        self.assertEqual(decision.notional, 25_000.0)
        engine_decision = strategy._last_platform_risk_engine_decision
        self.assertTrue(engine_decision.allowed)
        self.assertEqual(engine_decision.quantity, 250.0)
        self.assertEqual(engine_decision.notional, 25_000.0)
        self.assertEqual(engine_decision.risk_amount, 2_500.0)
        self.assertEqual(len(strategy._platform_risk_audits), 1)
        audit = strategy._last_platform_risk_audit.to_dict()
        self.assertEqual(audit["module"], "legacy_zone")
        self.assertEqual(audit["parity_status"], "matched")
        self.assertTrue(audit["allowed_match"])
        self.assertEqual(audit["legacy_notional"], 25_000.0)
        self.assertEqual(audit["engine_notional"], 25_000.0)
        self.assertFalse(audit["would_block_if_enforced"])

    def test_base_strategy_entry_records_signal_pipeline_decision_bridge_audit(self):
        from quant_btc.strategy import ATRHTFStopStrategy
        from quant_platform.portfolio import OrderAction

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        strategy = object.__new__(ATRHTFStopStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "_regime": [1],
                "_d_ema_dir": [1],
                "_w_ema_dir": [1],
                "_atr": [5.0],
                "long_entry": [True],
                "short_entry": [False],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = None
        strategy.equity = 100_000.0
        strategy._had_position = False
        strategy._pause_until_bar = -1
        strategy._last_trade_bar = -10**9
        strategy._update_circuit_breaker = lambda: None
        strategy._calc_sl_tp = lambda is_long, regime: (90.0, 120.0)
        strategy._calc_position_size = lambda entry, sl: 0.25
        orders = []
        strategy.buy = lambda **kwargs: orders.append(("buy", kwargs))
        strategy.sell = lambda **kwargs: orders.append(("sell", kwargs))

        strategy.next()

        self.assertEqual(orders, [("buy", {"size": 0.25, "sl": 90.0, "tp": 120.0})])
        decision = strategy._last_platform_risk_decision
        result = strategy._last_platform_pipeline_result
        order = result.portfolio_plan.orders[0]
        self.assertEqual(result.signals, [decision.signal])
        self.assertEqual(result.risk_decisions, [decision])
        self.assertIs(strategy._last_platform_entry_order, order)
        self.assertEqual(order.action, OrderAction.OPEN)
        self.assertEqual(order.layer, "tactical")
        self.assertEqual(order.symbol, "BTC/USDT")
        self.assertEqual(order.quantity, 250.0)
        self.assertEqual(order.entry_price, 100.0)
        self.assertEqual(order.stop_price, 90.0)
        self.assertEqual(order.target_price, 120.0)
        self.assertEqual(result.risk_diagnostics.portfolio.used, 2_500.0)
        self.assertEqual(strategy._platform_pipeline_results, [result])

    def test_base_strategy_entry_executes_platform_order_plan_prices_when_available(self):
        from types import SimpleNamespace

        from quant_btc.strategy import ATRHTFStopStrategy
        from quant_platform.signals import Direction

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        strategy = object.__new__(ATRHTFStopStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "_regime": [1],
                "_d_ema_dir": [1],
                "_w_ema_dir": [1],
                "_atr": [5.0],
                "long_entry": [True],
                "short_entry": [False],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = None
        strategy.equity = 100_000.0
        strategy._had_position = False
        strategy._pause_until_bar = -1
        strategy._last_trade_bar = -10**9
        strategy._update_circuit_breaker = lambda: None
        strategy._calc_sl_tp = lambda is_long, regime: (90.0, 120.0)
        strategy._calc_position_size = lambda entry, sl: 0.25

        def record_platform_order(**kwargs):
            strategy._last_platform_entry_order = SimpleNamespace(
                direction=Direction.LONG,
                stop_price=91.0,
                target_price=119.0,
            )

        strategy._record_legacy_entry_risk_decision = record_platform_order
        orders = []
        strategy.buy = lambda **kwargs: orders.append(("buy", kwargs))
        strategy.sell = lambda **kwargs: orders.append(("sell", kwargs))

        strategy.next()

        self.assertEqual(orders, [("buy", {"size": 0.25, "sl": 91.0, "tp": 119.0})])

    def test_weighted_legacy_entry_executes_platform_order_plan_when_available(self):
        from types import SimpleNamespace

        from quant_btc.strategy import WeightedSignalStrategy
        from quant_platform.signals import Direction

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        strategy = object.__new__(WeightedSignalStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "long_entry": [True],
                "short_entry": [False],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = None
        strategy.equity = 50_000.0
        strategy.cooldown_bars = 0
        strategy.trade_size_fraction = 0.95
        strategy.last_trade_bar = -10**9

        def record_platform_order(**kwargs):
            self.assertEqual(kwargs["signal"].module, "legacy_weighted")
            self.assertEqual(kwargs["size_fraction"], 0.95)
            strategy._last_platform_entry_order = SimpleNamespace(
                direction=Direction.SHORT,
                stop_price=111.0,
                target_price=88.0,
            )

        strategy._record_legacy_entry_risk_decision = record_platform_order
        orders = []
        strategy.buy = lambda **kwargs: orders.append(("buy", kwargs))
        strategy.sell = lambda **kwargs: orders.append(("sell", kwargs))

        strategy.next()

        self.assertEqual(orders, [("sell", {"size": 0.95, "sl": 111.0, "tp": 88.0})])

    def test_weighted_legacy_entry_records_platform_risk_decision_audit(self):
        from quant_btc.strategy import WeightedSignalStrategy
        from quant_platform.portfolio import OrderAction

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        strategy = object.__new__(WeightedSignalStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "long_entry": [True],
                "short_entry": [False],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = None
        strategy.equity = 50_000.0
        strategy.cooldown_bars = 0
        strategy.trade_size_fraction = 0.95
        strategy.last_trade_bar = -10**9
        orders = []
        strategy.buy = lambda **kwargs: orders.append(("buy", kwargs))
        strategy.sell = lambda **kwargs: orders.append(("sell", kwargs))

        strategy.next()

        self.assertEqual(orders, [("buy", {"size": 0.95})])
        decision = strategy._last_platform_risk_decision
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.signal.module, "legacy_weighted")
        self.assertEqual(decision.entry_price, 100.0)
        self.assertEqual(decision.quantity, 475.0)
        self.assertEqual(decision.notional, 47_500.0)
        self.assertEqual(decision.risk_amount, 0.0)
        engine_decision = strategy._last_platform_risk_engine_decision
        self.assertFalse(engine_decision.allowed)
        self.assertEqual(engine_decision.reason, "missing_stop")
        order = strategy._last_platform_pipeline_result.portfolio_plan.orders[0]
        self.assertIs(strategy._last_platform_entry_order, order)
        self.assertEqual(order.action, OrderAction.OPEN)
        self.assertEqual(order.layer, "tactical")
        self.assertEqual(strategy._platform_pipeline_results, [strategy._last_platform_pipeline_result])
        self.assertEqual(len(strategy._platform_risk_audits), 1)

    def test_weighted_legacy_opposite_signal_records_platform_close_order_audit(self):
        from quant_btc.strategy import WeightedSignalStrategy
        from quant_platform.portfolio import OrderAction
        from quant_platform.signals import Direction

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        class FakePosition:
            is_long = True
            is_short = False
            size = 0.95

            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        position = FakePosition()
        strategy = object.__new__(WeightedSignalStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "long_entry": [False],
                "short_entry": [True],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = position
        strategy.equity = 50_000.0
        strategy.cooldown_bars = 0
        strategy.trade_size_fraction = 0.95
        strategy.last_trade_bar = -10**9
        strategy._platform_pipeline_results = []

        strategy.next()

        self.assertTrue(position.closed)
        result = strategy._last_platform_pipeline_result
        order = result.portfolio_plan.orders[0]
        self.assertEqual(order.action, OrderAction.CLOSE)
        self.assertEqual(order.reason, "opposite_signal_close")
        self.assertEqual(order.direction, Direction.LONG)
        self.assertEqual(order.quantity, 475.0)
        self.assertEqual(order.symbol, "BTC/USDT")
        self.assertEqual(order.layer, "tactical")
        self.assertEqual(order.decision.signal.module, "legacy_weighted")
        self.assertEqual(strategy._platform_pipeline_results, [result])

    def test_base_strategy_time_stop_records_platform_close_order_audit(self):
        from quant_btc.config import RiskConfig
        from quant_btc.strategy import ATRHTFStopStrategy
        from quant_platform.portfolio import OrderAction, OrderStatus
        from quant_platform.signals import Direction

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        class FakePosition:
            is_long = True
            is_short = False
            size = 0.25

            def __init__(self):
                self.closed = False

            def __bool__(self):
                return True

            def close(self, portion=None):
                self.closed = True

        position = FakePosition()
        strategy = object.__new__(ATRHTFStopStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "_regime": [1],
                "_d_ema_dir": [1],
                "_w_ema_dir": [1],
                "_atr": [5.0],
                "long_entry": [False],
                "short_entry": [False],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = position
        strategy.equity = 100_000.0
        strategy.risk_cfg = RiskConfig()
        strategy.cooldown_bars = 0
        strategy._had_position = True
        strategy._pause_until_bar = -1
        strategy._last_trade_bar = -10**9
        strategy._entry_price = 100.0
        strategy._entry_bar = -85
        strategy._entry_atr = 5.0
        strategy._initial_risk = 10.0
        strategy._trailing_sl = 90.0
        strategy._extreme_since_entry = 100.0
        strategy._USE_TIME_STOP = True
        strategy._platform_pipeline_results = []
        strategy._last_platform_pipeline_result = None
        strategy._update_circuit_breaker = lambda: None
        strategy._on_trade_closed = lambda pnl: None

        strategy.next()

        self.assertTrue(position.closed)
        result = strategy._last_platform_pipeline_result
        order = result.portfolio_plan.orders[0]
        self.assertEqual(order.action, OrderAction.CLOSE)
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.reason, "time_stop")
        self.assertEqual(order.symbol, "BTC/USDT")
        self.assertEqual(order.layer, "tactical")
        self.assertEqual(order.direction, Direction.LONG)
        self.assertEqual(order.quantity, 250.0)
        self.assertEqual(order.decision.signal.module, "legacy_zone")
        self.assertEqual(strategy._platform_pipeline_results, [result])

    def test_base_strategy_partial_take_profit_records_platform_partial_close_audit(self):
        from quant_btc.config import RiskConfig
        from quant_btc.strategy import ATRHTFStopStrategy
        from quant_platform.portfolio import OrderAction, OrderStatus
        from quant_platform.signals import Direction

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        class FakePosition:
            is_long = True
            is_short = False
            size = 0.40

            def __init__(self):
                self.closed_portions = []

            def __bool__(self):
                return True

            def close(self, portion=None):
                self.closed_portions.append(portion)

        position = FakePosition()
        strategy = object.__new__(ATRHTFStopStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [120.0],
                "High": [121.0],
                "Low": [119.0],
                "_regime": [1],
                "_d_ema_dir": [1],
                "_w_ema_dir": [1],
                "_atr": [5.0],
                "long_entry": [False],
                "short_entry": [False],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = position
        strategy.equity = 100_000.0
        strategy.risk_cfg = RiskConfig()
        strategy.cooldown_bars = 0
        strategy._had_position = True
        strategy._pause_until_bar = -1
        strategy._last_trade_bar = -10**9
        strategy._entry_price = 100.0
        strategy._entry_bar = 0
        strategy._entry_atr = 5.0
        strategy._initial_risk = 10.0
        strategy._trailing_sl = 90.0
        strategy._extreme_since_entry = 120.0
        strategy._partial_done = False
        strategy._USE_PARTIAL_TP = True
        strategy._PARTIAL_TP_R = 1.5
        strategy._PARTIAL_TP_PCT = 0.35
        strategy._USE_TIME_STOP = False
        strategy._platform_pipeline_results = []
        strategy._last_platform_pipeline_result = None
        strategy._update_circuit_breaker = lambda: None
        strategy._on_trade_closed = lambda pnl: None

        strategy.next()

        self.assertEqual(position.closed_portions, [0.35])
        self.assertTrue(strategy._partial_done)
        result = strategy._last_platform_pipeline_result
        order = result.portfolio_plan.orders[0]
        self.assertEqual(order.action, OrderAction.CLOSE)
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.reason, "partial_take_profit")
        self.assertEqual(order.symbol, "BTC/USDT")
        self.assertEqual(order.layer, "tactical")
        self.assertEqual(order.direction, Direction.LONG)
        self.assertEqual(order.quantity, 116.66666666666666)
        self.assertEqual(order.existing_position.quantity, 333.3333333333333)
        self.assertEqual(order.decision.signal.module, "legacy_zone")
        self.assertEqual(strategy._platform_pipeline_results, [result])

    def test_base_strategy_entry_can_enforce_platform_risk_engine_block(self):
        from quant_btc.strategy import ATRHTFStopStrategy
        from quant_platform.risk import RiskEngine, RiskLimits

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        strategy = object.__new__(ATRHTFStopStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "_regime": [1],
                "_d_ema_dir": [1],
                "_w_ema_dir": [1],
                "_atr": [5.0],
                "long_entry": [True],
                "short_entry": [False],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = None
        strategy.equity = 100_000.0
        strategy._had_position = False
        strategy._pause_until_bar = -1
        strategy._last_trade_bar = -10**9
        strategy._update_circuit_breaker = lambda: None
        strategy._calc_sl_tp = lambda is_long, regime: (90.0, 120.0)
        strategy._calc_position_size = lambda entry, sl: 0.25
        strategy._ENFORCE_PLATFORM_RISK_ENGINE = True
        strategy._platform_risk_engine = RiskEngine(RiskLimits(
            risk_per_trade=0.02,
            portfolio_risk_budget=0.001,
        ))
        orders = []
        strategy.buy = lambda **kwargs: orders.append(("buy", kwargs))
        strategy.sell = lambda **kwargs: orders.append(("sell", kwargs))

        strategy.next()

        self.assertEqual(orders, [])
        self.assertTrue(strategy._last_platform_risk_decision.allowed)
        self.assertFalse(strategy._last_platform_risk_engine_decision.allowed)
        self.assertEqual(
            strategy._last_platform_risk_engine_decision.reason,
            "portfolio_risk_budget_exhausted",
        )

    def test_dual_layer_tactical_entry_records_platform_risk_decision_audit(self):
        from quant_btc.config import RiskConfig
        from quant_btc.strategy import DualLayerStrategy
        from quant_platform.portfolio import OrderAction
        from quant_platform.signals import Direction, Signal

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        strategy = object.__new__(DualLayerStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "_regime": [1],
                "_d_ema_dir": [1],
                "_w_ema_dir": [1],
                "_w_ema_169": [95.0],
                "_atr": [5.0],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = None
        strategy.equity = 50_000.0
        strategy.risk_cfg = RiskConfig(risk_breakout=0.008)
        strategy.cooldown_bars = 0
        strategy._last_trade_bar = -10**9
        strategy._pause_until_bar = -1
        strategy._core_active = False
        strategy._core_size = 0.0
        strategy._core_fully_loaded = False
        strategy._tac_direction = 0
        strategy._tac_size = 0.0
        strategy._bear_core_active = False
        strategy._bear_core_stage = 0
        strategy._bear_core_size = 0.0
        strategy._bear_core_entry_price = 0.0
        strategy._bear_group_id = 0
        strategy._bear_group_exposure = 0.0
        strategy._bear_group_entry_bar = -10**9
        strategy._bear_group_peak_r = 0.0
        strategy._bear_group_max_exposure = 0.50
        strategy._days_above_dema = 0
        strategy._flash_crash_active = False
        strategy._flash_crash_bar = -10**9
        strategy._update_circuit_breaker = lambda: None
        strategy._core_entry_standard_signal = lambda: None
        strategy._bear_core_probe_standard_signal = lambda: None
        strategy._bear_core_confirm_add_standard_signal = lambda: None
        strategy._bear_core_acceleration_add_standard_signal = lambda: None
        strategy._tactical_signal = lambda: Signal(
            module="breakout_retest",
            symbol="BTC/USDT",
            direction=Direction.LONG,
            score=88.0,
            entry_reason="legacy tactical",
            invalidation="legacy tactical exit",
        )
        strategy._tactical_sl_tp = lambda is_long: (92.0, 116.0)
        orders = []
        strategy._enter_long = lambda size, tag="", sl=None, tp=None: orders.append(
            ("long", size, tag, sl, tp)
        )
        strategy._enter_short = lambda size, tag="", sl=None, tp=None: orders.append(
            ("short", size, tag, sl, tp)
        )

        strategy.next()

        self.assertEqual(orders, [("long", 0.1, "breakout_retest_long", 92.0, 116.0)])
        decision = strategy._last_platform_risk_decision
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.signal.module, "breakout_retest")
        self.assertEqual(decision.entry_price, 100.0)
        self.assertEqual(decision.stop_price, 92.0)
        self.assertEqual(decision.signal.preferred_target, 116.0)
        self.assertEqual(decision.quantity, 50.0)
        self.assertEqual(decision.notional, 5_000.0)
        engine_decision = strategy._last_platform_risk_engine_decision
        self.assertTrue(engine_decision.allowed)
        self.assertEqual(engine_decision.quantity, 50.0)
        self.assertEqual(engine_decision.notional, 5_000.0)
        self.assertEqual(engine_decision.risk_amount, 400.0)
        order = strategy._last_platform_pipeline_result.portfolio_plan.orders[0]
        self.assertIs(strategy._last_platform_entry_order, order)
        self.assertEqual(order.action, OrderAction.OPEN)
        self.assertEqual(order.layer, "tactical")

    def test_dual_layer_tactical_entry_executes_platform_order_plan_prices_when_available(self):
        from types import SimpleNamespace

        from quant_btc.config import RiskConfig
        from quant_btc.strategy import DualLayerStrategy
        from quant_platform.signals import Direction, Signal

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        strategy = object.__new__(DualLayerStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "_regime": [1],
                "_d_ema_dir": [1],
                "_w_ema_dir": [1],
                "_w_ema_169": [95.0],
                "_atr": [5.0],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = None
        strategy.equity = 50_000.0
        strategy.risk_cfg = RiskConfig(risk_breakout=0.008)
        strategy.cooldown_bars = 0
        strategy._last_trade_bar = -10**9
        strategy._pause_until_bar = -1
        strategy._core_active = False
        strategy._core_size = 0.0
        strategy._core_fully_loaded = False
        strategy._tac_direction = 0
        strategy._tac_size = 0.0
        strategy._bear_core_active = False
        strategy._bear_core_stage = 0
        strategy._bear_core_size = 0.0
        strategy._bear_core_entry_price = 0.0
        strategy._bear_group_id = 0
        strategy._bear_group_exposure = 0.0
        strategy._bear_group_entry_bar = -10**9
        strategy._bear_group_peak_r = 0.0
        strategy._bear_group_max_exposure = 0.50
        strategy._days_above_dema = 0
        strategy._flash_crash_active = False
        strategy._flash_crash_bar = -10**9
        strategy._update_circuit_breaker = lambda: None
        strategy._core_entry_standard_signal = lambda: None
        strategy._bear_core_probe_standard_signal = lambda: None
        strategy._bear_core_confirm_add_standard_signal = lambda: None
        strategy._bear_core_acceleration_add_standard_signal = lambda: None
        strategy._tactical_signal = lambda: Signal(
            module="breakout_retest",
            symbol="BTC/USDT",
            direction=Direction.LONG,
            score=88.0,
            entry_reason="legacy tactical",
            invalidation="legacy tactical exit",
        )
        strategy._tactical_sl_tp = lambda is_long: (92.0, 116.0)

        def record_platform_order(**kwargs):
            strategy._last_platform_entry_order = SimpleNamespace(
                direction=Direction.LONG,
                stop_price=91.0,
                target_price=119.0,
            )

        strategy._record_legacy_entry_risk_decision = record_platform_order
        orders = []
        strategy._enter_long = lambda size, tag="", sl=None, tp=None: orders.append(
            ("long", size, tag, sl, tp)
        )
        strategy._enter_short = lambda size, tag="", sl=None, tp=None: orders.append(
            ("short", size, tag, sl, tp)
        )

        strategy.next()

        self.assertEqual(orders, [("long", 0.1, "breakout_retest_long", 91.0, 119.0)])
        self.assertEqual(strategy._tac_sl, 91.0)
        self.assertEqual(strategy._tac_tp, 119.0)

    def test_dual_layer_flash_crash_dip_buy_executes_platform_order_plan_prices_when_available(self):
        from types import SimpleNamespace

        from quant_btc.config import RiskConfig
        from quant_btc.strategy import DualLayerStrategy
        from quant_platform.signals import Direction

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        class FakePosition:
            size = 0.30

            def __bool__(self):
                return True

        strategy = object.__new__(DualLayerStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "High": [110.0],
                "Low": [99.0],
                "_regime": [1],
                "_d_ema_dir": [1],
                "_w_ema_dir": [1],
                "_w_ema_169": [95.0],
                "_atr": [5.0],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = FakePosition()
        strategy.equity = 50_000.0
        strategy.risk_cfg = RiskConfig(risk_breakout=0.008)
        strategy.cooldown_bars = 0
        strategy._last_trade_bar = -10**9
        strategy._pause_until_bar = -1
        strategy._core_active = True
        strategy._core_size = 0.30
        strategy._core_fully_loaded = True
        strategy._tac_direction = 0
        strategy._tac_size = 0.0
        strategy._bear_core_active = False
        strategy._bear_core_stage = 0
        strategy._bear_core_size = 0.0
        strategy._bear_core_entry_price = 0.0
        strategy._bear_group_id = 0
        strategy._bear_group_exposure = 0.0
        strategy._bear_group_entry_bar = -10**9
        strategy._bear_group_peak_r = 0.0
        strategy._bear_group_max_exposure = 0.50
        strategy._days_above_dema = 0
        strategy._flash_crash_active = True
        strategy._flash_crash_bar = -1
        strategy._update_circuit_breaker = lambda: None
        strategy._core_exit_signal = lambda: False
        strategy._core_trail_stop_hit = lambda: False
        strategy._core_entry_standard_signal = lambda: None
        strategy._core_add_standard_signal = lambda: None
        strategy._bear_core_probe_standard_signal = lambda: None
        strategy._bear_core_confirm_add_standard_signal = lambda: None
        strategy._bear_core_acceleration_add_standard_signal = lambda: None
        strategy._tactical_signal = lambda: None

        def record_platform_order(**kwargs):
            self.assertEqual(kwargs["signal"].module, "dip_buy")
            self.assertEqual(kwargs["size_fraction"], 0.10)
            strategy._last_platform_entry_order = SimpleNamespace(
                direction=Direction.LONG,
                stop_price=91.0,
                target_price=119.0,
            )

        strategy._record_legacy_entry_risk_decision = record_platform_order
        orders = []
        strategy._enter_long = lambda size, tag="", sl=None, tp=None: orders.append(
            ("long", size, tag, sl, tp)
        )
        strategy._enter_short = lambda size, tag="", sl=None, tp=None: orders.append(
            ("short", size, tag, sl, tp)
        )

        strategy.next()

        self.assertEqual(orders, [("long", 0.10, "dip_buy_long", 91.0, 119.0)])
        self.assertEqual(strategy._tac_sl, 91.0)
        self.assertEqual(strategy._tac_tp, 119.0)

    def test_dual_layer_tactical_entry_can_enforce_platform_risk_engine_block(self):
        from quant_btc.config import RiskConfig
        from quant_btc.strategy import DualLayerStrategy
        from quant_platform.risk import RiskEngine, RiskLimits
        from quant_platform.signals import Direction, Signal

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        strategy = object.__new__(DualLayerStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "_regime": [1],
                "_d_ema_dir": [1],
                "_w_ema_dir": [1],
                "_w_ema_169": [95.0],
                "_atr": [5.0],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = None
        strategy.equity = 50_000.0
        strategy.risk_cfg = RiskConfig(risk_breakout=0.008)
        strategy.cooldown_bars = 0
        strategy._last_trade_bar = -10**9
        strategy._pause_until_bar = -1
        strategy._core_active = False
        strategy._core_size = 0.0
        strategy._core_fully_loaded = False
        strategy._tac_direction = 0
        strategy._tac_size = 0.0
        strategy._bear_core_active = False
        strategy._bear_core_stage = 0
        strategy._bear_core_size = 0.0
        strategy._bear_core_entry_price = 0.0
        strategy._bear_group_id = 0
        strategy._bear_group_exposure = 0.0
        strategy._bear_group_entry_bar = -10**9
        strategy._bear_group_peak_r = 0.0
        strategy._bear_group_max_exposure = 0.50
        strategy._days_above_dema = 0
        strategy._flash_crash_active = False
        strategy._flash_crash_bar = -10**9
        strategy._update_circuit_breaker = lambda: None
        strategy._core_entry_standard_signal = lambda: None
        strategy._bear_core_probe_standard_signal = lambda: None
        strategy._bear_core_confirm_add_standard_signal = lambda: None
        strategy._bear_core_acceleration_add_standard_signal = lambda: None
        strategy._tactical_signal = lambda: Signal(
            module="breakout_retest",
            symbol="BTC/USDT",
            direction=Direction.LONG,
            score=88.0,
            entry_reason="legacy tactical",
            invalidation="legacy tactical exit",
        )
        strategy._tactical_sl_tp = lambda is_long: (92.0, 116.0)
        strategy._ENFORCE_PLATFORM_RISK_ENGINE = True
        strategy._platform_risk_engine = RiskEngine(RiskLimits(
            risk_per_trade=0.02,
            portfolio_risk_budget=0.001,
        ))
        orders = []
        strategy._enter_long = lambda size, tag="", sl=None, tp=None: orders.append(
            ("long", size, tag, sl, tp)
        )
        strategy._enter_short = lambda size, tag="", sl=None, tp=None: orders.append(
            ("short", size, tag, sl, tp)
        )

        strategy.next()

        self.assertEqual(orders, [])
        self.assertEqual(strategy._tac_direction, 0)
        self.assertTrue(strategy._last_platform_risk_decision.allowed)
        self.assertFalse(strategy._last_platform_risk_engine_decision.allowed)
        self.assertEqual(
            strategy._last_platform_risk_engine_decision.reason,
            "portfolio_risk_budget_exhausted",
        )

    def test_dual_layer_core_entry_executes_platform_order_plan_prices_when_available(self):
        from types import SimpleNamespace

        from quant_btc.config import RiskConfig
        from quant_btc.strategy import DualLayerStrategy
        from quant_platform.signals import Direction, Signal

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        strategy = object.__new__(DualLayerStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "_regime": [1],
                "_d_ema_dir": [1],
                "_w_ema_dir": [1],
                "_w_ema_169": [95.0],
                "_atr": [5.0],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = None
        strategy.equity = 50_000.0
        strategy.risk_cfg = RiskConfig(risk_core_alloc=0.35)
        strategy.cooldown_bars = 0
        strategy._last_trade_bar = -10**9
        strategy._pause_until_bar = -1
        strategy._core_active = False
        strategy._core_size = 0.0
        strategy._core_fully_loaded = True
        strategy._tac_direction = 0
        strategy._tac_size = 0.0
        strategy._bear_core_active = False
        strategy._bear_core_stage = 0
        strategy._bear_core_size = 0.0
        strategy._bear_core_entry_price = 0.0
        strategy._bear_group_id = 0
        strategy._bear_group_exposure = 0.0
        strategy._bear_group_entry_bar = -10**9
        strategy._bear_group_peak_r = 0.0
        strategy._bear_group_max_exposure = 0.50
        strategy._days_above_dema = 0
        strategy._flash_crash_active = False
        strategy._flash_crash_bar = -10**9
        strategy._update_circuit_breaker = lambda: None
        strategy._core_entry_standard_signal = lambda: Signal(
            module="core_long",
            symbol="BTC/USDT",
            direction=Direction.LONG,
            score=100.0,
            entry_reason="legacy core",
            invalidation="legacy core trend exit",
        )
        strategy._core_add_standard_signal = lambda: None
        strategy._bear_core_probe_standard_signal = lambda: None
        strategy._bear_core_confirm_add_standard_signal = lambda: None
        strategy._bear_core_acceleration_add_standard_signal = lambda: None
        strategy._tactical_signal = lambda: None

        def record_platform_order(**kwargs):
            strategy._last_platform_entry_order = SimpleNamespace(
                direction=Direction.LONG,
                stop_price=91.0,
                target_price=119.0,
            )

        strategy._record_legacy_entry_risk_decision = record_platform_order
        orders = []
        strategy._enter_long = lambda size, tag="", sl=None, tp=None: orders.append(
            ("long", size, tag, sl, tp)
        )
        strategy._enter_short = lambda size, tag="", sl=None, tp=None: orders.append(
            ("short", size, tag, sl, tp)
        )

        strategy.next()

        self.assertEqual(orders, [("long", 0.35, "core_long", 91.0, 119.0)])
        self.assertTrue(strategy._core_active)
        self.assertEqual(strategy._core_size, 0.35)

    def test_dual_layer_core_entry_can_enforce_platform_risk_engine_block(self):
        from quant_btc.config import RiskConfig
        from quant_btc.strategy import DualLayerStrategy
        from quant_platform.risk import RiskEngine
        from quant_platform.signals import Direction, Signal

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        strategy = object.__new__(DualLayerStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "_regime": [1],
                "_d_ema_dir": [1],
                "_w_ema_dir": [1],
                "_w_ema_169": [95.0],
                "_atr": [5.0],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = None
        strategy.equity = 50_000.0
        strategy.risk_cfg = RiskConfig()
        strategy.cooldown_bars = 0
        strategy._last_trade_bar = -10**9
        strategy._pause_until_bar = -1
        strategy._core_active = False
        strategy._core_size = 0.0
        strategy._core_fully_loaded = True
        strategy._tac_direction = 0
        strategy._tac_size = 0.0
        strategy._bear_core_active = False
        strategy._bear_core_stage = 0
        strategy._bear_core_size = 0.0
        strategy._bear_core_entry_price = 0.0
        strategy._bear_group_id = 0
        strategy._bear_group_exposure = 0.0
        strategy._bear_group_entry_bar = -10**9
        strategy._bear_group_peak_r = 0.0
        strategy._bear_group_max_exposure = 0.50
        strategy._days_above_dema = 0
        strategy._flash_crash_active = False
        strategy._flash_crash_bar = -10**9
        strategy._update_circuit_breaker = lambda: None
        strategy._core_entry_standard_signal = lambda: Signal(
            module="core_long",
            symbol="BTC/USDT",
            direction=Direction.LONG,
            score=100.0,
            entry_reason="legacy core",
            invalidation="legacy core trend exit",
        )
        strategy._core_add_standard_signal = lambda: None
        strategy._bear_core_probe_standard_signal = lambda: None
        strategy._bear_core_confirm_add_standard_signal = lambda: None
        strategy._bear_core_acceleration_add_standard_signal = lambda: None
        strategy._tactical_signal = lambda: None
        strategy._ENFORCE_PLATFORM_RISK_ENGINE = True
        strategy._platform_risk_engine = RiskEngine()
        orders = []
        strategy._enter_long = lambda size, tag="", sl=None, tp=None: orders.append(
            ("long", size, tag, sl, tp)
        )
        strategy._enter_short = lambda size, tag="", sl=None, tp=None: orders.append(
            ("short", size, tag, sl, tp)
        )

        strategy.next()

        self.assertEqual(orders, [])
        self.assertFalse(strategy._core_active)
        self.assertEqual(strategy._core_size, 0.0)
        self.assertTrue(strategy._last_platform_risk_decision.allowed)
        self.assertFalse(strategy._last_platform_risk_engine_decision.allowed)
        self.assertEqual(strategy._last_platform_risk_engine_decision.reason, "missing_stop")

    def test_dual_layer_core_exit_records_platform_close_order_audit(self):
        from quant_btc.config import RiskConfig
        from quant_btc.strategy import DualLayerStrategy
        from quant_platform.portfolio import OrderAction, OrderStatus
        from quant_platform.signals import Direction

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        class FakePosition:
            size = 0.35

            def __init__(self):
                self.closed_portions = []

            def close(self, portion=None):
                self.closed_portions.append(portion)

        position = FakePosition()
        strategy = object.__new__(DualLayerStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "_regime": [1],
                "_d_ema_dir": [1],
                "_w_ema_dir": [1],
                "_w_ema_169": [95.0],
                "_atr": [5.0],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = position
        strategy.equity = 50_000.0
        strategy.risk_cfg = RiskConfig()
        strategy.cooldown_bars = 0
        strategy._last_trade_bar = -10**9
        strategy._pause_until_bar = -1
        strategy._core_active = True
        strategy._core_size = 0.35
        strategy._core_fully_loaded = True
        strategy._tac_direction = 0
        strategy._tac_size = 0.0
        strategy._bear_core_active = False
        strategy._bear_core_stage = 0
        strategy._bear_core_size = 0.0
        strategy._bear_core_entry_price = 0.0
        strategy._bear_group_id = 0
        strategy._bear_group_exposure = 0.0
        strategy._bear_group_entry_bar = -10**9
        strategy._bear_group_peak_r = 0.0
        strategy._bear_group_max_exposure = 0.50
        strategy._days_above_dema = 0
        strategy._flash_crash_active = False
        strategy._flash_crash_bar = -10**9
        strategy._platform_pipeline_results = []
        strategy._last_platform_pipeline_result = None
        strategy._update_circuit_breaker = lambda: None
        strategy._core_exit_signal = lambda: True
        strategy._core_trail_stop_hit = lambda: False

        strategy.next()

        self.assertEqual(position.closed_portions, [1.0])
        result = strategy._last_platform_pipeline_result
        order = result.portfolio_plan.orders[0]
        self.assertEqual(order.action, OrderAction.CLOSE)
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.reason, "core_exit")
        self.assertEqual(order.symbol, "BTC/USDT")
        self.assertEqual(order.layer, "core")
        self.assertEqual(order.direction, Direction.LONG)
        self.assertEqual(order.quantity, 175.0)
        self.assertEqual(order.decision.signal.module, "core_long")
        self.assertEqual(strategy._platform_pipeline_results, [result])

    def test_dual_layer_tactical_exit_records_platform_close_order_audit(self):
        from quant_btc.config import RiskConfig
        from quant_btc.strategy import DualLayerStrategy
        from quant_platform.portfolio import OrderAction, OrderStatus
        from quant_platform.signals import Direction

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        class FakePosition:
            size = 0.50

            def __init__(self):
                self.closed_portions = []

            def close(self, portion=None):
                self.closed_portions.append(portion)

        position = FakePosition()
        strategy = object.__new__(DualLayerStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "_regime": [1],
                "_d_ema_dir": [1],
                "_w_ema_dir": [1],
                "_w_ema_169": [95.0],
                "_atr": [5.0],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = position
        strategy.equity = 50_000.0
        strategy.risk_cfg = RiskConfig()
        strategy.cooldown_bars = 12
        strategy._last_trade_bar = 0
        strategy._pause_until_bar = -1
        strategy._core_active = False
        strategy._core_size = 0.0
        strategy._core_fully_loaded = True
        strategy._tac_direction = 1
        strategy._tac_size = 0.20
        strategy._tac_module = "breakout_retest"
        strategy._bear_core_active = False
        strategy._bear_core_stage = 0
        strategy._bear_core_size = 0.0
        strategy._bear_core_entry_price = 0.0
        strategy._bear_group_id = 0
        strategy._bear_group_exposure = 0.0
        strategy._bear_group_entry_bar = -10**9
        strategy._bear_group_peak_r = 0.0
        strategy._bear_group_max_exposure = 0.50
        strategy._days_above_dema = 0
        strategy._flash_crash_active = False
        strategy._flash_crash_bar = -10**9
        strategy._platform_pipeline_results = []
        strategy._last_platform_pipeline_result = None
        strategy._update_circuit_breaker = lambda: None
        strategy._core_exit_signal = lambda: False
        strategy._core_trail_stop_hit = lambda: False
        strategy._check_tactical_exit = lambda: True

        strategy.next()

        self.assertEqual(position.closed_portions, [0.4])
        self.assertEqual(strategy._tac_direction, 0)
        self.assertEqual(strategy._tac_size, 0.0)
        result = strategy._last_platform_pipeline_result
        order = result.portfolio_plan.orders[0]
        self.assertEqual(order.action, OrderAction.CLOSE)
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.reason, "tactical_exit")
        self.assertEqual(order.symbol, "BTC/USDT")
        self.assertEqual(order.layer, "tactical")
        self.assertEqual(order.direction, Direction.LONG)
        self.assertEqual(order.quantity, 100.0)
        self.assertEqual(order.decision.signal.module, "breakout_retest")
        self.assertEqual(strategy._platform_pipeline_results, [result])

    def test_dual_layer_bear_core_trend_exit_records_platform_close_order_audit(self):
        from quant_btc.config import RiskConfig
        from quant_btc.strategy import DualLayerStrategy
        from quant_platform.portfolio import OrderAction, OrderStatus
        from quant_platform.signals import Direction

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        class FakePosition:
            size = -0.30

            def __init__(self):
                self.closed_portions = []

            def close(self, portion=None):
                self.closed_portions.append(portion)

        position = FakePosition()
        strategy = object.__new__(DualLayerStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "_regime": [2],
                "_d_ema_dir": [-1],
                "_w_ema_dir": [-1],
                "_w_ema_169": [105.0],
                "_atr": [5.0],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = position
        strategy.equity = 50_000.0
        strategy.risk_cfg = RiskConfig()
        strategy.cooldown_bars = 0
        strategy._last_trade_bar = -10**9
        strategy._pause_until_bar = -1
        strategy._core_active = False
        strategy._core_size = 0.0
        strategy._core_fully_loaded = True
        strategy._tac_direction = 0
        strategy._tac_size = 0.0
        strategy._bear_core_active = True
        strategy._bear_core_stage = 1
        strategy._bear_core_size = 0.30
        strategy._bear_core_entry_price = 100.0
        strategy._bear_core_entry_bar = 0
        strategy._bear_probe_peak_r = 0.0
        strategy._short_giveback_peak_r = -999.0
        strategy._bear_group_id = 1
        strategy._bear_group_exposure = 0.30
        strategy._bear_group_entry_bar = 0
        strategy._bear_group_peak_r = 0.0
        strategy._bear_group_max_exposure = 0.50
        strategy._days_above_dema = 0
        strategy._waterfall_triggered = False
        strategy._waterfall_lock_r = 1.0
        strategy._flash_crash_active = False
        strategy._flash_crash_bar = -10**9
        strategy._platform_pipeline_results = []
        strategy._last_platform_pipeline_result = None
        closed_pnls = []
        strategy._update_circuit_breaker = lambda: None
        strategy._on_trade_closed = lambda pnl: closed_pnls.append(pnl)
        strategy._core_exit_signal = lambda: False
        strategy._core_trail_stop_hit = lambda: False
        strategy._check_short_giveback_guard = lambda entry, stop: False
        strategy._bear_core_exit_signal = lambda: True

        strategy.next()

        self.assertEqual(position.closed_portions, [1.0])
        self.assertEqual(closed_pnls, [0.0])
        result = strategy._last_platform_pipeline_result
        order = result.portfolio_plan.orders[0]
        self.assertEqual(order.action, OrderAction.CLOSE)
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.reason, "bear_core_trend_exit")
        self.assertEqual(order.symbol, "BTC/USDT")
        self.assertEqual(order.layer, "bear_core")
        self.assertEqual(order.direction, Direction.SHORT)
        self.assertEqual(order.quantity, 150.0)
        self.assertEqual(order.decision.signal.module, "bear_core_probe")
        self.assertEqual(strategy._platform_pipeline_results, [result])

    def test_dual_layer_bear_core_v_reversal_exit_records_platform_close_order_audit(self):
        from quant_btc.config import RiskConfig
        from quant_btc.strategy import DualLayerStrategy
        from quant_platform.portfolio import OrderAction, OrderStatus
        from quant_platform.signals import Direction

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        class FakePosition:
            size = -0.25

            def __init__(self):
                self.closed_portions = []

            def close(self, portion=None):
                self.closed_portions.append(portion)

        position = FakePosition()
        strategy = object.__new__(DualLayerStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0, 100.0],
                "High": [101.0, 101.0],
                "Low": [99.0, 99.0],
                "_regime": [1, 1],
                "_d_ema_dir": [1, 1],
                "_w_ema_dir": [-1, -1],
                "_w_ema_169": [105.0, 105.0],
                "_atr": [5.0, 5.0],
            },
            index=pd.date_range("2026-06-03", periods=2, freq="4h", tz="UTC"),
        ))
        strategy.position = position
        strategy.equity = 40_000.0
        strategy.risk_cfg = RiskConfig()
        strategy.cooldown_bars = 0
        strategy._last_trade_bar = -10**9
        strategy._pause_until_bar = -1
        strategy._core_active = False
        strategy._core_size = 0.0
        strategy._core_fully_loaded = True
        strategy._tac_direction = 0
        strategy._tac_size = 0.0
        strategy._bear_core_active = True
        strategy._bear_core_stage = 2
        strategy._bear_core_size = 0.25
        strategy._bear_core_entry_price = 100.0
        strategy._bear_core_entry_bar = 0
        strategy._bear_probe_peak_r = 2.2
        strategy._short_giveback_peak_r = -999.0
        strategy._bear_group_id = 1
        strategy._bear_group_exposure = 0.25
        strategy._bear_group_entry_bar = 0
        strategy._bear_group_peak_r = 0.0
        strategy._bear_group_max_exposure = 0.50
        strategy._days_above_dema = 3
        strategy._waterfall_triggered = True
        strategy._waterfall_lock_r = 1.0
        strategy._flash_crash_active = False
        strategy._flash_crash_bar = -10**9
        strategy._platform_pipeline_results = []
        strategy._last_platform_pipeline_result = None
        closed_pnls = []
        strategy._update_circuit_breaker = lambda: None
        strategy._on_trade_closed = lambda pnl: closed_pnls.append(pnl)
        strategy._core_exit_signal = lambda: False
        strategy._core_trail_stop_hit = lambda: False
        strategy._bear_core_exit_signal = lambda: False

        strategy.next()

        self.assertEqual(position.closed_portions, [1.0])
        self.assertEqual(closed_pnls, [0.0])
        self.assertFalse(strategy._bear_core_active)
        self.assertEqual(strategy._bear_core_size, 0.0)
        self.assertFalse(strategy._waterfall_triggered)
        self.assertEqual(strategy._days_above_dema, 0)
        result = strategy._last_platform_pipeline_result
        order = result.portfolio_plan.orders[0]
        self.assertEqual(order.action, OrderAction.CLOSE)
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.reason, "bear_core_v_reversal_exit")
        self.assertEqual(order.symbol, "BTC/USDT")
        self.assertEqual(order.layer, "bear_core")
        self.assertEqual(order.direction, Direction.SHORT)
        self.assertEqual(order.quantity, 100.0)
        self.assertEqual(order.decision.signal.module, "bear_core_confirm")
        self.assertEqual(strategy._platform_pipeline_results, [result])

    def test_dual_layer_bear_core_giveback_exit_records_platform_close_order_audit(self):
        from quant_btc.config import RiskConfig
        from quant_btc.strategy import DualLayerStrategy
        from quant_platform.portfolio import OrderAction, OrderStatus
        from quant_platform.signals import Direction

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        class FakePosition:
            size = -0.20

            def __init__(self):
                self.closed_portions = []

            def close(self, portion=None):
                self.closed_portions.append(portion)

        position = FakePosition()
        strategy = object.__new__(DualLayerStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "_regime": [2],
                "_d_ema_dir": [-1],
                "_w_ema_dir": [-1],
                "_w_ema_169": [105.0],
                "_atr": [5.0],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = position
        strategy.equity = 60_000.0
        strategy.risk_cfg = RiskConfig()
        strategy.cooldown_bars = 0
        strategy._last_trade_bar = -10**9
        strategy._pause_until_bar = -1
        strategy._core_active = False
        strategy._core_size = 0.0
        strategy._core_fully_loaded = True
        strategy._tac_direction = 0
        strategy._tac_size = 0.0
        strategy._bear_core_active = True
        strategy._bear_core_stage = 3
        strategy._bear_core_size = 0.20
        strategy._bear_core_entry_price = 100.0
        strategy._bear_core_entry_bar = 0
        strategy._bear_probe_peak_r = 0.0
        strategy._short_giveback_peak_r = 3.0
        strategy._bear_group_id = 1
        strategy._bear_group_exposure = 0.20
        strategy._bear_group_entry_bar = 0
        strategy._bear_group_peak_r = 0.0
        strategy._bear_group_max_exposure = 0.50
        strategy._days_above_dema = 2
        strategy._waterfall_triggered = False
        strategy._waterfall_lock_r = 1.0
        strategy._flash_crash_active = False
        strategy._flash_crash_bar = -10**9
        strategy._platform_pipeline_results = []
        strategy._last_platform_pipeline_result = None
        closed_pnls = []
        strategy._update_circuit_breaker = lambda: None
        strategy._on_trade_closed = lambda pnl: closed_pnls.append(pnl)
        strategy._core_exit_signal = lambda: False
        strategy._core_trail_stop_hit = lambda: False
        strategy._check_short_giveback_guard = lambda entry, stop: True
        strategy._bear_core_exit_signal = lambda: False

        strategy.next()

        self.assertEqual(position.closed_portions, [1.0])
        self.assertEqual(closed_pnls, [0.0])
        self.assertFalse(strategy._bear_core_active)
        self.assertEqual(strategy._bear_core_size, 0.0)
        result = strategy._last_platform_pipeline_result
        order = result.portfolio_plan.orders[0]
        self.assertEqual(order.action, OrderAction.CLOSE)
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.reason, "bear_core_giveback_exit")
        self.assertEqual(order.symbol, "BTC/USDT")
        self.assertEqual(order.layer, "bear_core")
        self.assertEqual(order.direction, Direction.SHORT)
        self.assertEqual(order.quantity, 120.0)
        self.assertEqual(order.decision.signal.module, "bear_core_acceleration")
        self.assertEqual(strategy._platform_pipeline_results, [result])

    def test_dual_layer_bear_core_waterfall_runner_exit_records_platform_close_order_audit(self):
        from quant_btc.config import RiskConfig
        from quant_btc.strategy import DualLayerStrategy
        from quant_platform.portfolio import OrderAction, OrderStatus
        from quant_platform.signals import Direction

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        class FakePosition:
            size = -0.18

            def __init__(self):
                self.closed_portions = []

            def close(self, portion=None):
                self.closed_portions.append(portion)

        position = FakePosition()
        strategy = object.__new__(DualLayerStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [96.0],
                "High": [98.0],
                "Low": [95.0],
                "_regime": [2],
                "_d_ema_dir": [-1],
                "_w_ema_dir": [-1],
                "_w_ema_169": [105.0],
                "_atr": [5.0],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = position
        strategy.equity = 48_000.0
        strategy.risk_cfg = RiskConfig()
        strategy.cooldown_bars = 0
        strategy._last_trade_bar = -10**9
        strategy._pause_until_bar = -1
        strategy._core_active = False
        strategy._core_size = 0.0
        strategy._core_fully_loaded = True
        strategy._tac_direction = -1
        strategy._tac_size = 0.07
        strategy._bear_core_active = True
        strategy._bear_core_stage = 99
        strategy._bear_core_size = 0.18
        strategy._bear_core_entry_price = 100.0
        strategy._bear_core_entry_bar = 0
        strategy._bear_probe_peak_r = 0.0
        strategy._short_giveback_peak_r = -999.0
        strategy._bear_group_id = 1
        strategy._bear_group_exposure = 0.18
        strategy._bear_group_entry_bar = 0
        strategy._bear_group_peak_r = 0.0
        strategy._bear_group_max_exposure = 0.50
        strategy._days_above_dema = 4
        strategy._waterfall_triggered = True
        strategy._waterfall_lock_r = 1.0
        strategy._flash_crash_active = False
        strategy._flash_crash_bar = -10**9
        strategy._platform_pipeline_results = []
        strategy._last_platform_pipeline_result = None
        closed_pnls = []
        strategy._update_circuit_breaker = lambda: None
        strategy._on_trade_closed = lambda pnl: closed_pnls.append(pnl)
        strategy._core_exit_signal = lambda: False
        strategy._core_trail_stop_hit = lambda: False
        strategy._bear_core_sl = lambda: 112.0
        strategy._check_short_giveback_guard = lambda entry, stop: False
        strategy._bear_core_exit_signal = lambda: False

        strategy.next()

        self.assertEqual(position.closed_portions, [1.0])
        self.assertEqual(closed_pnls, [0.0])
        self.assertFalse(strategy._bear_core_active)
        self.assertEqual(strategy._bear_core_size, 0.0)
        self.assertEqual(strategy._tac_size, 0.0)
        self.assertFalse(strategy._waterfall_triggered)
        self.assertEqual(strategy._days_above_dema, 0)
        result = strategy._last_platform_pipeline_result
        order = result.portfolio_plan.orders[0]
        self.assertEqual(order.action, OrderAction.CLOSE)
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.reason, "bear_core_waterfall_runner_exit")
        self.assertEqual(order.symbol, "BTC/USDT")
        self.assertEqual(order.layer, "bear_core")
        self.assertEqual(order.direction, Direction.SHORT)
        self.assertEqual(order.quantity, 90.0)
        self.assertEqual(order.decision.signal.module, "bear_core_acceleration")
        self.assertEqual(strategy._platform_pipeline_results, [result])

    def test_dual_layer_bear_core_waterfall_guard_records_platform_partial_close_audit(self):
        from quant_btc.strategy import DualLayerStrategy
        from quant_platform.portfolio import OrderAction, OrderStatus
        from quant_platform.signals import Direction

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        class FakePosition:
            is_long = False
            is_short = True
            size = -0.30

            def __init__(self):
                self.closed_portions = []

            def __bool__(self):
                return True

            def close(self, portion=None):
                self.closed_portions.append(portion)

        position = FakePosition()
        strategy = object.__new__(DualLayerStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [96.0],
                "High": [100.0],
                "Low": [60.0],
                "_atr": [10.0],
                "_d_ema_dir": [1],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = position
        strategy.equity = 100_000.0
        strategy._bear_core_entry_price = 100.0
        strategy._bear_core_entry_bar = -5
        strategy._bear_core_stage = 1
        strategy._bear_core_size = 0.30
        strategy._platform_pipeline_results = []
        strategy._last_platform_pipeline_result = None

        self.assertTrue(strategy._check_waterfall_profit_guard())

        self.assertEqual(position.closed_portions, [0.70])
        self.assertEqual(strategy._waterfall_lock_r, 1.5)
        self.assertEqual(strategy._bear_core_stage, 99)
        result = strategy._last_platform_pipeline_result
        order = result.portfolio_plan.orders[0]
        self.assertEqual(order.action, OrderAction.CLOSE)
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.reason, "bear_core_waterfall_guard")
        self.assertEqual(order.symbol, "BTC/USDT")
        self.assertEqual(order.layer, "bear_core")
        self.assertEqual(order.direction, Direction.SHORT)
        self.assertEqual(order.quantity, 218.75)
        self.assertEqual(order.existing_position.quantity, 312.5)
        self.assertEqual(order.decision.signal.module, "bear_core_probe")
        self.assertEqual(strategy._platform_pipeline_results, [result])

    def test_dual_layer_core_add_executes_platform_order_plan_prices_when_available(self):
        from types import SimpleNamespace

        from quant_btc.config import RiskConfig
        from quant_btc.strategy import DualLayerStrategy
        from quant_platform.signals import Direction, Signal

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        class FakePosition:
            size = 0.20

        strategy = object.__new__(DualLayerStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "_regime": [1],
                "_d_ema_dir": [1],
                "_w_ema_dir": [1],
                "_w_ema_169": [95.0],
                "_atr": [5.0],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = FakePosition()
        strategy.equity = 50_000.0
        strategy.risk_cfg = RiskConfig()
        strategy.cooldown_bars = 0
        strategy._last_trade_bar = -10**9
        strategy._pause_until_bar = -1
        strategy._core_active = True
        strategy._core_entry_price = 90.0
        strategy._core_highest_close = 100.0
        strategy._core_size = 0.20
        strategy._core_fully_loaded = False
        strategy._tac_direction = 0
        strategy._tac_size = 0.0
        strategy._bear_core_active = False
        strategy._bear_core_stage = 0
        strategy._bear_core_size = 0.0
        strategy._bear_core_entry_price = 0.0
        strategy._bear_group_id = 0
        strategy._bear_group_exposure = 0.0
        strategy._bear_group_entry_bar = -10**9
        strategy._bear_group_peak_r = 0.0
        strategy._bear_group_max_exposure = 0.50
        strategy._days_above_dema = 0
        strategy._flash_crash_active = False
        strategy._flash_crash_bar = -10**9
        strategy._update_circuit_breaker = lambda: None
        strategy._core_exit_signal = lambda: False
        strategy._core_trail_stop_hit = lambda: False
        strategy._core_entry_standard_signal = lambda: None
        strategy._core_add_standard_signal = lambda: Signal(
            module="core_add",
            symbol="BTC/USDT",
            direction=Direction.LONG,
            score=90.0,
            entry_reason="legacy core add",
            invalidation="legacy core trend exit",
        )
        strategy._bear_core_probe_standard_signal = lambda: None
        strategy._bear_core_confirm_add_standard_signal = lambda: None
        strategy._bear_core_acceleration_add_standard_signal = lambda: None
        strategy._tactical_signal = lambda: None

        def record_platform_order(**kwargs):
            strategy._last_platform_entry_order = SimpleNamespace(
                direction=Direction.LONG,
                stop_price=91.0,
                target_price=119.0,
            )

        strategy._record_legacy_entry_risk_decision = record_platform_order
        orders = []
        strategy._enter_long = lambda size, tag="", sl=None, tp=None: orders.append(
            ("long", size, tag, sl, tp)
        )
        strategy._enter_short = lambda size, tag="", sl=None, tp=None: orders.append(
            ("short", size, tag, sl, tp)
        )

        strategy.next()

        self.assertEqual(orders, [("long", 0.525, "core_add_long", 91.0, 119.0)])
        self.assertTrue(strategy._core_active)
        self.assertEqual(strategy._core_size, 0.40)
        self.assertTrue(strategy._core_fully_loaded)

    def test_dual_layer_core_add_can_enforce_platform_risk_engine_block(self):
        from quant_btc.config import RiskConfig
        from quant_btc.strategy import DualLayerStrategy
        from quant_platform.risk import RiskEngine
        from quant_platform.signals import Direction, Signal

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        class FakePosition:
            size = 0.20

        strategy = object.__new__(DualLayerStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "_regime": [1],
                "_d_ema_dir": [1],
                "_w_ema_dir": [1],
                "_w_ema_169": [95.0],
                "_atr": [5.0],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = FakePosition()
        strategy.equity = 50_000.0
        strategy.risk_cfg = RiskConfig()
        strategy.cooldown_bars = 0
        strategy._last_trade_bar = -10**9
        strategy._pause_until_bar = -1
        strategy._core_active = True
        strategy._core_entry_price = 90.0
        strategy._core_highest_close = 100.0
        strategy._core_size = 0.20
        strategy._core_fully_loaded = False
        strategy._tac_direction = 0
        strategy._tac_size = 0.0
        strategy._bear_core_active = False
        strategy._bear_core_stage = 0
        strategy._bear_core_size = 0.0
        strategy._bear_core_entry_price = 0.0
        strategy._bear_group_id = 0
        strategy._bear_group_exposure = 0.0
        strategy._bear_group_entry_bar = -10**9
        strategy._bear_group_peak_r = 0.0
        strategy._bear_group_max_exposure = 0.50
        strategy._days_above_dema = 0
        strategy._flash_crash_active = False
        strategy._flash_crash_bar = -10**9
        strategy._update_circuit_breaker = lambda: None
        strategy._core_exit_signal = lambda: False
        strategy._core_trail_stop_hit = lambda: False
        strategy._core_entry_standard_signal = lambda: None
        strategy._core_add_standard_signal = lambda: Signal(
            module="core_add",
            symbol="BTC/USDT",
            direction=Direction.LONG,
            score=90.0,
            entry_reason="legacy core add",
            invalidation="legacy core trend exit",
        )
        strategy._bear_core_probe_standard_signal = lambda: None
        strategy._bear_core_confirm_add_standard_signal = lambda: None
        strategy._bear_core_acceleration_add_standard_signal = lambda: None
        strategy._tactical_signal = lambda: None
        strategy._ENFORCE_PLATFORM_RISK_ENGINE = True
        strategy._platform_risk_engine = RiskEngine()
        orders = []
        strategy._enter_long = lambda size, tag="", sl=None, tp=None: orders.append(
            ("long", size, tag, sl, tp)
        )
        strategy._enter_short = lambda size, tag="", sl=None, tp=None: orders.append(
            ("short", size, tag, sl, tp)
        )

        strategy.next()

        self.assertEqual(orders, [])
        self.assertTrue(strategy._core_active)
        self.assertEqual(strategy._core_size, 0.20)
        self.assertFalse(strategy._core_fully_loaded)
        self.assertTrue(strategy._last_platform_risk_decision.allowed)
        self.assertFalse(strategy._last_platform_risk_engine_decision.allowed)
        self.assertEqual(strategy._last_platform_risk_engine_decision.reason, "missing_stop")

    def test_dual_layer_bear_core_probe_executes_platform_order_plan_prices_when_available(self):
        from types import SimpleNamespace

        from quant_btc.config import RiskConfig
        from quant_btc.strategy import DualLayerStrategy
        from quant_platform.signals import Direction, Signal

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        strategy = object.__new__(DualLayerStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "_regime": [2],
                "_d_ema_dir": [-1],
                "_w_ema_dir": [-1],
                "_w_ema_169": [105.0],
                "_atr": [5.0],
                "_bull_guard": [False],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = None
        strategy.equity = 50_000.0
        strategy.risk_cfg = RiskConfig()
        strategy.cooldown_bars = 0
        strategy._last_trade_bar = -10**9
        strategy._pause_until_bar = -1
        strategy._core_active = False
        strategy._core_size = 0.0
        strategy._core_fully_loaded = True
        strategy._tac_direction = 0
        strategy._tac_size = 0.0
        strategy._bear_core_active = False
        strategy._bear_core_stage = 0
        strategy._bear_core_size = 0.0
        strategy._bear_core_entry_price = 0.0
        strategy._bear_group_id = 0
        strategy._bear_group_exposure = 0.0
        strategy._bear_group_entry_bar = -10**9
        strategy._bear_group_peak_r = 0.0
        strategy._bear_group_max_exposure = 0.50
        strategy._days_above_dema = 0
        strategy._flash_crash_active = False
        strategy._flash_crash_bar = -10**9
        strategy._update_circuit_breaker = lambda: None
        strategy._core_entry_standard_signal = lambda: None
        strategy._core_add_standard_signal = lambda: None
        strategy._bear_core_probe_standard_signal = lambda: Signal(
            module="bear_core_probe",
            symbol="BTC/USDT",
            direction=Direction.SHORT,
            score=80.0,
            entry_reason="legacy bear probe",
            invalidation="legacy bear-core exit",
        )
        strategy._bear_core_confirm_add_standard_signal = lambda: None
        strategy._bear_core_acceleration_add_standard_signal = lambda: None
        strategy._tactical_signal = lambda: None

        def record_platform_order(**kwargs):
            strategy._last_platform_entry_order = SimpleNamespace(
                direction=Direction.SHORT,
                stop_price=112.0,
                target_price=84.0,
            )

        strategy._record_legacy_entry_risk_decision = record_platform_order
        orders = []
        strategy._enter_long = lambda size, tag="", sl=None, tp=None: orders.append(
            ("long", size, tag, sl, tp)
        )
        strategy._enter_short = lambda size, tag="", sl=None, tp=None: orders.append(
            ("short", size, tag, sl, tp)
        )

        strategy.next()

        self.assertEqual(len(orders), 1)
        side, size, tag, stop_price, target_price = orders[0]
        self.assertEqual(side, "short")
        self.assertAlmostEqual(size, 0.14)
        self.assertEqual(tag, "bear_core")
        self.assertEqual(stop_price, 112.0)
        self.assertEqual(target_price, 84.0)
        self.assertTrue(strategy._bear_core_active)
        self.assertEqual(strategy._bear_core_stage, 1)
        self.assertAlmostEqual(strategy._bear_core_size, 0.14)
        self.assertAlmostEqual(strategy._bear_group_exposure, 0.14)

    def test_dual_layer_bear_core_probe_can_enforce_platform_risk_engine_block(self):
        from quant_btc.config import RiskConfig
        from quant_btc.strategy import DualLayerStrategy
        from quant_platform.risk import RiskEngine, RiskLimits
        from quant_platform.signals import Direction, Signal

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        strategy = object.__new__(DualLayerStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "_regime": [2],
                "_d_ema_dir": [-1],
                "_w_ema_dir": [-1],
                "_w_ema_169": [105.0],
                "_atr": [5.0],
                "_bull_guard": [False],
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        ))
        strategy.position = None
        strategy.equity = 50_000.0
        strategy.risk_cfg = RiskConfig()
        strategy.cooldown_bars = 0
        strategy._last_trade_bar = -10**9
        strategy._pause_until_bar = -1
        strategy._core_active = False
        strategy._core_size = 0.0
        strategy._core_fully_loaded = True
        strategy._tac_direction = 0
        strategy._tac_size = 0.0
        strategy._bear_core_active = False
        strategy._bear_core_stage = 0
        strategy._bear_core_size = 0.0
        strategy._bear_core_entry_price = 0.0
        strategy._bear_group_id = 0
        strategy._bear_group_exposure = 0.0
        strategy._bear_group_entry_bar = -10**9
        strategy._bear_group_peak_r = 0.0
        strategy._bear_group_max_exposure = 0.50
        strategy._days_above_dema = 0
        strategy._flash_crash_active = False
        strategy._flash_crash_bar = -10**9
        strategy._update_circuit_breaker = lambda: None
        strategy._core_entry_standard_signal = lambda: None
        strategy._core_add_standard_signal = lambda: None
        strategy._bear_core_probe_standard_signal = lambda: Signal(
            module="bear_core_probe",
            symbol="BTC/USDT",
            direction=Direction.SHORT,
            score=80.0,
            entry_reason="legacy bear probe",
            invalidation="legacy bear-core exit",
        )
        strategy._bear_core_confirm_add_standard_signal = lambda: None
        strategy._bear_core_acceleration_add_standard_signal = lambda: None
        strategy._tactical_signal = lambda: None
        strategy._ENFORCE_PLATFORM_RISK_ENGINE = True
        strategy._platform_risk_engine = RiskEngine(RiskLimits(
            risk_per_trade=0.02,
            portfolio_risk_budget=0.001,
        ))
        orders = []
        strategy._enter_long = lambda size, tag="", sl=None, tp=None: orders.append(
            ("long", size, tag, sl, tp)
        )
        strategy._enter_short = lambda size, tag="", sl=None, tp=None: orders.append(
            ("short", size, tag, sl, tp)
        )

        strategy.next()

        self.assertEqual(orders, [])
        self.assertFalse(strategy._bear_core_active)
        self.assertEqual(strategy._bear_core_stage, 0)
        self.assertEqual(strategy._bear_core_size, 0.0)
        self.assertEqual(strategy._bear_group_exposure, 0.0)
        self.assertTrue(strategy._last_platform_risk_decision.allowed)
        self.assertFalse(strategy._last_platform_risk_engine_decision.allowed)
        self.assertEqual(
            strategy._last_platform_risk_engine_decision.reason,
            "portfolio_risk_budget_exhausted",
        )

    def test_dual_layer_bear_core_confirm_add_executes_platform_order_plan_prices_when_available(self):
        from types import SimpleNamespace

        from quant_btc.config import RiskConfig
        from quant_btc.strategy import DualLayerStrategy
        from quant_platform.signals import Direction, Signal

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        class FakePosition:
            size = -0.14

        strategy = object.__new__(DualLayerStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0, 100.0],
                "High": [101.0, 101.0],
                "Low": [99.0, 99.0],
                "_regime": [2, 2],
                "_d_ema_dir": [-1, -1],
                "_w_ema_dir": [-1, -1],
                "_w_ema_169": [110.0, 110.0],
                "_atr": [5.0, 5.0],
                "_adx_signal": [0.0, 0.0],
                "_plus_di": [0.0, 0.0],
                "_minus_di": [0.0, 0.0],
            },
            index=pd.date_range("2026-06-03", periods=2, freq="4h", tz="UTC"),
        ))
        strategy.position = FakePosition()
        strategy.equity = 50_000.0
        strategy.risk_cfg = RiskConfig()
        strategy.cooldown_bars = 0
        strategy._last_trade_bar = 0
        strategy._pause_until_bar = -1
        strategy._core_active = False
        strategy._core_size = 0.0
        strategy._core_fully_loaded = True
        strategy._tac_direction = 0
        strategy._tac_size = 0.0
        strategy._bear_core_active = True
        strategy._bear_core_stage = 1
        strategy._bear_core_entry_price = 100.0
        strategy._bear_core_entry_bar = 0
        strategy._bear_probe_peak_r = 1.2
        strategy._bear_core_size = 0.14
        strategy._bear_group_id = 1
        strategy._bear_group_exposure = 0.14
        strategy._bear_group_entry_bar = 0
        strategy._bear_group_peak_r = 0.0
        strategy._bear_group_max_exposure = 0.50
        strategy._days_above_dema = 0
        strategy._flash_crash_active = False
        strategy._flash_crash_bar = -10**9
        strategy._waterfall_triggered = False
        strategy._update_circuit_breaker = lambda: None
        strategy._core_entry_standard_signal = lambda: None
        strategy._core_add_standard_signal = lambda: None
        strategy._bear_core_exit_signal = lambda: False
        strategy._check_short_giveback_guard = lambda entry, stop: False
        strategy._check_waterfall_profit_guard = lambda: False
        strategy._bear_core_probe_standard_signal = lambda: None
        strategy._bear_core_confirm_add_standard_signal = lambda: Signal(
            module="bear_core_confirm",
            symbol="BTC/USDT",
            direction=Direction.SHORT,
            score=80.0,
            entry_reason="legacy bear confirm",
            invalidation="legacy bear-core exit",
        )
        strategy._bear_core_acceleration_add_standard_signal = lambda: None
        strategy._tactical_signal = lambda: None

        def record_platform_order(**kwargs):
            strategy._last_platform_entry_order = SimpleNamespace(
                direction=Direction.SHORT,
                stop_price=112.0,
                target_price=84.0,
            )

        strategy._record_legacy_entry_risk_decision = record_platform_order
        orders = []
        strategy._enter_long = lambda size, tag="", sl=None, tp=None: orders.append(
            ("long", size, tag, sl, tp)
        )
        strategy._enter_short = lambda size, tag="", sl=None, tp=None: orders.append(
            ("short", size, tag, sl, tp)
        )

        strategy.next()

        self.assertEqual(len(orders), 1)
        side, size, tag, stop_price, target_price = orders[0]
        self.assertEqual(side, "short")
        self.assertAlmostEqual(size, 0.12)
        self.assertEqual(tag, "bear_core")
        self.assertEqual(stop_price, 112.0)
        self.assertEqual(target_price, 84.0)
        self.assertTrue(strategy._bear_core_active)
        self.assertEqual(strategy._bear_core_stage, 2)
        self.assertAlmostEqual(strategy._bear_core_size, 0.26)
        self.assertAlmostEqual(strategy._bear_group_exposure, 0.26)
        self.assertEqual(strategy._last_trade_bar, 1)

    def test_dual_layer_bear_core_confirm_add_can_enforce_platform_risk_engine_block(self):
        from quant_btc.config import RiskConfig
        from quant_btc.strategy import DualLayerStrategy
        from quant_platform.risk import RiskEngine, RiskLimits
        from quant_platform.signals import Direction, Signal

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        class FakePosition:
            size = -0.14

        strategy = object.__new__(DualLayerStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0, 100.0],
                "High": [101.0, 101.0],
                "Low": [99.0, 99.0],
                "_regime": [2, 2],
                "_d_ema_dir": [-1, -1],
                "_w_ema_dir": [-1, -1],
                "_w_ema_169": [110.0, 110.0],
                "_atr": [5.0, 5.0],
                "_adx_signal": [0.0, 0.0],
                "_plus_di": [0.0, 0.0],
                "_minus_di": [0.0, 0.0],
            },
            index=pd.date_range("2026-06-03", periods=2, freq="4h", tz="UTC"),
        ))
        strategy.position = FakePosition()
        strategy.equity = 50_000.0
        strategy.risk_cfg = RiskConfig()
        strategy.cooldown_bars = 0
        strategy._last_trade_bar = 0
        strategy._pause_until_bar = -1
        strategy._core_active = False
        strategy._core_size = 0.0
        strategy._core_fully_loaded = True
        strategy._tac_direction = 0
        strategy._tac_size = 0.0
        strategy._bear_core_active = True
        strategy._bear_core_stage = 1
        strategy._bear_core_entry_price = 100.0
        strategy._bear_core_entry_bar = 0
        strategy._bear_probe_peak_r = 1.2
        strategy._bear_core_size = 0.14
        strategy._bear_group_id = 1
        strategy._bear_group_exposure = 0.14
        strategy._bear_group_entry_bar = 0
        strategy._bear_group_peak_r = 0.0
        strategy._bear_group_max_exposure = 0.50
        strategy._days_above_dema = 0
        strategy._flash_crash_active = False
        strategy._flash_crash_bar = -10**9
        strategy._waterfall_triggered = False
        strategy._update_circuit_breaker = lambda: None
        strategy._core_entry_standard_signal = lambda: None
        strategy._core_add_standard_signal = lambda: None
        strategy._bear_core_exit_signal = lambda: False
        strategy._check_short_giveback_guard = lambda entry, stop: False
        strategy._check_waterfall_profit_guard = lambda: False
        strategy._bear_core_probe_standard_signal = lambda: None
        strategy._bear_core_confirm_add_standard_signal = lambda: Signal(
            module="bear_core_confirm",
            symbol="BTC/USDT",
            direction=Direction.SHORT,
            score=80.0,
            entry_reason="legacy bear confirm",
            invalidation="legacy bear-core exit",
        )
        strategy._bear_core_acceleration_add_standard_signal = lambda: None
        strategy._tactical_signal = lambda: None
        strategy._ENFORCE_PLATFORM_RISK_ENGINE = True
        strategy._platform_risk_engine = RiskEngine(RiskLimits(
            risk_per_trade=0.02,
            portfolio_risk_budget=0.001,
        ))
        orders = []
        strategy._enter_long = lambda size, tag="", sl=None, tp=None: orders.append(
            ("long", size, tag, sl, tp)
        )
        strategy._enter_short = lambda size, tag="", sl=None, tp=None: orders.append(
            ("short", size, tag, sl, tp)
        )

        strategy.next()

        self.assertEqual(orders, [])
        self.assertTrue(strategy._bear_core_active)
        self.assertEqual(strategy._bear_core_stage, 1)
        self.assertEqual(strategy._bear_core_size, 0.14)
        self.assertEqual(strategy._bear_group_exposure, 0.14)
        self.assertEqual(strategy._last_trade_bar, 0)
        self.assertTrue(strategy._last_platform_risk_decision.allowed)
        self.assertFalse(strategy._last_platform_risk_engine_decision.allowed)
        self.assertEqual(
            strategy._last_platform_risk_engine_decision.reason,
            "portfolio_risk_budget_exhausted",
        )

    def test_dual_layer_bear_core_acceleration_add_executes_platform_order_plan_prices_when_available(self):
        from types import SimpleNamespace

        from quant_btc.config import RiskConfig
        from quant_btc.strategy import DualLayerStrategy
        from quant_platform.signals import Direction, Signal

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        class FakePosition:
            size = -0.26

        strategy = object.__new__(DualLayerStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0, 100.0],
                "High": [101.0, 101.0],
                "Low": [99.0, 99.0],
                "_regime": [2, 2],
                "_d_ema_dir": [-1, -1],
                "_w_ema_dir": [-1, -1],
                "_w_ema_169": [110.0, 110.0],
                "_atr": [5.0, 5.0],
                "_adx_signal": [25.0, 25.0],
                "_plus_di": [10.0, 10.0],
                "_minus_di": [30.0, 30.0],
            },
            index=pd.date_range("2026-06-03", periods=2, freq="4h", tz="UTC"),
        ))
        strategy.position = FakePosition()
        strategy.equity = 50_000.0
        strategy.risk_cfg = RiskConfig()
        strategy.cooldown_bars = 0
        strategy._last_trade_bar = 0
        strategy._pause_until_bar = -1
        strategy._core_active = False
        strategy._core_size = 0.0
        strategy._core_fully_loaded = True
        strategy._tac_direction = 0
        strategy._tac_size = 0.0
        strategy._bear_core_active = True
        strategy._bear_core_stage = 2
        strategy._bear_core_entry_price = 100.0
        strategy._bear_core_entry_bar = 0
        strategy._bear_probe_peak_r = 1.2
        strategy._bear_core_size = 0.26
        strategy._bear_group_id = 1
        strategy._bear_group_exposure = 0.26
        strategy._bear_group_entry_bar = 0
        strategy._bear_group_peak_r = 0.0
        strategy._bear_group_max_exposure = 0.50
        strategy._days_above_dema = 0
        strategy._flash_crash_active = False
        strategy._flash_crash_bar = -10**9
        strategy._waterfall_triggered = False
        strategy._update_circuit_breaker = lambda: None
        strategy._core_entry_standard_signal = lambda: None
        strategy._core_add_standard_signal = lambda: None
        strategy._bear_core_exit_signal = lambda: False
        strategy._check_short_giveback_guard = lambda entry, stop: False
        strategy._check_waterfall_profit_guard = lambda: False
        strategy._bear_core_probe_standard_signal = lambda: None
        strategy._bear_core_confirm_add_standard_signal = lambda: None
        strategy._bear_core_acceleration_add_standard_signal = lambda: Signal(
            module="bear_core_acceleration",
            symbol="BTC/USDT",
            direction=Direction.SHORT,
            score=85.0,
            entry_reason="legacy bear acceleration",
            invalidation="legacy bear-core exit",
        )
        strategy._tactical_signal = lambda: None

        def record_platform_order(**kwargs):
            strategy._last_platform_entry_order = SimpleNamespace(
                direction=Direction.SHORT,
                stop_price=112.0,
                target_price=84.0,
            )

        strategy._record_legacy_entry_risk_decision = record_platform_order
        orders = []
        strategy._enter_long = lambda size, tag="", sl=None, tp=None: orders.append(
            ("long", size, tag, sl, tp)
        )
        strategy._enter_short = lambda size, tag="", sl=None, tp=None: orders.append(
            ("short", size, tag, sl, tp)
        )

        strategy.next()

        self.assertEqual(len(orders), 1)
        side, size, tag, stop_price, target_price = orders[0]
        self.assertEqual(side, "short")
        self.assertAlmostEqual(size, 0.14)
        self.assertEqual(tag, "bear_core")
        self.assertEqual(stop_price, 112.0)
        self.assertEqual(target_price, 84.0)
        self.assertTrue(strategy._bear_core_active)
        self.assertEqual(strategy._bear_core_stage, 3)
        self.assertAlmostEqual(strategy._bear_core_size, 0.40)
        self.assertAlmostEqual(strategy._bear_group_exposure, 0.40)

    def test_dual_layer_bear_core_acceleration_add_can_enforce_platform_risk_engine_block(self):
        from quant_btc.config import RiskConfig
        from quant_btc.strategy import DualLayerStrategy
        from quant_platform.risk import RiskEngine, RiskLimits
        from quant_platform.signals import Direction, Signal

        class FakeData:
            def __init__(self, df):
                self.df = df
                self.Close = df["Close"]

        class FakePosition:
            size = -0.26

        strategy = object.__new__(DualLayerStrategy)
        strategy.data = FakeData(pd.DataFrame(
            {
                "Close": [100.0, 100.0],
                "High": [101.0, 101.0],
                "Low": [99.0, 99.0],
                "_regime": [2, 2],
                "_d_ema_dir": [-1, -1],
                "_w_ema_dir": [-1, -1],
                "_w_ema_169": [110.0, 110.0],
                "_atr": [5.0, 5.0],
                "_adx_signal": [25.0, 25.0],
                "_plus_di": [10.0, 10.0],
                "_minus_di": [30.0, 30.0],
            },
            index=pd.date_range("2026-06-03", periods=2, freq="4h", tz="UTC"),
        ))
        strategy.position = FakePosition()
        strategy.equity = 50_000.0
        strategy.risk_cfg = RiskConfig()
        strategy.cooldown_bars = 0
        strategy._last_trade_bar = 0
        strategy._pause_until_bar = -1
        strategy._core_active = False
        strategy._core_size = 0.0
        strategy._core_fully_loaded = True
        strategy._tac_direction = 0
        strategy._tac_size = 0.0
        strategy._bear_core_active = True
        strategy._bear_core_stage = 2
        strategy._bear_core_entry_price = 100.0
        strategy._bear_core_entry_bar = 0
        strategy._bear_probe_peak_r = 1.2
        strategy._bear_core_size = 0.26
        strategy._bear_group_id = 1
        strategy._bear_group_exposure = 0.26
        strategy._bear_group_entry_bar = 0
        strategy._bear_group_peak_r = 0.0
        strategy._bear_group_max_exposure = 0.50
        strategy._days_above_dema = 0
        strategy._flash_crash_active = False
        strategy._flash_crash_bar = -10**9
        strategy._waterfall_triggered = False
        strategy._update_circuit_breaker = lambda: None
        strategy._core_entry_standard_signal = lambda: None
        strategy._core_add_standard_signal = lambda: None
        strategy._bear_core_exit_signal = lambda: False
        strategy._check_short_giveback_guard = lambda entry, stop: False
        strategy._check_waterfall_profit_guard = lambda: False
        strategy._bear_core_probe_standard_signal = lambda: None
        strategy._bear_core_confirm_add_standard_signal = lambda: None
        strategy._bear_core_acceleration_add_standard_signal = lambda: Signal(
            module="bear_core_acceleration",
            symbol="BTC/USDT",
            direction=Direction.SHORT,
            score=85.0,
            entry_reason="legacy bear acceleration",
            invalidation="legacy bear-core exit",
        )
        strategy._tactical_signal = lambda: None
        strategy._ENFORCE_PLATFORM_RISK_ENGINE = True
        strategy._platform_risk_engine = RiskEngine(RiskLimits(
            risk_per_trade=0.02,
            portfolio_risk_budget=0.001,
        ))
        orders = []
        strategy._enter_long = lambda size, tag="", sl=None, tp=None: orders.append(
            ("long", size, tag, sl, tp)
        )
        strategy._enter_short = lambda size, tag="", sl=None, tp=None: orders.append(
            ("short", size, tag, sl, tp)
        )

        strategy.next()

        self.assertEqual(orders, [])
        self.assertTrue(strategy._bear_core_active)
        self.assertEqual(strategy._bear_core_stage, 2)
        self.assertEqual(strategy._bear_core_size, 0.26)
        self.assertEqual(strategy._bear_group_exposure, 0.26)
        self.assertEqual(strategy._last_trade_bar, 0)
        self.assertTrue(strategy._last_platform_risk_decision.allowed)
        self.assertFalse(strategy._last_platform_risk_engine_decision.allowed)
        self.assertEqual(
            strategy._last_platform_risk_engine_decision.reason,
            "portfolio_risk_budget_exhausted",
        )


if __name__ == "__main__":
    unittest.main()
