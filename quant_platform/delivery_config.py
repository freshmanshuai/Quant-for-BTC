"""Configuration loader for signal delivery channels."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
from typing import Any

from quant_platform.delivery import (
    EmailDeliveryChannel,
    InMemoryDeliveryChannel,
    TelegramDeliveryChannel,
    WebhookDeliveryChannel,
)


class DeliveryConfigError(ValueError):
    """Raised when delivery channel configuration is invalid."""


def load_delivery_channels_json(
    path: str | Path,
    *,
    env: Mapping[str, str] | None = None,
    transports: Mapping[str, Callable[[dict[str, Any]], Any]] | None = None,
) -> list[Any]:
    """Build delivery channels from a secret-safe JSON config file."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return build_delivery_channels(payload, env=env, transports=transports)


def build_delivery_channels(
    payload: Mapping[str, Any],
    *,
    env: Mapping[str, str] | None = None,
    transports: Mapping[str, Callable[[dict[str, Any]], Any]] | None = None,
) -> list[Any]:
    """Build delivery channels from a parsed secret-safe config mapping."""
    environment = os.environ if env is None else env
    transport_map = dict(transports or {})
    channels: list[Any] = []

    for record in payload.get("channels", []):
        if not record.get("enabled", True):
            continue
        channel_type = str(record.get("type", "")).lower()
        if channel_type == "memory":
            channels.append(InMemoryDeliveryChannel(str(record.get("channel") or "dashboard")))
        elif channel_type == "webhook":
            channels.append(_build_webhook_channel(record, environment, transport_map))
        elif channel_type == "telegram":
            channels.append(_build_telegram_channel(record, environment, transport_map))
        elif channel_type == "email":
            channels.append(_build_email_channel(record, transport_map))
        else:
            raise DeliveryConfigError(f"Unsupported delivery channel type: {channel_type}")
    return channels


def _build_webhook_channel(
    record: Mapping[str, Any],
    env: Mapping[str, str],
    transports: Mapping[str, Callable[[dict[str, Any]], Any]],
) -> WebhookDeliveryChannel:
    if "url" in record:
        raise DeliveryConfigError("Webhook delivery config must use url_env, not a literal url.")
    url = _env_value(env, str(record.get("url_env") or ""), "webhook url_env")
    headers = dict(record.get("headers") or {})
    for header_name, env_name in dict(record.get("header_env") or {}).items():
        headers[str(header_name)] = _env_value(env, str(env_name), f"webhook header {header_name}")
    return WebhookDeliveryChannel(
        url,
        transport=_transport(transports, "webhook"),
        headers=headers,
    )


def _build_telegram_channel(
    record: Mapping[str, Any],
    env: Mapping[str, str],
    transports: Mapping[str, Callable[[dict[str, Any]], Any]],
) -> TelegramDeliveryChannel:
    if "bot_token" in record or "chat_id" in record:
        raise DeliveryConfigError(
            "Telegram delivery config must use bot_token_env and chat_id_env, not literal credentials."
        )
    bot_token = _env_value(env, str(record.get("bot_token_env") or ""), "telegram bot_token_env")
    chat_id = _env_value(env, str(record.get("chat_id_env") or ""), "telegram chat_id_env")
    return TelegramDeliveryChannel(
        bot_token=bot_token,
        chat_id=chat_id,
        transport=_transport(transports, "telegram"),
    )


def _build_email_channel(
    record: Mapping[str, Any],
    transports: Mapping[str, Callable[[dict[str, Any]], Any]],
) -> EmailDeliveryChannel:
    to_addresses = tuple(str(item) for item in record.get("to_addresses") or ())
    from_address = str(record.get("from_address") or "")
    if not to_addresses:
        raise DeliveryConfigError("Email delivery config requires to_addresses.")
    if not from_address:
        raise DeliveryConfigError("Email delivery config requires from_address.")
    return EmailDeliveryChannel(
        to_addresses=to_addresses,
        from_address=from_address,
        transport=_transport(transports, "email"),
    )


def _env_value(env: Mapping[str, str], name: str, field: str) -> str:
    if not name:
        raise DeliveryConfigError(f"Delivery config requires {field}.")
    value = env.get(name)
    if not value:
        raise DeliveryConfigError(f"Missing environment variable for delivery config: {name}")
    return value


def _transport(
    transports: Mapping[str, Callable[[dict[str, Any]], Any]],
    channel_type: str,
) -> Callable[[dict[str, Any]], Any]:
    transport = transports.get(channel_type)
    if transport is None:
        raise DeliveryConfigError(f"Delivery config requires transport for {channel_type}.")
    return transport
