from __future__ import annotations

import numpy as np
import pandas as pd
import pandas_ta as ta
from backtesting import Backtest, Strategy

from quant_btc.config import BacktestConfig


def prepare_features(df: pd.DataFrame, cfg: BacktestConfig) -> pd.DataFrame:
    out = df.copy()

    out["ema55"] = ta.ema(out["Close"], length=cfg.ema_fast_1)
    out["ema69"] = ta.ema(out["Close"], length=cfg.ema_fast_2)
    out["ema144"] = ta.ema(out["Close"], length=cfg.ema_slow_1)
    out["ema169"] = ta.ema(out["Close"], length=cfg.ema_slow_2)

    macd = ta.macd(out["Close"], fast=cfg.macd_fast, slow=cfg.macd_slow, signal=cfg.macd_signal)
    out["macd"] = macd[f"MACD_{cfg.macd_fast}_{cfg.macd_slow}_{cfg.macd_signal}"]
    out["macd_signal"] = macd[f"MACDs_{cfg.macd_fast}_{cfg.macd_slow}_{cfg.macd_signal}"]

    # Approximate HTF trend on 4H bars: 1D ~= 6 bars, 1W ~= 42 bars
    daily_equiv = cfg.daily_ema_len * 6
    weekly_equiv = cfg.weekly_ema_len * 42
    out["d_ema"] = ta.ema(out["Close"], length=daily_equiv)
    out["w_ema"] = ta.ema(out["Close"], length=weekly_equiv)

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
            self.buy()
            self.last_trade_bar = i
        elif short_entry:
            self.sell()
            self.last_trade_bar = i


def run_backtest(df: pd.DataFrame, cfg: BacktestConfig):
    bt = Backtest(
        df,
        WeightedSignalStrategy,
        cash=cfg.initial_cash,
        commission=cfg.commission,
        exclusive_orders=True,
        hedging=False,
    )
    return bt.run(), bt
