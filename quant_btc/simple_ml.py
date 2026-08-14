"""Minimal causal linear model for intraday price-feature research."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from quant_platform.features import atr, ema, htf_ema, rsi


EMA_FEATURE = "_ml_ema_distance"
RSI_FEATURE = "_ml_rsi"
VOLUME_FEATURE = "_ml_volume_zscore"
ATR_FEATURE = "_ml_atr_fraction"
TARGET_COLUMN = "_ml_forward_open_return"


@dataclass(frozen=True)
class SimpleMLConfig:
    ema_period: int = 20
    rsi_period: int = 14
    volume_period: int = 20
    atr_period: int = 14
    prediction_horizon_bars: int = 16
    ridge_alpha: float = 10.0
    minimum_training_rows_per_asset: int = 2_000
    bar_interval: str = "15min"
    entry_threshold: float = 0.0014


@dataclass(frozen=True)
class WalkForwardResult:
    predictions: dict[str, pd.Series]
    coefficients: pd.DataFrame


def build_simple_ml_features(
    bars: pd.DataFrame,
    config: SimpleMLConfig | None = None,
) -> pd.DataFrame:
    """Add four stable features and a next-open-to-future-open research label."""
    cfg = config or SimpleMLConfig()
    out = bars.copy()
    close = pd.to_numeric(out["Close"], errors="coerce")
    atr_values = atr(out["High"], out["Low"], close, cfg.atr_period)
    atr_scale = atr_values.replace(0.0, np.nan)
    log_volume = np.log1p(pd.to_numeric(out["Volume"], errors="coerce").clip(lower=0.0))
    volume_mean = log_volume.rolling(
        cfg.volume_period, min_periods=cfg.volume_period
    ).mean()
    volume_std = log_volume.rolling(
        cfg.volume_period, min_periods=cfg.volume_period
    ).std(ddof=0)

    out[EMA_FEATURE] = ((close - ema(close, cfg.ema_period)) / atr_scale).clip(-10.0, 10.0)
    out[RSI_FEATURE] = ((rsi(close, cfg.rsi_period) - 50.0) / 50.0).clip(-1.0, 1.0)
    out[VOLUME_FEATURE] = ((log_volume - volume_mean) / volume_std.replace(0.0, np.nan)).clip(
        -5.0, 5.0
    )
    out[ATR_FEATURE] = (atr_values / close.replace(0.0, np.nan)).clip(0.0, 0.20)
    horizon = cfg.prediction_horizon_bars
    out[TARGET_COLUMN] = out["Open"].shift(-(horizon + 1)) / out["Open"].shift(-1) - 1.0
    return out


def pooled_walk_forward_ridge(
    features_by_asset: dict[str, pd.DataFrame],
    feature_columns: tuple[str, ...],
    *,
    prediction_start: str | pd.Timestamp,
    prediction_end: str | pd.Timestamp,
    config: SimpleMLConfig | None = None,
) -> WalkForwardResult:
    """Fit one additive ridge model monthly using only labels available at each cutoff.

    Inputs are standardized separately per asset before pooling.  The returned
    score excludes the fitted intercept so that unconditional crypto drift is
    not presented as feature alpha.
    """
    cfg = config or SimpleMLConfig()
    if not feature_columns:
        raise ValueError("feature_columns cannot be empty")
    missing = {
        asset: [column for column in (*feature_columns, TARGET_COLUMN) if column not in frame]
        for asset, frame in features_by_asset.items()
    }
    missing = {asset: columns for asset, columns in missing.items() if columns}
    if missing:
        raise ValueError(f"missing model columns: {missing}")

    start = _coerce_timestamp(prediction_start, features_by_asset)
    end = _coerce_timestamp(prediction_end, features_by_asset)
    predictions = {
        asset: pd.Series(np.nan, index=frame.index, dtype=float, name="ml_prediction")
        for asset, frame in features_by_asset.items()
    }
    coefficient_rows: list[dict[str, object]] = []
    cutoff = start
    label_delay = (cfg.prediction_horizon_bars + 1) * pd.Timedelta(cfg.bar_interval)

    while cutoff <= end:
        next_cutoff = cutoff + pd.offsets.MonthBegin(1)
        pooled_x: list[np.ndarray] = []
        pooled_y: list[np.ndarray] = []
        scalers: dict[str, tuple[np.ndarray, np.ndarray]] = {}

        for asset, frame in features_by_asset.items():
            training = frame.loc[frame.index <= cutoff - label_delay, [*feature_columns, TARGET_COLUMN]]
            training = training.replace([np.inf, -np.inf], np.nan).dropna()
            if len(training) < cfg.minimum_training_rows_per_asset:
                raise ValueError(
                    f"{asset} has only {len(training)} training rows before {cutoff}"
                )
            raw_x = training.loc[:, feature_columns].to_numpy(dtype=float)
            mean = raw_x.mean(axis=0)
            scale = raw_x.std(axis=0)
            scale[scale < 1e-12] = 1.0
            standardized = (raw_x - mean) / scale
            scalers[asset] = (mean, scale)
            pooled_x.append(standardized)
            pooled_y.append(training[TARGET_COLUMN].to_numpy(dtype=float))

        x_train = np.vstack(pooled_x)
        y_train = np.concatenate(pooled_y)
        design = np.column_stack([np.ones(len(x_train)), x_train])
        penalty = np.eye(design.shape[1], dtype=float) * cfg.ridge_alpha
        penalty[0, 0] = 0.0
        coefficients = np.linalg.solve(
            design.T @ design + penalty,
            design.T @ y_train,
        )

        for asset, frame in features_by_asset.items():
            prediction_mask = (
                (frame.index >= max(cutoff, start))
                & (frame.index < min(next_cutoff, end + pd.Timedelta(cfg.bar_interval)))
            )
            raw_prediction = frame.loc[prediction_mask, feature_columns]
            valid = raw_prediction.replace([np.inf, -np.inf], np.nan).notna().all(axis=1)
            mean, scale = scalers[asset]
            standardized = (raw_prediction.loc[valid].to_numpy(dtype=float) - mean) / scale
            predictions[asset].loc[raw_prediction.index[valid]] = standardized @ coefficients[1:]

        coefficient_rows.append(
            {
                "cutoff": cutoff,
                "feature": "intercept_excluded_from_signal",
                "coefficient": float(coefficients[0]),
                "pooled_training_rows": int(len(y_train)),
            }
        )
        coefficient_rows.extend(
            {
                "cutoff": cutoff,
                "feature": feature,
                "coefficient": float(coefficient),
                "pooled_training_rows": int(len(y_train)),
            }
            for feature, coefficient in zip(feature_columns, coefficients[1:])
        )
        cutoff = next_cutoff

    return WalkForwardResult(
        predictions=predictions,
        coefficients=pd.DataFrame(coefficient_rows),
    )


def positions_from_prediction(
    prediction: pd.Series,
    entry_threshold: float,
) -> pd.Series:
    """Map forecasts to positions with a transaction-cost no-trade band.

    A flat strategy enters only beyond the round-trip hurdle.  An existing
    position is retained while its forecast keeps the same sign and is closed
    at zero.  This avoids repeatedly paying costs when a forecast oscillates
    just inside and outside the entry boundary.
    """
    if entry_threshold <= 0:
        raise ValueError("entry_threshold must be positive")
    values = pd.to_numeric(prediction, errors="coerce")
    position = np.zeros(len(values), dtype=float)
    state = 0.0
    for offset, value in enumerate(values.to_numpy(dtype=float)):
        if not math.isfinite(value):
            state = 0.0
        elif state == 0.0:
            if value >= entry_threshold:
                state = 1.0
            elif value <= -entry_threshold:
                state = -1.0
        elif state > 0.0 and value <= 0.0:
            state = -1.0 if value <= -entry_threshold else 0.0
        elif state < 0.0 and value >= 0.0:
            state = 1.0 if value >= entry_threshold else 0.0
        position[offset] = state
    return pd.Series(position, index=prediction.index, dtype=float, name="target_position")


def ema_trend_baseline_positions(bars: pd.DataFrame) -> pd.Series:
    """Current core EMA direction expressed as a comparable unit target."""
    close = pd.to_numeric(bars["Close"], errors="coerce")
    daily = htf_ema(close, "1D", 169)
    weekly = htf_ema(close, "1W", 40)
    values = np.select(
        [(close > daily) & (close > weekly), (close < daily) & (close < weekly)],
        [1.0, -1.0],
        default=0.0,
    )
    return pd.Series(values, index=bars.index, dtype=float, name="target_position")


def simulate_open_boundary_strategy(
    bars: pd.DataFrame,
    target_position: pd.Series,
    *,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    fee_rate_per_fill: float,
    slippage_bps_per_fill: float,
    funding: pd.DataFrame | None = None,
    bar_interval: str = "15min",
) -> dict[str, float | int | None]:
    """Simulate close decisions at the first available next bar-open proxy.

    This is an alpha-screening ledger, not a tick/order-book fill simulator.
    Position size is one unit of equity and leverage is fixed at 1x.
    """
    evaluation = bars.loc[start:end].copy()
    if len(evaluation) < 2:
        raise ValueError("evaluation requires at least two bars")
    target = target_position.reindex(evaluation.index).fillna(0.0).clip(-1.0, 1.0)
    position = target.shift(1).fillna(0.0)
    previous_position = position.shift(1).fillna(0.0)
    turnover = position.diff().abs().fillna(position.abs())
    per_fill_cost = float(fee_rate_per_fill) + float(slippage_bps_per_fill) / 10_000.0

    open_price = pd.to_numeric(evaluation["Open"], errors="coerce")
    interval_return = open_price.shift(-1) / open_price - 1.0
    interval_return.iloc[-1] = (
        float(evaluation["Close"].iloc[-1]) / float(open_price.iloc[-1]) - 1.0
    )
    execution_cost = turnover * per_fill_cost
    execution_cost.iloc[-1] += abs(float(position.iloc[-1])) * per_fill_cost
    funding_rate = _aligned_funding(funding, evaluation.index, bar_interval)
    funding_cashflow = previous_position * funding_rate
    gross_price_return = (position * interval_return).replace(
        [np.inf, -np.inf], np.nan
    ).fillna(0.0)
    after_execution_return = gross_price_return - execution_cost
    strategy_return = (
        after_execution_return - funding_cashflow
    ).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    equity = (1.0 + strategy_return).cumprod()
    gross_price_equity = (1.0 + gross_price_return).cumprod()
    after_execution_equity = (1.0 + after_execution_return).cumprod()

    equity_with_initial = pd.concat(
        [pd.Series([1.0], index=[evaluation.index[0] - pd.Timedelta(bar_interval)]), equity]
    )
    peak = equity_with_initial.cummax()
    max_drawdown = float((1.0 - equity_with_initial / peak).max())
    daily_equity = equity.resample("1D").last().dropna()
    daily_returns = daily_equity.pct_change().dropna()
    daily_volatility = float(daily_returns.std(ddof=1)) if len(daily_returns) > 1 else 0.0
    sharpe = (
        float(daily_returns.mean() / daily_volatility * math.sqrt(365.0))
        if daily_volatility > 0
        else None
    )
    elapsed_days = max(
        (equity.index[-1] - equity.index[0]).total_seconds() / 86_400.0,
        1.0,
    )
    final_equity = float(equity.iloc[-1])
    cagr = final_equity ** (365.0 / elapsed_days) - 1.0 if final_equity > 0 else -1.0
    total_turnover = float(turnover.sum() + abs(float(position.iloc[-1])))
    return {
        "gross_price_return_pct": 100.0 * (float(gross_price_equity.iloc[-1]) - 1.0),
        "after_execution_before_funding_return_pct": 100.0
        * (float(after_execution_equity.iloc[-1]) - 1.0),
        "total_return_pct": 100.0 * (final_equity - 1.0),
        "cagr_pct": 100.0 * cagr,
        "max_drawdown_pct": 100.0 * max_drawdown,
        "sharpe": sharpe,
        "calmar": cagr / max_drawdown if max_drawdown > 0 else None,
        "round_trip_equivalents": total_turnover / 2.0,
        "active_bar_fraction": float((position != 0.0).mean()),
        "long_bar_fraction": float((position > 0.0).mean()),
        "short_bar_fraction": float((position < 0.0).mean()),
        "execution_cost_pct_uncompounded": 100.0 * float(execution_cost.sum()),
        "funding_pct_uncompounded": 100.0 * float(funding_cashflow.sum()),
        "bars": int(len(evaluation)),
    }


def _aligned_funding(
    funding: pd.DataFrame | None,
    index: pd.DatetimeIndex,
    bar_interval: str,
) -> pd.Series:
    if funding is None or funding.empty or "funding_rate" not in funding:
        return pd.Series(0.0, index=index, dtype=float)
    rates = pd.to_numeric(funding["funding_rate"], errors="coerce").dropna()
    floor_interval = "15min" if bar_interval == "15m" else bar_interval
    rates = rates.groupby(rates.index.floor(floor_interval)).sum(min_count=1)
    return rates.reindex(index).fillna(0.0).astype(float)


def _coerce_timestamp(
    value: str | pd.Timestamp,
    frames: dict[str, pd.DataFrame],
) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    first_index = next(iter(frames.values())).index
    if timestamp.tz is None and isinstance(first_index, pd.DatetimeIndex):
        timestamp = timestamp.tz_localize(first_index.tz)
    return timestamp
