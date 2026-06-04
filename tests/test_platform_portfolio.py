import unittest

from quant_platform.risk import RiskDecision
from quant_platform.signals import Direction, Signal


class PortfolioEngineTest(unittest.TestCase):
    def _signal(
        self,
        module="breakout",
        symbol="BTC/USDT",
        direction=Direction.LONG,
        score=80.0,
        preferred_target=120.0,
    ):
        return Signal(
            module=module,
            symbol=symbol,
            direction=direction,
            score=score,
            entry_reason=module,
            invalidation="stop",
            preferred_stop=95.0,
            preferred_target=preferred_target,
            confidence=score / 100.0,
        )

    def _decision(self, signal, quantity=2.0, notional=200.0, risk_amount=10.0):
        return RiskDecision(
            allowed=True,
            reason="allowed",
            signal=signal,
            quantity=quantity,
            notional=notional,
            risk_amount=risk_amount,
            entry_price=100.0,
            stop_price=95.0,
            max_loss_per_unit=5.0,
        )

    def test_quantizes_orders_and_positions_with_market_spec_steps(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.portfolio import PortfolioEngine, PositionKey

        market = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
            tick_size=0.01,
            lot_size=0.001,
        )
        signal = self._signal(preferred_target=120.019)
        decision = RiskDecision(
            allowed=True,
            reason="allowed",
            signal=signal,
            quantity=0.123456,
            notional=12_345.60,
            risk_amount=5.0,
            entry_price=100.019,
            stop_price=95.019,
            max_loss_per_unit=5.0,
        )

        engine = PortfolioEngine(markets_by_symbol={"BTC/USDT": market})
        order = engine.apply([decision]).orders[0]
        position = engine.state.positions[PositionKey("BTC/USDT", "tactical")]

        self.assertEqual(order.quantity, 0.123)
        self.assertEqual(position.quantity, 0.123)
        self.assertEqual(position.entry_price, 100.01)
        self.assertEqual(position.stop_price, 95.01)
        self.assertEqual(position.target_price, 120.01)
        self.assertAlmostEqual(position.notional, 12.30123)

    def test_opens_multiple_symbols_and_tracks_open_risk(self):
        from quant_platform.portfolio import OrderAction, PortfolioEngine

        engine = PortfolioEngine()
        plan = engine.apply([
            self._decision(self._signal(symbol="BTC/USDT")),
            self._decision(self._signal(symbol="ETH/USDT"), quantity=5.0, notional=500.0, risk_amount=25.0),
        ])

        self.assertEqual([order.action for order in plan.orders], [OrderAction.OPEN, OrderAction.OPEN])
        self.assertEqual(len(engine.state.positions), 2)
        self.assertAlmostEqual(engine.state.open_risk(), 35.0)

    def test_allows_core_and_tactical_layers_for_same_symbol(self):
        from quant_platform.portfolio import OrderAction, PortfolioEngine, PositionKey

        engine = PortfolioEngine(layer_by_module={"core_long": "core", "breakout": "tactical"})
        plan = engine.apply([
            self._decision(self._signal(module="core_long", score=70.0), quantity=1.0),
            self._decision(self._signal(module="breakout", score=82.0), quantity=2.0),
        ])

        self.assertEqual([order.action for order in plan.orders], [OrderAction.OPEN, OrderAction.OPEN])
        self.assertIn(PositionKey("BTC/USDT", "core"), engine.state.positions)
        self.assertIn(PositionKey("BTC/USDT", "tactical"), engine.state.positions)

    def test_same_layer_conflict_keeps_highest_score_signal(self):
        from quant_platform.portfolio import OrderAction, PortfolioEngine, PositionKey

        engine = PortfolioEngine()
        plan = engine.apply([
            self._decision(self._signal(module="pullback", direction=Direction.LONG, score=65.0)),
            self._decision(self._signal(module="breakout", direction=Direction.SHORT, score=90.0)),
        ])

        self.assertEqual([order.action for order in plan.orders], [OrderAction.OPEN, OrderAction.IGNORE])
        self.assertEqual(plan.orders[1].reason, "conflicting_signal_lost")
        position = engine.state.positions[PositionKey("BTC/USDT", "tactical")]
        self.assertEqual(position.direction, Direction.SHORT)
        self.assertEqual(position.module, "breakout")

    def test_blocks_cross_layer_hedge_when_hedging_is_disabled(self):
        from quant_platform.portfolio import OrderAction, PortfolioEngine

        engine = PortfolioEngine(layer_by_module={"core_long": "core", "crash_short": "tactical"}, allow_hedging=False)
        plan = engine.apply([
            self._decision(self._signal(module="core_long", direction=Direction.LONG, score=80.0)),
            self._decision(self._signal(module="crash_short", direction=Direction.SHORT, score=92.0)),
        ])

        self.assertEqual([order.action for order in plan.orders], [OrderAction.OPEN, OrderAction.IGNORE])
        self.assertEqual(plan.orders[1].reason, "hedging_disabled")
        self.assertEqual(len(engine.state.positions), 1)

    def test_ignores_blocked_risk_decisions(self):
        from quant_platform.portfolio import OrderAction, PortfolioEngine

        blocked = RiskDecision(
            allowed=False,
            reason="daily_drawdown_limit",
            signal=self._signal(),
            entry_price=100.0,
        )
        plan = PortfolioEngine().apply([blocked])

        self.assertEqual(plan.orders[0].action, OrderAction.IGNORE)
        self.assertEqual(plan.orders[0].reason, "risk_blocked:daily_drawdown_limit")

    def test_tracks_submitted_partial_and_filled_order_state(self):
        from quant_platform.portfolio import OrderStatus, PortfolioEngine, PositionKey

        engine = PortfolioEngine()
        plan = engine.apply([self._decision(self._signal(), quantity=10.0)])
        order = plan.orders[0]

        self.assertEqual(order.status, OrderStatus.SUBMITTED)
        self.assertIn(order.order_id, engine.state.orders)

        partial = engine.record_fill(order.order_id, filled_quantity=4.0, fill_price=101.0)
        filled = engine.record_fill(order.order_id, filled_quantity=6.0, fill_price=102.0)

        self.assertEqual(partial.status, OrderStatus.PARTIALLY_FILLED)
        self.assertEqual(partial.filled_quantity, 4.0)
        self.assertEqual(filled.status, OrderStatus.FILLED)
        self.assertEqual(filled.filled_quantity, 10.0)
        self.assertAlmostEqual(filled.average_fill_price, 101.6)
        position = engine.state.positions[PositionKey("BTC/USDT", "tactical")]
        self.assertAlmostEqual(position.entry_price, 101.6)
        self.assertAlmostEqual(position.notional, 1016.0)

    def test_cancels_and_rejects_unfilled_orders(self):
        from quant_platform.portfolio import OrderStatus, PortfolioEngine

        cancel_engine = PortfolioEngine()
        cancel_order = cancel_engine.apply([self._decision(self._signal())]).orders[0]
        canceled = cancel_engine.cancel_order(cancel_order.order_id, reason="stale_signal")

        reject_engine = PortfolioEngine()
        reject_order = reject_engine.apply([self._decision(self._signal(symbol="ETH/USDT"))]).orders[0]
        rejected = reject_engine.reject_order(reject_order.order_id, reason="exchange_rejected")

        self.assertEqual(canceled.status, OrderStatus.CANCELED)
        self.assertEqual(canceled.reason, "stale_signal")
        self.assertEqual(rejected.status, OrderStatus.REJECTED)
        self.assertEqual(rejected.reason, "exchange_rejected")

    def test_closes_position_and_supports_partial_reduce(self):
        from quant_platform.portfolio import OrderAction, OrderStatus, PortfolioEngine, PositionKey

        engine = PortfolioEngine()
        open_order = engine.apply([self._decision(self._signal(), quantity=10.0)]).orders[0]
        engine.record_fill(open_order.order_id, filled_quantity=10.0, fill_price=100.0)

        partial = engine.close_position("BTC/USDT", "tactical", quantity=4.0, fill_price=110.0, reason="target")
        position = engine.state.positions[PositionKey("BTC/USDT", "tactical")]
        final = engine.close_position("BTC/USDT", "tactical", fill_price=112.0, reason="manual")

        self.assertEqual(partial.action, OrderAction.CLOSE)
        self.assertEqual(partial.status, OrderStatus.FILLED)
        self.assertEqual(partial.filled_quantity, 4.0)
        self.assertAlmostEqual(position.quantity, 6.0)
        self.assertAlmostEqual(position.risk_amount, 6.0)
        self.assertEqual(final.action, OrderAction.CLOSE)
        self.assertEqual(final.filled_quantity, 6.0)
        self.assertNotIn(PositionKey("BTC/USDT", "tactical"), engine.state.positions)


if __name__ == "__main__":
    unittest.main()
