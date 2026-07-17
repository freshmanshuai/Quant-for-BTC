"""Causal continuous price-action features for cross-asset ablation.

The features deliberately avoid named candle patterns.  Every value is
computed from the current completed bar and strictly earlier bars, so a signal
formed at the close can be executed no earlier than the next bar's open.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quant_platform.signals import Direction


@dataclass(frozen=True)
class PriceActionConfig:
    structure_short: int = 252
    structure_long: int = 1008
    level_lookback: int = 126
    level_decay: float = 42.0
    level_bandwidth_atr: float = 1.5
    jump_window: int = 42


def add_continuous_price_action_features(
    bars: pd.DataFrame,
    *,
    atr_values: pd.Series,
    config: PriceActionConfig | None = None,
    families: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Return only the pre-declared continuous feature families."""
    cfg = config or PriceActionConfig()
    enabled = set(
        ("structure", "support_resistance", "jump_risk")
        if families is None
        else families
    )
    unknown = enabled.difference({"structure", "support_resistance", "jump_risk"})
    if unknown:
        raise ValueError(f"unsupported price-action feature families: {sorted(unknown)}")
    out = bars.copy()
    close = pd.to_numeric(out["Close"], errors="coerce").astype(float)
    log_return = np.log(close).diff()

    if "structure" in enabled:
        structure_parts: list[pd.Series] = []
        for label, horizon in (("short", cfg.structure_short), ("long", cfg.structure_long)):
            squared_path = log_return.pow(2).rolling(horizon, min_periods=horizon).sum()
            momentum = log_return.rolling(horizon, min_periods=horizon).sum() / np.sqrt(
                horizon * squared_path
            ).replace(0.0, np.nan)
            price_path = close.diff().abs().rolling(horizon, min_periods=horizon).sum()
            efficiency = (close - close.shift(horizon)) / price_path.replace(0.0, np.nan)
            out[f"_structure_momentum_{label}"] = momentum.clip(-1.0, 1.0)
            out[f"_structure_efficiency_{label}"] = efficiency.clip(-1.0, 1.0)
            structure_parts.extend((momentum, efficiency))
        out["_structure_score"] = (
            pd.concat(structure_parts, axis=1).mean(axis=1).clip(-1.0, 1.0)
        )

    if "support_resistance" in enabled:
        level_balance, level_density = _causal_level_strength(
            out,
            atr_values=atr_values,
            lookback=cfg.level_lookback,
            decay=cfg.level_decay,
            bandwidth_atr=cfg.level_bandwidth_atr,
        )
        out["_level_balance"] = level_balance
        out["_level_density"] = level_density

    if "jump_risk" in enabled:
        absolute_return = log_return.abs()
        realized_variance = log_return.pow(2).rolling(
            cfg.jump_window, min_periods=cfg.jump_window
        ).sum()
        bipower_variation = (
            (np.pi / 2.0)
            * (absolute_return * absolute_return.shift(1)).rolling(
                cfg.jump_window, min_periods=cfg.jump_window
            ).sum()
        )
        jump_share = (
            (realized_variance - bipower_variation).clip(lower=0.0) / realized_variance
        ).clip(0.0, 1.0)
        prior_volatility = log_return.shift(1).rolling(
            cfg.jump_window, min_periods=cfg.jump_window
        ).std(ddof=0)
        gap_score = (
            np.log(
                pd.to_numeric(out["Open"], errors="coerce").astype(float) / close.shift(1)
            ).abs()
            / prior_volatility.replace(0.0, np.nan)
        )
        out["_jump_share"] = jump_share
        out["_gap_score"] = gap_score
        out["_jump_risk"] = pd.concat(
            (jump_share, (gap_score / 5.0).clip(0.0, 1.0)), axis=1
        ).max(axis=1)
    return out


def confidence_multiplier(
    row: pd.Series,
    direction: Direction,
    families: tuple[str, ...],
) -> float:
    """Map an ablated feature family to a bounded, monotonic size multiplier."""
    direction_sign = 1.0 if direction == Direction.LONG else -1.0
    multiplier = 1.0
    if "ema_strength" in families:
        strength = float(row.get("_ema_strength", np.nan))
        if np.isfinite(strength):
            alignment = max(0.0, direction_sign * strength)
            multiplier *= float(np.clip(0.75 + 0.50 * alignment, 0.75, 1.25))
    if "support_resistance" in families:
        balance = float(row.get("_level_balance", np.nan))
        density = float(row.get("_level_density", np.nan))
        if np.isfinite(balance) and np.isfinite(density):
            density_scale = float(np.clip(density / np.log(2.0), 0.0, 1.0))
            multiplier *= float(
                np.clip(
                    1.0 + 0.35 * direction_sign * balance * density_scale,
                    0.65,
                    1.35,
                )
            )
    if "jump_risk" in families:
        jump_risk = float(row.get("_jump_risk", np.nan))
        if np.isfinite(jump_risk):
            multiplier *= float(np.clip(1.0 - 0.50 * jump_risk, 0.50, 1.0))
    return float(np.clip(multiplier, 0.50, 1.50))


def _causal_level_strength(
    bars: pd.DataFrame,
    *,
    atr_values: pd.Series,
    lookback: int,
    decay: float,
    bandwidth_atr: float,
) -> tuple[pd.Series, pd.Series]:
    highs = pd.to_numeric(bars["High"], errors="coerce").to_numpy(dtype=float)
    lows = pd.to_numeric(bars["Low"], errors="coerce").to_numpy(dtype=float)
    closes = pd.to_numeric(bars["Close"], errors="coerce").to_numpy(dtype=float)
    atr_array = pd.to_numeric(atr_values.shift(1), errors="coerce").to_numpy(dtype=float)
    balance = np.full(len(bars), np.nan, dtype=float)
    density = np.full(len(bars), np.nan, dtype=float)
    lags = np.arange(lookback, 0, -1, dtype=float)
    weights = np.exp(-lags / decay)
    weights /= weights.sum()
    epsilon = np.finfo(float).eps

    for index in range(lookback, len(bars)):
        scale = bandwidth_atr * atr_array[index]
        if not np.isfinite(scale) or scale <= 0 or not np.isfinite(closes[index]):
            continue
        prior_levels = np.concatenate(
            (highs[index - lookback : index], lows[index - lookback : index])
        )
        level_weights = np.concatenate((weights, weights)) / 2.0
        signed_distance = (closes[index] - prior_levels) / scale
        kernel = np.exp(-(signed_distance**2))
        total = float(np.sum(level_weights * kernel))
        # Levels below price contribute continuously as support; levels above
        # price contribute continuously as resistance.
        balance[index] = float(
            np.sum(level_weights * kernel * np.tanh(signed_distance))
            / (total + epsilon)
        )
        density[index] = np.log1p(total)

    return (
        pd.Series(balance, index=bars.index),
        pd.Series(density, index=bars.index),
    )
