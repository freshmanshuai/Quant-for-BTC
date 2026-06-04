"""Valuescan payload adapters for platform external metric features."""

from __future__ import annotations

from typing import Any

import pandas as pd

from quant_platform.data import ExternalMetricSeriesId
from quant_platform.features import ExternalMetricFeatureConfig, ExternalMetricFeatureModule
from quant_platform.stores import ParquetExternalMetricStore


def build_valuescan_external_feature_frame(
    bars: pd.DataFrame,
    *,
    overview_payload: dict[str, Any] | None = None,
    lists_payload: dict[str, Any] | None = None,
    symbol: str = "BTC",
    prefix: str = "valuescan",
) -> pd.DataFrame:
    """Align normalized Valuescan metrics to bars as research-only external features."""
    frames: list[pd.DataFrame] = []
    if overview_payload:
        frames.append(valuescan_overview_to_metric_frame(overview_payload))
    if lists_payload:
        frames.append(valuescan_lists_to_metric_frame(lists_payload, symbol=symbol))

    metrics = _combine_metric_frames(frames)
    return ExternalMetricFeatureModule(
        metrics,
        ExternalMetricFeatureConfig(prefix=prefix),
    ).apply(bars)


def cache_valuescan_external_metrics(
    *,
    overview_payload: dict[str, Any] | None = None,
    lists_payload: dict[str, Any] | None = None,
    symbol: str = "BTC",
    series_id: ExternalMetricSeriesId,
    store: ParquetExternalMetricStore,
) -> dict[str, Any]:
    """Persist normalized Valuescan external metrics without feeding trading signals."""
    frames: list[pd.DataFrame] = []
    if overview_payload:
        frames.append(valuescan_overview_to_metric_frame(overview_payload))
    if lists_payload:
        frames.append(valuescan_lists_to_metric_frame(lists_payload, symbol=symbol))
    metrics = _combine_metric_frames(frames)
    path = store.write(series_id, metrics)
    return {
        "cacheKey": series_id.cache_key,
        "path": str(path),
        "rows": int(len(metrics)),
        "columns": list(metrics.columns),
    }


def valuescan_feature_preview_payload(
    bars: pd.DataFrame,
    *,
    overview_payload: dict[str, Any] | None = None,
    lists_payload: dict[str, Any] | None = None,
    symbol: str = "BTC",
    limit: int = 5,
) -> dict[str, Any]:
    """Build a REST-safe research preview of Valuescan external features aligned to bars."""
    features = build_valuescan_external_feature_frame(
        bars,
        overview_payload=overview_payload,
        lists_payload=lists_payload,
        symbol=symbol,
    )
    columns = [column for column in features.columns if column.startswith("valuescan_")]
    limited = features.tail(max(1, int(limit)))
    rows: list[dict[str, Any]] = []
    for index, row in limited.iterrows():
        item: dict[str, Any] = {
            "time": index.isoformat() if hasattr(index, "isoformat") else str(index),
        }
        for column in columns:
            item[column] = _optional_float(row.get(column))
        rows.append(item)

    return {
        "symbol": symbol,
        "rows": int(len(features)),
        "featureCount": len(columns),
        "columns": columns,
        "features": rows,
    }


def valuescan_overview_to_metric_frame(payload: dict[str, Any]) -> pd.DataFrame:
    """Convert a Valuescan overview response into one timestamped metric row."""
    timestamp_ms = _timestamp_ms(payload.get("updatedAt"))
    sentiment = payload.get("socialSentiment") or {}
    price_market = _first(payload.get("priceMarket") or {})
    support_rows = payload.get("supportResistance") or []
    support_prices = [_float(row.get("price")) for row in support_rows if _float(row.get("price")) is not None]

    row = {
        "bullish_ratio": _float(sentiment.get("bullishRatio"), 0.0),
        "neutral_ratio": _float(sentiment.get("neutralRatio"), 0.0),
        "bearish_ratio": _float(sentiment.get("bearishRatio"), 0.0),
        "price_market_type": _float(price_market.get("priceMarketType"), 0.0),
        "dense_area_count": float(len(support_rows)),
        "support_price_mean": sum(support_prices) / len(support_prices) if support_prices else 0.0,
        "market_analysis_count": float(len(payload.get("marketAnalysis") or [])),
    }
    return _frame(row, timestamp_ms)


def valuescan_lists_to_metric_frame(payload: dict[str, Any], *, symbol: str) -> pd.DataFrame:
    """Convert Valuescan AI list/message payloads into one symbol-specific metric row."""
    symbol_upper = symbol.upper()
    timestamp_ms = _timestamp_ms(payload.get("updatedAt"))
    opportunity = _first_matching(payload.get("opportunities") or [], symbol_upper)
    risk = _first_matching(payload.get("risks") or [], symbol_upper)
    funds = _first_matching(payload.get("funds") or [], symbol_upper)
    messages = payload.get("messages") or {}
    opportunity_message = _first_matching(messages.get("opportunities") or [], symbol_upper)
    risk_message = _first_matching(messages.get("risks") or [], symbol_upper)
    funds_message = _first_matching(messages.get("funds") or [], symbol_upper)

    row = {
        "opportunity_score": _float(opportunity.get("score"), 0.0),
        "opportunity_grade": _float(opportunity.get("grade"), 0.0),
        "risk_score": _float(risk.get("score"), 0.0),
        "risk_grade": _float(risk.get("grade"), 0.0),
        "funds_score": _float(funds.get("score"), 0.0),
        "funds_trade_type": _float(funds.get("tradeType"), 0.0),
        "opportunity_message_score": _float(opportunity_message.get("scoring"), 0.0),
        "risk_message_score": _float(risk_message.get("scoring"), 0.0),
        "funds_message_trade_type": _float(funds_message.get("tradeType"), 0.0),
    }
    return _frame(row, timestamp_ms)


def _frame(row: dict[str, float], timestamp_ms: int) -> pd.DataFrame:
    index = pd.to_datetime([timestamp_ms], unit="ms", utc=True)
    return pd.DataFrame(row, index=index)


def _combine_metric_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    frames = [frame for frame in frames if frame is not None and not frame.empty]
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, axis=1)
    combined = combined.loc[:, ~combined.columns.duplicated()]
    return combined.sort_index()


def _first(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        return value[0] if value else {}
    if isinstance(value, dict):
        return value
    return {}


def _first_matching(rows: list[dict[str, Any]], symbol: str) -> dict[str, Any]:
    for row in rows:
        if str(row.get("symbol", "")).upper() == symbol:
            return row
    return {}


def _float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    parsed = _float(value)
    return None if parsed is None else float(parsed)


def _timestamp_ms(value: Any) -> int:
    parsed = _float(value)
    if parsed is None or parsed <= 0:
        return 0
    return int(parsed)
