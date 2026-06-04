import unittest

import pandas as pd

from quant_platform.signals import Direction, Signal


class FixedSignalModule:
    name = "fixed"

    def __init__(self, signal):
        self.signal = signal

    def generate(self, features, symbol):
        return [self.signal]


class SignalPipelineTest(unittest.TestCase):
    def _features(self):
        return pd.DataFrame(
            {"Close": [100.0]},
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        )

    def _signal(self, **overrides):
        data = {
            "module": "breakout",
            "symbol": "BTC/USDT",
            "direction": Direction.LONG,
            "score": 82.0,
            "entry_reason": "breakout",
            "invalidation": "close below stop",
            "preferred_stop": 95.0,
            "preferred_target": 120.0,
            "confidence": 0.82,
        }
        data.update(overrides)
        return Signal(**data)

    def test_runs_signal_to_risk_portfolio_and_delivery(self):
        from quant_platform.delivery import InMemoryDeliveryChannel
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        delivery = InMemoryDeliveryChannel("dashboard")
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([FixedSignalModule(self._signal())]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=PortfolioEngine(),
            delivery_channels=(delivery,),
        )

        result = pipeline.run(self._features(), symbol="BTC/USDT", account=AccountState(equity=10_000.0))

        self.assertEqual(len(result.signals), 1)
        self.assertTrue(result.risk_decisions[0].allowed)
        self.assertEqual(result.portfolio_plan.orders[0].action, OrderAction.OPEN)
        self.assertEqual(len(result.delivery_results), 1)
        self.assertEqual(len(delivery.messages), 1)
        self.assertEqual(delivery.messages[0].order["order_id"], result.portfolio_plan.orders[0].order_id)

    def test_risk_blocked_signal_is_not_delivered(self):
        from quant_platform.delivery import InMemoryDeliveryChannel
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        delivery = InMemoryDeliveryChannel("dashboard")
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([FixedSignalModule(self._signal(preferred_stop=None))]),
            risk_engine=RiskEngine(RiskLimits()),
            portfolio_engine=PortfolioEngine(),
            delivery_channels=(delivery,),
        )

        result = pipeline.run(self._features(), symbol="BTC/USDT", account=AccountState(equity=10_000.0))

        self.assertFalse(result.risk_decisions[0].allowed)
        self.assertEqual(result.portfolio_plan.orders[0].action, OrderAction.IGNORE)
        self.assertEqual(result.portfolio_plan.orders[0].reason, "risk_blocked:missing_stop")
        self.assertEqual(result.delivery_results, [])
        self.assertEqual(delivery.messages, [])

    def test_pipeline_applies_market_specs_to_risk_and_portfolio_layers(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, PortfolioEngine, PositionKey
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        market = MarketSpec(
            asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
            exchange="nasdaq",
            market_type="equity",
            tick_size=0.01,
            lot_size=0.001,
            supports_short=False,
            supports_leverage=False,
        )
        short_pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([
                FixedSignalModule(self._signal(symbol="AAPL", direction=Direction.SHORT, preferred_stop=105.019))
            ]),
            risk_engine=RiskEngine(RiskLimits()),
            portfolio_engine=PortfolioEngine(),
            markets_by_symbol={"AAPL": market},
        )
        long_pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([
                FixedSignalModule(self._signal(symbol="AAPL", preferred_stop=90.019, preferred_target=120.019))
            ]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=PortfolioEngine(),
            markets_by_symbol={"AAPL": market},
        )

        blocked = short_pipeline.run(self._features(), symbol="AAPL", account=AccountState(equity=10_000.0))
        opened = long_pipeline.run(self._features(), symbol="AAPL", account=AccountState(equity=10_000.0))

        self.assertFalse(blocked.risk_decisions[0].allowed)
        self.assertEqual(blocked.risk_decisions[0].reason, "short_not_supported")
        self.assertEqual(blocked.portfolio_plan.orders[0].action, OrderAction.IGNORE)
        order = opened.portfolio_plan.orders[0]
        position = long_pipeline.portfolio_engine.state.positions[PositionKey("AAPL", "tactical")]
        self.assertEqual(order.quantity, 10.019)
        self.assertEqual(position.entry_price, 100.0)
        self.assertEqual(position.stop_price, 90.01)
        self.assertEqual(position.target_price, 120.01)

    def test_pipeline_blocks_signal_when_existing_position_exhausts_correlation_group_budget(self):
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, PortfolioEngine, PortfolioState, Position, PositionKey
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        state = PortfolioState(positions={
            PositionKey("BTC/USDT", "tactical"): Position(
                symbol="BTC/USDT",
                layer="tactical",
                direction=Direction.LONG,
                quantity=1.0,
                notional=10_000.0,
                risk_amount=450.0,
                module="breakout",
                entry_price=100.0,
                stop_price=95.0,
            )
        })
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([FixedSignalModule(self._signal(symbol="ETH/USDT"))]),
            risk_engine=RiskEngine(RiskLimits(
                risk_per_trade=0.02,
                portfolio_risk_budget=0.20,
                max_correlation_group_risk=0.05,
                correlation_groups={"BTC/USDT": "crypto_beta", "ETH/USDT": "crypto_beta"},
            )),
            portfolio_engine=PortfolioEngine(state=state),
        )

        result = pipeline.run(self._features(), symbol="ETH/USDT", account=AccountState(equity=10_000.0))

        self.assertFalse(result.risk_decisions[0].allowed)
        self.assertEqual(result.risk_decisions[0].reason, "correlation_group_risk_budget_exhausted")
        self.assertEqual(result.portfolio_plan.orders[0].action, OrderAction.IGNORE)

    def test_pipeline_blocks_signal_when_existing_position_exhausts_module_budget(self):
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, PortfolioEngine, PortfolioState, Position, PositionKey
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        state = PortfolioState(positions={
            PositionKey("BTC/USDT", "tactical"): Position(
                symbol="BTC/USDT",
                layer="tactical",
                direction=Direction.LONG,
                quantity=1.0,
                notional=10_000.0,
                risk_amount=450.0,
                module="breakout",
                entry_price=100.0,
                stop_price=95.0,
            )
        })
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([FixedSignalModule(self._signal(symbol="ETH/USDT", module="breakout"))]),
            risk_engine=RiskEngine(RiskLimits(
                risk_per_trade=0.02,
                portfolio_risk_budget=0.20,
                max_module_risk=0.05,
            )),
            portfolio_engine=PortfolioEngine(state=state),
        )

        result = pipeline.run(self._features(), symbol="ETH/USDT", account=AccountState(equity=10_000.0))

        self.assertFalse(result.risk_decisions[0].allowed)
        self.assertEqual(result.risk_decisions[0].reason, "module_risk_budget_exhausted")
        self.assertEqual(result.portfolio_plan.orders[0].action, OrderAction.IGNORE)

    def test_btc_standard_signal_with_preferred_exit_flows_through_pipeline(self):
        from quant_btc.signal_modules import generate_btc_standard_signals
        from quant_platform.delivery import InMemoryDeliveryChannel
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        features = pd.DataFrame(
            {
                "Close": [100.0],
                "_atr_signal": [5.0],
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
            },
            index=pd.date_range("2026-06-03", periods=1, freq="4h", tz="UTC"),
        )
        signals = generate_btc_standard_signals(features, symbol="BTC/USDT")
        delivery = InMemoryDeliveryChannel("dashboard")
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([FixedSignalModule(signals[0])]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=PortfolioEngine(),
            delivery_channels=(delivery,),
        )

        result = pipeline.run(features, symbol="BTC/USDT", account=AccountState(equity=10_000.0))

        self.assertTrue(result.risk_decisions[0].allowed)
        self.assertEqual(result.risk_decisions[0].stop_price, 90.0)
        self.assertEqual(result.portfolio_plan.orders[0].action, OrderAction.OPEN)
        self.assertEqual(len(delivery.messages), 1)


if __name__ == "__main__":
    unittest.main()
