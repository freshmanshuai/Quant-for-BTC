# Quant-for-BTC — Bitcoin Multi-Layer Quantitative Trading System

A complete quantitative trading system for BTC/USDT perpetual futures, evolved through nine iterative steps from a bare EMA-crossing strategy into a production-grade system with market regime classification, multi-module signal generation, four-dimensional quality scoring, module-specific exits, dual-layer portfolio structure, and risk-based position sizing.

## Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                   BITCOIN QUANT TRADING SYSTEM                        │
│                                                                       │
│  ┌─ Market State Layer ───────────────────────────────────────────┐ │
│  │  Bull / Bear / Ranging / Compression / HighRisk                 │ │
│  │  (Daily EMA169 + Weekly EMA169 + ADX + BB + ATR percentile)    │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                              │                                      │
│  ┌─ Scoring Layer ────────────────────────────────────────────────┐ │
│  │  Market State (30) + Pattern (30) + Momentum (20) + Risk (20)   │ │
│  │  Breakout >=55  |  Pullback >=75  |  Mean Reversion >=75       │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                              │                                      │
│  ┌─ Dual-Layer Portfolio ─────────────────────────────────────────┐ │
│  │  CORE (40% equity)          TACTICAL (per-module risk)          │ │
│  │  Long-only, BTC beta        Breakout 0.65% / Pullback 0.50%    │ │
│  │  Entry: Strong Bull          / Mean Reversion 0.25% risk        │ │
│  │  Exit:  Weekly failure      Priority: BO > PB > MR              │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                              │                                      │
│  ┌─ Risk Management ──────────────────────────────────────────────┐ │
│  │  Circuit Breaker (7.5% daily/weekly) | Consecutive Loss Control │ │
│  │  ATR-adaptive sizing | Bear short discount (x60%)               │ │
│  │  HTF conflict half-size | Initial SL -> Partial TP -> Trail     │ │
│  └──────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

## Backtest Results (2019-09-29 -> 2026-05-09, BTC/USDT 4H)

| Strategy | Trades | Return | Max DD | Win Rate | PF | Sharpe |
|----------|:------:|:------:|:------:|:--------:|:---:|:------:|
| 0. Legacy (no risk mgmt) | 7 | +3.3% | -80.8% | 28.6% | 1.76 | +0.01 |
| 1. Zone + Regime | 297 | +68.2% | -17.8% | 36.0% | 1.20 | +0.46 |
| 2. Pullback | 164 | -1.4% | -9.2% | 40.2% | 1.52 | -0.08 |
| 3. Breakout | 347 | +12.6% | -6.6% | 46.7% | 1.40 | +0.36 |
| 4. Mean Reversion | 36 | +0.2% | -0.5% | 38.9% | 1.17 | +0.12 |
| **5. Dual-Layer** | **513** | **+210.2%** | **-17.9%** | **46.4%** | **1.36** | **+1.09** |

| Metric | Value |
|--------|-------|
| Initial Capital | $100,000 |
| Final Equity | $310,200 |
| Annual Return | +18.66% CAGR |
| Buy & Hold | +891% |
| Alpha | +164% |
| Beta | 0.05 |
| Max Drawdown Duration | 1082 days |
| Avg Trade Duration | 3.1 days |

Strategies 0-4 represent single-module ablation tests. **Strategy 5 (Dual-Layer)** is the complete system: Core Long (40% equity, spot-like) + Tactical (Breakout / Pullback / Mean Reversion, priority-selected per regime).

## Project Structure

```
Quant-for-BTC/
├── quant_btc/
│   ├── config.py              # All configuration: risk, regime, scoring, exits
│   ├── data.py                # OHLCV data fetching (Binance/BinanceUS via CCXT)
│   ├── strategy.py            # All strategy classes and feature engineering
│   └── report.py              # Backtest reporting with charts (matplotlib)
├── run_backtest.py            # CLI entry point
├── btc_strategy_signals.pine  # TradingView Pine Script signal generator
├── requirements.txt
├── backtest_results/          # Auto-generated: charts and reports per run
└── README.md
```

## Installation

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
```

**Requirements:** `ccxt>=4.4.0`, `pandas>=2.0.0`, `numpy>=1.24.0`, `backtesting>=0.3.3`, `matplotlib>=3.0`

## Quick Start

```bash
# Run the dual-layer system (complete strategy):
python run_backtest.py --exchange binanceus --strategy dual

# Compare all strategies (ablation study):
python run_backtest.py --exchange binanceus --compare

# Run a specific module standalone:
python run_backtest.py --exchange binanceus --strategy breakout
python run_backtest.py --exchange binanceus --strategy pullback
python run_backtest.py --exchange binanceus --strategy meanrev

# With custom proxy:
python run_backtest.py --exchange binance --proxy-url http://127.0.0.1:7890
```

Each run auto-creates a directory `backtest_results/run_N/` containing:
- `equity_drawdown.png` — Equity curve + underwater plot
- `monthly_returns.png` — Monthly returns heatmap
- `rolling_sharpe.png` — 30-day rolling Sharpe ratio
- `trade_distribution.png` — Per-trade return distribution

## Decision Framework

The system follows a three-layer decision hierarchy:

### Layer 1: Market Regime Classification

Every 4H bar is classified into one of five states, evaluated in priority order:

| Priority | Regime | Condition | Allowed Actions |
|:--------:|--------|-----------|-----------------|
| 1 | **High Risk** (4) | ATR% > 90th %ile, or opposing large candles within 5 bars | No new positions; manage existing only |
| 2 | **Strong Bull** (1) | Close > Daily EMA169, Daily EMA169 slope positive | Core long + BO long + PB long; **no shorts** |
| 3 | **Strong Bear** (2) | Close < Daily EMA169, Daily EMA169 slope negative | BO short + PB short + MR short; **no longs** |
| 4 | **Compression** (3) | BB width < 25th %ile, ATR% < 30th %ile, ADX < 20 | Breakout long only |
| 5 | **Ranging** (0) | Everything else | Mean reversion only; **no breakout chasing** |

**Transition markets** (Weak Bull / Weak Bear): When HTF EMAs show mild directional bias without meeting strict regime criteria, position sizes are halved.

### Layer 2: Module Selection

Within each regime, modules are evaluated in priority order: **Breakout > Pullback > Mean Reversion**.

#### Breakout Module — Donchian 55 Channel Breakout
Captures main trending legs.

| Aspect | Long | Short |
|--------|------|-------|
| Entry | Close > 55-bar high[1] + vol expand + ADX strong/rising + ATR 30-85% + Close > EMA55 | Close < 55-bar low[1] + vol expand + ADX strong + Close < EMA55 |
| Initial SL | 2.5x ATR below entry, capped by 5-day swing low | 2.5x ATR above entry, capped by 5-day swing high |
| Partial TP | 1.5R -> close 35% | 1.5R -> close 35% |
| Trailing Exit | Donchian 20 reverse, or EMA144 2-bar cross, or 3x ATR trail | Symmetric |
| Regime Gate | Bull (1) or Compression (3) | Bear (2) only |
| Score Threshold | >= 55 | >= 55 |
| Risk per Trade | 0.65% | 0.65% x 0.60 (bear discount) |

#### Pullback Module — EMA Zone with Momentum Confirmation
Improves entry price quality by entering on pullbacks within trends.

| Aspect | Long | Short |
|--------|------|-------|
| Entry | Price in EMA55-EMA144 zone + RSI recovering from 40-50 + MACD hist rising 2 bars + Close > EMA55 + breaks prev high | Price in EMA zone + RSI falling from 50-60 + MACD hist falling 2 bars + Close < EMA55 + breaks prev low |
| Initial SL | 2.0x ATR below entry | 2.0x ATR above entry |
| BE Stop | At 1R, move SL to entry | Symmetric |
| Partial TP | 2R -> close 40% | 2R -> close 40% |
| Time Stop | 10 bars without reaching 0.5R | 10 bars |
| Trailing | 1.5x ATR from extreme | Symmetric |
| Regime Gate | Bull (1) or Weak Bull | Bear (2) |
| Score Threshold | >= 75 | >= 75 |
| Risk per Trade | 0.50% | 0.50% x 0.60 |

#### Mean Reversion Module — Bollinger Band Extremes
Small, frequent trades to smooth the equity curve.

| Aspect | Long | Short |
|--------|------|-------|
| Entry | ADX < 25 + near BB lower/DC20 low + RSI < 35 + lower wick or close-back | ADX < 25 + near BB upper/DC20 high + RSI > 65 + upper wick |
| Initial SL | 1.0x ATR below entry | 1.0x ATR above entry |
| Target | BB mid or EMA55 (whichever closer), capped at 2x ATR | Symmetric |
| Time Stop | 9 bars without reaching target | 9 bars |
| Regime Gate | Ranging (0) only; strong bull -> no shorts; strong bear -> no longs | Same |
| Score Threshold | >= 75 | >= 75 |
| Risk per Trade | 0.25% | 0.25% x 0.60 |

#### Core Long Module
Captures long-term BTC beta. Spot-like, unlevered.

| Aspect | Rule |
|--------|------|
| Entry | Strong Bull regime (regime == 1) |
| Add-on | Pullback long signals while core is active |
| Exit | Weekly EMA169 slope turns negative, OR 2 consecutive daily closes below Daily EMA169 |
| Allocation | 40% of equity |
| No 4H noise exit | Core ignores 4H stop-losses that would shake out long-term positions |

### Layer 3: Risk Controls

| Control | Implementation |
|---------|---------------|
| **Position Sizing** | `size = equity x risk_pct / abs(entry - stop)` — ATR-adaptive: smaller positions when volatility is high |
| **Circuit Breaker** | 7.5% intraday OR intraweek drawdown -> halt new entries until next period |
| **Consecutive Loss** | 3 losses -> reduce size to 50%; 5 losses -> pause trading for 18 bars (~3 days) |
| **Bear Short Discount** | Short positions are sized at 60% of equivalent long risk |
| **HTF Conflict** | When daily and weekly EMA directions disagree -> position size x 0.5 |
| **Max Position Cap** | Single entry <= 99% equity; combined core + tactical <= ~140% (FractionalBacktest) |

## Scoring System (0-100)

Entry quality is evaluated on four dimensions, replacing binary AND filters with continuous assessment:

| Dimension | Max Pts | Components |
|-----------|:-------:|------------|
| **Market State** | 30 | HTF alignment: strong bull=30, soft bull=20, neutral=10, soft bear=10, strong bear=30 (for shorts) |
| **Pattern / Position** | 30 | Breakout: Donchian strength + volume + ADX. Pullback: EMA zone proximity + RSI position. MeanRev: BB extreme distance + wick quality |
| **Momentum Confirmation** | 20 | MACD histogram direction + RSI momentum + ADX trend + volume expansion |
| **Risk / Reward** | 20 | Stop distance assessment + ATR percentile range (30-85% optimal) |

Thresholds: Breakout >= 55, Pullback >= 75, Mean Reversion >= 75.

## CLI Reference

```
python run_backtest.py [OPTIONS]

Options:
  --exchange EXCHANGE       CCXT exchange id (default: binance)
  --symbol SYMBOL           Trading pair (default: BTC/USDT)
  --timeframe TIMEFRAME     Bar interval (default: 4h)
  --limit N                 Max OHLCV bars to fetch (default: 50000, paginated)
  --timeout-ms MS           Request timeout in ms (default: 30000)
  --max-retries N           Retry count (default: 5)
  --proxy-url URL           Proxy URL (default: http://127.0.0.1:7897)
  --no-proxy                Disable proxy entirely
  --disable-binanceus-fallback  Don't fall back to BinanceUS
  --strategy NAME           Strategy to run (default: dual)
                            Choices: legacy | htf | atr_htf | pullback |
                                     breakout | meanrev | dual
  --compare                 Run all strategies side-by-side
  --leverage N              Leverage multiplier (default: 5)
```

## Configuration

All parameters are centralized in `quant_btc/config.py` as frozen dataclasses:

**`BacktestConfig`**: Symbol, timeframe, initial cash, commission, EMA/MACD/HTF lengths, signal weights, cooldown parameters.

**`RiskConfig`**: Leverage, per-module risk percentages, ATR multipliers for SL/TP, regime classification thresholds (ADX, BB percentile, ATR percentile), scoring weights and thresholds, circuit breaker limits, trailing stop parameters, time stop bars, partial TP ratios, core allocation, bear short discount.

Modify defaults directly in the dataclass or pass custom instances at runtime.

## TradingView Integration

`btc_strategy_signals.pine` replicates the decision framework in Pine Script v5 for real-time signal generation:

- **Visual**: Regime background colors (green=bull, red=bear, yellow=compression, magenta=high risk), EMA 4-line, Donchian 55/20 channels, Bollinger Bands, entry signal markers
- **Info Table**: Real-time regime, all 6 scores (BO L/S, PB L/S, MR L/S), ADX, ATR, RSI, current signal and module name
- **Alert Conditions**: `alert_long`, `alert_short`, `alert_core`, `alert_exit` — create TradingView alerts from these boolean conditions

Usage: Paste into Pine Editor on BTC/USDT 4H chart, add to chart, create alerts from the script's conditions.

## Strategy Evolution

| Step | Innovation | Key Result |
|:----:|-----------|------------|
| 0 | EMA zone-crossing, no risk controls | +3.8% return, -80.8% max DD |
| 1 | ATR stop-loss + take-profit + position sizing + market regime | -80.8% -> -13.4% max DD (6x improvement) |
| 2 | Pullback entry: EMA zone + RSI/MACD momentum + price confirmation | 37.1% win rate (vs 28.6% legacy) |
| 3 | Donchian 55 breakout + trend-following exit (no fixed TP) | First positive Sharpe ratio (+0.20) |
| 4 | Mean reversion for ranging markets (small position, BB extremes) | -0.5% max DD, curve smoothing |
| 5 | **Dual-layer**: core long (40%) + tactical (3 modules, priority-selected) | +291% return, +1.06 Sharpe |
| 6 | 4-dimensional scoring replaces binary AND filters | Breakout +54% (threshold 55), Pullback first positive |
| 7 | Module-specific exits: partial TP, time stop, BE, EMA cross | Breakout +28%, Pullback +0.5%, MeanRev +1.7% |
| 8 | Entry priority system + HTF conflict half-size + regime strict gating | No signal collisions, regime-compliant |
| 9 | Risk-based position sizing per module (0.25%-0.65%) | Breakout max DD -6.6%, Sharpe +0.43 |

## Ablation Study

Strategies 0-4 represent single-module ablation tests — each module running standalone with its own entry/exit logic. Strategy 5 (Dual-Layer) combines all modules with priority selection. The ablation results quantify each module's marginal contribution:

- **Removing Breakout** (compare Dual-Layer vs Pullback-only): Breakout is the primary return driver
- **Removing Pullback** (compare Dual-Layer vs Breakout-only): Pullback improves entry quality in trends
- **Removing Mean Reversion** (compare Dual-Layer vs Breakout+Pullback): MeanRev provides small but consistent gains with minimal drawdown
- **Removing Core** (compare Dual-Layer vs tactical-only): Core captures BTC beta; without it, max DD increases and long-term returns decrease

## US IP / Binance Restriction

If Binance.com is restricted from your location, the data layer automatically falls back to BinanceUS. Proxy support is built in:

```bash
# Use BinanceUS directly
python run_backtest.py --exchange binanceus

# Use explicit proxy
python run_backtest.py --proxy-url http://127.0.0.1:7897

# Disable proxy entirely
python run_backtest.py --no-proxy
```

Public market data requests do not require API keys.

## Notes

- This system is for educational and research purposes. Past performance does not guarantee future results.
- Before live deployment, add: execution-layer slippage model, exchange-specific fee structure, funding rate monitoring, and a paper-trading validation phase.
- The backtesting library (`backtesting.py`) does not natively support multi-position portfolios. The dual-layer architecture uses partial position closing to simulate core+tactical coexistence.
