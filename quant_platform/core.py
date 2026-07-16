"""Market and asset specifications used across connectors, stores, and signals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal, ROUND_FLOOR
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class AssetSpec:
    """Tradeable asset identity independent of any exchange adapter."""

    symbol: str
    base: str
    quote: str


@dataclass(frozen=True)
class MarketSpec:
    """Exchange-specific tradability constraints for an asset."""

    asset: AssetSpec
    exchange: str
    market_type: str
    tick_size: float | None = None
    lot_size: float | None = None
    fee_rate: float | None = None
    funding_rate: float | None = None
    contract_multiplier: float = 1.0
    trading_session: str = "24/7"
    session_timezone: str | None = None
    session_open: str | None = None
    session_close: str | None = None
    trading_days: tuple[str, ...] = ()
    correlation_group: str | None = None
    supports_short: bool = False
    supports_leverage: bool = False
    max_leverage: float | None = None
    maintenance_margin_rate: float | None = None
    maintenance_amount: float = 0.0
    liquidation_fee_rate: float | None = None

    @property
    def market_key(self) -> str:
        return f"{self.exchange}:{self.market_type}:{self.asset.symbol}"

    def quantize_price(self, price: float) -> float:
        return _floor_to_step(price, self.tick_size)

    def quantize_quantity(self, quantity: float) -> float:
        return _floor_to_step(quantity, self.lot_size)

    def is_trading_time(self, timestamp: datetime) -> bool:
        """Return whether a UTC timestamp falls inside this market's configured session."""
        if str(self.trading_session).lower() in {"24/7", "24x7", "always"}:
            return True
        if not self.trading_days and not (self.session_open and self.session_close):
            return True

        dt = _coerce_datetime(timestamp)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        local_dt = dt.astimezone(ZoneInfo(self.session_timezone or "UTC"))

        if self.trading_days and _weekday_name(local_dt) not in {day.lower() for day in self.trading_days}:
            return False
        if not (self.session_open and self.session_close):
            return True

        open_time = _parse_session_time(self.session_open)
        close_time = _parse_session_time(self.session_close)
        current_time = local_dt.time().replace(tzinfo=None)
        if open_time <= close_time:
            return open_time <= current_time < close_time
        return current_time >= open_time or current_time < close_time


def _floor_to_step(value: float, step: float | None) -> float:
    if step is None:
        return value
    step_decimal = Decimal(str(step))
    if step_decimal <= 0:
        return value
    value_decimal = Decimal(str(value))
    return float((value_decimal / step_decimal).to_integral_value(rounding=ROUND_FLOOR) * step_decimal)


def _coerce_datetime(value: datetime) -> datetime:
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    return value


def _weekday_name(value: datetime) -> str:
    return ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[value.weekday()]


def _parse_session_time(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(int(hour), int(minute))
