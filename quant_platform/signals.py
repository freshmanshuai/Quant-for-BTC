"""Standard signal contracts produced by strategy modules."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass(frozen=True)
class Signal:
    """Strategy-module output consumed by risk, portfolio, and delivery layers."""

    module: str
    symbol: str
    direction: Direction
    score: float
    entry_reason: str
    invalidation: str
    preferred_stop: float | None = None
    preferred_target: float | None = None
    confidence: float = 0.0
    required_data: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["direction"] = self.direction.value
        payload["required_data"] = list(self.required_data)
        return payload
