"""Market and asset specifications used across connectors, stores, and signals."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR


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
    supports_short: bool = False
    supports_leverage: bool = False

    @property
    def market_key(self) -> str:
        return f"{self.exchange}:{self.market_type}:{self.asset.symbol}"

    def quantize_price(self, price: float) -> float:
        return _floor_to_step(price, self.tick_size)

    def quantize_quantity(self, quantity: float) -> float:
        return _floor_to_step(quantity, self.lot_size)


def _floor_to_step(value: float, step: float | None) -> float:
    if step is None:
        return value
    step_decimal = Decimal(str(step))
    if step_decimal <= 0:
        return value
    value_decimal = Decimal(str(value))
    return float((value_decimal / step_decimal).to_integral_value(rounding=ROUND_FLOOR) * step_decimal)
