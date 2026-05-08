from __future__ import annotations

import numpy as np
import pandas as pd
from backtesting import Strategy
from backtesting.lib import FractionalBacktest

from quant_btc.config import BacktestConfig


def _ema(series: pd.Series, length: int) -> pd.Series:
    """Robust EMA that always returns numeric dtype (never Python None)."""
    return series.ewm(span=length, adjust=False, min_periods=1).mean()


def _macd(close: pd.Series, fast: int, slow: int, signal: int):
    """Compute MACD line and signal line. Returns (macd_line, signal_line)."""
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    return macd_line, signal_line


def _htf_ema(close: pd.Series, rule: str, length: int) -> pd.Series:
    """Compute HTF EMA on resampled close and forward-fill back to LTF index."""
    htf_close = close.resample(rule).last().ffill()
    htf_ema = _ema(htf_close, length)
    return htf_ema.reindex(close.index, method="ffill")


def prepare_features(df: pd.DataFrame, cfg: BacktestConfig) -> pd.DataFrame:
    out = df.copy()

    out["ema55"] = _ema(out["Close"], cfg.ema_fast_1)
    out["ema69"] = _ema(out["Close"], cfg.ema_fast_2)
    out["ema144"] = _ema(out["Close"], cfg.ema_slow_1)
    out["ema169"] = _ema(out["Close"], cfg.ema_slow_2)

    out["macd"], out["macd_signal"] = _macd(out["Close"], fast=cfg.macd_fast, slow=cfg.macd_slow, signal=cfg.macd_signal)

    # True HTF EMA filter: calculate on daily/weekly closes then map back to LTF bars.
    out["d_ema"] = _htf_ema(out["Close"], "1D", cfg.daily_ema_len)
    out["w_ema"] = _htf_ema(out["Close"], "1W", cfg.weekly_ema_len)

    zone_low = np.minimum(out["ema144"], out["ema169"])
    zone_high = np.maximum(out["ema144"], out["ema169"])
    in_zone = (out["Close"] >= zone_low) & (out["Close"] <= zone_high)

    # User's EMA logic
    ema_bear_struct = (out["ema144"] > out["ema69"]) & (out["ema169"] > out["ema55"])
    ema_bull_struct = (out["ema144"] < out["ema69"]) & (out["ema169"] < out["ema55"])

    first_enter_short = (out["Close"].shift(1) < zone_low.shift(1)) & in_zone
    first_enter_long = (out["Close"].shift(1) > zone_high.shift(1)) & in_zone

    out["ema_long_signal"] = ema_bull_struct & first_enter_long
    out["ema_short_signal"] = ema_bear_struct & first_enter_short

    out["macd_long_signal"] = (out["macd"] > out["macd_signal"]) & (out["macd"].shift(1) <= out["macd_signal"].shift(1))
    out["macd_short_signal"] = (out["macd"] < out["macd_signal"]) & (out["macd"].shift(1) >= out["macd_signal"].shift(1))

    out["long_score"] = (
        out["ema_long_signal"].astype(int) * cfg.ema_weight + out["macd_long_signal"].astype(int) * cfg.macd_weight
    )
    out["short_score"] = (
        out["ema_short_signal"].astype(int) * cfg.ema_weight + out["macd_short_signal"].astype(int) * cfg.macd_weight
    )

    out["major_bull"] = (out["Close"] > out["d_ema"]) & (out["Close"] > out["w_ema"])
    out["major_bear"] = (out["Close"] < out["d_ema"]) & (out["Close"] < out["w_ema"])

    out["long_entry"] = out["major_bull"] & (out["long_score"] >= cfg.signal_threshold)
    out["short_entry"] = out["major_bear"] & (out["short_score"] >= cfg.signal_threshold)

    return out.dropna().copy()


class WeightedSignalStrategy(Strategy):
    cooldown_bars = 12
    trade_size_fraction = 0.95

    def init(self):
        self.last_trade_bar = -10**9

    def next(self):
        i = len(self.data.Close) - 1
        if i - self.last_trade_bar < self.cooldown_bars:
            return

        long_entry = bool(self.data.df["long_entry"].iloc[i])
        short_entry = bool(self.data.df["short_entry"].iloc[i])

        if self.position:
            # Exit by opposite valid signal
            if self.position.is_long and short_entry:
                self.position.close()
                self.last_trade_bar = i
            elif self.position.is_short and long_entry:
                self.position.close()
                self.last_trade_bar = i
            return

        if long_entry:
            self.buy(size=self.trade_size_fraction)
            self.last_trade_bar = i
        elif short_entry:
            self.sell(size=self.trade_size_fraction)
            self.last_trade_bar = i


def run_backtest(df: pd.DataFrame, cfg: BacktestConfig):
    bt = FractionalBacktest(
        df,
        WeightedSignalStrategy,
        cash=cfg.initial_cash,
        commission=cfg.commission,
        exclusive_orders=True,
        hedging=False,
        finalize_trades=True,
    )
    return bt.run(trade_size_fraction=cfg.trade_size_fraction, cooldown_bars=cfg.cooldown_bars), bt
