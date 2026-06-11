"""Flask visualization server."""

import sys
from pathlib import Path

# Ensure project root is on sys.path so `serve` and `quant_btc` are importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import json
import math
import time
import pandas as pd
from flask import Flask, Response, jsonify, request, send_from_directory
from quant_platform.backtest import BacktestExecutionConfig
from quant_platform.data import ExternalMetricSeriesId
from quant_platform.stores import MissingStorageDependency, ParquetExternalMetricStore
from serve.valuescan_client import ValuescanAPIError, ValuescanClient, ValuescanConfigError
from serve.valuescan_metrics import cache_valuescan_external_metrics, valuescan_feature_preview_payload


_EXTERNAL_METRIC_STORE_DIR = _PROJECT_ROOT / "data" / "external_metrics"


def _safe_float(v, default=0.0):
    """Convert to float, replacing NaN/None with default."""
    try:
        f = float(v)
        return default if math.isnan(f) else f
    except (ValueError, TypeError):
        return default

from serve.data_loader import (
    get_equity_curve,
    get_monthly_returns,
    get_ohlcv,
    get_summary_stats,
    get_trade_log,
)
from serve.signal_preview import (
    get_btc_event_backtest_preview,
    get_btc_latest_signal_snapshot,
    get_btc_migration_comparison_preview,
    get_btc_pipeline_preview,
    get_btc_signal_preview,
    get_signal_market_options,
    get_signal_research_event_backtest_preview,
    get_signal_research_preview,
)


def create_app():
    app = Flask(__name__, static_folder="static", static_url_path="")

    def _bool_arg(name: str, default: bool = False) -> bool:
        value = request.args.get(name)
        if value is None:
            return default
        return value.lower() in {"1", "true", "yes", "on"}

    def _csv_or_value_arg(name: str, default: str):
        values = request.args.getlist(name)
        if not values:
            return default
        parts = [
            item.strip()
            for value in values
            for item in str(value).split(",")
            if item.strip()
        ]
        return parts if len(parts) > 1 else (parts[0] if parts else default)

    def _event_execution_config_arg() -> BacktestExecutionConfig | None:
        config: dict[str, object] = {}
        for name in (
            "fee_rate",
            "slippage_bps",
            "max_entry_fill_fraction_per_bar",
            "max_entry_volume_fraction_per_bar",
            "max_exit_fill_fraction_per_bar",
            "max_exit_volume_fraction_per_bar",
        ):
            if name in request.args:
                config[name] = float(request.args[name])
        for name in ("intrabar_stop_target", "intrabar_entry_limit"):
            if name in request.args:
                config[name] = _bool_arg(name)
        for name in ("max_entry_order_age_bars", "max_exit_order_age_bars"):
            if name in request.args:
                config[name] = int(request.args[name])
        for name in ("entry_spread_feature", "exit_spread_feature"):
            if name in request.args:
                value = request.args[name].strip()
                if value:
                    config[name] = value
        return BacktestExecutionConfig(**config) if config else None

    def _valuescan_error(exc: Exception, status: int):
        if isinstance(exc, ValuescanConfigError):
            return jsonify({"error": "valuescan_not_configured", "message": str(exc)}), 503
        return jsonify({"error": "valuescan_request_failed", "message": str(exc)}), status

    def _safe_valuescan_call(errors: dict[str, str], key: str, fn, fallback):
        try:
            return fn()
        except (ValuescanAPIError, OSError, ValueError) as exc:
            errors[key] = str(exc)
            return fallback

    # ── OHLCV API ──

    @app.route("/api/ohlcv/data")
    def ohlcv_data():
        tf = request.args.get("timeframe", "4h")
        df = get_ohlcv(tf)
        if df.empty:
            return jsonify({"error": "no data", "timeframe": tf})

        from_str = request.args.get("from")
        to_str = request.args.get("to")
        # Normalize timezone: cached data has tz-aware UTC index
        if hasattr(df.index, 'tz') and df.index.tz is not None:
            if from_str:
                df = df[df.index >= pd.Timestamp(from_str, tz='UTC')]
            if to_str:
                df = df[df.index <= pd.Timestamp(to_str, tz='UTC')]
        else:
            if from_str:
                df = df[df.index >= pd.Timestamp(from_str)]
            if to_str:
                df = df[df.index <= pd.Timestamp(to_str)]

        bars = []
        for idx, row in df.iterrows():
            bars.append({
                "t": idx.isoformat(),
                "o": _safe_float(row["Open"]),
                "h": _safe_float(row["High"]),
                "l": _safe_float(row["Low"]),
                "c": _safe_float(row["Close"]),
                "v": _safe_float(row["Volume"]),
            })
        return jsonify({
            "timeframe": tf,
            "bars": len(bars),
            "from": str(df.index[0]) if len(df) > 0 else None,
            "to": str(df.index[-1]) if len(df) > 0 else None,
            "data": bars,
        })

    @app.route("/api/ohlcv/timeframes")
    def ohlcv_timeframes():
        return jsonify({"timeframes": ["15m", "1h", "4h"]})

    # ── Returns API ──

    @app.route("/api/returns/equity")
    def returns_equity():
        eq = get_equity_curve()
        if eq.empty:
            return jsonify({"error": "no data"})
        return jsonify({
            "initial_equity": 100000,
            "final_equity": round(float(eq["equity"].iloc[-1]), 2),
            "total_return_pct": round((float(eq["equity"].iloc[-1]) / 100000 - 1) * 100, 2),
            "data": [
                {"date": str(r["date"]), "equity": r["equity"], "drawdown_pct": r["drawdown_pct"]}
                for _, r in eq.iterrows()
            ],
        })

    @app.route("/api/returns/heatmap")
    def returns_heatmap():
        data = get_monthly_returns()
        years = sorted(set(d["year"] for d in data))
        return jsonify({
            "years": years,
            "months": list(range(1, 13)),
            "data": data,
        })

    @app.route("/api/returns/summary")
    def returns_summary():
        return jsonify(get_summary_stats())

    @app.route("/api/returns/distribution")
    def returns_distribution():
        trades = get_trade_log()
        if trades.empty:
            return jsonify({"data": []})
        result = []
        for _, t in trades.iterrows():
            result.append({
                "id": int(t["trade_id"]),
                "pnl_pct": _safe_float(t["pnl_pct"]),
                "is_win": _safe_float(t["pnl"]) > 0,
                "module": str(t["module"]),
                "direction": str(t["direction"]),
            })
        return jsonify({"data": result})

    # ── Orders API ──

    @app.route("/api/orders/list")
    def orders_list():
        trades = get_trade_log()
        if trades.empty:
            return jsonify({"total": 0, "orders": []})

        # Filters
        direction = request.args.get("direction", "all")
        module = request.args.get("module", "all")
        if direction != "all":
            trades = trades[trades["direction"] == direction]
        if module != "all":
            trades = trades[trades["module"] == module]

        # Sort
        sort_by = request.args.get("sort_by", "trade_id")
        sort_dir = request.args.get("sort_dir", "asc")
        ascending = sort_dir == "asc"
        if sort_by in trades.columns:
            trades = trades.sort_values(sort_by, ascending=ascending)

        total = len(trades)

        # Pagination
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 50))
        start = (page - 1) * per_page
        end = start + per_page
        page_data = trades.iloc[start:end]

        orders = []
        for _, t in page_data.iterrows():
            orders.append({
                "trade_id": int(t["trade_id"]),
                "entry_time": str(t["entry_time"]),
                "exit_time": str(t["exit_time"]),
                "duration": str(t["duration"]),
                "direction": str(t["direction"]),
                "module": str(t["module"]),
                "entry_price": _safe_float(t["entry_price"]),
                "exit_price": _safe_float(t["exit_price"]),
                "sl_price": _safe_float(t.get("sl_price")),
                "tp_price": _safe_float(t.get("tp_price")),
                "position_size": _safe_float(t["position_size"]),
                "pnl": _safe_float(t["pnl"]),
                "pnl_pct": _safe_float(t["pnl_pct"]),
                "return_r": _safe_float(t.get("return_r")),
                "max_mfe_pct": _safe_float(t.get("max_mfe_pct")),
                "max_mae_pct": _safe_float(t.get("max_mae_pct")),
                "entry_regime": str(t.get("entry_regime", "")),
                "exit_reason": str(t.get("exit_reason", "")),
            })

        return jsonify({
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": max(1, (total + per_page - 1) // per_page),
            "orders": orders,
        })

    @app.route("/api/orders/filters")
    def orders_filters():
        trades = get_trade_log()
        if trades.empty:
            return jsonify({})
        return jsonify({
            "modules": sorted(trades["module"].dropna().unique().tolist()),
            "directions": ["LONG", "SHORT"],
            "exit_reasons": sorted(trades["exit_reason"].dropna().unique().tolist()),
        })

    # Standardized Signal API

    @app.route("/api/signals/preview")
    def signals_preview():
        timeframe = request.args.get("timeframe", "4h")
        symbol = request.args.get("symbol", "BTC/USDT")
        limit = max(1, min(int(request.args.get("limit", 50)), 500))
        try:
            return jsonify(get_btc_signal_preview(timeframe=timeframe, symbol=symbol, limit=limit))
        except ModuleNotFoundError as exc:
            return jsonify({
                "error": "signal_preview_unavailable",
                "message": f"Missing runtime dependency: {exc.name}",
            }), 503

    @app.route("/api/signals/pipeline-preview")
    def signals_pipeline_preview():
        timeframe = request.args.get("timeframe", "4h")
        symbol = request.args.get("symbol", "BTC/USDT")
        equity = max(1.0, float(request.args.get("equity", 10_000)))
        try:
            return jsonify(get_btc_pipeline_preview(timeframe=timeframe, symbol=symbol, equity=equity))
        except ModuleNotFoundError as exc:
            return jsonify({
                "error": "signal_pipeline_preview_unavailable",
                "message": f"Missing runtime dependency: {exc.name}",
            }), 503

    @app.route("/api/signals/latest")
    def signals_latest():
        timeframe = request.args.get("timeframe", "4h")
        symbol = request.args.get("symbol", "BTC/USDT")
        equity = max(1.0, float(request.args.get("equity", 10_000)))
        try:
            return jsonify(get_btc_latest_signal_snapshot(timeframe=timeframe, symbol=symbol, equity=equity))
        except ModuleNotFoundError as exc:
            return jsonify({
                "error": "signal_latest_unavailable",
                "message": f"Missing runtime dependency: {exc.name}",
            }), 503

    @app.route("/api/signals/markets")
    def signals_markets():
        return jsonify(get_signal_market_options())

    # ── Static files ──

    @app.route("/api/signals/research-preview")
    def signals_research_preview():
        timeframe = request.args.get("timeframe", "4h")
        symbol = request.args.get("symbol", "BTC/USDT")
        exchange = request.args.get("exchange", "binance")
        market_type = request.args.get("market_type", "swap")
        equity = max(1.0, float(request.args.get("equity", 10_000)))
        refresh_bars = _bool_arg("refresh_bars")
        refresh_features = _bool_arg("refresh_features")
        try:
            return jsonify(get_signal_research_preview(
                timeframe=timeframe,
                symbol=symbol,
                exchange=exchange,
                market_type=market_type,
                equity=equity,
                refresh_bars=refresh_bars,
                refresh_features=refresh_features,
            ))
        except ModuleNotFoundError as exc:
            return jsonify({
                "error": "signal_research_preview_unavailable",
                "message": f"Missing runtime dependency: {exc.name}",
            }), 503

    @app.route("/api/signals/event-backtest-preview")
    def signals_event_backtest_preview():
        timeframe = request.args.get("timeframe", "4h")
        symbol = request.args.get("symbol", "BTC/USDT")
        equity = max(1.0, float(request.args.get("equity", 10_000)))
        execution = _event_execution_config_arg()
        try:
            kwargs = {"timeframe": timeframe, "symbol": symbol, "equity": equity}
            if execution is not None:
                kwargs["execution"] = execution
            return jsonify(get_btc_event_backtest_preview(**kwargs))
        except ModuleNotFoundError as exc:
            return jsonify({
                "error": "signal_event_backtest_preview_unavailable",
                "message": f"Missing runtime dependency: {exc.name}",
            }), 503

    @app.route("/api/signals/research-event-backtest-preview")
    def signals_research_event_backtest_preview():
        timeframe = request.args.get("timeframe", "4h")
        symbol = _csv_or_value_arg("symbol", "BTC/USDT")
        exchange = _csv_or_value_arg("exchange", "binance")
        market_type = _csv_or_value_arg("market_type", "swap")
        equity = max(1.0, float(request.args.get("equity", 10_000)))
        refresh_bars = _bool_arg("refresh_bars")
        refresh_features = _bool_arg("refresh_features")
        execution = _event_execution_config_arg()
        try:
            kwargs = {
                "timeframe": timeframe,
                "symbol": symbol,
                "exchange": exchange,
                "market_type": market_type,
                "equity": equity,
                "refresh_bars": refresh_bars,
                "refresh_features": refresh_features,
            }
            if execution is not None:
                kwargs["execution"] = execution
            return jsonify(get_signal_research_event_backtest_preview(**kwargs))
        except ModuleNotFoundError as exc:
            return jsonify({
                "error": "signal_research_event_backtest_preview_unavailable",
                "message": f"Missing runtime dependency: {exc.name}",
            }), 503

    @app.route("/api/signals/migration-comparison-preview")
    def signals_migration_comparison_preview():
        timeframe = request.args.get("timeframe", "4h")
        symbol = request.args.get("symbol", "BTC/USDT")
        equity = max(1.0, float(request.args.get("equity", 10_000)))
        try:
            return jsonify(get_btc_migration_comparison_preview(timeframe=timeframe, symbol=symbol, equity=equity))
        except ModuleNotFoundError as exc:
            return jsonify({
                "error": "signal_migration_comparison_preview_unavailable",
                "message": f"Missing runtime dependency: {exc.name}",
            }), 503

    # Valuescan AI Tracking API

    @app.route("/api/valuescan/ai/overview")
    def valuescan_ai_overview():
        token_symbol = request.args.get("token", "BTC").upper()
        now_ms = int(time.time() * 1000)
        lookback_days = max(1, min(int(request.args.get("days", 7)), 30))
        start_ms = now_ms - lookback_days * 24 * 60 * 60 * 1000
        client = ValuescanClient()
        try:
            token = client.resolve_token(token_symbol)
            token_id = token.get("id") or token.get("vsTokenId")
            errors: dict[str, str] = {}
            return jsonify({
                "token": {
                    "vsTokenId": token_id,
                    "symbol": token.get("symbol", token_symbol),
                    "name": token.get("name", ""),
                },
                "supportResistance": _safe_valuescan_call(errors, "supportResistance", lambda: client.support_resistance(token_id, now_ms).get("data") or [], []),
                "priceMarket": _safe_valuescan_call(errors, "priceMarket", lambda: client.price_market(token_id, start_ms, now_ms).get("data") or [], []),
                "socialSentiment": _safe_valuescan_call(errors, "socialSentiment", lambda: client.social_sentiment(token_id).get("data") or {}, {}),
                "marketAnalysis": _safe_valuescan_call(errors, "marketAnalysis", lambda: client.market_analysis_history(page=1, page_size=8).get("data") or [], []),
                "errors": errors,
                "updatedAt": now_ms,
            })
        except ValuescanConfigError as exc:
            return _valuescan_error(exc, 503)
        except (ValuescanAPIError, OSError, ValueError) as exc:
            return _valuescan_error(exc, 502)

    @app.route("/api/valuescan/ai/lists")
    def valuescan_ai_lists():
        client = ValuescanClient()
        try:
            errors: dict[str, str] = {}
            opportunities = _safe_valuescan_call(errors, "opportunities", lambda: client.chance_coin_list().get("data") or [], [])
            risks = _safe_valuescan_call(errors, "risks", lambda: client.risk_coin_list().get("data") or [], [])
            funds = _safe_valuescan_call(errors, "funds", lambda: client.funds_coin_list().get("data") or [], [])
            first_opportunity = opportunities[0] if opportunities else {}
            first_risk = risks[0] if risks else {}
            first_funds = funds[0] if funds else {}
            return jsonify({
                "opportunities": opportunities,
                "risks": risks,
                "funds": funds,
                "messages": {
                    "opportunities": _safe_valuescan_call(errors, "opportunityMessages", lambda: client.chance_coin_messages(first_opportunity.get("vsTokenId")).get("data") or [], [])
                    if first_opportunity.get("vsTokenId") else [],
                    "risks": _safe_valuescan_call(errors, "riskMessages", lambda: client.risk_coin_messages(first_risk.get("vsTokenId")).get("data") or [], [])
                    if first_risk.get("vsTokenId") else [],
                    "funds": _safe_valuescan_call(errors, "fundMessages", lambda: client.funds_coin_messages(first_funds.get("vsTokenId"), first_funds.get("tradeType", 1)).get("data") or [], [])
                    if first_funds.get("vsTokenId") else [],
                },
                "errors": errors,
                "updatedAt": int(time.time() * 1000),
            })
        except ValuescanConfigError as exc:
            return _valuescan_error(exc, 503)
        except (ValuescanAPIError, OSError, ValueError) as exc:
            return _valuescan_error(exc, 502)

    @app.route("/api/valuescan/ai/features")
    def valuescan_ai_features():
        token_symbol = request.args.get("token", "BTC").upper()
        timeframe = request.args.get("timeframe", "4h")
        limit = max(1, min(int(request.args.get("limit", 5)), 50))
        now_ms = int(time.time() * 1000)
        lookback_days = max(1, min(int(request.args.get("days", 7)), 30))
        start_ms = now_ms - lookback_days * 24 * 60 * 60 * 1000
        client = ValuescanClient()
        try:
            bars = get_ohlcv(timeframe)
            token = client.resolve_token(token_symbol)
            token_id = token.get("id") or token.get("vsTokenId")
            errors: dict[str, str] = {}
            overview_payload = {
                "token": {
                    "vsTokenId": token_id,
                    "symbol": token.get("symbol", token_symbol),
                    "name": token.get("name", ""),
                },
                "supportResistance": _safe_valuescan_call(errors, "supportResistance", lambda: client.support_resistance(token_id, now_ms).get("data") or [], []),
                "priceMarket": _safe_valuescan_call(errors, "priceMarket", lambda: client.price_market(token_id, start_ms, now_ms).get("data") or [], []),
                "socialSentiment": _safe_valuescan_call(errors, "socialSentiment", lambda: client.social_sentiment(token_id).get("data") or {}, {}),
                "marketAnalysis": _safe_valuescan_call(errors, "marketAnalysis", lambda: client.market_analysis_history(page=1, page_size=8).get("data") or [], []),
                "updatedAt": now_ms,
            }
            opportunities = _safe_valuescan_call(errors, "opportunities", lambda: client.chance_coin_list().get("data") or [], [])
            risks = _safe_valuescan_call(errors, "risks", lambda: client.risk_coin_list().get("data") or [], [])
            funds = _safe_valuescan_call(errors, "funds", lambda: client.funds_coin_list().get("data") or [], [])
            matching_opportunity = next((row for row in opportunities if str(row.get("symbol", "")).upper() == token_symbol), {})
            matching_risk = next((row for row in risks if str(row.get("symbol", "")).upper() == token_symbol), {})
            matching_funds = next((row for row in funds if str(row.get("symbol", "")).upper() == token_symbol), {})
            lists_payload = {
                "opportunities": opportunities,
                "risks": risks,
                "funds": funds,
                "messages": {
                    "opportunities": _safe_valuescan_call(errors, "opportunityMessages", lambda: client.chance_coin_messages(matching_opportunity.get("vsTokenId")).get("data") or [], [])
                    if matching_opportunity.get("vsTokenId") else [],
                    "risks": _safe_valuescan_call(errors, "riskMessages", lambda: client.risk_coin_messages(matching_risk.get("vsTokenId")).get("data") or [], [])
                    if matching_risk.get("vsTokenId") else [],
                    "funds": _safe_valuescan_call(errors, "fundMessages", lambda: client.funds_coin_messages(matching_funds.get("vsTokenId"), matching_funds.get("tradeType", 1)).get("data") or [], [])
                    if matching_funds.get("vsTokenId") else [],
                },
                "updatedAt": now_ms,
            }
            payload = valuescan_feature_preview_payload(
                bars,
                overview_payload=overview_payload,
                lists_payload=lists_payload,
                symbol=token_symbol,
                limit=limit,
            )
            series_id = ExternalMetricSeriesId(
                symbol=token_symbol,
                provider="valuescan",
                dataset="ai_tracking",
                timeframe=timeframe,
                source="api",
            )
            try:
                payload["cache"] = cache_valuescan_external_metrics(
                    overview_payload=overview_payload,
                    lists_payload=lists_payload,
                    symbol=token_symbol,
                    series_id=series_id,
                    store=ParquetExternalMetricStore(_EXTERNAL_METRIC_STORE_DIR),
                )
            except (MissingStorageDependency, OSError, ValueError) as exc:
                errors["externalMetricCache"] = str(exc)
            payload["timeframe"] = timeframe
            payload["errors"] = errors
            return jsonify(payload)
        except ValuescanConfigError as exc:
            return _valuescan_error(exc, 503)
        except (ValuescanAPIError, OSError, ValueError) as exc:
            return _valuescan_error(exc, 502)

    @app.route("/api/valuescan/ai/stream")
    def valuescan_ai_stream():
        channel = request.args.get("type", "market")
        if channel not in {"market", "signal"}:
            return jsonify({"error": "invalid_stream_type"}), 400
        tokens = request.args.get("tokens", "")
        client = ValuescanClient()

        def generate():
            try:
                yield from client.stream_events(channel, tokens=tokens)
            except ValuescanConfigError as exc:
                data = json.dumps({"error": "valuescan_not_configured", "message": str(exc)}, ensure_ascii=False)
                yield f"event: error\ndata: {data}\n\n"
            except Exception as exc:
                data = json.dumps({"error": "valuescan_stream_failed", "message": str(exc)}, ensure_ascii=False)
                yield f"event: error\ndata: {data}\n\n"

        return Response(generate(), mimetype="text/event-stream")

    # Static files

    @app.route("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    return app


if __name__ == "__main__":
    create_app().run(debug=False, host="127.0.0.1", port=5000)
