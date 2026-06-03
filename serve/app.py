"""Flask visualization server."""

import sys
from pathlib import Path

# Ensure project root is on sys.path so `serve` and `quant_btc` are importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import math
import pandas as pd
from flask import Flask, jsonify, request, send_from_directory


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


def create_app():
    app = Flask(__name__, static_folder="static", static_url_path="")

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

    # ── Static files ──

    @app.route("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    return app


if __name__ == "__main__":
    create_app().run(debug=True, host="0.0.0.0", port=5000)
