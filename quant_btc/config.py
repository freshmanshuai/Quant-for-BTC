from dataclasses import dataclass


@dataclass(frozen=True)
class BacktestConfig:
    symbol: str = "BTC/USDT"
    timeframe: str = "4h"  # 1h or 4h recommended
    limit: int = 3000
    initial_cash: float = 100_000
    commission: float = 0.0006

    # Weighted score model
    ema_weight: int = 75
    macd_weight: int = 25
    signal_threshold: int = 75

    # EMA settings
    ema_fast_1: int = 55
    ema_fast_2: int = 69
    ema_slow_1: int = 144
    ema_slow_2: int = 169

    # MACD settings
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    # HTF filters
    daily_ema_len: int = 169
    weekly_ema_len: int = 169

    # Control duplicate entries
    cooldown_bars: int = 12
