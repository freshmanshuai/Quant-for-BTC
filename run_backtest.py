import argparse
import os
from pathlib import Path

from quant_btc.config import BacktestConfig
from quant_btc.data import DataFetchError, fetch_ohlcv
from quant_btc.report import generate_report
from quant_btc.strategy import prepare_features, run_backtest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BTC backtest from exchange data")
    parser.add_argument("--exchange", type=str, default="binance", help="CCXT exchange id, e.g. binance/binanceus")
    parser.add_argument("--symbol", type=str, default="BTC/USDT")
    parser.add_argument("--timeframe", type=str, default="4h")
    parser.add_argument("--limit", type=int, default=50000, help="Max OHLCV bars to fetch (paginated)")
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--proxy-url", type=str, default=None, help="Proxy URL, e.g. http://127.0.0.1:7897")
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        help="Disable proxy entirely (overrides config default and --proxy-url)",
    )
    parser.add_argument(
        "--disable-binanceus-fallback",
        action="store_true",
        help="Disable automatic fallback from binance to binanceus",
    )
    return parser.parse_args()


def _next_run_dir(base: str = "backtest_results") -> Path:
    base_path = Path(base)
    base_path.mkdir(parents=True, exist_ok=True)
    existing = [int(p.name.split("_")[1]) for p in base_path.glob("run_*") if p.name.split("_")[1].isdigit()]
    next_id = max(existing) + 1 if existing else 1
    run_dir = base_path / f"run_{next_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def main():
    args = parse_args()
    cfg = BacktestConfig(symbol=args.symbol, timeframe=args.timeframe, limit=args.limit)

    # Proxy priority: --no-proxy > CLI --proxy-url > env HTTPS_PROXY/HTTP_PROXY > config default
    if args.no_proxy:
        proxy_url = None
    else:
        proxy_url = args.proxy_url or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or cfg.proxy_url

    if proxy_url:
        os.environ.setdefault("HTTP_PROXY", proxy_url)
        os.environ.setdefault("HTTPS_PROXY", proxy_url)
        os.environ.setdefault("ALL_PROXY", proxy_url)

    # Auto-detect run dir
    run_dir = _next_run_dir()

    print(f"=== Run {run_dir.name} ===")
    print(f"Fetching {cfg.symbol} {cfg.timeframe} history from {args.exchange} (limit={args.limit})...")
    print(f"Proxy: {proxy_url}")

    try:
        raw = fetch_ohlcv(
            symbol=cfg.symbol,
            timeframe=cfg.timeframe,
            limit=cfg.limit,
            exchange_id=args.exchange,
            timeout_ms=args.timeout_ms,
            max_retries=args.max_retries,
            fallback_to_binanceus=not args.disable_binanceus_fallback,
            proxy_url=proxy_url,
        )
    except DataFetchError as exc:
        print(f"\n[Data Error] {exc}")
        print("Hint: check proxy, --timeout-ms, --max-retries, or try --exchange binanceus")
        return

    print(f"Fetched {len(raw)} bars ({raw.index[0]} → {raw.index[-1]})")
    print(f"Preparing features...")

    df = prepare_features(raw, cfg)
    print(f"Features ready: {len(df)} bars (after dropna)")

    print(f"Running backtest...")
    stats, bt = run_backtest(df, cfg)

    # Generate comprehensive report
    report = generate_report(stats, bt, output_dir=str(run_dir))

    print(report)


if __name__ == "__main__":
    main()
