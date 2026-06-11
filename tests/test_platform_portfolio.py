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

    def test_contract_multiplier_scales_position_notional_for_market_specs(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.portfolio import OrderStatus, PortfolioEngine, PositionKey

        market = MarketSpec(
            asset=AssetSpec(symbol="ES", base="ES", quote="USD"),
            exchange="cme",
            market_type="future",
            tick_size=0.01,
            lot_size=0.1,
            contract_multiplier=100.0,
        )
        signal = self._signal(symbol="ES", preferred_target=12.019)
        decision = RiskDecision(
            allowed=True,
            reason="allowed",
            signal=signal,
            quantity=1.234,
            notional=1_234.0,
            risk_amount=120.0,
            entry_price=10.019,
            stop_price=9.019,
            max_loss_per_unit=100.0,
        )

        engine = PortfolioEngine(markets_by_symbol={"ES": market})
        order = engine.apply([decision]).orders[0]
        position = engine.state.positions[PositionKey("ES", "tactical")]

        self.assertEqual(order.quantity, 1.2)
        self.assertAlmostEqual(position.notional, 1_201.2)

        filled = engine.record_fill(order.order_id, filled_quantity=1.2, fill_price=10.5)
        filled_position = engine.state.positions[PositionKey("ES", "tactical")]

        self.assertEqual(filled.status, OrderStatus.FILLED)
        self.assertAlmostEqual(filled_position.notional, 1_260.0)
        self.assertAlmostEqual(filled_position.entry_price, 10.5)

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

    def test_can_cancel_partially_filled_order_remainder(self):
        from quant_platform.portfolio import OrderStatus, PortfolioEngine, PositionKey

        engine = PortfolioEngine()
        order = engine.apply([self._decision(self._signal(), quantity=10.0)]).orders[0]
        engine.record_fill(order.order_id, filled_quantity=4.0, fill_price=101.0)

        canceled = engine.cancel_order(order.order_id, reason="stale_remainder")

        self.assertEqual(canceled.status, OrderStatus.CANCELED)
        self.assertEqual(canceled.reason, "stale_remainder")
        self.assertEqual(canceled.filled_quantity, 4.0)
        self.assertAlmostEqual(canceled.average_fill_price, 101.0)
        self.assertEqual(engine.state.orders[order.order_id].status, OrderStatus.CANCELED)
        position = engine.state.positions[PositionKey("BTC/USDT", "tactical")]
        self.assertAlmostEqual(position.quantity, 4.0)

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

    def test_close_position_quantizes_explicit_partial_quantity_to_market_lot(self):
        from quant_platform.core import AssetSpec, MarketSpec
        from quant_platform.portfolio import PortfolioEngine, PortfolioState, Position, PositionKey

        market = MarketSpec(
            asset=AssetSpec(symbol="BTC/USDT", base="BTC", quote="USDT"),
            exchange="binance",
            market_type="swap",
            lot_size=0.1,
        )
        key = PositionKey("BTC/USDT", "tactical")
        state = PortfolioState(positions={
            key: Position(
                symbol="BTC/USDT",
                layer="tactical",
                direction=Direction.LONG,
                quantity=1.2,
                notional=120.0,
                risk_amount=12.0,
                module="breakout",
                entry_price=100.0,
                stop_price=95.0,
                target_price=120.0,
            )
        })
        engine = PortfolioEngine(state=state, markets_by_symbol={"BTC/USDT": market})

        order = engine.close_position("BTC/USDT", "tactical", quantity=0.26, fill_price=110.0, reason="target")
        position = engine.state.positions[key]

        self.assertEqual(order.quantity, 0.2)
        self.assertEqual(order.filled_quantity, 0.2)
        self.assertAlmostEqual(position.quantity, 1.0)
        self.assertAlmostEqual(position.notional, 100.0)
        self.assertAlmostEqual(position.risk_amount, 10.0)

    def test_rebalances_existing_same_direction_position_when_enabled(self):
        from quant_platform.portfolio import OrderAction, PortfolioEngine, PortfolioState, Position, PositionKey

        state = PortfolioState(positions={
            PositionKey("BTC/USDT", "tactical"): Position(
                symbol="BTC/USDT",
                layer="tactical",
                direction=Direction.LONG,
                quantity=2.0,
                notional=200.0,
                risk_amount=10.0,
                module="breakout",
                entry_price=100.0,
                stop_price=95.0,
                target_price=120.0,
            )
        })
        engine = PortfolioEngine(state=state, rebalance_existing=True)
        order = engine.apply([
            self._decision(self._signal(module="pullback", direction=Direction.LONG), quantity=3.5)
        ]).orders[0]

        self.assertEqual(order.action, OrderAction.REBALANCE)
        self.assertEqual(order.reason, "increase_position")
        self.assertEqual(order.quantity, 1.5)
        self.assertEqual(order.existing_position, state.positions[PositionKey("BTC/USDT", "tactical")])

    def test_filled_rebalance_increase_updates_existing_position(self):
        from quant_platform.portfolio import OrderStatus, PortfolioEngine, PortfolioState, Position, PositionKey

        state = PortfolioState(positions={
            PositionKey("BTC/USDT", "tactical"): Position(
                symbol="BTC/USDT",
                layer="tactical",
                direction=Direction.LONG,
                quantity=2.0,
                notional=200.0,
                risk_amount=10.0,
                module="breakout",
                entry_price=100.0,
                stop_price=95.0,
                target_price=120.0,
            )
        })
        engine = PortfolioEngine(state=state, rebalance_existing=True)
        order = engine.apply([
            self._decision(
                self._signal(module="pullback", direction=Direction.LONG, preferred_target=125.0),
                quantity=3.5,
                notional=350.0,
                risk_amount=17.5,
            )
        ]).orders[0]

        filled = engine.record_fill(order.order_id, filled_quantity=1.5, fill_price=102.0)

        self.assertEqual(filled.status, OrderStatus.FILLED)
        position = engine.state.positions[PositionKey("BTC/USDT", "tactical")]
        self.assertAlmostEqual(position.quantity, 3.5)
        self.assertAlmostEqual(position.notional, 353.0)
        self.assertAlmostEqual(position.entry_price, 353.0 / 3.5)
        self.assertAlmostEqual(position.risk_amount, 17.5)
        self.assertEqual(position.stop_price, 95.0)
        self.assertEqual(position.target_price, 125.0)

    def test_filled_rebalance_reduce_updates_existing_position(self):
        from quant_platform.portfolio import OrderAction, OrderStatus, PortfolioEngine, PortfolioState, Position, PositionKey

        state = PortfolioState(positions={
            PositionKey("BTC/USDT", "tactical"): Position(
                symbol="BTC/USDT",
                layer="tactical",
                direction=Direction.LONG,
                quantity=4.0,
                notional=400.0,
                risk_amount=20.0,
                module="breakout",
                entry_price=100.0,
                stop_price=95.0,
                target_price=120.0,
            )
        })
        engine = PortfolioEngine(state=state, rebalance_existing=True)
        order = engine.apply([
            self._decision(
                self._signal(module="pullback", direction=Direction.LONG, preferred_target=118.0),
                quantity=2.5,
                notional=250.0,
                risk_amount=12.5,
            )
        ]).orders[0]

        self.assertEqual(order.action, OrderAction.REBALANCE)
        self.assertEqual(order.reason, "decrease_position")
        self.assertEqual(order.quantity, 1.5)

        filled = engine.record_fill(order.order_id, filled_quantity=1.5, fill_price=103.0)

        self.assertEqual(filled.status, OrderStatus.FILLED)
        position = engine.state.positions[PositionKey("BTC/USDT", "tactical")]
        self.assertAlmostEqual(position.quantity, 2.5)
        self.assertAlmostEqual(position.notional, 250.0)
        self.assertAlmostEqual(position.entry_price, 100.0)
        self.assertAlmostEqual(position.risk_amount, 12.5)
        self.assertEqual(position.stop_price, 95.0)
        self.assertEqual(position.target_price, 118.0)

    def test_opposite_signal_close_order_updates_existing_position_when_filled(self):
        from quant_platform.portfolio import OrderAction, OrderStatus, PortfolioEngine, PortfolioState, Position, PositionKey

        state = PortfolioState(positions={
            PositionKey("BTC/USDT", "tactical"): Position(
                symbol="BTC/USDT",
                layer="tactical",
                direction=Direction.LONG,
                quantity=3.0,
                notional=300.0,
                risk_amount=15.0,
                module="breakout",
                entry_price=100.0,
                stop_price=95.0,
                target_price=120.0,
            )
        })
        engine = PortfolioEngine(state=state, close_on_opposite_signal=True)
        order = engine.apply([
            self._decision(self._signal(module="crash_short", direction=Direction.SHORT), quantity=2.0)
        ]).orders[0]

        self.assertEqual(order.action, OrderAction.CLOSE)
        self.assertEqual(order.reason, "opposite_signal_close")
        self.assertEqual(order.status, OrderStatus.SUBMITTED)
        self.assertEqual(order.direction, Direction.LONG)
        self.assertEqual(order.quantity, 3.0)
        self.assertEqual(order.existing_position, state.positions[PositionKey("BTC/USDT", "tactical")])

        partial = engine.record_fill(order.order_id, filled_quantity=1.0, fill_price=98.0)
        position = engine.state.positions[PositionKey("BTC/USDT", "tactical")]

        self.assertEqual(partial.status, OrderStatus.PARTIALLY_FILLED)
        self.assertAlmostEqual(position.quantity, 2.0)
        self.assertAlmostEqual(position.notional, 200.0)
        self.assertAlmostEqual(position.risk_amount, 10.0)

        filled = engine.record_fill(order.order_id, filled_quantity=2.0, fill_price=99.0)

        self.assertEqual(filled.status, OrderStatus.FILLED)
        self.assertNotIn(PositionKey("BTC/USDT", "tactical"), engine.state.positions)

    def test_opposite_signal_can_plan_one_step_close_and_open_reversal_when_enabled(self):
        from quant_platform.portfolio import OrderAction, OrderStatus, PortfolioEngine, PortfolioState, Position, PositionKey

        key = PositionKey("BTC/USDT", "tactical")
        state = PortfolioState(positions={
            key: Position(
                symbol="BTC/USDT",
                layer="tactical",
                direction=Direction.LONG,
                quantity=3.0,
                notional=300.0,
                risk_amount=15.0,
                module="breakout",
                entry_price=100.0,
                stop_price=95.0,
                target_price=120.0,
            )
        })
        engine = PortfolioEngine(state=state, reverse_on_opposite_signal=True)

        plan = engine.apply([
            self._decision(
                self._signal(module="crash_short", direction=Direction.SHORT, preferred_target=80.0),
                quantity=2.0,
                notional=220.0,
                risk_amount=10.0,
            )
        ])

        self.assertEqual([order.action for order in plan.orders], [OrderAction.CLOSE, OrderAction.OPEN])
        self.assertEqual(plan.orders[0].reason, "opposite_signal_close")
        self.assertEqual(plan.orders[1].reason, "opposite_signal_open")
        self.assertEqual(plan.orders[0].existing_position, state.positions[key])
        self.assertEqual(state.positions[key].direction, Direction.LONG)

        closed = engine.record_fill(plan.orders[0].order_id, filled_quantity=3.0, fill_price=98.0)
        opened = engine.record_fill(plan.orders[1].order_id, filled_quantity=2.0, fill_price=98.0)

        self.assertEqual(closed.status, OrderStatus.FILLED)
        self.assertEqual(opened.status, OrderStatus.FILLED)
        position = engine.state.positions[key]
        self.assertEqual(position.direction, Direction.SHORT)
        self.assertEqual(position.module, "crash_short")
        self.assertAlmostEqual(position.quantity, 2.0)
        self.assertAlmostEqual(position.notional, 196.0)
        self.assertAlmostEqual(position.entry_price, 98.0)
        self.assertAlmostEqual(position.risk_amount, 10.0)
        self.assertEqual(position.stop_price, 95.0)
        self.assertEqual(position.target_price, 80.0)

    def test_same_direction_signal_can_transfer_existing_position_to_target_layer_when_enabled(self):
        from quant_platform.portfolio import OrderAction, OrderStatus, PortfolioEngine, PortfolioState, Position, PositionKey

        source_key = PositionKey("BTC/USDT", "tactical")
        target_key = PositionKey("BTC/USDT", "core")
        state = PortfolioState(positions={
            source_key: Position(
                symbol="BTC/USDT",
                layer="tactical",
                direction=Direction.LONG,
                quantity=3.0,
                notional=300.0,
                risk_amount=15.0,
                module="breakout",
                entry_price=100.0,
                stop_price=95.0,
                target_price=120.0,
            )
        })
        engine = PortfolioEngine(
            state=state,
            layer_by_module={"core_long": "core"},
            transfer_existing_layer=True,
        )

        plan = engine.apply([
            self._decision(self._signal(module="core_long", direction=Direction.LONG), quantity=3.0)
        ])

        self.assertEqual(len(plan.orders), 1)
        order = plan.orders[0]
        self.assertEqual(order.action, OrderAction.TRANSFER)
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertEqual(order.reason, "layer_transfer")
        self.assertEqual(order.layer, "core")
        self.assertEqual(order.existing_position, state.positions[target_key])
        self.assertNotIn(source_key, state.positions)
        self.assertIn(target_key, state.positions)
        position = state.positions[target_key]
        self.assertEqual(position.layer, "core")
        self.assertEqual(position.direction, Direction.LONG)
        self.assertEqual(position.quantity, 3.0)
        self.assertEqual(position.entry_price, 100.0)


if __name__ == "__main__":
    unittest.main()
