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

    def test_pipeline_uses_market_spec_correlation_group_for_existing_position_budget(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, PortfolioEngine, PortfolioState, Position, PositionKey
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        markets = {
            "AAPL": MarketSpec(
                asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
                exchange="nasdaq",
                market_type="equity",
                correlation_group="us_equity_beta",
            ),
            "MSFT": MarketSpec(
                asset=AssetSpec(symbol="MSFT", base="MSFT", quote="USD"),
                exchange="nasdaq",
                market_type="equity",
                correlation_group="us_equity_beta",
            ),
        }
        state = PortfolioState(positions={
            PositionKey("AAPL", "tactical"): Position(
                symbol="AAPL",
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
            signal_runner=SignalModuleRunner([FixedSignalModule(self._signal(symbol="MSFT"))]),
            risk_engine=RiskEngine(RiskLimits(
                risk_per_trade=0.02,
                portfolio_risk_budget=0.20,
                max_correlation_group_risk=0.05,
            )),
            portfolio_engine=PortfolioEngine(state=state),
            markets_by_symbol=markets,
        )

        result = pipeline.run(self._features(), symbol="MSFT", account=AccountState(equity=10_000.0))

        self.assertFalse(result.risk_decisions[0].allowed)
        self.assertEqual(result.risk_decisions[0].reason, "correlation_group_risk_budget_exhausted")
        self.assertEqual(result.portfolio_plan.orders[0].action, OrderAction.IGNORE)

    def test_pipeline_uses_market_spec_exchange_for_existing_position_budget(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, PortfolioEngine, PortfolioState, Position, PositionKey
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        markets = {
            "AAPL": MarketSpec(
                asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
                exchange="nasdaq",
                market_type="equity",
            ),
            "MSFT": MarketSpec(
                asset=AssetSpec(symbol="MSFT", base="MSFT", quote="USD"),
                exchange="nasdaq",
                market_type="equity",
            ),
        }
        state = PortfolioState(positions={
            PositionKey("AAPL", "tactical"): Position(
                symbol="AAPL",
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
            signal_runner=SignalModuleRunner([FixedSignalModule(self._signal(symbol="MSFT"))]),
            risk_engine=RiskEngine(RiskLimits(
                risk_per_trade=0.02,
                portfolio_risk_budget=0.20,
                max_exchange_risk=0.05,
            )),
            portfolio_engine=PortfolioEngine(state=state),
            markets_by_symbol=markets,
        )

        result = pipeline.run(self._features(), symbol="MSFT", account=AccountState(equity=10_000.0))

        self.assertFalse(result.risk_decisions[0].allowed)
        self.assertEqual(result.risk_decisions[0].reason, "exchange_risk_budget_exhausted")
        self.assertEqual(result.portfolio_plan.orders[0].action, OrderAction.IGNORE)

    def test_pipeline_accumulates_market_spec_correlation_group_within_signal_batch(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        markets = {
            "AAPL": MarketSpec(
                asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
                exchange="nasdaq",
                market_type="equity",
                correlation_group="us_equity_beta",
            ),
            "MSFT": MarketSpec(
                asset=AssetSpec(symbol="MSFT", base="MSFT", quote="USD"),
                exchange="nasdaq",
                market_type="equity",
                correlation_group="us_equity_beta",
            ),
        }
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([
                FixedSignalModule(self._signal(symbol="AAPL", score=90.0)),
                FixedSignalModule(self._signal(symbol="MSFT", score=80.0)),
            ]),
            risk_engine=RiskEngine(RiskLimits(
                risk_per_trade=0.02,
                portfolio_risk_budget=0.20,
                max_correlation_group_risk=0.03,
            )),
            portfolio_engine=PortfolioEngine(),
            markets_by_symbol=markets,
        )

        result = pipeline.run(
            self._features(),
            symbol="AAPL",
            account=AccountState(equity=10_000.0),
            entry_prices={"AAPL": 100.0, "MSFT": 100.0},
        )

        self.assertTrue(result.risk_decisions[0].allowed)
        self.assertFalse(result.risk_decisions[1].allowed)
        self.assertEqual(result.risk_decisions[1].reason, "correlation_group_risk_budget_exhausted")
        self.assertEqual(result.portfolio_plan.orders[0].action, OrderAction.OPEN)
        self.assertEqual(result.portfolio_plan.orders[1].action, OrderAction.IGNORE)

    def test_pipeline_accumulates_market_type_risk_within_signal_batch(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        markets = {
            "AAPL": MarketSpec(
                asset=AssetSpec(symbol="AAPL", base="AAPL", quote="USD"),
                exchange="nasdaq",
                market_type="equity",
            ),
            "MSFT": MarketSpec(
                asset=AssetSpec(symbol="MSFT", base="MSFT", quote="USD"),
                exchange="nyse",
                market_type="equity",
            ),
        }
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([
                FixedSignalModule(self._signal(symbol="AAPL", score=90.0)),
                FixedSignalModule(self._signal(symbol="MSFT", score=80.0)),
            ]),
            risk_engine=RiskEngine(RiskLimits(
                risk_per_trade=0.02,
                portfolio_risk_budget=0.20,
                max_market_type_risk=0.03,
            )),
            portfolio_engine=PortfolioEngine(),
            markets_by_symbol=markets,
        )

        result = pipeline.run(
            self._features(),
            symbol="AAPL",
            account=AccountState(equity=10_000.0),
            entry_prices={"AAPL": 100.0, "MSFT": 100.0},
        )

        self.assertTrue(result.risk_decisions[0].allowed)
        self.assertFalse(result.risk_decisions[1].allowed)
        self.assertEqual(result.risk_decisions[1].reason, "market_type_risk_budget_exhausted")
        self.assertEqual(result.portfolio_plan.orders[0].action, OrderAction.OPEN)
        self.assertEqual(result.portfolio_plan.orders[1].action, OrderAction.IGNORE)

    def test_pipeline_prioritizes_high_score_same_layer_signal_before_risk_budget(self):
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, PortfolioEngine, PositionKey
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        portfolio_engine = PortfolioEngine()
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([
                FixedSignalModule(self._signal(module="pullback", score=65.0)),
                FixedSignalModule(self._signal(module="breakout", score=95.0)),
            ]),
            risk_engine=RiskEngine(RiskLimits(
                risk_per_trade=0.02,
                portfolio_risk_budget=0.02,
                max_position_fraction=1.0,
            )),
            portfolio_engine=portfolio_engine,
        )

        result = pipeline.run(self._features(), symbol="BTC/USDT", account=AccountState(equity=10_000.0))

        self.assertEqual([decision.signal.module for decision in result.risk_decisions], ["breakout", "pullback"])
        self.assertTrue(result.risk_decisions[0].allowed)
        self.assertFalse(result.risk_decisions[1].allowed)
        self.assertEqual(result.risk_decisions[1].reason, "portfolio_risk_budget_exhausted")
        self.assertEqual(result.portfolio_plan.orders[0].action, OrderAction.OPEN)
        self.assertEqual(result.portfolio_plan.orders[0].decision.signal.module, "breakout")
        self.assertEqual(portfolio_engine.state.positions[PositionKey("BTC/USDT", "tactical")].module, "breakout")

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

    def test_pipeline_returns_risk_budget_diagnostics_after_allowed_decisions(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import PortfolioEngine, PortfolioState, Position, PositionKey
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        markets = {
            "BTC/USDT": MarketSpec(
                asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
                exchange="binance",
                market_type="swap",
                correlation_group="crypto_beta",
            ),
            "ETH/USDT": MarketSpec(
                asset=AssetSpec(symbol="ETH/USDT", base="ETH", quote="USDT"),
                exchange="okx",
                market_type="swap",
                correlation_group="crypto_beta",
            ),
        }
        state = PortfolioState(positions={
            PositionKey("BTC/USDT", "tactical"): Position(
                symbol="BTC/USDT",
                layer="tactical",
                direction=Direction.LONG,
                quantity=1.0,
                notional=10_000.0,
                risk_amount=100.0,
                module="breakout",
                entry_price=100.0,
                stop_price=95.0,
            )
        })
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([
                FixedSignalModule(self._signal(symbol="ETH/USDT", module="pullback", preferred_stop=90.0))
            ]),
            risk_engine=RiskEngine(RiskLimits(
                risk_per_trade=0.02,
                portfolio_risk_budget=0.10,
                max_symbol_risk=0.05,
                max_module_risk=0.06,
                max_correlation_group_risk=0.05,
                max_exchange_risk=0.05,
                max_market_type_risk=0.05,
                correlation_groups={"BTC/USDT": "crypto_beta", "ETH/USDT": "crypto_beta"},
            )),
            portfolio_engine=PortfolioEngine(state=state, allow_hedging=True),
            markets_by_symbol=markets,
        )

        result = pipeline.run(self._features(), symbol="ETH/USDT", account=AccountState(equity=10_000.0))
        diagnostics = result.risk_diagnostics.to_dict()

        self.assertTrue(result.risk_decisions[0].allowed)
        self.assertEqual(diagnostics["portfolio"]["used"], 300.0)
        self.assertEqual(diagnostics["portfolio"]["budget"], 1_000.0)
        self.assertEqual(diagnostics["symbols"]["BTC/USDT"]["used"], 100.0)
        self.assertEqual(diagnostics["symbols"]["ETH/USDT"]["used"], 200.0)
        self.assertEqual(diagnostics["symbols"]["ETH/USDT"]["budget"], 500.0)
        self.assertEqual(diagnostics["modules"]["breakout"]["used"], 100.0)
        self.assertEqual(diagnostics["modules"]["pullback"]["used"], 200.0)
        self.assertEqual(diagnostics["correlation_groups"]["crypto_beta"]["used"], 300.0)
        self.assertEqual(diagnostics["correlation_groups"]["crypto_beta"]["budget"], 500.0)
        self.assertEqual(diagnostics["exchanges"]["binance"]["used"], 100.0)
        self.assertEqual(diagnostics["exchanges"]["okx"]["used"], 200.0)
        self.assertEqual(diagnostics["exchanges"]["okx"]["budget"], 500.0)
        self.assertEqual(diagnostics["market_types"]["swap"]["used"], 300.0)
        self.assertEqual(diagnostics["market_types"]["swap"]["budget"], 500.0)

    def test_pipeline_can_apply_precomputed_risk_decisions_for_legacy_bridges(self):
        from quant_platform.delivery import InMemoryDeliveryChannel
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, PortfolioEngine
        from quant_platform.risk import AccountState, RiskDecision, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        signal = self._signal(module="legacy_breakout", preferred_stop=95.0, preferred_target=118.0)
        decision = RiskDecision(
            allowed=True,
            reason="legacy_compat_audit",
            signal=signal,
            quantity=4.0,
            notional=400.0,
            risk_amount=20.0,
            entry_price=100.0,
            stop_price=95.0,
            max_loss_per_unit=5.0,
        )
        delivery = InMemoryDeliveryChannel("dashboard")
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([]),
            risk_engine=RiskEngine(RiskLimits(portfolio_risk_budget=0.10)),
            portfolio_engine=PortfolioEngine(layer_by_module={"legacy_breakout": "tactical"}),
            delivery_channels=(delivery,),
        )

        result = pipeline.run_decisions([decision], account=AccountState(equity=10_000.0))

        self.assertEqual(result.signals, [signal])
        self.assertEqual(result.risk_decisions, [decision])
        self.assertEqual(result.portfolio_plan.orders[0].action, OrderAction.OPEN)
        self.assertIs(result.portfolio_plan.orders[0].decision, decision)
        self.assertEqual(len(result.delivery_results), 1)
        self.assertEqual(delivery.messages[0].risk["reason"], "legacy_compat_audit")
        self.assertEqual(result.risk_diagnostics.portfolio.used, 20.0)

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
