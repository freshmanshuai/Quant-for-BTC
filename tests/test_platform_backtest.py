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
        self.assertEqual(result.state_history[-1].position_count, 0)
        self.assertAlmostEqual(result.realized_pnl, 200.0)
        self.assertAlmostEqual(result.fees_paid, 4.4)
        self.assertAlmostEqual(result.equity_curve[-1].unrealized_pnl, 0.0)
        self.assertAlmostEqual(result.equity_curve[-1].equity, 10195.6)

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
        self.assertEqual(result.attribution.by_module["breakout"].trade_count, 2)
        self.assertAlmostEqual(result.attribution.by_module["breakout"].gross_pnl, 400.0)

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
