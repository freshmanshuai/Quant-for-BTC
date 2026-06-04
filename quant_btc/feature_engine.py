"""BTC compatibility feature engine wiring."""

from __future__ import annotations

import pandas as pd

from quant_btc.config import BacktestConfig
from quant_platform.data import FeatureSeriesId
from quant_platform.features import (
    BollingerConfig,
    BollingerFeatureModule,
    DonchianConfig,
    DonchianFeatureModule,
    FeatureEngine,
    PriceActionFeatureModule,
    TechnicalIndicatorConfig,
    TechnicalIndicatorModule,
    VolatilityConfig,
    VolatilityFeatureModule,
    VolumeConfig,
    VolumeFeatureModule,
    FeatureRunResult,
    FeatureStoreWriter,
    run_feature_engine_with_cache,
)


def btc_feature_series_id(
    *,
    symbol: str = "BTC/USDT",
    exchange: str = "binance",
    market_type: str = "swap",
    timeframe: str = "4h",
    feature_set: str = "btc_compat_v1",
) -> FeatureSeriesId:
    """Build the deterministic feature cache id for BTC compatibility features."""
    return FeatureSeriesId(
        symbol=symbol,
        exchange=exchange,
        market_type=market_type,
        timeframe=timeframe,
        source="feature_engine",
        feature_set=feature_set,
    )


def build_btc_feature_engine(cfg: BacktestConfig) -> FeatureEngine:
    """Build the compatibility feature engine for the existing BTC strategy."""
    return FeatureEngine([
        TechnicalIndicatorModule(
            TechnicalIndicatorConfig(
                ema_lengths=(cfg.ema_fast_1, cfg.ema_fast_2, cfg.ema_slow_1, cfg.ema_slow_2),
                macd_fast=cfg.macd_fast,
                macd_slow=cfg.macd_slow,
                macd_signal=cfg.macd_signal,
                rsi_period=14,
                htf_ema_rules={"d_ema": "1D", "w_ema": "1W"},
                htf_ema_lengths={"d_ema": cfg.daily_ema_len, "w_ema": cfg.weekly_ema_len},
            )
        ),
        DonchianFeatureModule(
            DonchianConfig(
                channel_periods={"roll": 55, "mr_dc20": 20},
                column_names={"mr_dc20": ("mr_dc20_high", "mr_dc20_low")},
            )
        ),
        VolumeFeatureModule(VolumeConfig(lookback=50, zscore_column="vol_zscore")),
        VolatilityFeatureModule(
            VolatilityConfig(
                period=14,
                percentile_lookback=120,
                atr_column="_atr_signal",
                atr_percentile_column="_atr_pct_signal",
                adx_column="_adx_signal",
            )
        ),
        BollingerFeatureModule(
            BollingerConfig(period=20, std_mult=2.0, upper_column="bb_upper", lower_column="bb_lower")
        ),
        PriceActionFeatureModule(),
    ])


def build_cached_btc_features(
    bars: pd.DataFrame,
    cfg: BacktestConfig,
    *,
    symbol: str = "BTC/USDT",
    exchange: str = "binance",
    market_type: str = "swap",
    timeframe: str = "4h",
    feature_set: str = "btc_compat_v1",
    store: FeatureStoreWriter | None = None,
) -> FeatureRunResult:
    """Run BTC compatibility features and optionally persist them through FeatureStore."""
    return run_feature_engine_with_cache(
        build_btc_feature_engine(cfg),
        bars,
        series_id=btc_feature_series_id(
            symbol=symbol,
            exchange=exchange,
            market_type=market_type,
            timeframe=timeframe,
            feature_set=feature_set,
        ),
        store=store,
    )
