"""Build data connector registries from project configuration files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quant_platform.connectors import DataConnectorRegistry
from quant_platform.connectors_alpha_vantage import AlphaVantageConnector
from quant_platform.connectors_ccxt import CcxtExchangeConnector
from quant_platform.connectors_csv import LocalCsvConnector
from quant_platform.connectors_polygon import PolygonConnector
from quant_platform.connectors_sqlite import SQLiteBarConnector
from quant_platform.connectors_yahoo import YahooFinanceConnector


class ConnectorConfigError(ValueError):
    """Raised when a connector config record cannot be loaded."""


def load_data_connector_registry_json(
    path: str | Path,
    *,
    base_dir: str | Path | None = None,
) -> DataConnectorRegistry:
    """Load configured local data connectors into a registry."""
    config_path = Path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    root = Path(base_dir) if base_dir is not None else config_path.parent
    registry = DataConnectorRegistry()

    for record in payload.get("connectors", []):
        connector_type = str(record.get("type", "")).lower()
        name = str(record.get("name") or connector_type)
        if connector_type == "csv":
            registry.register(_build_csv_connector(record, root), name=name)
        elif connector_type == "sqlite":
            registry.register(_build_sqlite_connector(record, root), name=name)
        elif connector_type == "ccxt":
            registry.register(_build_ccxt_connector(record), name=name)
        elif connector_type == "yahoo":
            registry.register(_build_yahoo_connector(record), name=name)
        elif connector_type == "alpha_vantage":
            registry.register(_build_alpha_vantage_connector(record), name=name)
        elif connector_type == "polygon":
            registry.register(_build_polygon_connector(record), name=name)
        else:
            raise ConnectorConfigError(f"Unsupported data connector type: {connector_type!r}")

    return registry


def _build_csv_connector(record: dict[str, Any], root: Path) -> LocalCsvConnector:
    files = record.get("files_by_symbol") or {}
    return LocalCsvConnector(
        files_by_symbol={symbol: _resolve_path(path, root) for symbol, path in files.items()},
        timestamp_column=str(record.get("timestamp_column", "timestamp")),
        column_map=dict(record.get("column_map") or {}),
    )


def _build_sqlite_connector(record: dict[str, Any], root: Path) -> SQLiteBarConnector:
    database_path = record.get("database_path")
    if not database_path:
        raise ConnectorConfigError("SQLite connector requires database_path.")
    return SQLiteBarConnector(
        database_path=_resolve_path(database_path, root),
        tables_by_symbol=dict(record.get("tables_by_symbol") or {}),
        timestamp_column=str(record.get("timestamp_column", "timestamp")),
        timeframe_column=str(record.get("timeframe_column", "timeframe")),
        column_map=dict(record.get("column_map") or {}),
    )


def _build_ccxt_connector(record: dict[str, Any]) -> CcxtExchangeConnector:
    return CcxtExchangeConnector(
        timeout_ms=int(record.get("timeout_ms", 30_000)),
        proxy_url=record.get("proxy_url"),
        batch_size=int(record.get("batch_size", 1000)),
        max_pages=int(record.get("max_pages", 100)),
        max_retries=int(record.get("max_retries", 5)),
    )


def _build_yahoo_connector(record: dict[str, Any]) -> YahooFinanceConnector:
    return YahooFinanceConnector(
        symbols_by_symbol=dict(record.get("symbols_by_symbol") or {}),
        base_url=str(record.get("base_url", "https://query1.finance.yahoo.com")),
    )


def _build_alpha_vantage_connector(record: dict[str, Any]) -> AlphaVantageConnector:
    if record.get("api_key"):
        raise ConnectorConfigError("Alpha Vantage connector config must use api_key_env, not inline api_key.")
    return AlphaVantageConnector(
        api_key_env=str(record.get("api_key_env", "ALPHA_VANTAGE_API_KEY")),
        symbols_by_symbol=dict(record.get("symbols_by_symbol") or {}),
        base_url=str(record.get("base_url", "https://www.alphavantage.co/query")),
        outputsize=str(record.get("outputsize", "compact")),
    )


def _build_polygon_connector(record: dict[str, Any]) -> PolygonConnector:
    if record.get("api_key"):
        raise ConnectorConfigError("Polygon connector config must use api_key_env, not inline api_key.")
    return PolygonConnector(
        api_key_env=str(record.get("api_key_env", "POLYGON_API_KEY")),
        symbols_by_symbol=dict(record.get("symbols_by_symbol") or {}),
        base_url=str(record.get("base_url", "https://api.polygon.io")),
        adjusted=bool(record.get("adjusted", True)),
    )


def _resolve_path(path: str | Path, root: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return root / candidate
