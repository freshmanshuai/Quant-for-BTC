import unittest

import pandas as pd

from quant_platform.signals import Direction, Signal


class SignalOnSecondBar:
    name = "second_bar"

    def generate(self, features, symbol):
        if len(features) < 2:
            return []
        close = float(features["Close"].iloc[-1])
        return [
            Signal(
                module="breakout",
                symbol=symbol,
                direction=Direction.LONG,
                score=80.0,
                entry_reason="second bar breakout",
                invalidation="close below stop",
                preferred_stop=close - 5.0,
                preferred_target=close + 10.0,
                confidence=0.8,
            )
        ]


class SignalOnlyOnSecondBar:
    name = "second_bar_only"

    def generate(self, features, symbol):
        if len(features) != 2:
            return []
        close = float(features["Close"].iloc[-1])
        return [
            Signal(
                module="breakout",
                symbol=symbol,
                direction=Direction.LONG,
                score=80.0,
                entry_reason="second bar breakout",
                invalidation="close below stop",
                preferred_stop=close - 5.0,
                preferred_target=close + 10.0,
                confidence=0.8,
            )
        ]


class DirectionBySymbolOnSecondBar:
    name = "direction_by_symbol"

    def __init__(self, directions):
        self.directions = directions

    def generate(self, features, symbol):
        if len(features) < 2:
            return []
        close = float(features["Close"].iloc[-1])
        direction = self.directions[symbol]
        if direction == Direction.LONG:
            stop = close - 5.0
            target = close + 10.0
        else:
            stop = close + 5.0
            target = close - 10.0
        return [
            Signal(
                module=f"{symbol}_module",
                symbol=symbol,
                direction=direction,
                score=80.0,
                entry_reason="second bar signal",
                invalidation="stop",
                preferred_stop=stop,
                preferred_target=target,
                confidence=0.8,
            )
        ]


class LongThenShortSignal:
    name = "long_then_short"

    def generate(self, features, symbol):
        close = float(features["Close"].iloc[-1])
        if len(features) == 2:
            return [
                Signal(
                    module="breakout",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=80.0,
                    entry_reason="long setup",
                    invalidation="long stop",
                    preferred_stop=close - 5.0,
                    preferred_target=close + 50.0,
                    confidence=0.8,
                )
            ]
        if len(features) == 3:
            return [
                Signal(
                    module="crash_short",
                    symbol=symbol,
                    direction=Direction.SHORT,
                    score=90.0,
                    entry_reason="short reversal",
                    invalidation="short stop",
                    preferred_stop=close + 5.0,
                    preferred_target=close - 50.0,
                    confidence=0.9,
                )
            ]
        return []


class LongThenScaleInSignal:
    name = "long_then_scale_in"

    def generate(self, features, symbol):
        close = float(features["Close"].iloc[-1])
        if len(features) == 2:
            return [
                Signal(
                    module="breakout",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=80.0,
                    entry_reason="initial long",
                    invalidation="initial stop",
                    preferred_stop=close - 5.0,
                    preferred_target=close + 50.0,
                    confidence=0.8,
                )
            ]
        if len(features) == 3:
            return [
                Signal(
                    module="pullback",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=85.0,
                    entry_reason="scale in",
                    invalidation="scale stop",
                    preferred_stop=close - 2.5,
                    preferred_target=close + 40.0,
                    confidence=0.85,
                )
            ]
        return []


class LongThenScaleDownSignal:
    name = "long_then_scale_down"

    def generate(self, features, symbol):
        close = float(features["Close"].iloc[-1])
        if len(features) == 2:
            return [
                Signal(
                    module="breakout",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=80.0,
                    entry_reason="initial long",
                    invalidation="initial stop",
                    preferred_stop=close - 2.5,
                    preferred_target=close + 50.0,
                    confidence=0.8,
                )
            ]
        if len(features) == 3:
            return [
                Signal(
                    module="pullback",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=85.0,
                    entry_reason="scale down",
                    invalidation="wider stop",
                    preferred_stop=close - 5.0,
                    preferred_target=close + 40.0,
                    confidence=0.85,
                )
            ]
        return []


class LongThenCoreTransferSignal:
    name = "long_then_core_transfer"

    def generate(self, features, symbol):
        close = float(features["Close"].iloc[-1])
        if len(features) == 2:
            return [
                Signal(
                    module="breakout",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=80.0,
                    entry_reason="initial tactical long",
                    invalidation="initial stop",
                    preferred_stop=close - 5.0,
                    preferred_target=close + 50.0,
                    confidence=0.8,
                )
            ]
        if len(features) == 3:
            return [
                Signal(
                    module="core_long",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=90.0,
                    entry_reason="promote to core",
                    invalidation="core exit",
                    preferred_stop=close - 10.0,
                    preferred_target=close + 100.0,
                    confidence=0.9,
                )
            ]
        return []


class LongFirstSymbolThenSecondSymbolSignal:
    name = "long_first_symbol_then_second_symbol"

    def generate(self, features, symbol):
        close = float(features["Close"].iloc[-1])
        if symbol == "AAA/USDT" and len(features) == 2:
            return [
                Signal(
                    module="breakout",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=80.0,
                    entry_reason="first symbol long",
                    invalidation="first symbol stop",
                    preferred_stop=close - 10.0,
                    preferred_target=close + 100.0,
                    confidence=0.8,
                )
            ]
        if symbol == "BBB/USDT" and len(features) == 3:
            return [
                Signal(
                    module="pullback",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=80.0,
                    entry_reason="second symbol after drawdown",
                    invalidation="second symbol stop",
                    preferred_stop=close - 5.0,
                    preferred_target=close + 20.0,
                    confidence=0.8,
                )
            ]
        return []


class LossThenSecondSymbolSignal:
    name = "loss_then_second_symbol"

    def generate(self, features, symbol):
        close = float(features["Close"].iloc[-1])
        if symbol == "AAA/USDT" and len(features) == 2:
            return [
                Signal(
                    module="breakout",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=80.0,
                    entry_reason="first symbol long",
                    invalidation="first symbol stop",
                    preferred_stop=close - 5.0,
                    preferred_target=close + 100.0,
                    confidence=0.8,
                )
            ]
        if symbol == "BBB/USDT" and len(features) == 3:
            return [
                Signal(
                    module="pullback",
                    symbol=symbol,
                    direction=Direction.LONG,
                    score=80.0,
                    entry_reason="second symbol after loss",
                    invalidation="second symbol stop",
                    preferred_stop=close - 5.0,
                    preferred_target=close + 20.0,
                    confidence=0.8,
                )
            ]
        return []


class EventDrivenBacktestTest(unittest.TestCase):
    def test_runs_signal_pipeline_over_multiple_symbols_and_bars(self):
        from quant_platform.backtest import EventDrivenBacktest
        from quant_platform.delivery import InMemoryDeliveryChannel
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=2, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame({"Close": [100.0, 105.0]}, index=index),
            "ETH/USDT": pd.DataFrame({"Close": [50.0, 55.0]}, index=index),
        }
        delivery = InMemoryDeliveryChannel("dashboard")
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([SignalOnSecondBar()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=PortfolioEngine(max_positions_per_symbol=1),
            delivery_channels=(delivery,),
        )
        backtest = EventDrivenBacktest(pipeline=pipeline, account=AccountState(equity=10_000.0))

        result = backtest.run(features_by_symbol)

        self.assertEqual(len(result.steps), 4)
        self.assertEqual([order.symbol for order in result.orders], ["BTC/USDT", "ETH/USDT"])
        self.assertEqual([order.action for order in result.orders], [OrderAction.OPEN, OrderAction.OPEN])
        self.assertEqual(len(result.signals), 2)
        self.assertEqual(len(delivery.messages), 2)

    def test_records_exposure_curve_after_each_event(self):
        from quant_platform.backtest import EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=2, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame({"Close": [100.0, 105.0]}, index=index),
            "ETH/USDT": pd.DataFrame({"Close": [50.0, 55.0]}, index=index),
        }
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([
                DirectionBySymbolOnSecondBar({
                    "BTC/USDT": Direction.LONG,
                    "ETH/USDT": Direction.SHORT,
                })
            ]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=PortfolioEngine(max_positions_per_symbol=1),
        )
        backtest = EventDrivenBacktest(pipeline=pipeline, account=AccountState(equity=10_000.0))

        result = backtest.run(features_by_symbol)

        self.assertEqual(len(result.exposure_curve), 4)
        after_btc_open = result.exposure_curve[2]
        self.assertEqual(after_btc_open.position_count, 1)
        self.assertAlmostEqual(after_btc_open.long_notional, 2100.0)
        self.assertAlmostEqual(after_btc_open.short_notional, 0.0)
        self.assertAlmostEqual(after_btc_open.gross_notional, 2100.0)
        self.assertAlmostEqual(after_btc_open.net_notional, 2100.0)
        self.assertAlmostEqual(after_btc_open.open_risk, 100.0)

        final = result.exposure_curve[-1]
        self.assertEqual(final.position_count, 2)
        self.assertAlmostEqual(final.long_notional, 2100.0)
        self.assertAlmostEqual(final.short_notional, 1100.0)
        self.assertAlmostEqual(final.gross_notional, 3200.0)
        self.assertAlmostEqual(final.net_notional, 1000.0)
        self.assertAlmostEqual(final.open_risk, 200.0)

    def test_exposure_curve_groups_notional_and_risk_by_market_correlation_group(self):
        from quant_platform.backtest import EventDrivenBacktest
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=2, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame({"Close": [100.0, 105.0]}, index=index),
            "ETH/USDT": pd.DataFrame({"Close": [50.0, 55.0]}, index=index),
        }
        markets_by_symbol = {
            "BTC/USDT": MarketSpec(
                asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
                exchange="binance",
                market_type="swap",
                correlation_group="crypto",
            ),
            "ETH/USDT": MarketSpec(
                asset=AssetSpec(symbol="ETH/USDT", base="ETH", quote="USDT"),
                exchange="binance",
                market_type="swap",
                correlation_group="crypto",
                supports_short=True,
            ),
        }
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([
                DirectionBySymbolOnSecondBar({
                    "BTC/USDT": Direction.LONG,
                    "ETH/USDT": Direction.SHORT,
                })
            ]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=PortfolioEngine(
                max_positions_per_symbol=1,
                layer_by_module={
                    "BTC/USDT_module": "core",
                    "ETH/USDT_module": "tactical",
                },
            ),
            markets_by_symbol=markets_by_symbol,
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            markets_by_symbol=markets_by_symbol,
        )

        result = backtest.run(features_by_symbol)

        crypto = result.exposure_curve[-1].group_exposure["crypto"]
        self.assertAlmostEqual(crypto.long_notional, 2100.0)
        self.assertAlmostEqual(crypto.short_notional, 1100.0)
        self.assertAlmostEqual(crypto.gross_notional, 3200.0)
        self.assertAlmostEqual(crypto.net_notional, 1000.0)
        self.assertAlmostEqual(crypto.open_risk, 200.0)
        symbol_exposure = result.exposure_curve[-1].symbol_exposure
        self.assertAlmostEqual(symbol_exposure["BTC/USDT"].long_notional, 2100.0)
        self.assertAlmostEqual(symbol_exposure["BTC/USDT"].gross_notional, 2100.0)
        self.assertAlmostEqual(symbol_exposure["BTC/USDT"].open_risk, 100.0)
        self.assertAlmostEqual(symbol_exposure["ETH/USDT"].short_notional, 1100.0)
        self.assertAlmostEqual(symbol_exposure["ETH/USDT"].gross_notional, 1100.0)
        self.assertAlmostEqual(symbol_exposure["ETH/USDT"].open_risk, 100.0)
        layer_exposure = result.exposure_curve[-1].layer_exposure
        self.assertAlmostEqual(layer_exposure["core"].long_notional, 2100.0)
        self.assertAlmostEqual(layer_exposure["core"].gross_notional, 2100.0)
        self.assertAlmostEqual(layer_exposure["core"].open_risk, 100.0)
        self.assertAlmostEqual(layer_exposure["tactical"].short_notional, 1100.0)
        self.assertAlmostEqual(layer_exposure["tactical"].gross_notional, 1100.0)
        self.assertAlmostEqual(layer_exposure["tactical"].open_risk, 100.0)
        module_exposure = result.exposure_curve[-1].module_exposure
        self.assertAlmostEqual(module_exposure["BTC/USDT_module"].long_notional, 2100.0)
        self.assertAlmostEqual(module_exposure["BTC/USDT_module"].gross_notional, 2100.0)
        self.assertAlmostEqual(module_exposure["BTC/USDT_module"].open_risk, 100.0)
        self.assertAlmostEqual(module_exposure["ETH/USDT_module"].short_notional, 1100.0)
        self.assertAlmostEqual(module_exposure["ETH/USDT_module"].gross_notional, 1100.0)
        self.assertAlmostEqual(module_exposure["ETH/USDT_module"].open_risk, 100.0)

    def test_summarizes_peak_portfolio_exposure_from_exposure_curve(self):
        from quant_platform.backtest import EventDrivenBacktest
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=2, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame({"Close": [100.0, 105.0]}, index=index),
            "ETH/USDT": pd.DataFrame({"Close": [50.0, 55.0]}, index=index),
        }
        markets_by_symbol = {
            "BTC/USDT": MarketSpec(
                asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
                exchange="binance",
                market_type="swap",
                correlation_group="crypto",
            ),
            "ETH/USDT": MarketSpec(
                asset=AssetSpec(symbol="ETH/USDT", base="ETH", quote="USDT"),
                exchange="binance",
                market_type="swap",
                correlation_group="crypto",
                supports_short=True,
            ),
        }
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([
                DirectionBySymbolOnSecondBar({
                    "BTC/USDT": Direction.LONG,
                    "ETH/USDT": Direction.SHORT,
                })
            ]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=PortfolioEngine(
                max_positions_per_symbol=1,
                layer_by_module={
                    "BTC/USDT_module": "core",
                    "ETH/USDT_module": "tactical",
                },
            ),
            markets_by_symbol=markets_by_symbol,
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            markets_by_symbol=markets_by_symbol,
        )

        result = backtest.run(features_by_symbol)

        summary = result.exposure_summary
        self.assertEqual(summary.max_position_count, 2)
        self.assertAlmostEqual(summary.max_gross_notional, 3200.0)
        self.assertAlmostEqual(summary.max_abs_net_notional, 2100.0)
        self.assertAlmostEqual(summary.max_open_risk, 200.0)
        self.assertAlmostEqual(summary.max_group_gross_notional, 3200.0)
        self.assertAlmostEqual(summary.max_group_open_risk, 200.0)
        self.assertEqual(summary.max_group_gross_notional_group, "crypto")
        self.assertEqual(summary.max_group_open_risk_group, "crypto")
        self.assertAlmostEqual(summary.max_symbol_gross_notional, 2100.0)
        self.assertAlmostEqual(summary.max_symbol_open_risk, 100.0)
        self.assertEqual(summary.max_symbol_gross_notional_symbol, "BTC/USDT")
        self.assertEqual(summary.max_symbol_open_risk_symbol, "BTC/USDT")
        self.assertAlmostEqual(summary.max_layer_gross_notional, 2100.0)
        self.assertAlmostEqual(summary.max_layer_open_risk, 100.0)
        self.assertEqual(summary.max_layer_gross_notional_layer, "core")
        self.assertEqual(summary.max_layer_open_risk_layer, "core")
        self.assertAlmostEqual(summary.max_module_gross_notional, 2100.0)
        self.assertAlmostEqual(summary.max_module_open_risk, 100.0)
        self.assertEqual(summary.max_module_gross_notional_module, "BTC/USDT_module")
        self.assertEqual(summary.max_module_open_risk_module, "BTC/USDT_module")

    def test_summarizes_event_backtest_performance_from_equity_curve(self):
        from quant_platform.backtest import BacktestEquityPoint, BacktestTrade, EventDrivenBacktestResult

        result = EventDrivenBacktestResult(
            steps=[],
            initial_equity=10_000.0,
            realized_pnl=250.0,
            fees_paid=12.0,
            funding_paid=3.0,
            equity_curve=[
                BacktestEquityPoint("BTC/USDT", "t0", 0, 10_000.0, 0.0, 10_000.0),
                BacktestEquityPoint("BTC/USDT", "t1", 1, 10_500.0, 0.0, 10_500.0),
                BacktestEquityPoint("BTC/USDT", "t2", 2, 9_700.0, 0.0, 9_700.0),
                BacktestEquityPoint("BTC/USDT", "t3", 3, 10_000.0, 100.0, 10_100.0),
            ],
            trades=[
                BacktestTrade(
                    symbol="BTC/USDT",
                    layer="tactical",
                    module="breakout",
                    direction=Direction.LONG,
                    entry_price=100.0,
                    exit_price=130.0,
                    quantity=10.0,
                    gross_pnl=300.0,
                    entry_fee=0.0,
                    exit_fee=0.0,
                    net_pnl=300.0,
                    exit_reason="target",
                    holding_bars=2,
                ),
                BacktestTrade(
                    symbol="BTC/USDT",
                    layer="tactical",
                    module="breakout",
                    direction=Direction.LONG,
                    entry_price=100.0,
                    exit_price=95.0,
                    quantity=10.0,
                    gross_pnl=-50.0,
                    entry_fee=0.0,
                    exit_fee=0.0,
                    net_pnl=-50.0,
                    exit_reason="stop",
                    holding_bars=4,
                ),
            ],
        )

        summary = result.performance_summary

        self.assertAlmostEqual(summary.initial_equity, 10_000.0)
        self.assertAlmostEqual(summary.final_equity, 10_100.0)
        self.assertAlmostEqual(summary.total_return_pct, 0.01)
        self.assertAlmostEqual(summary.final_unrealized_pnl, 100.0)
        self.assertAlmostEqual(summary.realized_pnl, 250.0)
        self.assertAlmostEqual(summary.fees_paid, 12.0)
        self.assertAlmostEqual(summary.funding_paid, 3.0)
        self.assertAlmostEqual(summary.max_equity, 10_500.0)
        self.assertAlmostEqual(summary.min_equity, 9_700.0)
        self.assertAlmostEqual(summary.max_drawdown_amount, 800.0)
        self.assertAlmostEqual(summary.max_drawdown_pct, 800.0 / 10_500.0)
        self.assertEqual(summary.trade_count, 2)
        self.assertAlmostEqual(summary.win_rate, 0.5)
        self.assertAlmostEqual(summary.average_trade_net_pnl, 125.0)
        self.assertAlmostEqual(summary.average_holding_bars, 3.0)
        self.assertAlmostEqual(summary.gross_profit, 300.0)
        self.assertAlmostEqual(summary.gross_loss, 50.0)
        self.assertAlmostEqual(summary.profit_factor, 6.0)
        self.assertAlmostEqual(summary.average_win_net_pnl, 300.0)
        self.assertAlmostEqual(summary.average_loss_net_pnl, 50.0)
        self.assertAlmostEqual(summary.payoff_ratio, 6.0)

    def test_fills_submitted_orders_and_records_state_history(self):
        from quant_platform.backtest import EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderStatus, PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=2, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame({"Close": [100.0, 105.0]}, index=index),
        }
        portfolio_engine = PortfolioEngine(max_positions_per_symbol=1)
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([SignalOnSecondBar()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=portfolio_engine,
        )
        backtest = EventDrivenBacktest(pipeline=pipeline, account=AccountState(equity=10_000.0))

        result = backtest.run(features_by_symbol)

        self.assertEqual([order.status for order in result.filled_orders], [OrderStatus.FILLED])
        self.assertAlmostEqual(result.filled_orders[0].average_fill_price, 105.0)
        self.assertEqual(len(result.state_history), 2)
        self.assertEqual(result.state_history[-1].symbol, "BTC/USDT")
        self.assertEqual(result.state_history[-1].position_count, 1)
        self.assertEqual(result.state_history[-1].submitted_order_count, 0)
        self.assertEqual(result.state_history[-1].filled_order_count, 1)
        self.assertAlmostEqual(result.state_history[-1].open_risk, 100.0)
        self.assertEqual(result.order_status_counts[OrderStatus.FILLED], 1)
        self.assertEqual(result.order_status_counts[OrderStatus.SUBMITTED], 0)

    def test_passes_mark_to_market_equity_into_risk_evaluation(self):
        from quant_platform.backtest import EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=3, freq="4h", tz="UTC")
        features_by_symbol = {
            "AAA/USDT": pd.DataFrame({"Close": [100.0, 100.0, 80.0]}, index=index),
            "BBB/USDT": pd.DataFrame({"Close": [50.0, 50.0, 50.0]}, index=index),
        }
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([LongFirstSymbolThenSecondSymbolSignal()]),
            risk_engine=RiskEngine(
                RiskLimits(
                    risk_per_trade=0.10,
                    max_position_fraction=1.0,
                    portfolio_risk_budget=1.0,
                    max_drawdown_pct=0.10,
                )
            ),
            portfolio_engine=PortfolioEngine(max_positions_per_symbol=1),
        )
        backtest = EventDrivenBacktest(pipeline=pipeline, account=AccountState(equity=10_000.0))

        result = backtest.run(features_by_symbol)

        second_symbol_decision = [
            decision
            for step in result.steps
            for decision in step.result.risk_decisions
            if decision.signal.symbol == "BBB/USDT"
        ][0]
        self.assertFalse(second_symbol_decision.allowed)
        self.assertEqual(second_symbol_decision.reason, "max_drawdown_limit")
        self.assertAlmostEqual(second_symbol_decision.entry_price, 50.0)
        self.assertEqual(result.orders[-1].action, OrderAction.IGNORE)
        self.assertEqual(result.orders[-1].reason, "risk_blocked:max_drawdown_limit")
        self.assertAlmostEqual(result.equity_curve[-1].equity, 8_000.0)

    def test_records_realized_losses_into_risk_state_before_later_events(self):
        from quant_platform.backtest import EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=3, freq="4h", tz="UTC")
        features_by_symbol = {
            "AAA/USDT": pd.DataFrame({"Close": [100.0, 100.0, 90.0]}, index=index),
            "BBB/USDT": pd.DataFrame({"Close": [50.0, 50.0, 50.0]}, index=index),
        }
        risk_engine = RiskEngine(
            RiskLimits(
                risk_per_trade=0.02,
                max_position_fraction=1.0,
                portfolio_risk_budget=1.0,
                consecutive_loss_limit=1,
                reduced_size_multiplier=0.5,
            )
        )
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([LossThenSecondSymbolSignal()]),
            risk_engine=risk_engine,
            portfolio_engine=PortfolioEngine(max_positions_per_symbol=1),
        )
        backtest = EventDrivenBacktest(pipeline=pipeline, account=AccountState(equity=10_000.0))

        result = backtest.run(features_by_symbol)

        second_symbol_decision = [
            decision
            for step in result.steps
            for decision in step.result.risk_decisions
            if decision.signal.symbol == "BBB/USDT"
        ][0]
        self.assertEqual(len(result.trades), 1)
        self.assertAlmostEqual(result.trades[0].net_pnl, -400.0)
        self.assertEqual(risk_engine.state.consecutive_losses, 1)
        self.assertEqual(risk_engine.state.realized_pnl, [-400.0])
        self.assertTrue(second_symbol_decision.allowed)
        self.assertEqual(second_symbol_decision.applied_size_multiplier, 0.5)
        self.assertAlmostEqual(second_symbol_decision.risk_amount, 96.0)
        self.assertAlmostEqual(second_symbol_decision.quantity, 19.2)

    def test_intrabar_entry_limit_leaves_untouched_open_order_submitted(self):
        from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderStatus, PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=2, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame(
                {
                    "High": [101.0, 104.0],
                    "Low": [99.0, 103.0],
                    "Close": [100.0, 105.0],
                },
                index=index,
            ),
        }
        portfolio_engine = PortfolioEngine(max_positions_per_symbol=1)
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([SignalOnSecondBar()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=portfolio_engine,
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            execution=BacktestExecutionConfig(intrabar_entry_limit=True),
        )

        result = backtest.run(features_by_symbol)

        self.assertEqual(result.filled_orders, [])
        self.assertEqual(result.orders[0].status, OrderStatus.SUBMITTED)
        self.assertEqual(result.state_history[-1].submitted_order_count, 1)
        self.assertEqual(result.state_history[-1].filled_order_count, 0)
        self.assertEqual(result.state_history[-1].position_count, 0)
        self.assertEqual(result.order_status_counts[OrderStatus.SUBMITTED], 1)
        self.assertEqual(result.order_status_counts[OrderStatus.FILLED], 0)

    def test_pending_intrabar_entry_limit_fills_when_later_bar_touches_price(self):
        from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderStatus, PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=3, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame(
                {
                    "High": [101.0, 104.0, 106.0],
                    "Low": [99.0, 103.0, 104.0],
                    "Close": [100.0, 105.0, 106.0],
                },
                index=index,
            ),
        }
        portfolio_engine = PortfolioEngine(max_positions_per_symbol=1)
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([SignalOnlyOnSecondBar()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=portfolio_engine,
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            execution=BacktestExecutionConfig(intrabar_entry_limit=True),
        )

        result = backtest.run(features_by_symbol)

        self.assertEqual(len(result.filled_orders), 1)
        self.assertEqual(result.filled_orders[0].status, OrderStatus.FILLED)
        self.assertAlmostEqual(result.filled_orders[0].average_fill_price, 105.0)
        self.assertEqual(result.state_history[1].submitted_order_count, 1)
        self.assertEqual(result.state_history[1].position_count, 0)
        self.assertEqual(result.state_history[-1].submitted_order_count, 0)
        self.assertEqual(result.state_history[-1].filled_order_count, 1)
        self.assertEqual(result.state_history[-1].position_count, 1)
        self.assertEqual(result.order_status_counts[OrderStatus.SUBMITTED], 0)
        self.assertEqual(result.order_status_counts[OrderStatus.FILLED], 1)

    def test_pending_entry_order_can_expire_after_configured_bar_age(self):
        from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderStatus, PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=4, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame(
                {
                    "High": [101.0, 104.0, 104.0, 104.0],
                    "Low": [99.0, 103.0, 103.0, 103.0],
                    "Close": [100.0, 105.0, 104.0, 104.0],
                },
                index=index,
            ),
        }
        portfolio_engine = PortfolioEngine(max_positions_per_symbol=1)
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([SignalOnlyOnSecondBar()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=portfolio_engine,
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            execution=BacktestExecutionConfig(intrabar_entry_limit=True, max_entry_order_age_bars=1),
        )

        result = backtest.run(features_by_symbol)

        self.assertEqual(result.filled_orders, [])
        self.assertEqual([order.status for order in result.terminal_orders], [OrderStatus.CANCELED])
        self.assertEqual(result.terminal_orders[0].reason, "entry_order_expired")
        self.assertEqual(result.state_history[1].submitted_order_count, 1)
        self.assertEqual(result.state_history[2].submitted_order_count, 1)
        self.assertEqual(result.state_history[-1].submitted_order_count, 0)
        self.assertEqual(result.state_history[-1].position_count, 0)
        self.assertEqual(result.order_status_counts[OrderStatus.SUBMITTED], 0)
        self.assertEqual(result.order_status_counts[OrderStatus.CANCELED], 1)

    def test_execution_can_partially_fill_open_order_across_bars(self):
        from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderStatus, PortfolioEngine, PositionKey
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=3, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame({"Close": [100.0, 105.0, 106.0]}, index=index),
        }
        portfolio_engine = PortfolioEngine(max_positions_per_symbol=1)
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([SignalOnlyOnSecondBar()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=portfolio_engine,
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            execution=BacktestExecutionConfig(fee_rate=0.001, max_entry_fill_fraction_per_bar=0.5),
        )

        result = backtest.run(features_by_symbol)

        self.assertEqual([order.status for order in result.filled_orders], [
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
        ])
        self.assertAlmostEqual(result.filled_orders[0].filled_quantity, 10.0)
        self.assertAlmostEqual(result.filled_orders[0].average_fill_price, 105.0)
        self.assertAlmostEqual(result.filled_orders[1].filled_quantity, 20.0)
        self.assertAlmostEqual(result.filled_orders[1].average_fill_price, 105.5)
        self.assertEqual(result.state_history[1].submitted_order_count, 1)
        self.assertEqual(result.state_history[1].filled_order_count, 0)
        self.assertEqual(result.state_history[1].position_count, 1)
        self.assertEqual(result.state_history[-1].submitted_order_count, 0)
        self.assertEqual(result.state_history[-1].filled_order_count, 1)
        position = portfolio_engine.state.positions[PositionKey("BTC/USDT", "tactical")]
        self.assertAlmostEqual(position.quantity, 20.0)
        self.assertAlmostEqual(position.entry_price, 105.5)
        self.assertAlmostEqual(result.fees_paid, 2.11)
        self.assertEqual(result.order_status_counts[OrderStatus.PARTIALLY_FILLED], 0)
        self.assertEqual(result.order_status_counts[OrderStatus.FILLED], 1)

    def test_execution_can_cap_entry_fills_by_bar_volume_participation(self):
        from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderStatus, PortfolioEngine, PositionKey
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=3, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame(
                {
                    "Close": [100.0, 105.0, 106.0],
                    "Volume": [100.0, 12.0, 40.0],
                },
                index=index,
            ),
        }
        portfolio_engine = PortfolioEngine(max_positions_per_symbol=1)
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([SignalOnlyOnSecondBar()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=portfolio_engine,
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            execution=BacktestExecutionConfig(fee_rate=0.001, max_entry_volume_fraction_per_bar=0.5),
        )

        result = backtest.run(features_by_symbol)

        self.assertEqual([order.status for order in result.filled_orders], [
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
        ])
        self.assertAlmostEqual(result.filled_orders[0].filled_quantity, 6.0)
        self.assertAlmostEqual(result.filled_orders[1].filled_quantity, 20.0)
        self.assertAlmostEqual(result.filled_orders[1].average_fill_price, 105.7)
        position = portfolio_engine.state.positions[PositionKey("BTC/USDT", "tactical")]
        self.assertAlmostEqual(position.quantity, 20.0)
        self.assertAlmostEqual(position.entry_price, 105.7)
        self.assertAlmostEqual(result.fees_paid, 2.114)
        self.assertEqual(result.order_status_counts[OrderStatus.FILLED], 1)

    def test_tracks_equity_after_fees_and_unrealized_pnl(self):
        from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=3, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame({"Close": [100.0, 105.0, 110.0]}, index=index),
        }
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([SignalOnSecondBar()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=PortfolioEngine(max_positions_per_symbol=1),
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            execution=BacktestExecutionConfig(fee_rate=0.001, slippage_bps=10.0),
        )

        result = backtest.run(features_by_symbol)

        self.assertEqual(len(result.equity_curve), 3)
        self.assertAlmostEqual(result.filled_orders[0].average_fill_price, 105.105)
        self.assertAlmostEqual(result.fees_paid, 2.1021, places=4)
        self.assertAlmostEqual(result.equity_curve[-1].cash, 9997.8979, places=4)
        self.assertAlmostEqual(result.equity_curve[-1].unrealized_pnl, 97.9, places=1)
        self.assertAlmostEqual(result.equity_curve[-1].equity, 10095.7979, places=4)

    def test_entry_execution_can_use_order_book_spread_feature(self):
        from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import PortfolioEngine, PositionKey
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=3, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame(
                {
                    "Close": [100.0, 105.0, 110.0],
                    "order_book_spread": [0.25, 1.0, 2.0],
                },
                index=index,
            ),
        }
        portfolio_engine = PortfolioEngine(max_positions_per_symbol=1)
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([SignalOnSecondBar()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=portfolio_engine,
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            execution=BacktestExecutionConfig(slippage_bps=10.0, entry_spread_feature="order_book_spread"),
        )

        result = backtest.run(features_by_symbol)

        position = portfolio_engine.state.positions[PositionKey("BTC/USDT", "tactical")]
        self.assertAlmostEqual(result.filled_orders[0].average_fill_price, 105.6055)
        self.assertAlmostEqual(position.entry_price, 105.6055)

    def test_exit_execution_can_use_order_book_spread_feature(self):
        from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=4, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame(
                {
                    "Close": [100.0, 105.0, 110.0, 115.0],
                    "order_book_spread": [0.25, 1.0, 1.5, 2.0],
                },
                index=index,
            ),
        }
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([SignalOnSecondBar()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=PortfolioEngine(max_positions_per_symbol=1),
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            execution=BacktestExecutionConfig(slippage_bps=10.0, exit_spread_feature="order_book_spread"),
        )

        result = backtest.run(features_by_symbol)

        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades[0].exit_reason, "target")
        self.assertAlmostEqual(result.trades[0].exit_price, 113.886)
        self.assertAlmostEqual(result.trades[0].gross_pnl, 175.62)

    def test_closes_position_on_target_and_records_realized_trade(self):
        from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=4, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame({"Close": [100.0, 105.0, 110.0, 115.0]}, index=index),
        }
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([SignalOnSecondBar()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=PortfolioEngine(max_positions_per_symbol=1),
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            execution=BacktestExecutionConfig(fee_rate=0.001),
        )

        result = backtest.run(features_by_symbol)

        self.assertEqual(len(result.trades), 1)
        trade = result.trades[0]
        self.assertEqual(trade.exit_reason, "target")
        self.assertAlmostEqual(trade.entry_price, 105.0)
        self.assertAlmostEqual(trade.exit_price, 115.0)
        self.assertAlmostEqual(trade.gross_pnl, 200.0)
        self.assertAlmostEqual(trade.net_pnl, 195.6)
        self.assertEqual(trade.entry_timestamp, index[1])
        self.assertEqual(trade.exit_timestamp, index[3])
        self.assertEqual(trade.entry_bar_index, 1)
        self.assertEqual(trade.exit_bar_index, 3)
        self.assertEqual(trade.holding_bars, 2)
        self.assertEqual(result.state_history[-1].position_count, 0)
        self.assertAlmostEqual(result.realized_pnl, 200.0)
        self.assertAlmostEqual(result.fees_paid, 4.4)
        self.assertAlmostEqual(result.equity_curve[-1].unrealized_pnl, 0.0)
        self.assertAlmostEqual(result.equity_curve[-1].equity, 10195.6)

    def test_execution_can_partially_fill_triggered_target_exit_across_bars(self):
        from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=4, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame({"Close": [100.0, 105.0, 115.0, 120.0]}, index=index),
        }
        portfolio_engine = PortfolioEngine(max_positions_per_symbol=1)
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([SignalOnSecondBar()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=portfolio_engine,
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            execution=BacktestExecutionConfig(max_exit_fill_fraction_per_bar=0.5),
        )

        result = backtest.run(features_by_symbol)

        self.assertEqual(len(result.trades), 2)
        self.assertEqual([trade.exit_reason for trade in result.trades], ["target", "target"])
        self.assertAlmostEqual(result.trades[0].quantity, 10.0)
        self.assertAlmostEqual(result.trades[0].exit_price, 115.0)
        self.assertAlmostEqual(result.trades[0].gross_pnl, 100.0)
        self.assertAlmostEqual(result.trades[1].quantity, 10.0)
        self.assertAlmostEqual(result.trades[1].exit_price, 120.0)
        self.assertAlmostEqual(result.trades[1].gross_pnl, 150.0)
        self.assertEqual(result.state_history[2].position_count, 1)
        self.assertEqual(result.state_history[-1].position_count, 0)
        self.assertAlmostEqual(result.realized_pnl, 250.0)

    def test_execution_can_cap_triggered_target_exit_by_bar_volume_participation(self):
        from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=4, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame(
                {
                    "Close": [100.0, 105.0, 115.0, 120.0],
                    "Volume": [100.0, 100.0, 3.0, 50.0],
                },
                index=index,
            ),
        }
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([SignalOnSecondBar()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=PortfolioEngine(max_positions_per_symbol=1),
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            execution=BacktestExecutionConfig(max_exit_volume_fraction_per_bar=2.0),
        )

        result = backtest.run(features_by_symbol)

        self.assertEqual(len(result.trades), 2)
        self.assertAlmostEqual(result.trades[0].quantity, 6.0)
        self.assertAlmostEqual(result.trades[0].gross_pnl, 60.0)
        self.assertAlmostEqual(result.trades[1].quantity, 14.0)
        self.assertAlmostEqual(result.trades[1].gross_pnl, 210.0)
        self.assertAlmostEqual(result.realized_pnl, 270.0)

    def test_intrabar_target_fill_uses_high_low_trigger_price_when_enabled(self):
        from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=3, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame(
                {
                    "High": [101.0, 106.0, 116.0],
                    "Low": [99.0, 104.0, 111.0],
                    "Close": [100.0, 105.0, 112.0],
                },
                index=index,
            ),
        }
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([SignalOnSecondBar()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=PortfolioEngine(max_positions_per_symbol=1),
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            execution=BacktestExecutionConfig(fee_rate=0.001, intrabar_stop_target=True),
        )

        result = backtest.run(features_by_symbol)

        self.assertEqual(len(result.trades), 1)
        trade = result.trades[0]
        self.assertEqual(trade.exit_reason, "target")
        self.assertAlmostEqual(trade.entry_price, 105.0)
        self.assertAlmostEqual(trade.exit_price, 115.0)
        self.assertAlmostEqual(trade.gross_pnl, 200.0)
        self.assertAlmostEqual(result.realized_pnl, 200.0)
        self.assertAlmostEqual(result.fees_paid, 4.4)
        self.assertAlmostEqual(result.equity_curve[-1].equity, 10195.6)

    def test_fills_opposite_signal_close_order_and_records_realized_trade(self):
        from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, OrderStatus, PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=3, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame({"Close": [100.0, 105.0, 110.0]}, index=index),
        }
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([LongThenShortSignal()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=PortfolioEngine(max_positions_per_symbol=1, close_on_opposite_signal=True),
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            execution=BacktestExecutionConfig(fee_rate=0.001),
        )

        result = backtest.run(features_by_symbol)

        self.assertEqual([order.action for order in result.filled_orders], [OrderAction.OPEN, OrderAction.CLOSE])
        self.assertEqual(len(result.trades), 1)
        trade = result.trades[0]
        self.assertEqual(trade.exit_reason, "opposite_signal_close")
        self.assertEqual(trade.module, "breakout")
        self.assertEqual(trade.direction, Direction.LONG)
        self.assertAlmostEqual(trade.entry_price, 105.0)
        self.assertAlmostEqual(trade.exit_price, 110.0)
        self.assertAlmostEqual(trade.gross_pnl, 100.0)
        self.assertAlmostEqual(trade.entry_fee, 2.1)
        self.assertAlmostEqual(trade.exit_fee, 2.2)
        self.assertAlmostEqual(trade.net_pnl, 95.7)
        self.assertEqual(result.state_history[-1].position_count, 0)
        self.assertAlmostEqual(result.realized_pnl, 100.0)
        self.assertAlmostEqual(result.fees_paid, 4.3)
        self.assertAlmostEqual(result.equity_curve[-1].equity, 10095.7)

    def test_execution_can_partially_fill_close_order_across_bars(self):
        from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, OrderStatus, PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=4, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame({"Close": [100.0, 105.0, 110.0, 115.0]}, index=index),
        }
        portfolio_engine = PortfolioEngine(max_positions_per_symbol=1, close_on_opposite_signal=True)
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([LongThenShortSignal()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=portfolio_engine,
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            execution=BacktestExecutionConfig(max_exit_fill_fraction_per_bar=0.5),
        )

        result = backtest.run(features_by_symbol)

        self.assertEqual([order.action for order in result.filled_orders], [OrderAction.OPEN, OrderAction.CLOSE, OrderAction.CLOSE])
        self.assertEqual(result.filled_orders[1].status, OrderStatus.PARTIALLY_FILLED)
        self.assertEqual(result.filled_orders[2].status, OrderStatus.FILLED)
        self.assertAlmostEqual(result.filled_orders[1].filled_quantity, 10.0)
        self.assertAlmostEqual(result.filled_orders[2].filled_quantity, 10.0)
        self.assertEqual(len(result.trades), 2)
        self.assertAlmostEqual(result.trades[0].quantity, 10.0)
        self.assertAlmostEqual(result.trades[0].exit_price, 110.0)
        self.assertAlmostEqual(result.trades[0].gross_pnl, 50.0)
        self.assertAlmostEqual(result.trades[1].quantity, 10.0)
        self.assertAlmostEqual(result.trades[1].exit_price, 115.0)
        self.assertAlmostEqual(result.trades[1].gross_pnl, 100.0)
        self.assertEqual(result.state_history[-1].position_count, 0)
        self.assertAlmostEqual(result.realized_pnl, 150.0)

    def test_execution_can_cap_exit_fills_by_bar_volume_participation(self):
        from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=4, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame(
                {
                    "Close": [100.0, 105.0, 110.0, 115.0],
                    "Volume": [100.0, 100.0, 3.0, 50.0],
                },
                index=index,
            ),
        }
        portfolio_engine = PortfolioEngine(max_positions_per_symbol=1, close_on_opposite_signal=True)
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([LongThenShortSignal()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=portfolio_engine,
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            execution=BacktestExecutionConfig(max_exit_volume_fraction_per_bar=2.0),
        )

        result = backtest.run(features_by_symbol)

        self.assertEqual([order.action for order in result.filled_orders], [OrderAction.OPEN, OrderAction.CLOSE, OrderAction.CLOSE])
        self.assertAlmostEqual(result.filled_orders[1].filled_quantity, 6.0)
        self.assertAlmostEqual(result.filled_orders[2].filled_quantity, 14.0)
        self.assertEqual(len(result.trades), 2)
        self.assertAlmostEqual(result.trades[0].gross_pnl, 30.0)
        self.assertAlmostEqual(result.trades[1].gross_pnl, 140.0)
        self.assertAlmostEqual(result.realized_pnl, 170.0)

    def test_execution_can_cancel_stale_unfilled_close_order(self):
        from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, OrderStatus, PortfolioEngine, PositionKey
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=5, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame(
                {
                    "Close": [100.0, 105.0, 110.0, 111.0, 112.0],
                    "Volume": [100.0, 100.0, 0.0, 0.0, 0.0],
                },
                index=index,
            ),
        }
        portfolio_engine = PortfolioEngine(max_positions_per_symbol=1, close_on_opposite_signal=True)
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([LongThenShortSignal()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=portfolio_engine,
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            execution=BacktestExecutionConfig(max_exit_volume_fraction_per_bar=0.0, max_exit_order_age_bars=1),
        )

        result = backtest.run(features_by_symbol)

        self.assertEqual([order.action for order in result.filled_orders], [OrderAction.OPEN])
        self.assertEqual([order.status for order in result.terminal_orders], [OrderStatus.CANCELED])
        self.assertEqual(result.terminal_orders[0].action, OrderAction.CLOSE)
        self.assertEqual(result.terminal_orders[0].reason, "exit_order_expired")
        self.assertEqual(result.state_history[-1].submitted_order_count, 0)
        self.assertEqual(result.state_history[-1].position_count, 1)
        self.assertIn(PositionKey("BTC/USDT", "tactical"), portfolio_engine.state.positions)
        self.assertEqual(result.order_status_counts[OrderStatus.SUBMITTED], 0)
        self.assertEqual(result.order_status_counts[OrderStatus.CANCELED], 1)

    def test_execution_can_cancel_stale_partially_filled_close_order_remainder(self):
        from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, OrderStatus, PortfolioEngine, PositionKey
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=5, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame(
                {
                    "Close": [100.0, 105.0, 110.0, 111.0, 112.0],
                    "Volume": [100.0, 100.0, 10.0, 0.0, 0.0],
                },
                index=index,
            ),
        }
        portfolio_engine = PortfolioEngine(max_positions_per_symbol=1, close_on_opposite_signal=True)
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([LongThenShortSignal()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=portfolio_engine,
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            execution=BacktestExecutionConfig(max_exit_volume_fraction_per_bar=1.0, max_exit_order_age_bars=1),
        )

        result = backtest.run(features_by_symbol)

        self.assertEqual([order.action for order in result.filled_orders], [OrderAction.OPEN, OrderAction.CLOSE])
        self.assertEqual(result.filled_orders[1].status, OrderStatus.PARTIALLY_FILLED)
        self.assertAlmostEqual(result.filled_orders[1].filled_quantity, 10.0)
        self.assertEqual([order.status for order in result.terminal_orders], [OrderStatus.CANCELED])
        self.assertEqual(result.terminal_orders[0].reason, "exit_order_expired")
        self.assertAlmostEqual(result.terminal_orders[0].filled_quantity, 10.0)
        self.assertEqual(len(result.trades), 1)
        self.assertAlmostEqual(result.trades[0].quantity, 10.0)
        self.assertAlmostEqual(result.trades[0].gross_pnl, 50.0)
        position = portfolio_engine.state.positions[PositionKey("BTC/USDT", "tactical")]
        self.assertAlmostEqual(position.quantity, 10.0)
        self.assertEqual(result.state_history[-1].submitted_order_count, 0)
        self.assertEqual(result.order_status_counts[OrderStatus.CANCELED], 1)
        self.assertEqual(result.order_status_counts[OrderStatus.PARTIALLY_FILLED], 0)

    def test_fills_opposite_signal_close_and_open_reversal_orders(self):
        from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, PortfolioEngine, PositionKey
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=3, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame({"Close": [100.0, 105.0, 110.0]}, index=index),
        }
        portfolio_engine = PortfolioEngine(max_positions_per_symbol=1, reverse_on_opposite_signal=True)
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([LongThenShortSignal()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=portfolio_engine,
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            execution=BacktestExecutionConfig(fee_rate=0.001),
        )

        result = backtest.run(features_by_symbol)

        self.assertEqual(
            [order.action for order in result.filled_orders],
            [OrderAction.OPEN, OrderAction.CLOSE, OrderAction.OPEN],
        )
        self.assertEqual(result.filled_orders[2].reason, "opposite_signal_open")
        self.assertEqual(len(result.trades), 1)
        trade = result.trades[0]
        self.assertEqual(trade.exit_reason, "opposite_signal_close")
        self.assertEqual(trade.direction, Direction.LONG)
        self.assertAlmostEqual(trade.entry_price, 105.0)
        self.assertAlmostEqual(trade.exit_price, 110.0)
        self.assertAlmostEqual(trade.gross_pnl, 100.0)
        position = portfolio_engine.state.positions[PositionKey("BTC/USDT", "tactical")]
        self.assertEqual(position.direction, Direction.SHORT)
        self.assertEqual(position.module, "crash_short")
        self.assertAlmostEqual(position.quantity, 20.1958)
        self.assertAlmostEqual(position.entry_price, 110.0)
        self.assertEqual(result.state_history[-1].position_count, 1)
        self.assertAlmostEqual(result.realized_pnl, 100.0)
        self.assertAlmostEqual(result.fees_paid, 6.521538)
        self.assertAlmostEqual(result.equity_curve[-1].cash, 10093.478462)
        self.assertAlmostEqual(result.equity_curve[-1].unrealized_pnl, 0.0)
        self.assertAlmostEqual(result.equity_curve[-1].equity, 10093.478462)

    def test_fills_rebalance_scale_in_order_and_updates_position(self):
        from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, PortfolioEngine, PositionKey
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=3, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame({"Close": [100.0, 105.0, 110.0]}, index=index),
        }
        portfolio_engine = PortfolioEngine(max_positions_per_symbol=1, rebalance_existing=True)
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([LongThenScaleInSignal()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=portfolio_engine,
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            execution=BacktestExecutionConfig(fee_rate=0.001),
        )

        result = backtest.run(features_by_symbol)

        self.assertEqual([order.action for order in result.filled_orders], [OrderAction.OPEN, OrderAction.REBALANCE])
        self.assertEqual(result.filled_orders[1].reason, "increase_position")
        self.assertAlmostEqual(result.filled_orders[1].quantity, 20.3916)
        position = portfolio_engine.state.positions[PositionKey("BTC/USDT", "tactical")]
        self.assertAlmostEqual(position.quantity, 40.3916)
        self.assertAlmostEqual(position.notional, 4343.076)
        self.assertAlmostEqual(position.entry_price, 107.5242, places=4)
        self.assertAlmostEqual(result.fees_paid, 4.343076)
        self.assertAlmostEqual(result.equity_curve[-1].cash, 9995.656924)
        self.assertAlmostEqual(result.equity_curve[-1].unrealized_pnl, 100.0)
        self.assertAlmostEqual(result.equity_curve[-1].equity, 10095.656924)

    def test_fills_rebalance_reduce_order_and_records_realized_trade(self):
        from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, PortfolioEngine, PositionKey
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=3, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame({"Close": [100.0, 105.0, 110.0]}, index=index),
        }
        portfolio_engine = PortfolioEngine(max_positions_per_symbol=1, rebalance_existing=True)
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([LongThenScaleDownSignal()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=portfolio_engine,
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            execution=BacktestExecutionConfig(fee_rate=0.001),
        )

        result = backtest.run(features_by_symbol)

        self.assertEqual([order.action for order in result.filled_orders], [OrderAction.OPEN, OrderAction.REBALANCE])
        self.assertEqual(result.filled_orders[1].reason, "decrease_position")
        self.assertAlmostEqual(result.filled_orders[1].quantity, 19.6084)
        self.assertEqual(len(result.trades), 1)
        trade = result.trades[0]
        self.assertEqual(trade.exit_reason, "decrease_position")
        self.assertEqual(trade.module, "breakout")
        self.assertEqual(trade.direction, Direction.LONG)
        self.assertAlmostEqual(trade.entry_price, 105.0)
        self.assertAlmostEqual(trade.exit_price, 110.0)
        self.assertAlmostEqual(trade.quantity, 19.6084)
        self.assertAlmostEqual(trade.gross_pnl, 98.042)
        self.assertAlmostEqual(trade.entry_fee, 2.058882)
        self.assertAlmostEqual(trade.exit_fee, 2.156924)
        self.assertAlmostEqual(trade.net_pnl, 93.826194)
        position = portfolio_engine.state.positions[PositionKey("BTC/USDT", "tactical")]
        self.assertAlmostEqual(position.quantity, 20.3916)
        self.assertAlmostEqual(position.notional, 2141.118)
        self.assertAlmostEqual(position.entry_price, 105.0)
        self.assertAlmostEqual(result.realized_pnl, 98.042)
        self.assertAlmostEqual(result.fees_paid, 6.356924)
        self.assertAlmostEqual(result.equity_curve[-1].cash, 10091.685076)
        self.assertAlmostEqual(result.equity_curve[-1].unrealized_pnl, 101.958)
        self.assertAlmostEqual(result.equity_curve[-1].equity, 10193.643076)

    def test_records_filled_layer_transfer_orders_in_event_result(self):
        from quant_platform.backtest import EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import OrderAction, PortfolioEngine, PositionKey
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=3, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame({"Close": [100.0, 105.0, 110.0]}, index=index),
        }
        portfolio_engine = PortfolioEngine(
            layer_by_module={"core_long": "core"},
            max_positions_per_symbol=2,
            transfer_existing_layer=True,
        )
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([LongThenCoreTransferSignal()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=portfolio_engine,
        )
        backtest = EventDrivenBacktest(pipeline=pipeline, account=AccountState(equity=10_000.0))

        result = backtest.run(features_by_symbol)

        self.assertEqual([order.action for order in result.filled_orders], [OrderAction.OPEN, OrderAction.TRANSFER])
        transfer = result.filled_orders[1]
        self.assertEqual(transfer.reason, "layer_transfer")
        self.assertEqual(transfer.layer, "core")
        self.assertEqual(result.state_history[-1].position_count, 1)
        self.assertNotIn(PositionKey("BTC/USDT", "tactical"), portfolio_engine.state.positions)
        self.assertIn(PositionKey("BTC/USDT", "core"), portfolio_engine.state.positions)

    def test_summarizes_realized_trade_attribution_by_symbol_layer_and_module(self):
        from quant_platform.backtest import EventDrivenBacktest
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=4, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC/USDT": pd.DataFrame({"Close": [100.0, 105.0, 110.0, 115.0]}, index=index),
            "ETH/USDT": pd.DataFrame({"Close": [50.0, 55.0, 60.0, 65.0]}, index=index),
        }
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([SignalOnSecondBar()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=PortfolioEngine(max_positions_per_symbol=1),
        )
        backtest = EventDrivenBacktest(pipeline=pipeline, account=AccountState(equity=10_000.0))

        result = backtest.run(features_by_symbol)

        self.assertEqual(result.attribution.by_symbol["BTC/USDT"].trade_count, 1)
        self.assertEqual(result.attribution.by_symbol["ETH/USDT"].trade_count, 1)
        self.assertAlmostEqual(result.attribution.by_symbol["BTC/USDT"].gross_pnl, 200.0)
        self.assertAlmostEqual(result.attribution.by_symbol["ETH/USDT"].gross_pnl, 200.0)
        self.assertAlmostEqual(result.attribution.by_symbol["BTC/USDT"].win_rate, 1.0)
        self.assertEqual(result.attribution.by_layer["tactical"].trade_count, 2)
        self.assertAlmostEqual(result.attribution.by_layer["tactical"].net_pnl, 400.0)
        self.assertAlmostEqual(result.attribution.by_layer["tactical"].average_holding_bars, 2.0)
        self.assertEqual(result.attribution.by_module["breakout"].trade_count, 2)
        self.assertAlmostEqual(result.attribution.by_module["breakout"].gross_pnl, 400.0)
        self.assertAlmostEqual(result.attribution.by_module["breakout"].average_holding_bars, 2.0)

    def test_summarizes_realized_trade_attribution_by_direction(self):
        from quant_platform.backtest import BacktestTrade, EventDrivenBacktestResult

        result = EventDrivenBacktestResult(
            steps=[],
            trades=[
                BacktestTrade(
                    symbol="BTC/USDT",
                    layer="tactical",
                    module="breakout",
                    direction=Direction.LONG,
                    entry_price=100.0,
                    exit_price=110.0,
                    quantity=10.0,
                    gross_pnl=100.0,
                    entry_fee=1.0,
                    exit_fee=1.0,
                    net_pnl=98.0,
                    exit_reason="target",
                    holding_bars=2,
                ),
                BacktestTrade(
                    symbol="ETH/USDT",
                    layer="tactical",
                    module="failed_bounce",
                    direction=Direction.SHORT,
                    entry_price=50.0,
                    exit_price=55.0,
                    quantity=5.0,
                    gross_pnl=-25.0,
                    entry_fee=0.5,
                    exit_fee=0.5,
                    net_pnl=-26.0,
                    exit_reason="stop",
                    holding_bars=4,
                ),
            ],
        )

        self.assertEqual(result.attribution.by_direction["long"].trade_count, 1)
        self.assertAlmostEqual(result.attribution.by_direction["long"].net_pnl, 98.0)
        self.assertAlmostEqual(result.attribution.by_direction["long"].gross_profit, 98.0)
        self.assertAlmostEqual(result.attribution.by_direction["long"].gross_loss, 0.0)
        self.assertIsNone(result.attribution.by_direction["long"].profit_factor)
        self.assertEqual(result.attribution.by_direction["short"].trade_count, 1)
        self.assertAlmostEqual(result.attribution.by_direction["short"].net_pnl, -26.0)
        self.assertAlmostEqual(result.attribution.by_direction["short"].average_holding_bars, 4.0)
        self.assertEqual(result.attribution.by_exit_reason["target"].trade_count, 1)
        self.assertAlmostEqual(result.attribution.by_exit_reason["target"].net_pnl, 98.0)
        self.assertEqual(result.attribution.by_exit_reason["stop"].trade_count, 1)
        self.assertAlmostEqual(result.attribution.by_exit_reason["stop"].average_holding_bars, 4.0)
        self.assertAlmostEqual(result.attribution.by_layer["tactical"].gross_profit, 98.0)
        self.assertAlmostEqual(result.attribution.by_layer["tactical"].gross_loss, 26.0)
        self.assertAlmostEqual(result.attribution.by_layer["tactical"].profit_factor, 98.0 / 26.0)
        self.assertAlmostEqual(result.attribution.by_layer["tactical"].payoff_ratio, 98.0 / 26.0)

    def test_summarizes_terminal_order_reasons(self):
        from quant_platform.backtest import EventDrivenBacktestResult
        from quant_platform.portfolio import OrderAction, OrderStatus, PortfolioOrder

        result = EventDrivenBacktestResult(
            steps=[],
            terminal_orders=[
                PortfolioOrder(
                    order_id="entry-1",
                    action=OrderAction.OPEN,
                    symbol="BTC/USDT",
                    layer="tactical",
                    direction=Direction.LONG,
                    quantity=10.0,
                    reason="entry_order_expired",
                    status=OrderStatus.CANCELED,
                ),
                PortfolioOrder(
                    order_id="entry-2",
                    action=OrderAction.OPEN,
                    symbol="ETH/USDT",
                    layer="tactical",
                    direction=Direction.LONG,
                    quantity=5.0,
                    reason="entry_order_expired",
                    status=OrderStatus.CANCELED,
                ),
                PortfolioOrder(
                    order_id="exit-1",
                    action=OrderAction.CLOSE,
                    symbol="BTC/USDT",
                    layer="tactical",
                    direction=Direction.LONG,
                    quantity=10.0,
                    reason="exit_order_expired",
                    status=OrderStatus.CANCELED,
                ),
            ],
        )

        self.assertEqual(result.terminal_order_reason_counts, {
            "entry_order_expired": 2,
            "exit_order_expired": 1,
        })

    def test_summarizes_order_actions(self):
        from quant_platform.backtest import EventDrivenBacktestResult
        from quant_platform.portfolio import OrderAction, OrderStatus, PortfolioOrder

        result = EventDrivenBacktestResult(
            steps=[],
            filled_orders=[
                PortfolioOrder(
                    order_id="open-1",
                    action=OrderAction.OPEN,
                    symbol="BTC/USDT",
                    layer="tactical",
                    direction=Direction.LONG,
                    quantity=10.0,
                    reason="breakout",
                    status=OrderStatus.FILLED,
                ),
            ],
            terminal_orders=[
                PortfolioOrder(
                    order_id="open-2",
                    action=OrderAction.OPEN,
                    symbol="ETH/USDT",
                    layer="tactical",
                    direction=Direction.LONG,
                    quantity=5.0,
                    reason="entry_order_expired",
                    status=OrderStatus.CANCELED,
                ),
                PortfolioOrder(
                    order_id="close-1",
                    action=OrderAction.CLOSE,
                    symbol="BTC/USDT",
                    layer="tactical",
                    direction=Direction.LONG,
                    quantity=10.0,
                    reason="exit_order_expired",
                    status=OrderStatus.CANCELED,
                ),
            ],
        )

        self.assertEqual(result.order_action_counts[OrderAction.OPEN], 2)
        self.assertEqual(result.order_action_counts[OrderAction.CLOSE], 1)
        self.assertEqual(result.order_action_counts[OrderAction.REBALANCE], 0)

    def test_summarizes_order_modules(self):
        from quant_platform.backtest import EventDrivenBacktestResult
        from quant_platform.portfolio import OrderAction, OrderStatus, PortfolioOrder
        from quant_platform.risk import RiskDecision

        breakout_signal = Signal(
            module="breakout",
            symbol="BTC/USDT",
            direction=Direction.LONG,
            score=80.0,
            entry_reason="breakout",
            invalidation="stop",
            preferred_stop=95.0,
            preferred_target=120.0,
            confidence=0.8,
        )
        pullback_signal = Signal(
            module="pullback",
            symbol="ETH/USDT",
            direction=Direction.LONG,
            score=70.0,
            entry_reason="pullback",
            invalidation="stop",
            preferred_stop=90.0,
            preferred_target=115.0,
            confidence=0.7,
        )
        result = EventDrivenBacktestResult(
            steps=[],
            filled_orders=[
                PortfolioOrder(
                    order_id="open-1",
                    action=OrderAction.OPEN,
                    symbol="BTC/USDT",
                    layer="tactical",
                    direction=Direction.LONG,
                    quantity=10.0,
                    reason="breakout",
                    status=OrderStatus.FILLED,
                    decision=RiskDecision(allowed=True, reason="allowed", signal=breakout_signal),
                ),
            ],
            terminal_orders=[
                PortfolioOrder(
                    order_id="open-2",
                    action=OrderAction.OPEN,
                    symbol="BTC/USDT",
                    layer="tactical",
                    direction=Direction.LONG,
                    quantity=5.0,
                    reason="entry_order_expired",
                    status=OrderStatus.CANCELED,
                    decision=RiskDecision(allowed=True, reason="allowed", signal=breakout_signal),
                ),
                PortfolioOrder(
                    order_id="open-3",
                    action=OrderAction.OPEN,
                    symbol="ETH/USDT",
                    layer="tactical",
                    direction=Direction.LONG,
                    quantity=3.0,
                    reason="entry_order_expired",
                    status=OrderStatus.CANCELED,
                    decision=RiskDecision(allowed=True, reason="allowed", signal=pullback_signal),
                ),
            ],
        )

        self.assertEqual(result.order_module_counts, {"breakout": 2, "pullback": 1})

    def test_summarizes_order_symbols_and_layers(self):
        from quant_platform.backtest import EventDrivenBacktestResult
        from quant_platform.portfolio import OrderAction, OrderStatus, PortfolioOrder

        result = EventDrivenBacktestResult(
            steps=[],
            filled_orders=[
                PortfolioOrder(
                    order_id="btc-core-open",
                    action=OrderAction.OPEN,
                    symbol="BTC/USDT",
                    layer="core",
                    direction=Direction.LONG,
                    quantity=10.0,
                    reason="core long",
                    status=OrderStatus.FILLED,
                ),
            ],
            terminal_orders=[
                PortfolioOrder(
                    order_id="btc-tactical-open",
                    action=OrderAction.OPEN,
                    symbol="BTC/USDT",
                    layer="tactical",
                    direction=Direction.LONG,
                    quantity=5.0,
                    reason="entry_order_expired",
                    status=OrderStatus.CANCELED,
                ),
                PortfolioOrder(
                    order_id="eth-tactical-open",
                    action=OrderAction.OPEN,
                    symbol="ETH/USDT",
                    layer="tactical",
                    direction=Direction.LONG,
                    quantity=3.0,
                    reason="entry_order_expired",
                    status=OrderStatus.CANCELED,
                ),
            ],
        )

        self.assertEqual(result.order_symbol_counts, {"BTC/USDT": 2, "ETH/USDT": 1})
        self.assertEqual(result.order_layer_counts, {"core": 1, "tactical": 2})

    def test_uses_market_spec_fee_multiplier_and_funding_for_accounting(self):
        from quant_platform.backtest import EventDrivenBacktest
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.pipeline import SignalPipeline
        from quant_platform.portfolio import PortfolioEngine
        from quant_platform.risk import AccountState, RiskEngine, RiskLimits
        from quant_platform.signal_modules import SignalModuleRunner

        index = pd.date_range("2026-06-03", periods=4, freq="4h", tz="UTC")
        features_by_symbol = {
            "BTC-PERP": pd.DataFrame({"Close": [100.0, 105.0, 110.0, 115.0]}, index=index),
        }
        markets_by_symbol = {
            "BTC-PERP": MarketSpec(
                asset=AssetSpec(symbol="BTC-PERP", base="BTC", quote="USDT"),
                exchange="binance",
                market_type="perp",
                fee_rate=0.002,
                funding_rate=0.0001,
                contract_multiplier=0.5,
                supports_short=True,
                supports_leverage=True,
            )
        }
        pipeline = SignalPipeline(
            signal_runner=SignalModuleRunner([SignalOnSecondBar()]),
            risk_engine=RiskEngine(RiskLimits(risk_per_trade=0.01, max_position_fraction=1.0)),
            portfolio_engine=PortfolioEngine(max_positions_per_symbol=1),
        )
        backtest = EventDrivenBacktest(
            pipeline=pipeline,
            account=AccountState(equity=10_000.0),
            markets_by_symbol=markets_by_symbol,
        )

        result = backtest.run(features_by_symbol)

        trade = result.trades[0]
        self.assertAlmostEqual(trade.gross_pnl, 100.0)
        self.assertAlmostEqual(trade.entry_fee, 2.1)
        self.assertAlmostEqual(trade.exit_fee, 2.3)
        self.assertAlmostEqual(trade.net_pnl, 95.6)
        self.assertAlmostEqual(result.funding_paid, 0.315)
        self.assertAlmostEqual(result.fees_paid, 4.4)
        self.assertAlmostEqual(result.equity_curve[-1].equity, 10095.285)


if __name__ == "__main__":
    unittest.main()
