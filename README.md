# Quant-for-BTC

A BTC quantitative strategy repo focused on **backtesting first** and going live only after stable performance.

## What's included

- `pine/btc_weighted_signal_v1.pine`: TradingView signal script (EMA 75% + MACD 25%).
- `quant_btc/`: Python backtesting implementation of the weighted signal strategy.
- `run_backtest.py`: one-command backtest runner.

## Strategy logic (current phase)

- Trade timeframe: 1H or 4H (default 4H).
- Multi-timeframe bias: daily + weekly trend filter.
- Signal score:
  - EMA structure + first-touch zone logic = 75 points
  - MACD crossover = 25 points
- Trigger when score >= threshold (default 75).
- Long and short both enabled.
- No TP/SL yet (as requested); exits happen on opposite signal.

## Quick start (backtest only)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run_backtest.py
```

## Notes

- This repo uses **historical market data** from Binance public endpoints for backtesting.
- No private key is required unless you later add order execution.
- Before live deployment, add execution-layer controls: slippage model, funding cost, TP/SL, max drawdown guard, and paper-trading phase.
