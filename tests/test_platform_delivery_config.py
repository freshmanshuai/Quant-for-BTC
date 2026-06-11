import json
import tempfile
import unittest
from pathlib import Path


class DeliveryConfigTest(unittest.TestCase):
    def test_build_delivery_channels_is_exported_from_platform_package(self):
        from quant_platform import DeliveryConfigError, InMemoryDeliveryChannel, build_delivery_channels

        self.assertTrue(issubclass(DeliveryConfigError, ValueError))

        channels = build_delivery_channels({"channels": [{"type": "memory", "channel": "dashboard"}]})

        self.assertEqual(len(channels), 1)
        self.assertIsInstance(channels[0], InMemoryDeliveryChannel)

    def test_load_delivery_channels_json_builds_enabled_channels_from_env_refs(self):
        from quant_platform.delivery import EmailDeliveryChannel, InMemoryDeliveryChannel
        from quant_platform.delivery import TelegramDeliveryChannel, WebhookDeliveryChannel
        from quant_platform.delivery_config import load_delivery_channels_json

        payload = {
            "channels": [
                {"type": "memory", "channel": "dashboard"},
                {
                    "type": "webhook",
                    "url_env": "SIGNAL_WEBHOOK_URL",
                    "headers": {"X-Desk": "research"},
                    "header_env": {"Authorization": "SIGNAL_WEBHOOK_AUTH"},
                },
                {
                    "type": "telegram",
                    "bot_token_env": "SIGNAL_TELEGRAM_TOKEN",
                    "chat_id_env": "SIGNAL_TELEGRAM_CHAT",
                },
                {
                    "type": "email",
                    "from_address": "signals@example.test",
                    "to_addresses": ["ops@example.test", "pm@example.test"],
                },
            ],
        }
        env = {
            "SIGNAL_WEBHOOK_URL": "https://hooks.example.test/signals",
            "SIGNAL_WEBHOOK_AUTH": "Bearer runtime-token",
            "SIGNAL_TELEGRAM_TOKEN": "telegram-runtime-token",
            "SIGNAL_TELEGRAM_CHAT": "chat-123",
        }
        transports = {
            "webhook": lambda request: {"status_code": 202},
            "telegram": lambda request: {"status_code": 200},
            "email": lambda message: {"accepted": True},
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "delivery.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            channels = load_delivery_channels_json(path, env=env, transports=transports)

        self.assertIsInstance(channels[0], InMemoryDeliveryChannel)
        self.assertIsInstance(channels[1], WebhookDeliveryChannel)
        self.assertIsInstance(channels[2], TelegramDeliveryChannel)
        self.assertIsInstance(channels[3], EmailDeliveryChannel)
        self.assertEqual(channels[1].url, "https://hooks.example.test/signals")
        self.assertEqual(
            channels[1].headers,
            {"X-Desk": "research", "Authorization": "Bearer runtime-token"},
        )
        self.assertEqual(channels[2].bot_token, "telegram-runtime-token")
        self.assertEqual(channels[2].chat_id, "chat-123")
        self.assertEqual(channels[3].to_addresses, ("ops@example.test", "pm@example.test"))

    def test_load_delivery_channels_json_skips_disabled_and_reports_missing_env(self):
        from quant_platform.delivery_config import DeliveryConfigError, load_delivery_channels_json

        payload = {
            "channels": [
                {"type": "memory", "enabled": False, "channel": "disabled"},
                {"type": "webhook", "url_env": "SIGNAL_WEBHOOK_URL"},
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "delivery.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(DeliveryConfigError, "SIGNAL_WEBHOOK_URL"):
                load_delivery_channels_json(
                    path,
                    env={},
                    transports={"webhook": lambda request: {"status_code": 202}},
                )

    def test_load_delivery_channels_json_rejects_literal_webhook_url(self):
        from quant_platform.delivery_config import DeliveryConfigError, load_delivery_channels_json

        payload = {"channels": [{"type": "webhook", "url": "https://hooks.example.test/secret"}]}

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "delivery.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(DeliveryConfigError, "url_env"):
                load_delivery_channels_json(
                    path,
                    env={},
                    transports={"webhook": lambda request: {"status_code": 202}},
                )

    def test_load_delivery_channels_json_rejects_literal_telegram_credentials(self):
        from quant_platform.delivery_config import DeliveryConfigError, load_delivery_channels_json

        payload = {
            "channels": [
                {
                    "type": "telegram",
                    "bot_token": "literal-token",
                    "bot_token_env": "SIGNAL_TELEGRAM_TOKEN",
                    "chat_id_env": "SIGNAL_TELEGRAM_CHAT",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "delivery.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(DeliveryConfigError, "bot_token_env"):
                load_delivery_channels_json(
                    path,
                    env={
                        "SIGNAL_TELEGRAM_TOKEN": "telegram-runtime-token",
                        "SIGNAL_TELEGRAM_CHAT": "chat-123",
                    },
                    transports={"telegram": lambda request: {"status_code": 200}},
                )


if __name__ == "__main__":
    unittest.main()
