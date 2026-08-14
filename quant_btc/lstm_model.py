"""Causal medium-size LSTM for intraday price-feature research."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math

import numpy as np
import pandas as pd
import torch
from torch import nn

from quant_btc.simple_ml import TARGET_COLUMN
from quant_platform.features import atr, ema, rsi


EMA_PERIODS = (55, 69, 144, 169)
EMA_FEATURES = tuple(f"_lstm_ema_{period}_distance" for period in EMA_PERIODS)
RSI_FEATURE = "_lstm_rsi_14"
ATR_FEATURE = "_lstm_atr_14_fraction"
VOLUME_FEATURE = "_lstm_volume_zscore"
BOLL_POSITION_FEATURE = "_lstm_boll_position"
BOLL_WIDTH_FEATURE = "_lstm_boll_width"
SUPPORT_DISTANCE_FEATURE = "_lstm_support_distance"
RESISTANCE_DISTANCE_FEATURE = "_lstm_resistance_distance"

CORE_FEATURES = (*EMA_FEATURES, RSI_FEATURE, ATR_FEATURE, VOLUME_FEATURE)
BOLL_FEATURES = (BOLL_POSITION_FEATURE, BOLL_WIDTH_FEATURE)
LEVEL_FEATURES = (SUPPORT_DISTANCE_FEATURE, RESISTANCE_DISTANCE_FEATURE)
FULL_FEATURES = (*CORE_FEATURES, *BOLL_FEATURES, *LEVEL_FEATURES)


@dataclass(frozen=True)
class LSTMConfig:
    ema_periods: tuple[int, ...] = EMA_PERIODS
    rsi_period: int = 14
    atr_period: int = 14
    volume_period: int = 20
    boll_period: int = 20
    boll_std: float = 2.0
    level_lookback: int = 96
    prediction_horizon_bars: int = 16
    sequence_length: int = 96
    hidden_size: int = 64
    num_layers: int = 2
    dropout: float = 0.20
    head_size: int = 32
    batch_size: int = 512
    prediction_batch_size: int = 2_048
    learning_rate: float = 0.001
    weight_decay: float = 0.0001
    max_epochs: int = 20
    patience: int = 4
    validation_days: int = 30
    huber_delta_bps: float = 10.0
    minimum_training_sequences_per_asset: int = 2_000
    bar_interval: str = "15min"


@dataclass(frozen=True)
class LSTMTrainingResult:
    predictions: dict[str, pd.Series]
    diagnostics: dict[str, float | int | str]
    state_dict: dict[str, torch.Tensor]
    preprocessing: dict[str, dict[str, np.ndarray | float]]


class MediumLSTM(nn.Module):
    """Two-layer unidirectional LSTM with a compact nonlinear output head."""

    def __init__(
        self,
        input_size: int,
        *,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.20,
        head_size: int = 32,
    ):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
            bidirectional=False,
        )
        self.head = nn.Sequential(
            nn.LayerNorm(hidden_size),
            nn.Linear(hidden_size, head_size),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(head_size, 1),
        )

    def forward(self, sequence: torch.Tensor) -> torch.Tensor:
        output, _ = self.lstm(sequence)
        return self.head(output[:, -1, :]).squeeze(-1)


def build_lstm_features(
    bars: pd.DataFrame,
    config: LSTMConfig | None = None,
) -> pd.DataFrame:
    """Build only the requested continuous EMA/RSI/ATR/VOL/BOLL/level features."""
    cfg = config or LSTMConfig()
    out = bars.copy()
    close = pd.to_numeric(out["Close"], errors="coerce").astype(float)
    high = pd.to_numeric(out["High"], errors="coerce").astype(float)
    low = pd.to_numeric(out["Low"], errors="coerce").astype(float)
    atr_values = atr(high, low, close, cfg.atr_period)
    atr_scale = atr_values.replace(0.0, np.nan)

    for period in cfg.ema_periods:
        out[f"_lstm_ema_{period}_distance"] = (
            (close - ema(close, period)) / atr_scale
        ).clip(-10.0, 10.0)
    out[RSI_FEATURE] = ((rsi(close, cfg.rsi_period) - 50.0) / 50.0).clip(-1.0, 1.0)
    out[ATR_FEATURE] = (atr_values / close.replace(0.0, np.nan)).clip(0.0, 0.20)

    log_volume = np.log1p(pd.to_numeric(out["Volume"], errors="coerce").clip(lower=0.0))
    volume_mean = log_volume.rolling(
        cfg.volume_period, min_periods=cfg.volume_period
    ).mean()
    volume_std = log_volume.rolling(
        cfg.volume_period, min_periods=cfg.volume_period
    ).std(ddof=0)
    out[VOLUME_FEATURE] = (
        (log_volume - volume_mean) / volume_std.replace(0.0, np.nan)
    ).clip(-5.0, 5.0)

    boll_mid = close.rolling(cfg.boll_period, min_periods=cfg.boll_period).mean()
    boll_std = close.rolling(cfg.boll_period, min_periods=cfg.boll_period).std(ddof=0)
    half_band = cfg.boll_std * boll_std
    out[BOLL_POSITION_FEATURE] = (
        (close - boll_mid) / half_band.replace(0.0, np.nan)
    ).clip(-5.0, 5.0)
    out[BOLL_WIDTH_FEATURE] = (
        2.0 * half_band / boll_mid.replace(0.0, np.nan)
    ).clip(0.0, 0.50)

    prior_support = low.shift(1).rolling(
        cfg.level_lookback, min_periods=cfg.level_lookback
    ).min()
    prior_resistance = high.shift(1).rolling(
        cfg.level_lookback, min_periods=cfg.level_lookback
    ).max()
    out[SUPPORT_DISTANCE_FEATURE] = (
        (close - prior_support) / atr_scale
    ).clip(-10.0, 10.0)
    out[RESISTANCE_DISTANCE_FEATURE] = (
        (prior_resistance - close) / atr_scale
    ).clip(-10.0, 10.0)

    horizon = cfg.prediction_horizon_bars
    out[TARGET_COLUMN] = out["Open"].shift(-(horizon + 1)) / out["Open"].shift(-1) - 1.0
    return out


def train_predict_lstm(
    features_by_asset: dict[str, pd.DataFrame],
    feature_columns: tuple[str, ...],
    *,
    training_cutoff: str | pd.Timestamp,
    prediction_start: str | pd.Timestamp,
    prediction_end: str | pd.Timestamp,
    seed: int,
    config: LSTMConfig | None = None,
    device: str | None = None,
) -> LSTMTrainingResult:
    """Train with a chronological inner validation window and predict one OOS block."""
    cfg = config or LSTMConfig()
    if not feature_columns:
        raise ValueError("feature_columns cannot be empty")
    if cfg.num_layers < 2:
        raise ValueError("medium LSTM requires at least two recurrent layers")
    _validate_columns(features_by_asset, feature_columns)
    cutoff = _timestamp(training_cutoff, features_by_asset)
    prediction_start_ts = _timestamp(prediction_start, features_by_asset)
    prediction_end_ts = _timestamp(prediction_end, features_by_asset)
    validation_start = cutoff - pd.Timedelta(days=cfg.validation_days)
    label_delay = (cfg.prediction_horizon_bars + 1) * pd.Timedelta(cfg.bar_interval)
    training_end = validation_start - label_delay
    validation_end = cutoff - label_delay
    selected_device = device or ("cuda" if torch.cuda.is_available() else "cpu")

    _set_seed(seed)
    prepared = _prepare_assets(
        features_by_asset,
        feature_columns,
        training_end=training_end,
        validation_start=validation_start,
        validation_end=validation_end,
        prediction_start=prediction_start_ts,
        prediction_end=prediction_end_ts,
        config=cfg,
    )
    model = MediumLSTM(
        len(feature_columns),
        hidden_size=cfg.hidden_size,
        num_layers=cfg.num_layers,
        dropout=cfg.dropout,
        head_size=cfg.head_size,
    ).to(selected_device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=cfg.learning_rate,
        weight_decay=cfg.weight_decay,
    )
    loss_function = nn.HuberLoss(delta=cfg.huber_delta_bps)
    best_loss = float("inf")
    best_epoch = 0
    best_state: dict[str, torch.Tensor] | None = None
    stale_epochs = 0

    for epoch in range(1, cfg.max_epochs + 1):
        model.train()
        batches = _training_batches(prepared, cfg.batch_size, seed + epoch)
        for asset, window_indices in batches:
            record = prepared[asset]
            sequence = record["windows"][window_indices].to(selected_device)
            target = record["target"][window_indices].to(selected_device)
            optimizer.zero_grad(set_to_none=True)
            loss = loss_function(model(sequence), target)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

        validation_loss = _validation_loss(
            model,
            prepared,
            loss_function,
            cfg.prediction_batch_size,
            selected_device,
        )
        if validation_loss < best_loss - 1e-6:
            best_loss = validation_loss
            best_epoch = epoch
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= cfg.patience:
                break

    if best_state is None:
        raise RuntimeError("LSTM training did not produce a valid checkpoint")
    model.load_state_dict(best_state)
    predictions = _predict(
        model,
        prepared,
        features_by_asset,
        cfg.prediction_batch_size,
        selected_device,
    )
    if selected_device.startswith("cuda"):
        torch.cuda.empty_cache()
    return LSTMTrainingResult(
        predictions=predictions,
        diagnostics={
            "seed": seed,
            "device": selected_device,
            "best_epoch": best_epoch,
            "validation_huber_loss_bps": best_loss,
            "training_sequences": sum(len(record["train_indices"]) for record in prepared.values()),
            "validation_sequences": sum(len(record["validation_indices"]) for record in prepared.values()),
            "parameters": sum(parameter.numel() for parameter in model.parameters()),
        },
        state_dict=best_state,
        preprocessing={
            asset: {
                "mean": np.asarray(record["mean"], dtype=np.float32),
                "scale": np.asarray(record["scale"], dtype=np.float32),
                "target_mean": float(record["target_mean"]),
            }
            for asset, record in prepared.items()
        },
    )


def _prepare_assets(
    features_by_asset: dict[str, pd.DataFrame],
    feature_columns: tuple[str, ...],
    *,
    training_end: pd.Timestamp,
    validation_start: pd.Timestamp,
    validation_end: pd.Timestamp,
    prediction_start: pd.Timestamp,
    prediction_end: pd.Timestamp,
    config: LSTMConfig,
) -> dict[str, dict[str, object]]:
    prepared: dict[str, dict[str, object]] = {}
    for asset, frame in features_by_asset.items():
        raw_x = frame.loc[:, feature_columns].to_numpy(dtype=np.float32)
        raw_y = pd.to_numeric(frame[TARGET_COLUMN], errors="coerce").to_numpy(dtype=np.float32)
        training_rows = (
            (frame.index <= training_end)
            & np.isfinite(raw_x).all(axis=1)
            & np.isfinite(raw_y)
        )
        mean = raw_x[training_rows].mean(axis=0)
        scale = raw_x[training_rows].std(axis=0)
        scale[scale < 1e-6] = 1.0
        standardized = (raw_x - mean) / scale
        row_valid = np.isfinite(standardized).all(axis=1)
        valid_windows = (
            np.convolve(
                row_valid.astype(np.int16),
                np.ones(config.sequence_length, dtype=np.int16),
                mode="valid",
            )
            == config.sequence_length
        )
        window_end_index = np.arange(config.sequence_length - 1, len(frame))
        valid_end = window_end_index[valid_windows]
        target_mean = float(np.nanmean(raw_y[training_rows]))
        centered_target_bps = (raw_y - target_mean) * 10_000.0

        train_end = _end_indices(frame.index, valid_end, None, training_end, raw_y)
        validation = _end_indices(
            frame.index,
            valid_end,
            validation_start,
            validation_end,
            raw_y,
        )
        prediction = _end_indices(
            frame.index,
            valid_end,
            prediction_start,
            prediction_end,
            None,
        )
        if len(train_end) < config.minimum_training_sequences_per_asset:
            raise ValueError(f"{asset} has only {len(train_end)} LSTM training sequences")
        if not len(validation):
            raise ValueError(f"{asset} has no LSTM validation sequences")

        tensor_x = torch.from_numpy(np.nan_to_num(standardized, nan=0.0).astype(np.float32))
        windows = tensor_x.unfold(0, config.sequence_length, 1).permute(0, 2, 1)
        target = torch.from_numpy(centered_target_bps[config.sequence_length - 1 :])
        prepared[asset] = {
            "windows": windows,
            "target": target,
            "train_indices": train_end - (config.sequence_length - 1),
            "validation_indices": validation - (config.sequence_length - 1),
            "prediction_indices": prediction - (config.sequence_length - 1),
            "prediction_end_indices": prediction,
            "mean": mean,
            "scale": scale,
            "target_mean": target_mean,
        }
    return prepared


def _training_batches(
    prepared: dict[str, dict[str, object]],
    batch_size: int,
    seed: int,
) -> list[tuple[str, np.ndarray]]:
    rng = np.random.default_rng(seed)
    batches: list[tuple[str, np.ndarray]] = []
    for asset, record in prepared.items():
        indices = np.asarray(record["train_indices"], dtype=np.int64)
        shuffled = rng.permutation(indices)
        batches.extend(
            (asset, shuffled[start : start + batch_size])
            for start in range(0, len(shuffled), batch_size)
        )
    rng.shuffle(batches)
    return batches


def _validation_loss(
    model: MediumLSTM,
    prepared: dict[str, dict[str, object]],
    loss_function: nn.Module,
    batch_size: int,
    device: str,
) -> float:
    model.eval()
    total_loss = 0.0
    total_rows = 0
    with torch.no_grad():
        for record in prepared.values():
            indices = np.asarray(record["validation_indices"], dtype=np.int64)
            for start in range(0, len(indices), batch_size):
                batch = indices[start : start + batch_size]
                sequence = record["windows"][batch].to(device)
                target = record["target"][batch].to(device)
                loss = loss_function(model(sequence), target)
                total_loss += float(loss) * len(batch)
                total_rows += len(batch)
    return total_loss / total_rows if total_rows else float("inf")


def _predict(
    model: MediumLSTM,
    prepared: dict[str, dict[str, object]],
    frames: dict[str, pd.DataFrame],
    batch_size: int,
    device: str,
) -> dict[str, pd.Series]:
    model.eval()
    output: dict[str, pd.Series] = {}
    with torch.no_grad():
        for asset, record in prepared.items():
            indices = np.asarray(record["prediction_indices"], dtype=np.int64)
            values: list[np.ndarray] = []
            for start in range(0, len(indices), batch_size):
                batch = indices[start : start + batch_size]
                prediction_bps = model(record["windows"][batch].to(device))
                values.append(prediction_bps.detach().cpu().numpy())
            series = pd.Series(np.nan, index=frames[asset].index, dtype=float, name="lstm_prediction")
            end_indices = np.asarray(record["prediction_end_indices"], dtype=np.int64)
            if values:
                series.iloc[end_indices] = np.concatenate(values) / 10_000.0
            output[asset] = series
    return output


def _end_indices(
    index: pd.DatetimeIndex,
    valid_end: np.ndarray,
    start: pd.Timestamp | None,
    end: pd.Timestamp,
    target: np.ndarray | None,
) -> np.ndarray:
    mask = index[valid_end] <= end
    if start is not None:
        mask &= index[valid_end] >= start
    if target is not None:
        mask &= np.isfinite(target[valid_end])
    return valid_end[mask]


def _validate_columns(
    frames: dict[str, pd.DataFrame],
    feature_columns: tuple[str, ...],
) -> None:
    if not frames:
        raise ValueError("features_by_asset cannot be empty")
    missing = {
        asset: [column for column in (*feature_columns, TARGET_COLUMN) if column not in frame]
        for asset, frame in frames.items()
    }
    missing = {asset: columns for asset, columns in missing.items() if columns}
    if missing:
        raise ValueError(f"missing LSTM columns: {missing}")


def _timestamp(
    value: str | pd.Timestamp,
    frames: dict[str, pd.DataFrame],
) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    timezone = next(iter(frames.values())).index.tz
    if timestamp.tz is None:
        timestamp = timestamp.tz_localize(timezone)
    return timestamp


def _set_seed(seed: int) -> None:
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
