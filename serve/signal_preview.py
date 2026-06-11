"""Standardized signal preview service for the visualization API."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

import pandas as pd

from quant_platform.backtest import (
    BacktestAttribution,
    BacktestEquityPoint,
    BacktestExecutionConfig,
    BacktestExposurePoint,
    BacktestTrade,
    EventDrivenBacktest,
)
from quant_platform.connector_config import load_data_connector_registry_json
from quant_platform.connectors import (
    fetch_bars_with_cache,
    fetch_derivatives_with_cache,
    fetch_order_book_snapshots_with_cache,
)
from quant_platform.core import MarketSpec
from quant_platform.data import FeatureSeriesId
from quant_platform.delivery import InMemoryDeliveryChannel
from quant_platform.features import (
    BollingerConfig,
    BollingerFeatureModule,
    DerivativesFeatureModule,
    DonchianConfig,
    DonchianFeatureModule,
    FeatureEngine,
    FeatureRunResult,
    OrderBookFeatureConfig,
    OrderBookFeatureModule,
    PriceActionFeatureModule,
    TechnicalIndicatorConfig,
    TechnicalIndicatorModule,
    VolatilityConfig,
    VolatilityFeatureModule,
    VolumeConfig,
    VolumeFeatureModule,
    run_feature_engine_with_cache,
)
from quant_platform.markets import default_crypto_market_catalog, load_market_catalog_json
from quant_platform.pipeline import PipelineResult, SignalPipeline
from quant_platform.portfolio import OrderAction, OrderStatus, PortfolioEngine, PortfolioOrder, PortfolioState, Position
from quant_platform.regimes import RegimeLabel, RegimeModel, RegimeProfile, RegimeProfileRegistry, load_regime_profile_registry_json
from quant_platform.risk import AccountState, RiskDecision, RiskEngine, RiskLimits
from quant_platform.signal_modules import (
    BreakoutSignalConfig,
    BreakoutSignalModule,
    BullTrapSignalConfig,
    BullTrapSignalModule,
    CrashShortSignalConfig,
    CrashShortSignalModule,
    FailedBounceSignalConfig,
    FailedBounceSignalModule,
    MeanReversionSignalConfig,
    MeanReversionSignalModule,
    PullbackSignalConfig,
    PullbackSignalModule,
    SignalModuleRunner,
    SweepReversalSignalConfig,
    SweepReversalSignalModule,
    default_signal_module_registry,
)
from quant_platform.signals import Signal
from quant_platform.stores import (
    MissingStorageDependency,
    ParquetBarStore,
    ParquetDerivativeStore,
    ParquetFeatureStore,
    ParquetOrderBookStore,
)
from serve.data_loader import get_ohlcv, get_summary_stats, get_trade_log


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_FEATURE_STORE_DIR = _PROJECT_ROOT / "data" / "features"
_MARKET_CATALOG_PATH = _PROJECT_ROOT / "config" / "markets.json"
_REGIME_PROFILE_PATH = _PROJECT_ROOT / "config" / "regime_profiles.json"
_RESEARCH_DATA_SOURCE_PATH = _PROJECT_ROOT / "config" / "research_data_sources.json"
_RESEARCH_SIGNAL_MODULE_PATH = _PROJECT_ROOT / "config" / "research_signal_modules.json"


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
            "riskDiagnostics": _empty_risk_diagnostics(equity),
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
        "riskDiagnostics": result.risk_diagnostics.to_dict(),
        "latestBar": _latest_bar(features),
    }


def get_btc_latest_signal_snapshot(
    *,
    timeframe: str = "4h",
    symbol: str = "BTC/USDT",
    equity: float = 10_000.0,
    load_ohlcv: Callable[[str], pd.DataFrame] | None = None,
    build_features: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
    generate_signals: Callable[[pd.DataFrame, str], list[Signal]] | None = None,
) -> dict[str, Any]:
    """Return the latest read-only standardized BTC signal pipeline snapshot."""
    payload = get_btc_pipeline_preview(
        timeframe=timeframe,
        symbol=symbol,
        equity=equity,
        load_ohlcv=load_ohlcv,
        build_features=build_features,
        generate_signals=generate_signals,
    )
    return {
        **payload,
        "mode": "latest",
        "readOnly": True,
    }


def get_signal_research_preview(
    *,
    timeframe: str,
    symbol: str,
    exchange: str,
    market_type: str,
    equity: float = 10_000.0,
    load_ohlcv: Callable[[str, MarketSpec], pd.DataFrame] | None = None,
    build_features: Callable[[pd.DataFrame, MarketSpec, RegimeProfile], pd.DataFrame] | None = None,
    generate_signals: Callable[[pd.DataFrame, str, MarketSpec, RegimeProfile], list[Signal]] | None = None,
    refresh_bars: bool = False,
    refresh_features: bool = False,
) -> dict[str, Any]:
    """Run a generic read-only signal research preview for a configured market."""
    market = resolve_market_spec(symbol, exchange=exchange, market_type=market_type)
    regime_profile = resolve_regime_profile(market)
    bars = (
        load_ohlcv(timeframe, market)
        if load_ohlcv
        else load_research_preview_bars(timeframe, market, refresh=refresh_bars)
    )
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
            "riskDiagnostics": _empty_risk_diagnostics(equity),
            "latestRegime": None,
            "latestBar": None,
            "featureCache": None,
        }

    if build_features:
        features = build_features(bars, market, regime_profile)
        feature_cache = None
    else:
        feature_result = _default_research_feature_result(
            bars,
            market,
            regime_profile,
            timeframe=timeframe,
            refresh=refresh_features,
        )
        features = feature_result.features
        feature_cache = feature_result.cache
    signals = (
        generate_signals(features, symbol, market, regime_profile)
        if generate_signals
        else _default_research_signal_generator(features, symbol, timeframe=timeframe, market=market)
    )
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
        "riskDiagnostics": result.risk_diagnostics.to_dict(),
        "latestRegime": _latest_regime(features, regime_profile),
        "latestBar": _latest_bar(features),
        "featureCache": feature_cache,
    }


def get_btc_event_backtest_preview(
    *,
    timeframe: str = "4h",
    symbol: str = "BTC/USDT",
    equity: float = 10_000.0,
    load_ohlcv: Callable[[str], pd.DataFrame] | None = None,
    build_features: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
    generate_signals: Callable[[pd.DataFrame, str], list[Signal]] | None = None,
    execution: BacktestExecutionConfig | None = None,
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
            "summary": _empty_event_summary(equity),
            "orders": [],
            "orderActionCounts": _empty_order_action_counts(),
            "orderModuleCounts": {},
            "orderSymbolCounts": {},
            "orderLayerCounts": {},
            "orderStatusCounts": _empty_order_status_counts(),
            "filledOrderCount": 0,
            "filledOrders": [],
            "terminalOrderCount": 0,
            "terminalOrderReasonCounts": {},
            "terminalOrders": [],
            "trades": [],
            "equityCurve": [],
            "exposureCurve": [],
            "exposureSummary": _empty_exposure_summary(),
            "attribution": _attribution_to_dict(BacktestAttribution({}, {}, {}, {}, {})),
            "finalPortfolio": _portfolio_state_to_dict(PortfolioState()),
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
        execution=execution,
        markets_by_symbol=markets_by_symbol,
    ).run({symbol: features})
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "rows": int(len(features)),
        "stepCount": len(result.steps),
        "signalCount": len(result.signals),
        "orderCount": len(result.orders) + len(result.trades),
        "filledOrderCount": len(result.filled_orders),
        "terminalOrderCount": len(result.terminal_orders),
        "terminalOrderReasonCounts": result.terminal_order_reason_counts,
        "tradeCount": len(result.trades),
        "summary": _performance_summary_to_dict(result.performance_summary),
        "orders": [_order_to_dict(order) for order in result.orders],
        "orderActionCounts": _order_action_counts_to_dict(result.order_action_counts),
        "orderModuleCounts": result.order_module_counts,
        "orderSymbolCounts": result.order_symbol_counts,
        "orderLayerCounts": result.order_layer_counts,
        "orderStatusCounts": _order_status_counts_to_dict(result.order_status_counts),
        "filledOrders": [_order_to_dict(order) for order in result.filled_orders],
        "terminalOrders": [_order_to_dict(order) for order in result.terminal_orders],
        "trades": [_trade_to_dict(trade) for trade in result.trades],
        "equityCurve": [_equity_point_to_dict(point) for point in result.equity_curve],
        "exposureCurve": [_exposure_point_to_dict(point) for point in result.exposure_curve],
        "exposureSummary": _exposure_summary_to_dict(result.exposure_summary),
        "attribution": _attribution_to_dict(result.attribution),
        "finalPortfolio": _portfolio_state_to_dict(pipeline.portfolio_engine.state),
        "latestBar": _latest_bar(features),
    }


def get_signal_research_event_backtest_preview(
    *,
    timeframe: str,
    symbol: str | list[str],
    exchange: str | list[str],
    market_type: str | list[str],
    equity: float = 10_000.0,
    load_ohlcv: Callable[[str, MarketSpec], pd.DataFrame] | None = None,
    build_features: Callable[[pd.DataFrame, MarketSpec, RegimeProfile], pd.DataFrame] | None = None,
    generate_signals: Callable[[pd.DataFrame, str, MarketSpec, RegimeProfile], list[Signal]] | None = None,
    refresh_bars: bool = False,
    refresh_features: bool = False,
    execution: BacktestExecutionConfig | None = None,
) -> dict[str, Any]:
    """Run a generic read-only event-driven research backtest for a configured market."""
    market_queries = _research_market_queries(symbol, exchange, market_type)
    if len(market_queries) > 1:
        return _get_signal_research_multi_event_backtest_preview(
            timeframe=timeframe,
            market_queries=market_queries,
            equity=equity,
            load_ohlcv=load_ohlcv,
            build_features=build_features,
            generate_signals=generate_signals,
            refresh_bars=refresh_bars,
            refresh_features=refresh_features,
            execution=execution,
        )

    symbol, exchange, market_type = market_queries[0]
    market = resolve_market_spec(symbol, exchange=exchange, market_type=market_type)
    regime_profile = resolve_regime_profile(market)
    bars = (
        load_ohlcv(timeframe, market)
        if load_ohlcv
        else load_research_preview_bars(timeframe, market, refresh=refresh_bars)
    )
    if bars.empty:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "market": _market_to_dict(market),
            "regimeProfile": _regime_profile_to_dict(regime_profile),
            "rows": 0,
            "stepCount": 0,
            "signalCount": 0,
            "orderCount": 0,
            "tradeCount": 0,
            "summary": _empty_event_summary(equity),
            "orders": [],
            "orderActionCounts": _empty_order_action_counts(),
            "orderModuleCounts": {},
            "orderSymbolCounts": {},
            "orderLayerCounts": {},
            "orderStatusCounts": _empty_order_status_counts(),
            "filledOrderCount": 0,
            "filledOrders": [],
            "terminalOrderCount": 0,
            "terminalOrderReasonCounts": {},
            "terminalOrders": [],
            "trades": [],
            "equityCurve": [],
            "exposureCurve": [],
            "exposureSummary": _empty_exposure_summary(),
            "attribution": _attribution_to_dict(BacktestAttribution({}, {}, {}, {}, {})),
            "finalPortfolio": _portfolio_state_to_dict(PortfolioState()),
            "latestRegime": None,
            "latestBar": None,
            "featureCaches": {symbol: None},
        }

    if build_features:
        features = build_features(bars, market, regime_profile)
        feature_cache = None
    else:
        feature_result = _default_research_feature_result(
            bars,
            market,
            regime_profile,
            timeframe=timeframe,
            refresh=refresh_features,
        )
        features = feature_result.features
        feature_cache = feature_result.cache

    def signal_generator(frame: pd.DataFrame, signal_symbol: str) -> list[Signal]:
        if generate_signals:
            return generate_signals(frame, signal_symbol, market, regime_profile)
        return _default_research_signal_generator(frame, signal_symbol, timeframe=timeframe, market=market)

    markets_by_symbol = {symbol: market}
    pipeline = SignalPipeline(
        signal_runner=SignalModuleRunner([_CallableSignalModule(signal_generator)]),
        risk_engine=RiskEngine(RiskLimits()),
        portfolio_engine=PortfolioEngine(),
        markets_by_symbol=markets_by_symbol,
    )
    result = EventDrivenBacktest(
        pipeline=pipeline,
        account=AccountState(equity=float(equity)),
        execution=execution,
        markets_by_symbol=markets_by_symbol,
    ).run({symbol: features})
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "market": _market_to_dict(market),
        "regimeProfile": _regime_profile_to_dict(regime_profile),
        "rows": int(len(features)),
        "stepCount": len(result.steps),
        "signalCount": len(result.signals),
        "orderCount": len(result.orders) + len(result.trades),
        "filledOrderCount": len(result.filled_orders),
        "terminalOrderCount": len(result.terminal_orders),
        "terminalOrderReasonCounts": result.terminal_order_reason_counts,
        "tradeCount": len(result.trades),
        "summary": _performance_summary_to_dict(result.performance_summary),
        "orders": [_order_to_dict(order) for order in result.orders],
        "orderActionCounts": _order_action_counts_to_dict(result.order_action_counts),
        "orderModuleCounts": result.order_module_counts,
        "orderSymbolCounts": result.order_symbol_counts,
        "orderLayerCounts": result.order_layer_counts,
        "orderStatusCounts": _order_status_counts_to_dict(result.order_status_counts),
        "filledOrders": [_order_to_dict(order) for order in result.filled_orders],
        "terminalOrders": [_order_to_dict(order) for order in result.terminal_orders],
        "trades": [_trade_to_dict(trade) for trade in result.trades],
        "equityCurve": [_equity_point_to_dict(point) for point in result.equity_curve],
        "exposureCurve": [_exposure_point_to_dict(point) for point in result.exposure_curve],
        "exposureSummary": _exposure_summary_to_dict(result.exposure_summary),
        "attribution": _attribution_to_dict(result.attribution),
        "finalPortfolio": _portfolio_state_to_dict(pipeline.portfolio_engine.state),
        "latestRegime": _latest_regime(features, regime_profile),
        "latestBar": _latest_bar(features),
        "featureCaches": {symbol: feature_cache},
    }


def _get_signal_research_multi_event_backtest_preview(
    *,
    timeframe: str,
    market_queries: list[tuple[str, str, str]],
    equity: float,
    load_ohlcv: Callable[[str, MarketSpec], pd.DataFrame] | None,
    build_features: Callable[[pd.DataFrame, MarketSpec, RegimeProfile], pd.DataFrame] | None,
    generate_signals: Callable[[pd.DataFrame, str, MarketSpec, RegimeProfile], list[Signal]] | None,
    refresh_bars: bool,
    refresh_features: bool,
    execution: BacktestExecutionConfig | None,
) -> dict[str, Any]:
    markets_by_symbol: dict[str, MarketSpec] = {}
    regimes_by_symbol: dict[str, RegimeProfile] = {}
    features_by_symbol: dict[str, pd.DataFrame] = {}
    feature_caches: dict[str, dict[str, object] | None] = {}
    latest_bars: dict[str, dict[str, Any] | None] = {}
    latest_regimes: dict[str, dict[str, Any] | None] = {}

    for query_symbol, query_exchange, query_market_type in market_queries:
        market = resolve_market_spec(query_symbol, exchange=query_exchange, market_type=query_market_type)
        if market.asset.symbol in markets_by_symbol:
            raise ValueError(f"Duplicate research market symbol: {market.asset.symbol}")
        regime_profile = resolve_regime_profile(market)
        bars = (
            load_ohlcv(timeframe, market)
            if load_ohlcv
            else load_research_preview_bars(timeframe, market, refresh=refresh_bars)
        )
        markets_by_symbol[market.asset.symbol] = market
        regimes_by_symbol[market.asset.symbol] = regime_profile
        if bars.empty:
            feature_caches[market.asset.symbol] = None
            latest_bars[market.asset.symbol] = None
            latest_regimes[market.asset.symbol] = None
            continue
        if build_features:
            features = build_features(bars, market, regime_profile)
            feature_cache = None
        else:
            feature_result = _default_research_feature_result(
                bars,
                market,
                regime_profile,
                timeframe=timeframe,
                refresh=refresh_features,
            )
            features = feature_result.features
            feature_cache = feature_result.cache
        features_by_symbol[market.asset.symbol] = features
        feature_caches[market.asset.symbol] = feature_cache
        latest_bars[market.asset.symbol] = _latest_bar(features)
        latest_regimes[market.asset.symbol] = _latest_regime(features, regime_profile)

    def signal_generator(frame: pd.DataFrame, signal_symbol: str) -> list[Signal]:
        market = markets_by_symbol[signal_symbol]
        regime_profile = regimes_by_symbol[signal_symbol]
        if generate_signals:
            return generate_signals(frame, signal_symbol, market, regime_profile)
        return _default_research_signal_generator(frame, signal_symbol, timeframe=timeframe, market=market)

    pipeline = SignalPipeline(
        signal_runner=SignalModuleRunner([_CallableSignalModule(signal_generator)]),
        risk_engine=RiskEngine(RiskLimits()),
        portfolio_engine=PortfolioEngine(),
        markets_by_symbol=markets_by_symbol,
    )
    result = EventDrivenBacktest(
        pipeline=pipeline,
        account=AccountState(equity=float(equity)),
        execution=execution,
        markets_by_symbol=markets_by_symbol,
    ).run(features_by_symbol)
    return {
        "symbols": [market.asset.symbol for market in markets_by_symbol.values()],
        "timeframe": timeframe,
        "markets": {
            symbol: _market_to_dict(market)
            for symbol, market in markets_by_symbol.items()
        },
        "regimeProfiles": {
            symbol: _regime_profile_to_dict(profile)
            for symbol, profile in regimes_by_symbol.items()
        },
        "rows": sum(int(len(features)) for features in features_by_symbol.values()),
        "stepCount": len(result.steps),
        "signalCount": len(result.signals),
        "orderCount": len(result.orders) + len(result.trades),
        "filledOrderCount": len(result.filled_orders),
        "terminalOrderCount": len(result.terminal_orders),
        "terminalOrderReasonCounts": result.terminal_order_reason_counts,
        "tradeCount": len(result.trades),
        "summary": _performance_summary_to_dict(result.performance_summary),
        "orders": [_order_to_dict(order) for order in result.orders],
        "orderActionCounts": _order_action_counts_to_dict(result.order_action_counts),
        "orderModuleCounts": result.order_module_counts,
        "orderSymbolCounts": result.order_symbol_counts,
        "orderLayerCounts": result.order_layer_counts,
        "orderStatusCounts": _order_status_counts_to_dict(result.order_status_counts),
        "filledOrders": [_order_to_dict(order) for order in result.filled_orders],
        "terminalOrders": [_order_to_dict(order) for order in result.terminal_orders],
        "trades": [_trade_to_dict(trade) for trade in result.trades],
        "equityCurve": [_equity_point_to_dict(point) for point in result.equity_curve],
        "exposureCurve": [_exposure_point_to_dict(point) for point in result.exposure_curve],
        "exposureSummary": _exposure_summary_to_dict(result.exposure_summary),
        "attribution": _attribution_to_dict(result.attribution),
        "finalPortfolio": _portfolio_state_to_dict(pipeline.portfolio_engine.state),
        "latestRegimes": latest_regimes,
        "latestBars": latest_bars,
        "featureCaches": feature_caches,
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
    load_risk_audits: Callable[[], list[Any]] | None = None,
    load_pipeline_audits: Callable[[], list[Any]] | None = None,
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
    risk_audit_loader = load_risk_audits or (
        lambda: load_btc_legacy_risk_audits(
            timeframe=timeframe,
            symbol=symbol,
            equity=equity,
            load_ohlcv=load_ohlcv,
            build_features=build_features,
        )
    )
    risk_audit = _risk_audit_payload(risk_audit_loader())
    pipeline_audit_loader = load_pipeline_audits or (
        lambda: load_btc_legacy_pipeline_audits(
            timeframe=timeframe,
            symbol=symbol,
            equity=equity,
            load_ohlcv=load_ohlcv,
            build_features=build_features,
        )
    )
    pipeline_audit = _pipeline_audit_payload(pipeline_audit_loader())
    order_parity = _order_parity_payload(pipeline_audit, event)
    migration_readiness = _migration_readiness_payload(
        risk_audit, pipeline_audit, order_parity
    )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "legacy": legacy,
        "event": event_summary,
        "riskAudit": risk_audit,
        "pipelineAudit": pipeline_audit,
        "orderParity": order_parity,
        "migrationReadiness": migration_readiness,
        "delta": {
            "tradeCount": event_summary["tradeCount"] - legacy["tradeCount"],
            "totalPnl": event_summary["realizedPnl"] - legacy["totalPnl"],
            "finalEquity": event_summary["finalEquity"] - legacy["finalEquity"],
            "winRatePct": event_summary["winRatePct"] - legacy["winRatePct"],
        },
    }


def load_btc_legacy_risk_audits(
    *,
    timeframe: str = "4h",
    symbol: str = "BTC/USDT",
    equity: float = 10_000.0,
    load_ohlcv: Callable[[str], pd.DataFrame] | None = None,
    build_features: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
    run_legacy_backtest: Callable[..., Any] | None = None,
) -> list[Any]:
    """Run the legacy BTC backtest path and return recorded platform risk audits."""
    result = _run_btc_legacy_backtest_for_audit(
        timeframe=timeframe,
        symbol=symbol,
        equity=equity,
        load_ohlcv=load_ohlcv,
        build_features=build_features,
        run_legacy_backtest=run_legacy_backtest,
    )
    if result is None:
        return []
    return _extract_legacy_strategy_risk_audits(result)


def load_btc_legacy_pipeline_audits(
    *,
    timeframe: str = "4h",
    symbol: str = "BTC/USDT",
    equity: float = 10_000.0,
    load_ohlcv: Callable[[str], pd.DataFrame] | None = None,
    build_features: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
    run_legacy_backtest: Callable[..., Any] | None = None,
) -> list[Any]:
    """Run the legacy BTC backtest path and return recorded platform pipeline audits."""
    result = _run_btc_legacy_backtest_for_audit(
        timeframe=timeframe,
        symbol=symbol,
        equity=equity,
        load_ohlcv=load_ohlcv,
        build_features=build_features,
        run_legacy_backtest=run_legacy_backtest,
    )
    if result is None:
        return []
    return _extract_legacy_strategy_pipeline_results(result)


def _run_btc_legacy_backtest_for_audit(
    *,
    timeframe: str,
    symbol: str,
    equity: float,
    load_ohlcv: Callable[[str], pd.DataFrame] | None,
    build_features: Callable[[pd.DataFrame], pd.DataFrame] | None,
    run_legacy_backtest: Callable[..., Any] | None,
) -> Any | None:
    bars = (load_ohlcv or get_ohlcv)(timeframe)
    if bars.empty:
        return None

    features = (
        build_features(bars)
        if build_features
        else _default_btc_feature_builder(bars, timeframe=timeframe, symbol=symbol)
    )
    from quant_btc.config import BacktestConfig, RiskConfig

    runner = run_legacy_backtest
    if runner is None:
        from quant_btc.strategy import FractionalBacktest, run_backtest

        if FractionalBacktest is None:
            return None
        runner = run_backtest
    return runner(
        features,
        BacktestConfig(symbol=symbol, timeframe=timeframe, initial_cash=float(equity)),
        strategy_name="dual",
        risk_cfg=RiskConfig(),
    )


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


def get_signal_market_options() -> dict[str, Any]:
    """Return configured markets for dashboard/API selection controls."""
    catalog = _load_project_market_catalog()
    return {
        "markets": [
            _market_to_dict(market)
            for record in catalog.to_records()
            for market in [catalog.resolve(
                record["symbol"],
                exchange=record["exchange"],
                market_type=record["market_type"],
            )]
        ]
    }


def resolve_regime_profile(market: MarketSpec) -> RegimeProfile:
    return _load_project_regime_profiles().profile_for(market)


def _research_market_queries(
    symbol: str | list[str],
    exchange: str | list[str],
    market_type: str | list[str],
) -> list[tuple[str, str, str]]:
    symbols = _query_values(symbol)
    exchanges = _broadcast_query_values(exchange, len(symbols), "exchange")
    market_types = _broadcast_query_values(market_type, len(symbols), "market_type")
    return list(zip(symbols, exchanges, market_types))


def _query_values(value: str | list[str]) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [str(item).strip() for item in values if str(item).strip()]


def _broadcast_query_values(value: str | list[str], expected: int, name: str) -> list[str]:
    values = _query_values(value)
    if len(values) == expected:
        return values
    if len(values) == 1 and expected > 1:
        return values * expected
    raise ValueError(f"Expected 1 or {expected} {name} values, got {len(values)}.")


def load_research_preview_bars(timeframe: str, market: MarketSpec, *, refresh: bool = False) -> pd.DataFrame:
    """Load preview bars through configured project data connectors."""
    if market.asset.symbol == "BTC/USDT" and market.exchange == "binance" and market.market_type == "swap":
        return get_ohlcv(timeframe)
    if not _RESEARCH_DATA_SOURCE_PATH.exists():
        return pd.DataFrame()

    payload = json.loads(_RESEARCH_DATA_SOURCE_PATH.read_text(encoding="utf-8"))
    route = _resolve_research_data_route(payload.get("routes", []), market, timeframe)
    if route is None:
        return pd.DataFrame()

    source = route.get("source")
    if not source:
        raise ValueError("Research data source route requires source.")
    registry = load_data_connector_registry_json(_RESEARCH_DATA_SOURCE_PATH, base_dir=_PROJECT_ROOT)
    bars = fetch_bars_with_cache(
        connector=registry.get(str(source)),
        store=ParquetBarStore(_PROJECT_ROOT / "data" / "research_bars"),
        source=str(source),
        market=market,
        timeframe=timeframe,
        limit=route.get("limit"),
        refresh=refresh or bool(route.get("refresh", False)),
    )
    return _filter_research_bars_to_market_session(bars, timeframe, market)


def _filter_research_bars_to_market_session(
    bars: pd.DataFrame,
    timeframe: str,
    market: MarketSpec,
) -> pd.DataFrame:
    if bars.empty or not _is_intraday_timeframe(timeframe):
        return bars
    mask = [market.is_trading_time(timestamp) for timestamp in bars.index]
    return bars.loc[mask]


def _is_intraday_timeframe(timeframe: str) -> bool:
    value = str(timeframe).strip().lower()
    return value.endswith("m") or value.endswith("min") or value.endswith("h")


def load_research_preview_derivatives(
    timeframe: str,
    market: MarketSpec,
    *,
    refresh: bool = False,
) -> pd.DataFrame | None:
    """Load funding/open-interest research data through configured project data connectors."""
    if market.market_type not in {"swap", "future", "futures"}:
        return None
    if not _RESEARCH_DATA_SOURCE_PATH.exists():
        return None

    payload = json.loads(_RESEARCH_DATA_SOURCE_PATH.read_text(encoding="utf-8"))
    route = _resolve_research_data_route(
        payload.get("routes", []),
        market,
        timeframe,
        data_type="derivatives",
    )
    if route is None:
        return None

    source = route.get("source")
    if not source:
        raise ValueError("Research derivative source route requires source.")
    registry = load_data_connector_registry_json(_RESEARCH_DATA_SOURCE_PATH, base_dir=_PROJECT_ROOT)
    return fetch_derivatives_with_cache(
        connector=registry.get(str(source)),
        store=ParquetDerivativeStore(_PROJECT_ROOT / "data" / "research_derivatives"),
        source=str(source),
        market=market,
        funding_limit=int(route.get("funding_limit", 1000)),
        open_interest_timeframe=str(route.get("open_interest_timeframe", timeframe)),
        open_interest_limit=int(route.get("open_interest_limit", 1000)),
        refresh=refresh or bool(route.get("refresh", False)),
    )


def load_research_preview_order_book(
    timeframe: str,
    market: MarketSpec,
    *,
    refresh: bool = False,
) -> pd.DataFrame | None:
    """Load order-book research snapshots through configured project data connectors."""
    if not _RESEARCH_DATA_SOURCE_PATH.exists():
        return None

    payload = json.loads(_RESEARCH_DATA_SOURCE_PATH.read_text(encoding="utf-8"))
    route = _resolve_research_data_route(
        payload.get("routes", []),
        market,
        timeframe,
        data_type="order_book",
    )
    if route is None:
        return None

    source = route.get("source")
    if not source:
        raise ValueError("Research order-book source route requires source.")
    depth = int(route.get("depth", 5))
    registry = load_data_connector_registry_json(_RESEARCH_DATA_SOURCE_PATH, base_dir=_PROJECT_ROOT)
    snapshots = fetch_order_book_snapshots_with_cache(
        connector=registry.get(str(source)),
        store=ParquetOrderBookStore(_PROJECT_ROOT / "data" / "research_order_books"),
        source=str(source),
        market=market,
        depth=depth,
        sample_interval=str(route.get("sample_interval", "snapshot")),
        limit=int(route.get("limit", 1000)),
        refresh=refresh or bool(route.get("refresh", False)),
    )
    snapshots.attrs["depth"] = depth
    return snapshots


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


def _default_research_feature_builder(
    bars: pd.DataFrame,
    market: MarketSpec,
    regime_profile: RegimeProfile,
    *,
    timeframe: str,
    refresh: bool = False,
) -> pd.DataFrame:
    return _default_research_feature_result(
        bars,
        market,
        regime_profile,
        timeframe=timeframe,
        refresh=refresh,
    ).features


def _default_research_feature_result(
    bars: pd.DataFrame,
    market: MarketSpec,
    regime_profile: RegimeProfile,
    *,
    timeframe: str,
    refresh: bool = False,
) -> FeatureRunResult:
    try:
        derivatives = load_research_preview_derivatives(timeframe, market, refresh=refresh)
    except (NotImplementedError, MissingStorageDependency, OSError):
        derivatives = None
    try:
        order_book = load_research_preview_order_book(timeframe, market, refresh=refresh)
    except (NotImplementedError, MissingStorageDependency, OSError):
        order_book = None
    modules = [
        TechnicalIndicatorModule(TechnicalIndicatorConfig(ema_lengths=(regime_profile.trend_ema_length,))),
        DonchianFeatureModule(DonchianConfig()),
        VolumeFeatureModule(VolumeConfig()),
        VolatilityFeatureModule(
            VolatilityConfig(
                period=regime_profile.atr_period,
                adx_period=regime_profile.adx_period,
                percentile_lookback=regime_profile.regime_lookback,
            )
        ),
        BollingerFeatureModule(
            BollingerConfig(
                period=regime_profile.bb_period,
                std_mult=regime_profile.bb_std_mult,
            )
        ),
        PriceActionFeatureModule(),
    ]
    include_derivatives = derivatives is not None and not derivatives.empty
    if include_derivatives:
        modules.append(DerivativesFeatureModule(derivatives))
    include_order_book = order_book is not None and not order_book.empty
    order_book_depth = int(order_book.attrs.get("depth", 5)) if include_order_book else None
    if include_order_book:
        modules.append(OrderBookFeatureModule(order_book, OrderBookFeatureConfig(depth=order_book_depth or 5)))
    engine = FeatureEngine(modules)
    series_id = FeatureSeriesId(
        symbol=market.asset.symbol,
        exchange=market.exchange,
        market_type=market.market_type,
        timeframe=timeframe,
        source="feature_engine",
        feature_set=_default_research_feature_set(
            regime_profile,
            include_derivatives=include_derivatives,
            order_book_depth=order_book_depth,
        ),
    )
    try:
        return run_feature_engine_with_cache(
            engine,
            bars,
            series_id=series_id,
            store=ParquetFeatureStore(_PROJECT_ROOT / "data" / "research_features"),
            refresh=refresh,
        )
    except (MissingStorageDependency, OSError, ValueError):
        return FeatureRunResult(features=engine.run(bars))


def _default_research_feature_set(
    regime_profile: RegimeProfile,
    *,
    include_derivatives: bool = False,
    order_book_depth: int | None = None,
) -> str:
    feature_set = (
        f"research_default_v1_ema{int(regime_profile.trend_ema_length)}"
        f"_atr{int(regime_profile.atr_period)}"
        f"_adx{int(regime_profile.adx_period)}"
        f"_bb{int(regime_profile.bb_period)}x{_feature_set_number(regime_profile.bb_std_mult)}"
    )
    if include_derivatives:
        feature_set += "_derivatives"
    if order_book_depth is not None:
        feature_set += f"_order_book_d{int(order_book_depth)}"
    return feature_set


def _feature_set_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return str(value).replace(".", "p")


def _default_btc_signal_generator(features: pd.DataFrame, symbol: str) -> list[Signal]:
    from quant_btc.signal_modules import generate_btc_standard_signals

    return generate_btc_standard_signals(features, symbol=symbol)


def _default_research_signal_generator(
    features: pd.DataFrame,
    symbol: str,
    *,
    timeframe: str,
    market: MarketSpec | None = None,
) -> list[Signal]:
    runner = _research_signal_module_runner(timeframe=timeframe, market=market)
    return runner.generate(features, symbol=symbol)


def _research_signal_module_runner(*, timeframe: str, market: MarketSpec | None) -> SignalModuleRunner:
    records = _configured_research_signal_module_records(timeframe=timeframe, market=market)
    if records is None:
        return SignalModuleRunner([
            BreakoutSignalModule(BreakoutSignalConfig(lookback=3, timeframe=timeframe)),
            PullbackSignalModule(PullbackSignalConfig(ema_length=3, timeframe=timeframe)),
            MeanReversionSignalModule(MeanReversionSignalConfig(lookback=3, std_mult=1.0, timeframe=timeframe)),
            SweepReversalSignalModule(SweepReversalSignalConfig(lookback=3, timeframe=timeframe)),
            CrashShortSignalModule(CrashShortSignalConfig(lookback=3, timeframe=timeframe)),
            FailedBounceSignalModule(FailedBounceSignalConfig(lookback=3, timeframe=timeframe)),
            BullTrapSignalModule(BullTrapSignalConfig(lookback=3, timeframe=timeframe)),
        ])
    return default_signal_module_registry().build_runner(records)


def _configured_research_signal_module_records(
    *,
    timeframe: str,
    market: MarketSpec | None,
) -> list[dict[str, object]] | None:
    if market is None or not _RESEARCH_SIGNAL_MODULE_PATH.exists():
        return None
    payload = json.loads(_RESEARCH_SIGNAL_MODULE_PATH.read_text(encoding="utf-8"))
    module_set_name = _resolve_research_signal_module_set(payload, market, timeframe)
    if not module_set_name:
        return None
    module_sets = {
        str(record.get("name")): record
        for record in payload.get("module_sets", [])
        if record.get("name")
    }
    module_set = module_sets.get(str(module_set_name))
    if module_set is None:
        raise ValueError(f"Research signal module set not found: {module_set_name}")
    return _signal_module_records_with_timeframe(module_set.get("modules", []), timeframe)


def _resolve_research_signal_module_set(payload: dict[str, Any], market: MarketSpec, timeframe: str) -> str | None:
    for route in payload.get("routes", []):
        if route.get("symbol") != market.asset.symbol:
            continue
        if route.get("exchange") != market.exchange:
            continue
        if route.get("market_type") != market.market_type:
            continue
        route_timeframe = route.get("timeframe")
        if route_timeframe is not None and route_timeframe != timeframe:
            continue
        return route.get("module_set")
    return payload.get("default_module_set")


def _signal_module_records_with_timeframe(
    records: list[dict[str, Any]],
    timeframe: str,
) -> list[dict[str, object]]:
    configured: list[dict[str, object]] = []
    for record in records:
        module_record = dict(record)
        params = dict(module_record.get("params") or {})
        if module_record.get("type") != "column" and "timeframe" not in params:
            params["timeframe"] = timeframe
        module_record["params"] = params
        configured.append(module_record)
    return configured


def _resolve_research_data_route(
    routes: list[dict[str, Any]],
    market: MarketSpec,
    timeframe: str,
    *,
    data_type: str = "bars",
) -> dict[str, Any] | None:
    for route in routes:
        route_data_type = route.get("data_type", "bars")
        if route_data_type != data_type:
            continue
        if route.get("symbol") != market.asset.symbol:
            continue
        if route.get("exchange") != market.exchange:
            continue
        if route.get("market_type") != market.market_type:
            continue
        route_timeframe = route.get("timeframe")
        if route_timeframe is not None and route_timeframe != timeframe:
            continue
        return route
    return None


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


def _latest_regime(features: pd.DataFrame, profile: RegimeProfile) -> dict[str, Any] | None:
    if features.empty:
        return None
    classified = RegimeModel(profile).classify(features)
    row = classified.iloc[-1]
    index = classified.index[-1]
    value = int(row["_regime"])
    try:
        label = RegimeLabel(value).name.lower()
    except ValueError:
        label = "unknown"
    return {
        "time": index.isoformat() if hasattr(index, "isoformat") else str(index),
        "value": value,
        "label": label,
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


def _empty_risk_diagnostics(equity: float) -> dict[str, Any]:
    return RiskEngine(RiskLimits()).budget_diagnostics(
        AccountState(equity=float(equity))
    ).to_dict()


def _order_to_dict(order: PortfolioOrder) -> dict[str, Any]:
    decision = order.decision
    module = decision.signal.module if decision is not None else ""
    return {
        "order_id": order.order_id,
        "action": order.action.value,
        "symbol": order.symbol,
        "layer": order.layer,
        "module": module,
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


def _position_to_dict(position: Position) -> dict[str, Any]:
    return {
        "symbol": position.symbol,
        "layer": position.layer,
        "module": position.module,
        "direction": position.direction.value,
        "quantity": position.quantity,
        "notional": position.notional,
        "riskAmount": position.risk_amount,
        "entryPrice": position.entry_price,
        "stopPrice": position.stop_price,
        "targetPrice": position.target_price,
    }


def _portfolio_state_to_dict(state: PortfolioState) -> dict[str, Any]:
    positions = sorted(
        state.positions.values(),
        key=lambda position: (position.symbol, position.layer, position.module),
    )
    return {
        "positionCount": len(positions),
        "openRisk": state.open_risk(),
        "positions": [_position_to_dict(position) for position in positions],
    }


def _empty_order_status_counts() -> dict[str, int]:
    return {status.value: 0 for status in OrderStatus}


def _empty_order_action_counts() -> dict[str, int]:
    return {action.value: 0 for action in OrderAction}


def _order_action_counts_to_dict(counts: dict[OrderAction, int]) -> dict[str, int]:
    return {action.value: int(counts.get(action, 0)) for action in OrderAction}


def _order_status_counts_to_dict(counts: dict[OrderStatus, int]) -> dict[str, int]:
    return {status.value: int(counts.get(status, 0)) for status in OrderStatus}


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
        "sessionTimezone": market.session_timezone,
        "sessionOpen": market.session_open,
        "sessionClose": market.session_close,
        "tradingDays": list(market.trading_days),
        "correlationGroup": market.correlation_group,
        "supportsShort": market.supports_short,
        "supportsLeverage": market.supports_leverage,
        "maxLeverage": market.max_leverage,
    }


def _regime_profile_to_dict(profile: RegimeProfile) -> dict[str, Any]:
    return {_snake_to_camel(key): value for key, value in asdict(profile).items()}


def _snake_to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def _empty_event_summary(equity: float) -> dict[str, Any]:
    return {
        "initialEquity": float(equity),
        "finalEquity": float(equity),
        "totalReturnPct": 0.0,
        "finalUnrealizedPnl": 0.0,
        "realizedPnl": 0.0,
        "feesPaid": 0.0,
        "fundingPaid": 0.0,
        "maxEquity": float(equity),
        "minEquity": float(equity),
        "maxDrawdownAmount": 0.0,
        "maxDrawdownPct": 0.0,
        "tradeCount": 0,
        "winRate": 0.0,
        "averageTradeNetPnl": 0.0,
        "averageHoldingBars": None,
        "grossProfit": 0.0,
        "grossLoss": 0.0,
        "profitFactor": None,
        "averageWinNetPnl": None,
        "averageLossNetPnl": None,
        "payoffRatio": None,
    }


def _performance_summary_to_dict(summary) -> dict[str, Any]:
    return {
        "initialEquity": summary.initial_equity,
        "finalEquity": summary.final_equity,
        "totalReturnPct": summary.total_return_pct,
        "finalUnrealizedPnl": summary.final_unrealized_pnl,
        "realizedPnl": summary.realized_pnl,
        "feesPaid": summary.fees_paid,
        "fundingPaid": summary.funding_paid,
        "maxEquity": summary.max_equity,
        "minEquity": summary.min_equity,
        "maxDrawdownAmount": summary.max_drawdown_amount,
        "maxDrawdownPct": summary.max_drawdown_pct,
        "tradeCount": summary.trade_count,
        "winRate": summary.win_rate,
        "averageTradeNetPnl": summary.average_trade_net_pnl,
        "averageHoldingBars": summary.average_holding_bars,
        "grossProfit": summary.gross_profit,
        "grossLoss": summary.gross_loss,
        "profitFactor": summary.profit_factor,
        "averageWinNetPnl": summary.average_win_net_pnl,
        "averageLossNetPnl": summary.average_loss_net_pnl,
        "payoffRatio": summary.payoff_ratio,
    }


def _timestamp_to_dict_value(timestamp: object | None) -> str | None:
    if timestamp is None:
        return None
    return timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)


def _trade_to_dict(trade: BacktestTrade) -> dict[str, Any]:
    return {
        "symbol": trade.symbol,
        "layer": trade.layer,
        "module": trade.module,
        "direction": trade.direction.value,
        "entry_time": _timestamp_to_dict_value(trade.entry_timestamp),
        "exit_time": _timestamp_to_dict_value(trade.exit_timestamp),
        "entry_bar_index": trade.entry_bar_index,
        "exit_bar_index": trade.exit_bar_index,
        "holding_bars": trade.holding_bars,
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


def _exposure_point_to_dict(point: BacktestExposurePoint) -> dict[str, Any]:
    return {
        "symbol": point.symbol,
        "time": point.timestamp.isoformat() if hasattr(point.timestamp, "isoformat") else str(point.timestamp),
        "barIndex": point.bar_index,
        "positionCount": point.position_count,
        "longNotional": point.long_notional,
        "shortNotional": point.short_notional,
        "grossNotional": point.gross_notional,
        "netNotional": point.net_notional,
        "openRisk": point.open_risk,
        "symbolExposure": {
            symbol: _exposure_bucket_to_dict(bucket)
            for symbol, bucket in point.symbol_exposure.items()
        },
        "layerExposure": {
            layer: _exposure_bucket_to_dict(bucket)
            for layer, bucket in point.layer_exposure.items()
        },
        "moduleExposure": {
            module: _exposure_bucket_to_dict(bucket)
            for module, bucket in point.module_exposure.items()
        },
        "groupExposure": {
            group: _exposure_bucket_to_dict(bucket)
            for group, bucket in point.group_exposure.items()
        },
    }


def _exposure_bucket_to_dict(bucket) -> dict[str, Any]:
    return {
        "positionCount": bucket.position_count,
        "longNotional": bucket.long_notional,
        "shortNotional": bucket.short_notional,
        "grossNotional": bucket.gross_notional,
        "netNotional": bucket.net_notional,
        "openRisk": bucket.open_risk,
    }


def _exposure_summary_to_dict(summary) -> dict[str, Any]:
    return {
        "maxPositionCount": summary.max_position_count,
        "maxGrossNotional": summary.max_gross_notional,
        "maxAbsNetNotional": summary.max_abs_net_notional,
        "maxOpenRisk": summary.max_open_risk,
        "maxSymbolGrossNotional": summary.max_symbol_gross_notional,
        "maxSymbolOpenRisk": summary.max_symbol_open_risk,
        "maxLayerGrossNotional": summary.max_layer_gross_notional,
        "maxLayerOpenRisk": summary.max_layer_open_risk,
        "maxModuleGrossNotional": summary.max_module_gross_notional,
        "maxModuleOpenRisk": summary.max_module_open_risk,
        "maxGroupGrossNotional": summary.max_group_gross_notional,
        "maxGroupOpenRisk": summary.max_group_open_risk,
        "maxSymbolGrossNotionalSymbol": summary.max_symbol_gross_notional_symbol,
        "maxSymbolOpenRiskSymbol": summary.max_symbol_open_risk_symbol,
        "maxLayerGrossNotionalLayer": summary.max_layer_gross_notional_layer,
        "maxLayerOpenRiskLayer": summary.max_layer_open_risk_layer,
        "maxModuleGrossNotionalModule": summary.max_module_gross_notional_module,
        "maxModuleOpenRiskModule": summary.max_module_open_risk_module,
        "maxGroupGrossNotionalGroup": summary.max_group_gross_notional_group,
        "maxGroupOpenRiskGroup": summary.max_group_open_risk_group,
    }


def _empty_exposure_summary() -> dict[str, Any]:
    return {
        "maxPositionCount": 0,
        "maxGrossNotional": 0.0,
        "maxAbsNetNotional": 0.0,
        "maxOpenRisk": 0.0,
        "maxSymbolGrossNotional": 0.0,
        "maxSymbolOpenRisk": 0.0,
        "maxLayerGrossNotional": 0.0,
        "maxLayerOpenRisk": 0.0,
        "maxModuleGrossNotional": 0.0,
        "maxModuleOpenRisk": 0.0,
        "maxGroupGrossNotional": 0.0,
        "maxGroupOpenRisk": 0.0,
        "maxSymbolGrossNotionalSymbol": None,
        "maxSymbolOpenRiskSymbol": None,
        "maxLayerGrossNotionalLayer": None,
        "maxLayerOpenRiskLayer": None,
        "maxModuleGrossNotionalModule": None,
        "maxModuleOpenRiskModule": None,
        "maxGroupGrossNotionalGroup": None,
        "maxGroupOpenRiskGroup": None,
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
                "averageHoldingBars": bucket.average_holding_bars,
                "grossProfit": bucket.gross_profit,
                "grossLoss": bucket.gross_loss,
                "profitFactor": bucket.profit_factor,
                "averageWinNetPnl": bucket.average_win_net_pnl,
                "averageLossNetPnl": bucket.average_loss_net_pnl,
                "payoffRatio": bucket.payoff_ratio,
            }
            for key, bucket in items.items()
        }

    return {
        "bySymbol": bucket_map(attribution.by_symbol),
        "byLayer": bucket_map(attribution.by_layer),
        "byModule": bucket_map(attribution.by_module),
        "byDirection": bucket_map(attribution.by_direction),
        "byExitReason": bucket_map(attribution.by_exit_reason),
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


def _risk_audit_payload(audits: list[Any] | None) -> dict[str, Any]:
    rows = [_risk_audit_to_dict(audit) for audit in (audits or [])]
    status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("parity_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "auditCount": len(rows),
        "wouldBlockIfEnforcedCount": sum(
            1 for row in rows if bool(row.get("would_block_if_enforced"))
        ),
        "mismatchCount": sum(
            1 for row in rows if row.get("parity_status") != "matched"
        ),
        "parityStatusCounts": status_counts,
        "audits": rows,
    }


def _pipeline_audit_payload(results: list[Any] | None) -> dict[str, Any]:
    rows = [_pipeline_result_to_dict(result) for result in (results or [])]
    return {
        "auditCount": len(rows),
        "signalCount": sum(int(row.get("signalCount") or 0) for row in rows),
        "riskDecisionCount": sum(int(row.get("riskDecisionCount") or 0) for row in rows),
        "orderCount": sum(int(row.get("orderCount") or 0) for row in rows),
        "blockedDecisionCount": sum(
            1
            for row in rows
            for decision in row.get("riskDecisions", [])
            if not bool(decision.get("allowed"))
        ),
        "audits": rows,
    }


def _order_parity_payload(pipeline_audit: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    legacy_orders = [
        order
        for audit in pipeline_audit.get("audits", [])
        for order in audit.get("orders", [])
        if order.get("action") != "ignore"
    ]
    event_orders = [
        order
        for order in event.get("orders", [])
        if order.get("action") != "ignore"
    ]
    payload = _order_parity_counts(legacy_orders, event_orders)
    payload["missingFromEvent"] = [
        _order_signature_to_dict(signature) for signature in payload.pop("_missing")
    ]
    payload["extraInEvent"] = [
        _order_signature_to_dict(signature) for signature in payload.pop("_extra")
    ]
    modules = sorted({_order_module(order) for order in legacy_orders + event_orders})
    payload["byModule"] = {}
    for module in modules:
        module_legacy_orders = [
            order for order in legacy_orders if _order_module(order) == module
        ]
        module_event_orders = [
            order for order in event_orders if _order_module(order) == module
        ]
        module_counts = _order_parity_counts(module_legacy_orders, module_event_orders)
        module_counts.pop("_missing")
        module_counts.pop("_extra")
        payload["byModule"][module] = module_counts
    return payload


def _order_parity_counts(
    legacy_orders: list[dict[str, Any]], event_orders: list[dict[str, Any]]
) -> dict[str, Any]:
    legacy_counter = Counter(_order_signature(order) for order in legacy_orders)
    event_counter = Counter(_order_signature(order) for order in event_orders)
    matched_count = sum((legacy_counter & event_counter).values())
    missing = list((legacy_counter - event_counter).elements())
    extra = list((event_counter - legacy_counter).elements())
    return {
        "legacyOrderCount": len(legacy_orders),
        "eventOrderCount": len(event_orders),
        "matchedCount": matched_count,
        "mismatchCount": len(missing) + len(extra),
        "_missing": missing,
        "_extra": extra,
    }


def _order_module(order: dict[str, Any]) -> str:
    return str(order.get("module") or "unknown")


def _migration_readiness_payload(
    risk_audit: dict[str, Any],
    pipeline_audit: dict[str, Any],
    order_parity: dict[str, Any],
) -> dict[str, Any]:
    risk_by_module: dict[str, dict[str, int]] = {}
    for row in risk_audit.get("audits", []):
        module = str(row.get("module") or "unknown")
        bucket = risk_by_module.setdefault(
            module,
            {
                "riskAuditCount": 0,
                "riskMismatchCount": 0,
                "wouldBlockIfEnforcedCount": 0,
            },
        )
        bucket["riskAuditCount"] += 1
        if row.get("parity_status") != "matched":
            bucket["riskMismatchCount"] += 1
        if bool(row.get("would_block_if_enforced")):
            bucket["wouldBlockIfEnforcedCount"] += 1

    pipeline_by_module = _pipeline_audit_by_module(pipeline_audit)
    order_by_module = order_parity.get("byModule", {})
    modules = sorted(
        set(risk_by_module.keys())
        | set(pipeline_by_module.keys())
        | set(order_by_module.keys())
    )
    rows = []
    by_module = {}
    for module in modules:
        risk_counts = risk_by_module.get(module, {})
        pipeline_counts = pipeline_by_module.get(module, {})
        order_counts = order_by_module.get(module, {})
        reasons = []
        if int(pipeline_counts.get("pipelineAuditCount") or 0) == 0:
            reasons.append("missing_pipeline_audit")
        if int(pipeline_counts.get("pipelineOrderCount") or 0) == 0:
            reasons.append("missing_pipeline_order_audit")
        if int(risk_counts.get("riskAuditCount") or 0) == 0:
            reasons.append("missing_risk_audit")
        if int(risk_counts.get("riskMismatchCount") or 0) > 0:
            reasons.append("risk_parity_mismatch")
        if int(risk_counts.get("wouldBlockIfEnforcedCount") or 0) > 0:
            reasons.append("platform_would_block")
        if int(order_counts.get("mismatchCount") or 0) > 0:
            reasons.append("order_parity_mismatch")
        ready = not reasons
        status = "ready" if ready else "blocked"
        if any(reason.startswith("missing_") for reason in reasons):
            status = "needs_audit"
        row = {
            "module": module,
            "readyToMigrate": ready,
            "status": status,
            "reasons": reasons,
            "riskAuditCount": int(risk_counts.get("riskAuditCount") or 0),
            "riskMismatchCount": int(risk_counts.get("riskMismatchCount") or 0),
            "wouldBlockIfEnforcedCount": int(
                risk_counts.get("wouldBlockIfEnforcedCount") or 0
            ),
            "pipelineAuditCount": int(pipeline_counts.get("pipelineAuditCount") or 0),
            "pipelineSignalCount": int(pipeline_counts.get("pipelineSignalCount") or 0),
            "pipelineRiskDecisionCount": int(
                pipeline_counts.get("pipelineRiskDecisionCount") or 0
            ),
            "pipelineOrderCount": int(pipeline_counts.get("pipelineOrderCount") or 0),
            "legacyOrderCount": int(order_counts.get("legacyOrderCount") or 0),
            "eventOrderCount": int(order_counts.get("eventOrderCount") or 0),
            "matchedOrderCount": int(order_counts.get("matchedCount") or 0),
            "orderMismatchCount": int(order_counts.get("mismatchCount") or 0),
        }
        rows.append(row)
        by_module[module] = row
    return {
        "readyCount": sum(1 for row in rows if row["readyToMigrate"]),
        "blockedCount": sum(1 for row in rows if row["status"] == "blocked"),
        "needsAuditCount": sum(1 for row in rows if row["status"] == "needs_audit"),
        "modules": rows,
        "byModule": by_module,
    }


def _pipeline_audit_by_module(pipeline_audit: dict[str, Any]) -> dict[str, dict[str, int]]:
    by_module: dict[str, dict[str, int]] = {}
    for audit in pipeline_audit.get("audits", []):
        modules = set()
        for signal in audit.get("signals", []):
            modules.add(_payload_module(signal))
        for decision in audit.get("riskDecisions", []):
            modules.add(_payload_module(decision.get("signal", {})))
        for order in audit.get("orders", []):
            modules.add(_payload_module(order))
        for module in modules:
            bucket = by_module.setdefault(module, _empty_pipeline_module_counts())
            bucket["pipelineAuditCount"] += 1
        for signal in audit.get("signals", []):
            by_module.setdefault(_payload_module(signal), _empty_pipeline_module_counts())[
                "pipelineSignalCount"
            ] += 1
        for decision in audit.get("riskDecisions", []):
            by_module.setdefault(
                _payload_module(decision.get("signal", {})),
                _empty_pipeline_module_counts(),
            )["pipelineRiskDecisionCount"] += 1
        for order in audit.get("orders", []):
            if order.get("action") != "ignore":
                by_module.setdefault(
                    _payload_module(order), _empty_pipeline_module_counts()
                )["pipelineOrderCount"] += 1
    return by_module


def _empty_pipeline_module_counts() -> dict[str, int]:
    return {
        "pipelineAuditCount": 0,
        "pipelineSignalCount": 0,
        "pipelineRiskDecisionCount": 0,
        "pipelineOrderCount": 0,
    }


def _payload_module(payload: dict[str, Any]) -> str:
    return str(payload.get("module") or "unknown")


def _order_signature(order: dict[str, Any]) -> tuple[Any, ...]:
    return (
        order.get("action") or "",
        order.get("symbol") or "",
        order.get("layer") or "",
        order.get("direction") or "",
        order.get("module") or "",
        _signature_float(order.get("quantity")),
        _signature_float(order.get("entry_price")),
        _signature_float(order.get("stop_price")),
        _signature_float(order.get("target_price")),
    )


def _order_signature_to_dict(signature: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "action": signature[0],
        "symbol": signature[1],
        "layer": signature[2],
        "direction": signature[3],
        "module": signature[4],
        "quantity": signature[5],
        "entry_price": signature[6],
        "stop_price": signature[7],
        "target_price": signature[8],
    }


def _signature_float(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 8)


def _pipeline_result_to_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return dict(result)
    if not isinstance(result, PipelineResult):
        return {"value": result}
    return {
        "signalCount": len(result.signals),
        "riskDecisionCount": len(result.risk_decisions),
        "orderCount": len(result.portfolio_plan.orders),
        "deliveryCount": len(result.delivery_results),
        "signals": [signal.to_dict() for signal in result.signals],
        "riskDecisions": [_risk_decision_to_dict(decision) for decision in result.risk_decisions],
        "orders": [_order_to_dict(order) for order in result.portfolio_plan.orders],
        "deliveries": [_delivery_result_to_dict(delivery) for delivery in result.delivery_results],
        "riskDiagnostics": result.risk_diagnostics.to_dict(),
    }


def _delivery_result_to_dict(result: Any) -> dict[str, Any]:
    return {
        "ok": bool(getattr(result, "ok", False)),
        "channel": getattr(result, "channel", ""),
        "destination": getattr(result, "destination", ""),
        "response": getattr(result, "response", None),
        "error": getattr(result, "error", ""),
    }


def _risk_audit_to_dict(audit: Any) -> dict[str, Any]:
    if hasattr(audit, "to_dict"):
        return dict(audit.to_dict())
    if isinstance(audit, dict):
        return dict(audit)
    return {"value": audit}


def _extract_legacy_strategy_risk_audits(backtest_result: Any) -> list[Any]:
    strategy = _extract_legacy_strategy(backtest_result)
    return list(getattr(strategy, "_platform_risk_audits", []) or []) if strategy is not None else []


def _extract_legacy_strategy_pipeline_results(backtest_result: Any) -> list[Any]:
    strategy = _extract_legacy_strategy(backtest_result)
    if strategy is None:
        return []
    results = list(getattr(strategy, "_platform_pipeline_results", []) or [])
    if not results:
        last_result = getattr(strategy, "_last_platform_pipeline_result", None)
        if last_result is not None:
            results.append(last_result)
    return results


def _extract_legacy_strategy(backtest_result: Any) -> Any | None:
    stats = backtest_result[0] if isinstance(backtest_result, tuple) else backtest_result
    strategy = stats.get("_strategy") if hasattr(stats, "get") else None
    if strategy is None:
        strategy = getattr(stats, "_strategy", None)
    if strategy is None and isinstance(backtest_result, tuple) and len(backtest_result) > 1:
        results = getattr(backtest_result[1], "_results", None)
        strategy = results.get("_strategy") if hasattr(results, "get") else None
    return strategy


def _optional_float(value: Any) -> float | None:
    if pd.isna(value):
        return None
    return float(value)
