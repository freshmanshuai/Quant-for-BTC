"""Standardized signal preview service for the visualization API."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from quant_platform.backtest import BacktestAttribution, BacktestEquityPoint, BacktestTrade, EventDrivenBacktest
from quant_platform.core import MarketSpec
from quant_platform.delivery import InMemoryDeliveryChannel
from quant_platform.markets import default_crypto_market_catalog, load_market_catalog_json
from quant_platform.pipeline import SignalPipeline
from quant_platform.portfolio import PortfolioEngine, PortfolioOrder
from quant_platform.regimes import RegimeProfile, RegimeProfileRegistry, load_regime_profile_registry_json
from quant_platform.risk import AccountState, RiskDecision, RiskEngine, RiskLimits
from quant_platform.signal_modules import SignalModuleRunner
from quant_platform.signals import Signal
from quant_platform.stores import MissingStorageDependency, ParquetFeatureStore
from serve.data_loader import get_ohlcv, get_summary_stats, get_trade_log


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_FEATURE_STORE_DIR = _PROJECT_ROOT / "data" / "features"
_MARKET_CATALOG_PATH = _PROJECT_ROOT / "config" / "markets.json"
_REGIME_PROFILE_PATH = _PROJECT_ROOT / "config" / "regime_profiles.json"


def get_btc_signal_preview(
    *,
    timeframe: str = "4h",
    symbol: str = "BTC/USDT",
    limit: int = 50,
    load_ohlcv: Callable[[str], pd.DataFrame] | None = None,
    build_features: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
    generate_signals: Callable[[pd.DataFrame, str], list[Signal]] | None = None,
) -> dict[str, Any]:
    """Return a REST-safe snapshot of standardized BTC signals from cached bars."""
    bars = (load_ohlcv or get_ohlcv)(timeframe)
    if bars.empty:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "rows": 0,
            "signalCount": 0,
            "signals": [],
            "latestBar": None,
        }

    signal_generator = generate_signals or _default_btc_signal_generator
    features = (
        build_features(bars)
        if build_features
        else _default_btc_feature_builder(bars, timeframe=timeframe, symbol=symbol)
    )
    signals = signal_generator(features, symbol)
    limited_signals = signals[-max(1, int(limit)):]

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "rows": int(len(features)),
        "signalCount": len(limited_signals),
        "signals": [signal.to_dict() for signal in limited_signals],
        "latestBar": _latest_bar(features),
    }


def get_btc_pipeline_preview(
    *,
    timeframe: str = "4h",
    symbol: str = "BTC/USDT",
    equity: float = 10_000.0,
    load_ohlcv: Callable[[str], pd.DataFrame] | None = None,
    build_features: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
    generate_signals: Callable[[pd.DataFrame, str], list[Signal]] | None = None,
) -> dict[str, Any]:
    """Return a read-only SignalPipeline preview for standardized BTC signals."""
    bars = (load_ohlcv or get_ohlcv)(timeframe)
    if bars.empty:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "rows": 0,
            "signalCount": 0,
            "riskDecisionCount": 0,
            "orderCount": 0,
            "deliveryCount": 0,
            "signals": [],
            "riskDecisions": [],
            "orders": [],
            "deliveries": [],
            "latestBar": None,
        }

    signal_generator = generate_signals or _default_btc_signal_generator
    features = (
        build_features(bars)
        if build_features
        else _default_btc_feature_builder(bars, timeframe=timeframe, symbol=symbol)
    )
    signals = signal_generator(features, symbol)
    delivery = InMemoryDeliveryChannel("dashboard")
    markets_by_symbol = {symbol: build_btc_market_spec(symbol)}
    pipeline = SignalPipeline(
        signal_runner=SignalModuleRunner([_FixedSignalModule(signals)]),
        risk_engine=RiskEngine(RiskLimits()),
        portfolio_engine=PortfolioEngine(),
        delivery_channels=(delivery,),
        markets_by_symbol=markets_by_symbol,
    )
    result = pipeline.run(features, symbol=symbol, account=AccountState(equity=float(equity)))

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "rows": int(len(features)),
        "signalCount": len(result.signals),
        "riskDecisionCount": len(result.risk_decisions),
        "orderCount": len(result.portfolio_plan.orders),
        "deliveryCount": len(result.delivery_results),
        "signals": [signal.to_dict() for signal in result.signals],
        "riskDecisions": [_risk_decision_to_dict(decision) for decision in result.risk_decisions],
        "orders": [_order_to_dict(order) for order in result.portfolio_plan.orders],
        "deliveries": [payload.to_dict() for payload in delivery.messages],
        "latestBar": _latest_bar(features),
    }


def get_signal_research_preview(
    *,
    timeframe: str,
    symbol: str,
    exchange: str,
    market_type: str,
    equity: float = 10_000.0,
    load_ohlcv: Callable[[str, MarketSpec], pd.DataFrame],
    build_features: Callable[[pd.DataFrame, MarketSpec, RegimeProfile], pd.DataFrame] | None = None,
    generate_signals: Callable[[pd.DataFrame, str, MarketSpec, RegimeProfile], list[Signal]] | None = None,
) -> dict[str, Any]:
    """Run a generic read-only signal research preview for a configured market."""
    market = resolve_market_spec(symbol, exchange=exchange, market_type=market_type)
    regime_profile = resolve_regime_profile(market)
    bars = load_ohlcv(timeframe, market)
    if bars.empty:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "market": _market_to_dict(market),
            "regimeProfile": _regime_profile_to_dict(regime_profile),
            "rows": 0,
            "signalCount": 0,
            "riskDecisionCount": 0,
            "orderCount": 0,
            "deliveryCount": 0,
            "signals": [],
            "riskDecisions": [],
            "orders": [],
            "deliveries": [],
            "latestBar": None,
        }

    features = build_features(bars, market, regime_profile) if build_features else bars.copy()
    signals = generate_signals(features, symbol, market, regime_profile) if generate_signals else []
    delivery = InMemoryDeliveryChannel("dashboard")
    markets_by_symbol = {symbol: market}
    pipeline = SignalPipeline(
        signal_runner=SignalModuleRunner([_FixedSignalModule(signals)]),
        risk_engine=RiskEngine(RiskLimits()),
        portfolio_engine=PortfolioEngine(),
        delivery_channels=(delivery,),
        markets_by_symbol=markets_by_symbol,
    )
    result = pipeline.run(features, symbol=symbol, account=AccountState(equity=float(equity)))

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "market": _market_to_dict(market),
        "regimeProfile": _regime_profile_to_dict(regime_profile),
        "rows": int(len(features)),
        "signalCount": len(result.signals),
        "riskDecisionCount": len(result.risk_decisions),
        "orderCount": len(result.portfolio_plan.orders),
        "deliveryCount": len(result.delivery_results),
        "signals": [signal.to_dict() for signal in result.signals],
        "riskDecisions": [_risk_decision_to_dict(decision) for decision in result.risk_decisions],
        "orders": [_order_to_dict(order) for order in result.portfolio_plan.orders],
        "deliveries": [payload.to_dict() for payload in delivery.messages],
        "latestBar": _latest_bar(features),
    }


def get_btc_event_backtest_preview(
    *,
    timeframe: str = "4h",
    symbol: str = "BTC/USDT",
    equity: float = 10_000.0,
    load_ohlcv: Callable[[str], pd.DataFrame] | None = None,
    build_features: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
    generate_signals: Callable[[pd.DataFrame, str], list[Signal]] | None = None,
) -> dict[str, Any]:
    """Run a read-only event-driven BTC backtest preview from standardized signal modules."""
    bars = (load_ohlcv or get_ohlcv)(timeframe)
    if bars.empty:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "rows": 0,
            "stepCount": 0,
            "signalCount": 0,
            "orderCount": 0,
            "tradeCount": 0,
            "summary": {
                "initialEquity": float(equity),
                "finalEquity": float(equity),
                "realizedPnl": 0.0,
                "feesPaid": 0.0,
                "fundingPaid": 0.0,
            },
            "trades": [],
            "equityCurve": [],
            "attribution": _attribution_to_dict(BacktestAttribution({}, {}, {})),
            "latestBar": None,
        }

    signal_generator = generate_signals or _default_btc_signal_generator
    features = (
        build_features(bars)
        if build_features
        else _default_btc_feature_builder(bars, timeframe=timeframe, symbol=symbol)
    )
    markets_by_symbol = {symbol: build_btc_market_spec(symbol)}
    pipeline = SignalPipeline(
        signal_runner=SignalModuleRunner([_CallableSignalModule(signal_generator)]),
        risk_engine=RiskEngine(RiskLimits()),
        portfolio_engine=PortfolioEngine(),
        markets_by_symbol=markets_by_symbol,
    )
    result = EventDrivenBacktest(
        pipeline=pipeline,
        account=AccountState(equity=float(equity)),
        markets_by_symbol=markets_by_symbol,
    ).run({symbol: features})
    final_equity = result.equity_curve[-1].equity if result.equity_curve else float(equity)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "rows": int(len(features)),
        "stepCount": len(result.steps),
        "signalCount": len(result.signals),
        "orderCount": len(result.orders) + len(result.trades),
        "tradeCount": len(result.trades),
        "summary": {
            "initialEquity": float(equity),
            "finalEquity": final_equity,
            "realizedPnl": result.realized_pnl,
            "feesPaid": result.fees_paid,
            "fundingPaid": result.funding_paid,
        },
        "trades": [_trade_to_dict(trade) for trade in result.trades],
        "equityCurve": [_equity_point_to_dict(point) for point in result.equity_curve],
        "attribution": _attribution_to_dict(result.attribution),
        "latestBar": _latest_bar(features),
    }


def get_btc_migration_comparison_preview(
    *,
    timeframe: str = "4h",
    symbol: str = "BTC/USDT",
    equity: float = 10_000.0,
    load_ohlcv: Callable[[str], pd.DataFrame] | None = None,
    build_features: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
    generate_signals: Callable[[pd.DataFrame, str], list[Signal]] | None = None,
    load_trade_log: Callable[[], pd.DataFrame] | None = None,
    load_legacy_summary: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compare legacy cached backtest metrics with the event-driven preview."""
    event = get_btc_event_backtest_preview(
        timeframe=timeframe,
        symbol=symbol,
        equity=equity,
        load_ohlcv=load_ohlcv,
        build_features=build_features,
        generate_signals=generate_signals,
    )
    legacy_summary = (load_legacy_summary or get_summary_stats)() or {}
    legacy_trades = (load_trade_log or get_trade_log)()
    legacy = _legacy_summary_to_dict(legacy_summary, legacy_trades)
    event_summary = _event_summary_to_dict(event)

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "legacy": legacy,
        "event": event_summary,
        "delta": {
            "tradeCount": event_summary["tradeCount"] - legacy["tradeCount"],
            "totalPnl": event_summary["realizedPnl"] - legacy["totalPnl"],
            "finalEquity": event_summary["finalEquity"] - legacy["finalEquity"],
            "winRatePct": event_summary["winRatePct"] - legacy["winRatePct"],
        },
    }


class _FixedSignalModule:
    name = "btc_preview"

    def __init__(self, signals: list[Signal]):
        self.signals = list(signals)

    def generate(self, features: pd.DataFrame, symbol: str) -> list[Signal]:
        return self.signals


class _CallableSignalModule:
    name = "btc_event_backtest"

    def __init__(self, generate_signals: Callable[[pd.DataFrame, str], list[Signal]]):
        self.generate_signals = generate_signals

    def generate(self, features: pd.DataFrame, symbol: str) -> list[Signal]:
        return self.generate_signals(features, symbol)


def build_btc_market_spec(symbol: str = "BTC/USDT") -> MarketSpec:
    return resolve_market_spec(symbol, exchange="binance", market_type="swap")


def resolve_market_spec(symbol: str, *, exchange: str, market_type: str) -> MarketSpec:
    return _load_project_market_catalog().resolve(symbol, exchange=exchange, market_type=market_type)


def resolve_regime_profile(market: MarketSpec) -> RegimeProfile:
    return _load_project_regime_profiles().profile_for(market)


def _load_project_market_catalog():
    if _MARKET_CATALOG_PATH.exists():
        return load_market_catalog_json(_MARKET_CATALOG_PATH)
    return default_crypto_market_catalog()


def _load_project_regime_profiles() -> RegimeProfileRegistry:
    if _REGIME_PROFILE_PATH.exists():
        return load_regime_profile_registry_json(_REGIME_PROFILE_PATH)
    return RegimeProfileRegistry()


def _default_btc_feature_builder(
    bars: pd.DataFrame,
    *,
    timeframe: str = "4h",
    symbol: str = "BTC/USDT",
) -> pd.DataFrame:
    from quant_btc.config import BacktestConfig
    from quant_btc.feature_engine import build_cached_btc_features
    from quant_btc.strategy import prepare_features

    cfg = BacktestConfig()
    try:
        build_cached_btc_features(
            bars,
            cfg,
            symbol=symbol,
            timeframe=timeframe,
            store=ParquetFeatureStore(_FEATURE_STORE_DIR),
        )
    except (MissingStorageDependency, OSError, ValueError):
        pass
    return prepare_features(bars, cfg)


def _default_btc_signal_generator(features: pd.DataFrame, symbol: str) -> list[Signal]:
    from quant_btc.signal_modules import generate_btc_standard_signals

    return generate_btc_standard_signals(features, symbol=symbol)


def _latest_bar(features: pd.DataFrame) -> dict[str, Any] | None:
    if features.empty:
        return None
    row = features.iloc[-1]
    index = features.index[-1]
    return {
        "time": index.isoformat() if hasattr(index, "isoformat") else str(index),
        "open": _optional_float(row.get("Open")),
        "high": _optional_float(row.get("High")),
        "low": _optional_float(row.get("Low")),
        "close": _optional_float(row.get("Close")),
        "volume": _optional_float(row.get("Volume")),
    }


def _risk_decision_to_dict(decision: RiskDecision) -> dict[str, Any]:
    return {
        "allowed": decision.allowed,
        "reason": decision.reason,
        "signal": decision.signal.to_dict(),
        "quantity": decision.quantity,
        "notional": decision.notional,
        "risk_amount": decision.risk_amount,
        "entry_price": decision.entry_price,
        "stop_price": decision.stop_price,
        "max_loss_per_unit": decision.max_loss_per_unit,
        "applied_size_multiplier": decision.applied_size_multiplier,
    }


def _order_to_dict(order: PortfolioOrder) -> dict[str, Any]:
    return {
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
        "entry_price": order.entry_price,
        "stop_price": order.stop_price,
        "target_price": order.target_price,
    }


def _market_to_dict(market: MarketSpec) -> dict[str, Any]:
    return {
        "symbol": market.asset.symbol,
        "base": market.asset.base,
        "quote": market.asset.quote,
        "exchange": market.exchange,
        "marketType": market.market_type,
        "tickSize": market.tick_size,
        "lotSize": market.lot_size,
        "feeRate": market.fee_rate,
        "fundingRate": market.funding_rate,
        "contractMultiplier": market.contract_multiplier,
        "tradingSession": market.trading_session,
        "supportsShort": market.supports_short,
        "supportsLeverage": market.supports_leverage,
    }


def _regime_profile_to_dict(profile: RegimeProfile) -> dict[str, Any]:
    return {_snake_to_camel(key): value for key, value in asdict(profile).items()}


def _snake_to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def _trade_to_dict(trade: BacktestTrade) -> dict[str, Any]:
    return {
        "symbol": trade.symbol,
        "layer": trade.layer,
        "module": trade.module,
        "direction": trade.direction.value,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "quantity": trade.quantity,
        "gross_pnl": trade.gross_pnl,
        "entry_fee": trade.entry_fee,
        "exit_fee": trade.exit_fee,
        "net_pnl": trade.net_pnl,
        "exit_reason": trade.exit_reason,
    }


def _equity_point_to_dict(point: BacktestEquityPoint) -> dict[str, Any]:
    return {
        "symbol": point.symbol,
        "time": point.timestamp.isoformat() if hasattr(point.timestamp, "isoformat") else str(point.timestamp),
        "bar_index": point.bar_index,
        "cash": point.cash,
        "unrealized_pnl": point.unrealized_pnl,
        "equity": point.equity,
    }


def _attribution_to_dict(attribution: BacktestAttribution) -> dict[str, Any]:
    def bucket_map(items):
        return {
            key: {
                "tradeCount": bucket.trade_count,
                "grossPnl": bucket.gross_pnl,
                "netPnl": bucket.net_pnl,
                "feesPaid": bucket.fees_paid,
                "winCount": bucket.win_count,
                "winRate": bucket.win_rate,
            }
            for key, bucket in items.items()
        }

    return {
        "bySymbol": bucket_map(attribution.by_symbol),
        "byLayer": bucket_map(attribution.by_layer),
        "byModule": bucket_map(attribution.by_module),
    }


def _legacy_summary_to_dict(summary: dict[str, Any], trades: pd.DataFrame) -> dict[str, Any]:
    source_rows = int(len(trades)) if isinstance(trades, pd.DataFrame) else 0
    return {
        "tradeCount": int(summary.get("total_trades") or source_rows or 0),
        "sourceTradeRows": source_rows,
        "totalPnl": float(summary.get("total_pnl") or 0.0),
        "finalEquity": float(summary.get("final_equity") or 0.0),
        "winRatePct": float(summary.get("win_rate_pct") or 0.0),
    }


def _event_summary_to_dict(event: dict[str, Any]) -> dict[str, Any]:
    trades = event.get("trades") or []
    wins = sum(float(trade.get("net_pnl") or 0.0) > 0 for trade in trades)
    trade_count = int(event.get("tradeCount") or len(trades))
    win_rate = wins / trade_count * 100.0 if trade_count else 0.0
    summary = event.get("summary") or {}
    return {
        "tradeCount": trade_count,
        "realizedPnl": float(summary.get("realizedPnl") or 0.0),
        "finalEquity": float(summary.get("finalEquity") or 0.0),
        "winRatePct": win_rate,
    }


def _optional_float(value: Any) -> float | None:
    if pd.isna(value):
        return None
    return float(value)
