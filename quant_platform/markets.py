"""Reusable market specification catalog."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from quant_platform.core import AssetSpec, MarketSpec


@dataclass
class MarketCatalog:
    """Registry for exchange-specific MarketSpec objects."""

    markets: dict[tuple[str, str, str], MarketSpec] = field(default_factory=dict)

    @classmethod
    def from_records(cls, records: Iterable[dict]) -> "MarketCatalog":
        catalog = cls()
        for record in records:
            catalog.register(_market_from_record(record))
        return catalog

    def register(self, market: MarketSpec) -> "MarketCatalog":
        self.markets[_market_key(market.asset.symbol, market.exchange, market.market_type)] = market
        return self

    def register_many(self, markets: Iterable[MarketSpec]) -> "MarketCatalog":
        for market in markets:
            self.register(market)
        return self

    def resolve(self, symbol: str, *, exchange: str, market_type: str) -> MarketSpec:
        key = _market_key(symbol, exchange, market_type)
        try:
            return self.markets[key]
        except KeyError as exc:
            raise KeyError(
                f"No market spec registered for symbol={symbol!r}, exchange={exchange!r}, "
                f"market_type={market_type!r}"
            ) from exc

    def by_symbol(self, *, exchange: str | None = None, market_type: str | None = None) -> dict[str, MarketSpec]:
        result: dict[str, MarketSpec] = {}
        for (symbol, market_exchange, market_kind), market in self.markets.items():
            if exchange is not None and market_exchange != exchange:
                continue
            if market_type is not None and market_kind != market_type:
                continue
            result.setdefault(symbol, market)
        return result

    def to_records(self) -> list[dict]:
        return [
            _market_to_record(market)
            for _, market in sorted(
                self.markets.items(),
                key=lambda item: (item[0][1], item[0][2], item[0][0]),
            )
        ]


def default_crypto_market_catalog() -> MarketCatalog:
    return MarketCatalog.from_records([
        {
            "symbol": "BTC/USDT",
            "base": "BTC",
            "quote": "USDT",
            "exchange": "binance",
            "market_type": "swap",
            "tick_size": 0.1,
            "lot_size": 0.001,
            "supports_short": True,
            "supports_leverage": True,
        }
    ])


def load_market_catalog_json(path: str | Path) -> MarketCatalog:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return MarketCatalog.from_records(payload.get("markets", []))


def save_market_catalog_json(catalog: MarketCatalog, path: str | Path) -> Path:
    target = Path(path)
    target.write_text(
        json.dumps({"markets": catalog.to_records()}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _market_key(symbol: str, exchange: str, market_type: str) -> tuple[str, str, str]:
    return symbol.upper(), exchange.lower(), market_type.lower()


def _market_from_record(record: dict) -> MarketSpec:
    symbol = str(record["symbol"])
    return MarketSpec(
        asset=AssetSpec(
            symbol=symbol,
            base=str(record.get("base") or _base_from_symbol(symbol)),
            quote=str(record.get("quote") or _quote_from_symbol(symbol)),
        ),
        exchange=str(record["exchange"]),
        market_type=str(record["market_type"]),
        tick_size=_optional_float(record.get("tick_size")),
        lot_size=_optional_float(record.get("lot_size")),
        fee_rate=_optional_float(record.get("fee_rate")),
        funding_rate=_optional_float(record.get("funding_rate")),
        contract_multiplier=float(record.get("contract_multiplier", 1.0)),
        trading_session=str(record.get("trading_session", "24/7")),
        session_timezone=_optional_str(record.get("session_timezone")),
        session_open=_optional_str(record.get("session_open")),
        session_close=_optional_str(record.get("session_close")),
        trading_days=tuple(str(day) for day in record.get("trading_days", ())),
        correlation_group=_optional_str(record.get("correlation_group")),
        supports_short=bool(record.get("supports_short", False)),
        supports_leverage=bool(record.get("supports_leverage", False)),
        max_leverage=_optional_float(record.get("max_leverage")),
    )


def _market_to_record(market: MarketSpec) -> dict:
    record = {
        "symbol": market.asset.symbol,
        "base": market.asset.base,
        "quote": market.asset.quote,
        "exchange": market.exchange,
        "market_type": market.market_type,
    }
    _add_optional(record, "tick_size", market.tick_size)
    _add_optional(record, "lot_size", market.lot_size)
    _add_optional(record, "fee_rate", market.fee_rate)
    _add_optional(record, "funding_rate", market.funding_rate)
    if market.contract_multiplier != 1.0:
        record["contract_multiplier"] = market.contract_multiplier
    elif market.fee_rate is not None or market.funding_rate is not None:
        record["contract_multiplier"] = market.contract_multiplier
    if market.trading_session != "24/7":
        record["trading_session"] = market.trading_session
    elif market.supports_short or market.supports_leverage:
        record["trading_session"] = market.trading_session
    _add_optional_str(record, "session_timezone", market.session_timezone)
    _add_optional_str(record, "session_open", market.session_open)
    _add_optional_str(record, "session_close", market.session_close)
    if market.trading_days:
        record["trading_days"] = list(market.trading_days)
    _add_optional_str(record, "correlation_group", market.correlation_group)
    record["supports_short"] = market.supports_short
    record["supports_leverage"] = market.supports_leverage
    _add_optional(record, "max_leverage", market.max_leverage)
    return record


def _add_optional(record: dict, key: str, value: float | None) -> None:
    if value is not None:
        record[key] = value


def _optional_float(value) -> float | None:
    return None if value is None else float(value)


def _optional_str(value) -> str | None:
    return None if value is None else str(value)


def _add_optional_str(record: dict, key: str, value: str | None) -> None:
    if value is not None:
        record[key] = value


def _base_from_symbol(symbol: str) -> str:
    if "/" in symbol:
        return symbol.split("/", 1)[0]
    return symbol


def _quote_from_symbol(symbol: str) -> str:
    if "/" in symbol:
        return symbol.split("/", 1)[1]
    return ""
