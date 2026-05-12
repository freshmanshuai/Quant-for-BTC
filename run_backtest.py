import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

from quant_btc.attribution import analyze as attr_analyze, format_report as attr_format
from quant_btc.config import BacktestConfig, RiskConfig
from quant_btc.data import DataFetchError, fetch_derivative_data, fetch_ohlcv
from quant_btc.strategy import compute_derivative_bonus
from quant_btc.report import generate_report
from quant_btc.strategy import (
    STRATEGY_MAP,
    StrategyName,
    prepare_features,
    run_backtest,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BTC backtest from exchange data")
    parser.add_argument(
        "--exchange", type=str, default="binance",
        help="CCXT exchange id, e.g. binance/binanceus",
    )
    parser.add_argument("--symbol", type=str, default="BTC/USDT")
    parser.add_argument("--timeframe", type=str, default="4h")
    parser.add_argument("--limit", type=int, default=50000)
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--proxy-url", type=str, default=None)
    parser.add_argument("--no-proxy", action="store_true")
    parser.add_argument(
        "--refresh-data", action="store_true",
        help="Bypass cache and re-fetch OHLCV from exchange",
    )

    parser.add_argument(
        "--strategy", type=str, default="htf",
        choices=["legacy", "htf", "atr_htf", "pullback", "breakout", "meanrev", "dual"],
        help="Which stop-loss scheme to use (default: htf)",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Run both HTF and ATR+HTF strategies and display a side-by-side comparison",
    )
    parser.add_argument("--leverage", type=int, default=5, help="Leverage multiplier (default: 5)")
    parser.add_argument(
        "--market-type", type=str, default="swap",
        choices=["spot", "swap"],
        help="Market type: spot (cash) or swap (perpetual futures).  Swap uses Binance/Bybit/OKX futures; spot uses Binance/BinanceUS.",
    )
    return parser.parse_args()


def _next_run_dir(base: str = "backtest_results") -> Path:
    base_path = Path(base)
    base_path.mkdir(parents=True, exist_ok=True)
    existing = [
        int(p.name.split("_")[1])
        for p in base_path.glob("run_*")
        if p.name.split("_")[1].isdigit()
    ]
    next_id = max(existing) + 1 if existing else 1
    run_dir = base_path / f"run_{next_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _run_single(
    args: argparse.Namespace,
    cfg: BacktestConfig,
    rcfg: RiskConfig,
    proxy_url: str | None,
    raw,
    strategy_name: StrategyName,
    run_dir: str,
):
    """Run one strategy variant and return (report_str, stats, bt)."""
    label = strategy_name.upper().replace("_", " + ")
    print(f"\n{'='*60}")
    print(f"  Running: {label}")
    print(f"{'='*60}")

    df = prepare_features(raw, cfg)

    # Attach derivative bonus for short signals (Step 7)
    if strategy_name in ("dual", "pullback", "breakout"):
        try:
            deriv = fetch_derivative_data(
                cfg.symbol, exchange_id=cfg.exchange_id,
                proxy_url=proxy_url,
            )
            df["_short_deriv_bonus"] = compute_derivative_bonus(df, deriv)
        except Exception:
            df["_short_deriv_bonus"] = 0.0
    else:
        df["_short_deriv_bonus"] = 0.0

    print(f"  Features ready: {len(df)} bars")

    stats, bt = run_backtest(df, cfg, strategy_name=strategy_name, risk_cfg=rcfg)
    return stats, bt


def _comparison_table(results: list[tuple[str, dict]]) -> str:
    """Build a side-by-side comparison table."""
    rows = []
    metrics = [
        ("Return [%]", "Total Return", "+.2f"),
        ("Buy & Hold Return [%]", "Buy & Hold", "+.2f"),
        ("Return (Ann.) [%]", "Annual Return", "+.2f"),
        ("Sharpe Ratio", "Sharpe", ".4f"),
        ("Sortino Ratio", "Sortino", ".4f"),
        ("Calmar Ratio", "Calmar", ".4f"),
        ("Max. Drawdown [%]", "Max DD", "+.2f"),
        ("Avg. Drawdown [%]", "Avg DD", "+.2f"),
        ("Volatility (Ann.) [%]", "Volatility", ".2f"),
        ("# Trades", "Trades", "d"),
        ("Win Rate [%]", "Win Rate", ".2f"),
        ("Best Trade [%]", "Best Trade", "+.2f"),
        ("Worst Trade [%]", "Worst Trade", "+.2f"),
        ("Profit Factor", "Profit Factor", ".2f"),
        ("SQN", "SQN", ".4f"),
        ("Equity Final [$]", "Final Equity", "$"),
        ("Max. Drawdown Duration", "Max DD Dur", ""),
    ]

    hdr_cols = [f"{'Metric':<22}"]
    for name, _ in results:
        hdr_cols.append(f"{name:>18}")
    rows.append("  " + " | ".join(hdr_cols))
    rows.append("  " + "-" * (22 + 19 * len(results)))

    for key, label, fmt in metrics:
        cols = [f"{label:<22}"]
        for _, stats in results:
            val = stats.get(key)
            try:
                if val is None or (isinstance(val, float) and np.isnan(val)):
                    s = "N/A"
                elif isinstance(val, pd.Timedelta):
                    s = str(val)
                elif fmt == "d":
                    s = str(int(val))
                elif fmt == "$":
                    s = f"${val:,.0f}"
                elif fmt == "":
                    s = str(val)
                else:
                    s = format(val, fmt)
                cols.append(f"{s:>18}")
            except Exception:
                cols.append(f"{str(val)[:18]:>18}")
        rows.append("  " + " | ".join(cols))

    return "\n".join(rows)


def main():
    args = parse_args()
    cfg = BacktestConfig(
        symbol=args.symbol, timeframe=args.timeframe, limit=args.limit,
    )
    rcfg = RiskConfig(leverage=args.leverage)

    # Proxy
    if args.no_proxy:
        proxy_url = None
    else:
        proxy_url = (
            args.proxy_url
            or os.getenv("HTTPS_PROXY")
            or os.getenv("HTTP_PROXY")
            or cfg.proxy_url
        )
    if proxy_url:
        os.environ.setdefault("HTTP_PROXY", proxy_url)
        os.environ.setdefault("HTTPS_PROXY", proxy_url)
        os.environ.setdefault("ALL_PROXY", proxy_url)

    print(f"Fetching {cfg.symbol} {cfg.timeframe} history from {args.exchange} ({args.market_type}) (limit={args.limit})...")
    print(f"Proxy: {proxy_url}")

    try:
        raw = fetch_ohlcv(
            symbol=cfg.symbol,
            timeframe=cfg.timeframe,
            limit=cfg.limit,
            market_type=args.market_type,
            exchange_id=args.exchange,
            timeout_ms=args.timeout_ms,
            max_retries=args.max_retries,
            proxy_url=proxy_url,
            refresh=args.refresh_data,
        )
    except DataFetchError as exc:
        print(f"\n[Data Error] {exc}")
        print("Hint: check proxy, --timeout-ms, --max-retries, or try --exchange binanceus")
        return

    print(f"Fetched {len(raw)} bars ({raw.index[0]} -> {raw.index[-1]})")

    if args.compare:
        # Run all three strategies
        run_dir = _next_run_dir()
        print(f"\n=== Comparison Mode — output dir: {run_dir} ===\n")
        print(f"  Risk Config: {args.leverage}x leverage, {rcfg.risk_per_trade*100:.0f}% risk/trade, "
              f"daily/weekly DD limit {rcfg.daily_dd_limit*100:.1f}%")
        print(f"  SL/TP:   Scheme A = Pure HTF (1D high/low)   |   Scheme B = ATR + HTF cap")
        print(f"  Trailing: BE@{rcfg.trailing_breakeven_r}R, Trail@{rcfg.trailing_activate_r}R "
              f"({rcfg.trailing_distance_atr}x ATR distance)")

        results = []
        for sname in ("legacy", "htf", "atr_htf"):
            stats, bt = _run_single(args, cfg, rcfg, proxy_url, raw, sname, str(run_dir))
            results.append((STRATEGY_MAP[sname].__name__, stats))
            report_str = generate_report(stats, bt, output_dir=str(run_dir / sname))
            print(report_str)

        print("\n" + "=" * 120)
        print("  STRATEGY COMPARISON")
        print("=" * 120)
        print(_comparison_table(results))
        print()

    else:
        run_dir = _next_run_dir()
        print(f"=== Run {run_dir.name} ({args.strategy}) ===\n")
        print(f"  Risk Config: {args.leverage}x leverage, {rcfg.risk_per_trade*100:.0f}% risk/trade")

        stats, bt = _run_single(args, cfg, rcfg, proxy_url, raw, args.strategy, str(run_dir))
        report_str = generate_report(stats, bt, output_dir=str(run_dir))
        print(report_str)

        # Attribution for dual-layer
        if args.strategy == "dual":
            attr = attr_analyze(stats, raw)
            print(attr_format(attr))


if __name__ == "__main__":
    main()
