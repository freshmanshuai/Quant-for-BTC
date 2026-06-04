"""BTC compatibility regime model wiring."""

from __future__ import annotations

from quant_btc.config import BacktestConfig, RiskConfig
from quant_platform.regimes import RegimeModel, RegimeProfile


def btc_regime_entry_gate(
    *,
    regime: int,
    d_dir: int | float,
    w_dir: int | float,
    mode: str = "default",
) -> tuple[bool, bool]:
    """Return BTC compatibility long/short entry permissions for a strategy mode."""
    if mode == "default":
        allow_long = regime == 1 or (d_dir >= 0 and w_dir >= 0)
        allow_short = regime == 2 or (d_dir <= 0 and w_dir <= 0)
        return allow_long, allow_short
    if mode == "breakout":
        return regime in (1, 3), regime == 2 and w_dir <= 0
    if mode == "meanrev":
        allow = regime == 0
        return allow, allow
    raise ValueError(f"Unknown BTC regime gate mode: {mode}")


def build_btc_regime_model(cfg: RiskConfig) -> RegimeModel:
    """Build the compatibility regime model for the existing BTC strategy."""
    base_cfg = BacktestConfig()
    return RegimeModel(
        RegimeProfile(
            trend_ema_length=base_cfg.daily_ema_len,
            daily_rule="1D",
            weekly_rule="1W",
            atr_period=cfg.atr_period,
            adx_period=cfg.adx_period,
            bb_period=cfg.bb_period,
            bb_std_mult=cfg.bb_std_mult,
            regime_lookback=cfg.regime_lookback,
            compression_bb_pct=cfg.compression_bb_pct,
            compression_atr_pct=cfg.compression_atr_pct,
            high_vol_atr_pct=cfg.high_vol_atr_pct,
            high_vol_large_candle_mult=cfg.high_vol_large_candle_mult,
            adx_ranging_threshold=cfg.adx_ranging_threshold,
        )
    )
