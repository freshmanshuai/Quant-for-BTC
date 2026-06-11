import json
import tempfile
import unittest
from pathlib import Path

from quant_platform.portfolio import OrderAction, OrderStatus, PortfolioOrder
from quant_platform.risk import RiskDecision
from quant_platform.signals import Direction, Signal


class SignalDeliveryTest(unittest.TestCase):
    def _signal(self):
        return Signal(
            module="breakout",
            symbol="BTC/USDT",
            direction=Direction.LONG,
            score=82.0,
            entry_reason="donchian breakout",
            invalidation="close below stop",
            preferred_stop=95.0,
            preferred_target=120.0,
            confidence=0.81,
            required_data=("ohlcv", "atr"),
        )

    def _order(self):
        signal = self._signal()
        decision = RiskDecision(
            allowed=True,
            reason="allowed",
            signal=signal,
            quantity=2.0,
            notional=200.0,
            risk_amount=10.0,
            entry_price=100.0,
            stop_price=95.0,
            max_loss_per_unit=5.0,
        )
        return PortfolioOrder(
            order_id="ord-000001",
            action=OrderAction.OPEN,
            symbol="BTC/USDT",
            layer="tactical",
            direction=Direction.LONG,
            quantity=2.0,
            reason="opened",
            status=OrderStatus.SUBMITTED,
            decision=decision,
        )

    def test_builds_dashboard_payload_from_portfolio_order(self):
        from quant_platform.delivery import DeliveryPayload

        payload = DeliveryPayload.from_order(self._order(), channel="dashboard")
        data = payload.to_dict()

        self.assertEqual(data["channel"], "dashboard")
        self.assertEqual(data["signal"]["symbol"], "BTC/USDT")
        self.assertEqual(data["signal"]["direction"], "long")
        self.assertEqual(data["risk"]["risk_amount"], 10.0)
        self.assertEqual(data["order"]["order_id"], "ord-000001")
        self.assertEqual(data["order"]["status"], "submitted")

    def test_memory_delivery_channel_stores_payloads(self):
        from quant_platform.delivery import DeliveryPayload, InMemoryDeliveryChannel

        channel = InMemoryDeliveryChannel("dashboard")
        result = channel.publish(DeliveryPayload.from_order(self._order(), channel="dashboard"))

        self.assertTrue(result.ok)
        self.assertEqual(result.channel, "dashboard")
        self.assertEqual(len(channel.messages), 1)

    def test_webhook_and_telegram_channels_use_injected_transport(self):
        from quant_platform.delivery import DeliveryPayload, TelegramDeliveryChannel, WebhookDeliveryChannel

        sent = []

        def transport(request):
            sent.append(request)
            return {"status_code": 202}

        payload = DeliveryPayload.from_order(self._order(), channel="webhook")
        webhook_result = WebhookDeliveryChannel("https://example.test/hook", transport=transport).publish(payload)
        telegram_result = TelegramDeliveryChannel(
            bot_token="token",
            chat_id="chat",
            transport=transport,
        ).publish(payload)

        self.assertTrue(webhook_result.ok)
        self.assertTrue(telegram_result.ok)
        self.assertEqual(sent[0]["method"], "POST")
        self.assertEqual(sent[0]["url"], "https://example.test/hook")
        self.assertEqual(sent[1]["url"], "https://api.telegram.org/bot(token)/sendMessage")
        self.assertIn("BTC/USDT", sent[1]["json"]["text"])

    def test_email_channel_uses_injected_transport(self):
        from quant_platform.delivery import DeliveryPayload, EmailDeliveryChannel

        sent = []

        def transport(message):
            sent.append(message)
            return {"accepted": True}

        result = EmailDeliveryChannel(
            to_addresses=("ops@example.test",),
            from_address="signals@example.test",
            transport=transport,
        ).publish(DeliveryPayload.from_order(self._order(), channel="email"))

        self.assertTrue(result.ok)
        self.assertEqual(sent[0]["to"], ["ops@example.test"])
        self.assertIn("BTC/USDT", sent[0]["subject"])
        self.assertIn("breakout", sent[0]["body"])

    def test_pine_golden_vector_is_deterministic(self):
        from quant_platform.delivery import PineGoldenVector

        vector = PineGoldenVector.from_order(self._order(), bar_time="2026-06-03T08:00:00Z")

        self.assertEqual(vector.to_dict()["signal_key"], "BTC/USDT|tactical|breakout|long")
        self.assertEqual(vector.to_pine_comment(), "// BTC/USDT|tactical|breakout|long entry=100.0 stop=95.0 target=120.0 score=82.0")

    def test_compares_pine_observations_against_golden_vectors(self):
        from quant_platform.delivery import PineGoldenVector, compare_pine_golden_vectors

        vector = PineGoldenVector.from_order(self._order(), bar_time="2026-06-03T08:00:00Z")
        matching = {
            "signal_key": "BTC/USDT|tactical|breakout|long",
            "bar_time": "2026-06-03T08:00:00Z",
            "entry_price": 100.0,
            "stop_price": 95.0,
            "target_price": 120.0,
            "score": 82.0,
        }
        mismatched = dict(matching, entry_price=100.25, score=81.0)

        self.assertEqual(compare_pine_golden_vectors([vector], [matching]), [])
        issues = compare_pine_golden_vectors([vector], [mismatched], tolerance=0.01)

        self.assertEqual(len(issues), 2)
        self.assertIn("entry_price expected=100.0 actual=100.25", issues[0])
        self.assertIn("score expected=82.0 actual=81.0", issues[1])

    def test_pine_golden_vector_artifact_round_trips_and_compares_observed_csv(self):
        from quant_platform.delivery import (
            PineGoldenVector,
            compare_pine_golden_vector_files,
            load_pine_golden_vectors_json,
            write_pine_golden_vectors_json,
        )

        vector = PineGoldenVector.from_order(self._order(), bar_time="2026-06-03T08:00:00Z")
        with tempfile.TemporaryDirectory() as tmp:
            expected_path = Path(tmp) / "expected_vectors.json"
            observed_path = Path(tmp) / "pine_observed.csv"

            write_pine_golden_vectors_json(expected_path, [vector])
            self.assertEqual(
                json.loads(expected_path.read_text(encoding="utf-8")),
                [vector.to_dict()],
            )
            self.assertEqual(
                [loaded.to_dict() for loaded in load_pine_golden_vectors_json(expected_path)],
                [vector.to_dict()],
            )

            observed_path.write_text(
                "\n".join([
                    "signal_key,bar_time,entry_price,stop_price,target_price,score",
                    "BTC/USDT|tactical|breakout|long,2026-06-03T08:00:00Z,100.0,95.0,120.0,81.0",
                ]),
                encoding="utf-8",
            )
            issues = compare_pine_golden_vector_files(expected_path, observed_path, tolerance=0.01)

        self.assertEqual(
            issues,
            [
                "BTC/USDT|tactical|breakout|long 2026-06-03T08:00:00Z: "
                "score expected=82.0 actual=81.0"
            ],
        )


if __name__ == "__main__":
    unittest.main()
