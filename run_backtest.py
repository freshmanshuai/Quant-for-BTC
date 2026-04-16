from quant_btc.config import BacktestConfig
from quant_btc.data import fetch_ohlcv
from quant_btc.strategy import prepare_features, run_backtest


def main():
    cfg = BacktestConfig()

    print(f"Fetching {cfg.symbol} {cfg.timeframe} history from Binance...")
    raw = fetch_ohlcv(cfg.symbol, cfg.timeframe, cfg.limit)
    df = prepare_features(raw, cfg)

    stats, bt = run_backtest(df, cfg)
    print("\n===== Backtest Summary =====")
    print(stats)

    # Uncomment for chart output in local environment
    # bt.plot()


if __name__ == "__main__":
    main()
