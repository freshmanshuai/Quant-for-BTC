"""Signal delivery payloads and channel adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from quant_platform.portfolio import PortfolioOrder


@dataclass(frozen=True)
class DeliveryPayload:
    """Normalized payload emitted to dashboard, API, webhook, chat, email, or Pine tests."""

    channel: str
    signal: dict[str, Any]
    risk: dict[str, Any]
    order: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_order(
        cls,
        order: PortfolioOrder,
        *,
        channel: str,
        metadata: dict[str, Any] | None = None,
    ) -> "DeliveryPayload":
        decision = order.decision
        signal = decision.signal if decision else None
        return cls(
            channel=channel,
            signal=signal.to_dict() if signal else {
                "symbol": order.symbol,
                "direction": order.direction.value,
            },
            risk={
                "allowed": decision.allowed if decision else None,
                "reason": decision.reason if decision else "",
                "quantity": decision.quantity if decision else order.quantity,
                "notional": decision.notional if decision else 0.0,
                "risk_amount": decision.risk_amount if decision else 0.0,
                "entry_price": decision.entry_price if decision else 0.0,
                "stop_price": decision.stop_price if decision else None,
            },
            order={
                "order_id": order.order_id,
                "action": order.action.value,
                "symbol": order.symbol,
                "layer": order.layer,
                "direction": order.direction.value,
                "quantity": order.quantity,
                "reason": order.reason,
                "status": order.status.value,
                "filled_quantity": order.filled_quantity,
                "average_fill_price": order.average_fill_price,
            },
            metadata=dict(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "signal": dict(self.signal),
            "risk": dict(self.risk),
            "order": dict(self.order),
            "metadata": dict(self.metadata),
        }

    def summary(self) -> str:
        signal = self.signal
        order = self.order
        return (
            f"{signal.get('symbol', order.get('symbol'))} "
            f"{signal.get('direction', order.get('direction'))} "
            f"{signal.get('module', '')} "
            f"score={signal.get('score', '')} "
            f"status={order.get('status', '')}"
        ).strip()


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    channel: str
    destination: str
    response: Any = None
    error: str = ""


class InMemoryDeliveryChannel:
    """Delivery channel for dashboard state, tests, and local API collection."""

    def __init__(self, channel: str = "dashboard"):
        self.channel = channel
        self.messages: list[DeliveryPayload] = []

    def publish(self, payload: DeliveryPayload) -> DeliveryResult:
        self.messages.append(payload)
        return DeliveryResult(ok=True, channel=self.channel, destination="memory", response=payload.to_dict())


class WebhookDeliveryChannel:
    def __init__(
        self,
        url: str,
        *,
        transport: Callable[[dict[str, Any]], Any],
        headers: dict[str, str] | None = None,
    ):
        self.url = url
        self.transport = transport
        self.headers = dict(headers or {})

    def publish(self, payload: DeliveryPayload) -> DeliveryResult:
        request = {
            "method": "POST",
            "url": self.url,
            "headers": self.headers,
            "json": payload.to_dict(),
        }
        response = self.transport(request)
        return DeliveryResult(ok=_response_ok(response), channel=payload.channel, destination=self.url, response=response)


class TelegramDeliveryChannel:
    def __init__(
        self,
        *,
        bot_token: str,
        chat_id: str,
        transport: Callable[[dict[str, Any]], Any],
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.transport = transport

    def publish(self, payload: DeliveryPayload) -> DeliveryResult:
        safe_token = f"({self.bot_token})"
        url = f"https://api.telegram.org/bot{safe_token}/sendMessage"
        request = {
            "method": "POST",
            "url": url,
            "json": {
                "chat_id": self.chat_id,
                "text": payload.summary(),
            },
        }
        response = self.transport(request)
        return DeliveryResult(ok=_response_ok(response), channel="telegram", destination=self.chat_id, response=response)


class EmailDeliveryChannel:
    def __init__(
        self,
        *,
        to_addresses: tuple[str, ...],
        from_address: str,
        transport: Callable[[dict[str, Any]], Any],
    ):
        self.to_addresses = tuple(to_addresses)
        self.from_address = from_address
        self.transport = transport

    def publish(self, payload: DeliveryPayload) -> DeliveryResult:
        message = {
            "from": self.from_address,
            "to": list(self.to_addresses),
            "subject": f"Signal {payload.signal.get('symbol', payload.order.get('symbol'))} {payload.signal.get('direction', '')}",
            "body": _plain_text_body(payload),
        }
        response = self.transport(message)
        return DeliveryResult(ok=_response_ok(response), channel="email", destination=",".join(self.to_addresses), response=response)


@dataclass(frozen=True)
class PineGoldenVector:
    signal_key: str
    bar_time: str
    entry_price: float
    stop_price: float | None
    target_price: float | None
    score: float

    @classmethod
    def from_order(cls, order: PortfolioOrder, *, bar_time: str) -> "PineGoldenVector":
        if order.decision is None:
            raise ValueError("Pine golden vectors require a risk decision")
        signal = order.decision.signal
        return cls(
            signal_key=f"{signal.symbol}|{order.layer}|{signal.module}|{signal.direction.value}",
            bar_time=bar_time,
            entry_price=order.decision.entry_price,
            stop_price=order.decision.stop_price,
            target_price=signal.preferred_target,
            score=signal.score,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_key": self.signal_key,
            "bar_time": self.bar_time,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "score": self.score,
        }

    def to_pine_comment(self) -> str:
        return (
            f"// {self.signal_key} "
            f"entry={self.entry_price} "
            f"stop={self.stop_price} "
            f"target={self.target_price} "
            f"score={self.score}"
        )


def compare_pine_golden_vectors(
    expected: list[PineGoldenVector],
    observed: list[dict[str, Any]],
    *,
    tolerance: float = 1e-9,
) -> list[str]:
    observed_by_key = {
        (str(row.get("signal_key")), str(row.get("bar_time"))): row
        for row in observed
    }
    issues: list[str] = []
    for vector in expected:
        key = (vector.signal_key, vector.bar_time)
        row = observed_by_key.get(key)
        if row is None:
            issues.append(f"{vector.signal_key} {vector.bar_time}: missing pine observation")
            continue
        for field in ("entry_price", "stop_price", "target_price", "score"):
            expected_value = getattr(vector, field)
            actual_value = row.get(field)
            if not _values_match(expected_value, actual_value, tolerance):
                issues.append(
                    f"{vector.signal_key} {vector.bar_time}: "
                    f"{field} expected={expected_value} actual={actual_value}"
                )
    return issues


def _values_match(expected: Any, actual: Any, tolerance: float) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    try:
        return abs(float(expected) - float(actual)) <= tolerance
    except (TypeError, ValueError):
        return expected == actual


def _plain_text_body(payload: DeliveryPayload) -> str:
    signal = payload.signal
    risk = payload.risk
    order = payload.order
    return "\n".join([
        f"symbol: {signal.get('symbol', order.get('symbol'))}",
        f"module: {signal.get('module', '')}",
        f"direction: {signal.get('direction', order.get('direction'))}",
        f"score: {signal.get('score', '')}",
        f"entry: {risk.get('entry_price', '')}",
        f"stop: {risk.get('stop_price', '')}",
        f"target: {signal.get('preferred_target', '')}",
        f"order: {order.get('order_id', '')} {order.get('status', '')}",
    ])


def _response_ok(response: Any) -> bool:
    if isinstance(response, dict):
        if "accepted" in response:
            return bool(response["accepted"])
        status_code = int(response.get("status_code", 200))
        return 200 <= status_code < 300
    return bool(response)
