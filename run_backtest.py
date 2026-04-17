import argparse

from quant_btc.config import BacktestConfig
from quant_btc.data import DataFetchError, fetch_ohlcv
from quant_btc.strategy import prepare_features, run_backtest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run BTC backtest from exchange data")
    parser.add_argument("--exchange", type=str, default="binance", help="CCXT exchange id, e.g. binance/binanceus")
    parser.add_argument("--symbol", type=str, default="BTC/USDT")
    parser.add_argument("--timeframe", type=str, default="4h")
    parser.add_argument("--limit", type=int, default=3000)
    parser.add_argument("--timeout-ms", type=int, default=20000)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument(
        "--disable-binanceus-fallback",
        action="store_true",
        help="Disable automatic fallback from binance to binanceus",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    cfg = BacktestConfig(symbol=args.symbol, timeframe=args.timeframe, limit=args.limit)

    try:
        print(f"Fetching {cfg.symbol} {cfg.timeframe} history from {args.exchange}...")
        raw = fetch_ohlcv(
            symbol=cfg.symbol,
            timeframe=cfg.timeframe,
            limit=cfg.limit,
            exchange_id=args.exchange,
            timeout_ms=args.timeout_ms,
            max_retries=args.max_retries,
            fallback_to_binanceus=not args.disable_binanceus_fallback,
        )
    except DataFetchError as exc:
        print("\n[Data Error]", exc)
        print("Hint: try --exchange binanceus or increase --timeout-ms / --max-retries")
        return

    df = prepare_features(raw, cfg)
    stats, bt = run_backtest(df, cfg)

    print("\n===== Backtest Summary =====")
    print(stats)

    # Uncomment for chart output in local environment
    # bt.plot()


if __name__ == "__main__":
    main()
