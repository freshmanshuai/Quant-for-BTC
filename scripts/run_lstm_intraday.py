"""Train and evaluate the requested medium LSTM on BTC/ETH/SOL."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from quant_btc.lstm_model import LSTMConfig, build_lstm_features, train_predict_lstm
from quant_btc.simple_ml import (
    SimpleMLConfig,
    ema_trend_baseline_positions,
    pooled_walk_forward_ridge,
    positions_from_prediction,
    simulate_open_boundary_strategy,
)
from quant_platform.data import clean_ohlcv_bars


ASSETS = ("BTC", "ETH", "SOL")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, default=Path("config/lstm_protocol.json"))
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        default=Path("audit_artifacts/backtest_research_20260715/data_snapshots"),
    )
    parser.add_argument("--derivatives-root", type=Path, default=Path("data/derivatives"))
    parser.add_argument("--variants", default="")
    parser.add_argument("--splits", default="")
    parser.add_argument("--seeds", default="")
    parser.add_argument("--device", default="")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _load_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_pickle(path) if path.suffix.lower() in {".pkl", ".pickle"} else pd.read_csv(path, index_col=0)
    frame.index = pd.to_datetime(frame.index, format="mixed", utc=True)
    return frame.sort_index()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _config(protocol: dict[str, object]) -> LSTMConfig:
    features = protocol["features"]
    model = protocol["model"]
    return LSTMConfig(
        ema_periods=tuple(int(value) for value in features["ema_periods"]),
        rsi_period=int(features["rsi_period"]),
        atr_period=int(features["atr_period"]),
        volume_period=int(features["volume_period"]),
        boll_period=int(features["boll_period"]),
        boll_std=float(features["boll_std"]),
        level_lookback=int(features["level_lookback"]),
        prediction_horizon_bars=int(model["prediction_horizon_bars"]),
        sequence_length=int(model["sequence_length"]),
        hidden_size=int(model["hidden_size"]),
        num_layers=int(model["num_layers"]),
        dropout=float(model["dropout"]),
        head_size=int(model["head_size"]),
        batch_size=int(model["batch_size"]),
        prediction_batch_size=int(model["prediction_batch_size"]),
        learning_rate=float(model["learning_rate"]),
        weight_decay=float(model["weight_decay"]),
        max_epochs=int(model["max_epochs"]),
        patience=int(model["patience"]),
        validation_days=int(model["validation_days"]),
        huber_delta_bps=float(model["huber_delta_bps"]),
        minimum_training_sequences_per_asset=int(
            model["minimum_training_sequences_per_asset"]
        ),
        bar_interval="15min" if protocol["timeframe"] == "15m" else protocol["timeframe"],
    )


def _forecast_diagnostics(
    score: pd.Series,
    realized: pd.Series,
    start: str,
    end: str,
) -> dict[str, float | None]:
    paired = pd.concat([score.rename("score"), realized.rename("realized")], axis=1)
    paired = paired.loc[start:end].replace([np.inf, -np.inf], np.nan).dropna()
    if len(paired) < 2:
        return {
            "spearman_ic": None,
            "directional_accuracy": None,
            "prediction_mean_bps": None,
            "prediction_std_bps": None,
            "prediction_p05_bps": None,
            "prediction_p95_bps": None,
        }
    return {
        "spearman_ic": float(paired["score"].rank().corr(paired["realized"].rank())),
        "directional_accuracy": float(
            ((paired["score"] > 0) == (paired["realized"] > 0)).mean()
        ),
        "prediction_mean_bps": 10_000.0 * float(paired["score"].mean()),
        "prediction_std_bps": 10_000.0 * float(paired["score"].std(ddof=0)),
        "prediction_p05_bps": 10_000.0 * float(paired["score"].quantile(0.05)),
        "prediction_p95_bps": 10_000.0 * float(paired["score"].quantile(0.95)),
    }


def _evaluate(
    bars: pd.DataFrame,
    features: pd.DataFrame,
    funding: pd.DataFrame,
    prediction: pd.Series,
    *,
    start: str,
    end: str,
    execution: dict[str, object],
    config: LSTMConfig,
) -> dict[str, float | int | None]:
    metrics = simulate_open_boundary_strategy(
        bars,
        positions_from_prediction(prediction, float(execution["entry_threshold"])),
        start=start,
        end=end,
        fee_rate_per_fill=float(execution["fee_rate_per_fill"]),
        slippage_bps_per_fill=float(execution["slippage_bps_per_fill"]),
        funding=funding,
        bar_interval=config.bar_interval,
    )
    return {**metrics, **_forecast_diagnostics(prediction, features["_ml_forward_open_return"], start, end)}


def main() -> None:
    args = parse_args()
    protocol_bytes = args.protocol.read_bytes()
    protocol = json.loads(protocol_bytes.decode("utf-8"))
    config = _config(protocol)
    declared_variants = {key: tuple(value) for key, value in protocol["variants"].items()}
    variants = args.variants.split(",") if args.variants else list(declared_variants)
    splits = args.splits.split(",") if args.splits else ["validation", "research_holdout"]
    seeds = (
        [int(value) for value in args.seeds.split(",")]
        if args.seeds
        else [int(value) for value in protocol["model"]["seeds"]]
    )
    unknown_variants = sorted(set(variants).difference(declared_variants))
    unknown_splits = sorted(set(splits).difference({"validation", "research_holdout"}))
    if unknown_variants or unknown_splits:
        raise ValueError(f"unknown variants={unknown_variants}, splits={unknown_splits}")
    if len(seeds) < 1:
        raise ValueError("at least one seed is required")
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    execution = protocol["execution"]

    bars_by_asset: dict[str, pd.DataFrame] = {}
    features_by_asset: dict[str, pd.DataFrame] = {}
    funding_by_asset: dict[str, pd.DataFrame] = {}
    data_hashes: dict[str, str] = {}
    for asset in ASSETS:
        bars_path = args.snapshot_root / f"binance_usdm_{asset}USDT_15m_through_2026-06.pkl"
        funding_path = args.derivatives_root / f"{asset}USDT_funding.csv"
        bars = clean_ohlcv_bars(_load_frame(bars_path), "15min", require_contiguous=True)
        bars_by_asset[asset] = bars
        features_by_asset[asset] = build_lstm_features(bars, config)
        funding_by_asset[asset] = _load_frame(funding_path)
        data_hashes[f"{asset}:ohlcv"] = _file_hash(bars_path)
        data_hashes[f"{asset}:funding"] = _file_hash(funding_path)

    args.output.mkdir(parents=True, exist_ok=True)
    models_dir = args.output / "models"
    models_dir.mkdir(exist_ok=True)
    seed_rows: list[dict[str, object]] = []
    ensemble_rows: list[dict[str, object]] = []
    training_rows: list[dict[str, object]] = []
    ensemble_predictions: dict[tuple[str, str, str], pd.Series] = {}

    for split in splits:
        definition = protocol[split]
        for variant in variants:
            seed_predictions: dict[str, list[pd.Series]] = {asset: [] for asset in ASSETS}
            columns = declared_variants[variant]
            for seed in seeds:
                result = train_predict_lstm(
                    features_by_asset,
                    columns,
                    training_cutoff=definition["training_cutoff"],
                    prediction_start=definition["start"],
                    prediction_end=definition["end"],
                    seed=seed,
                    config=config,
                    device=device,
                )
                checkpoint = {
                    "state_dict": result.state_dict,
                    "preprocessing": result.preprocessing,
                    "feature_columns": columns,
                    "config": config.__dict__,
                    "split": split,
                    "variant": variant,
                    "diagnostics": result.diagnostics,
                }
                torch.save(checkpoint, models_dir / f"{split}_{variant}_seed{seed}.pt")
                training_rows.append({"split": split, "variant": variant, **result.diagnostics})
                for asset in ASSETS:
                    prediction = result.predictions[asset]
                    seed_predictions[asset].append(prediction)
                    metrics = _evaluate(
                        bars_by_asset[asset],
                        features_by_asset[asset],
                        funding_by_asset[asset],
                        prediction,
                        start=definition["start"],
                        end=definition["end"],
                        execution=execution,
                        config=config,
                    )
                    seed_rows.append(
                        {
                            "asset": asset,
                            "variant": variant,
                            "split": split,
                            "seed": seed,
                            **metrics,
                        }
                    )
            for asset in ASSETS:
                median_prediction = pd.concat(seed_predictions[asset], axis=1).median(
                    axis=1, skipna=True
                )
                ensemble_predictions[(split, variant, asset)] = median_prediction
                metrics = _evaluate(
                    bars_by_asset[asset],
                    features_by_asset[asset],
                    funding_by_asset[asset],
                    median_prediction,
                    start=definition["start"],
                    end=definition["end"],
                    execution=execution,
                    config=config,
                )
                ensemble_rows.append(
                    {
                        "asset": asset,
                        "variant": variant,
                        "parent": {
                            "lstm_core": "ridge_same_features",
                            "lstm_core_boll": "lstm_core",
                            "lstm_full": "lstm_core_boll",
                        }.get(variant),
                        "split": split,
                        **metrics,
                    }
                )
            print(split, variant, "complete")

    prediction_start = protocol["validation"]["start"]
    prediction_end = protocol["research_holdout"]["end"]
    full_columns = declared_variants["lstm_full"]
    ridge = pooled_walk_forward_ridge(
        features_by_asset,
        full_columns,
        prediction_start=prediction_start,
        prediction_end=prediction_end,
        config=SimpleMLConfig(
            prediction_horizon_bars=config.prediction_horizon_bars,
            minimum_training_rows_per_asset=config.minimum_training_sequences_per_asset,
            bar_interval=config.bar_interval,
            entry_threshold=float(execution["entry_threshold"]),
        ),
    )
    for split in splits:
        definition = protocol[split]
        for asset in ASSETS:
            baselines = {
                "ema_trend_rule": ema_trend_baseline_positions(bars_by_asset[asset]),
                "ridge_same_features": ridge.predictions[asset],
            }
            for variant, prediction in baselines.items():
                if variant == "ema_trend_rule":
                    target = prediction
                    metrics = simulate_open_boundary_strategy(
                        bars_by_asset[asset],
                        target,
                        start=definition["start"],
                        end=definition["end"],
                        fee_rate_per_fill=float(execution["fee_rate_per_fill"]),
                        slippage_bps_per_fill=float(execution["slippage_bps_per_fill"]),
                        funding=funding_by_asset[asset],
                        bar_interval=config.bar_interval,
                    )
                    metrics.update(
                        _forecast_diagnostics(
                            prediction,
                            features_by_asset[asset]["_ml_forward_open_return"],
                            definition["start"],
                            definition["end"],
                        )
                    )
                else:
                    metrics = _evaluate(
                        bars_by_asset[asset],
                        features_by_asset[asset],
                        funding_by_asset[asset],
                        prediction,
                        start=definition["start"],
                        end=definition["end"],
                        execution=execution,
                        config=config,
                    )
                ensemble_rows.append(
                    {
                        "asset": asset,
                        "variant": variant,
                        "parent": None if variant == "ema_trend_rule" else "ema_trend_rule",
                        "split": split,
                        **metrics,
                    }
                )

    scorecard = pd.DataFrame(ensemble_rows)
    seed_scorecard = pd.DataFrame(seed_rows)
    scorecard.to_csv(args.output / "scorecard.csv", index=False)
    seed_scorecard.to_csv(args.output / "seed_scorecard.csv", index=False)
    pd.DataFrame(training_rows).to_csv(args.output / "training_diagnostics.csv", index=False)
    ridge.coefficients.to_csv(args.output / "ridge_coefficients.csv", index=False)

    decisions: list[dict[str, object]] = []
    rule = protocol["promotion_rule"]
    for split in splits:
        candidate = scorecard[
            (scorecard["variant"] == "lstm_full") & (scorecard["split"] == split)
        ]
        ridge_rows = scorecard[
            (scorecard["variant"] == "ridge_same_features")
            & (scorecard["split"] == split)
        ].set_index("asset")
        profitable_assets = int((candidate["total_return_pct"] > 0).sum())
        beats_ridge = sum(
            pd.notna(row.calmar)
            and pd.notna(ridge_rows.loc[row.asset, "calmar"])
            and row.calmar > ridge_rows.loc[row.asset, "calmar"]
            for row in candidate.itertuples()
        )
        stable_assets = 0
        for asset in ASSETS:
            outcomes = seed_scorecard[
                (seed_scorecard["variant"] == "lstm_full")
                & (seed_scorecard["split"] == split)
                & (seed_scorecard["asset"] == asset)
            ]["total_return_pct"]
            if len(outcomes) >= int(rule["minimum_seeds"]) and float(outcomes.median()) > 0:
                stable_assets += 1
        adequate_assets = int(
            (
                candidate["round_trip_equivalents"]
                >= float(rule["minimum_round_trip_equivalents_per_asset"])
            ).sum()
        )
        passed = (
            profitable_assets >= int(rule["minimum_profitable_assets"])
            and beats_ridge
            >= int(rule["minimum_assets_beating_same_feature_ridge_calmar"])
            and stable_assets >= int(rule["minimum_profitable_assets"])
            and adequate_assets == len(ASSETS)
        )
        decisions.append(
            {
                "variant": "lstm_full",
                "split": split,
                "profitable_assets": profitable_assets,
                "assets_beating_same_feature_ridge_calmar": beats_ridge,
                "assets_with_positive_seed_median": stable_assets,
                "assets_with_minimum_trades": adequate_assets,
                "passed": passed,
            }
        )
    pd.DataFrame(decisions).to_csv(args.output / "gate_decision.csv", index=False)

    code_paths = [
        Path("quant_btc/lstm_model.py"),
        Path("quant_btc/simple_ml.py"),
        Path("scripts/run_lstm_intraday.py"),
    ]
    manifest = {
        "protocol": protocol,
        "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
        "data_sha256": data_hashes,
        "code_sha256": {str(path): _file_hash(path) for path in code_paths},
        "torch_version": torch.__version__,
        "device": device,
        "variants": variants,
        "splits": splits,
        "seeds": seeds,
        "selection_status": "research_only",
        "execution_limit": "15m next-open and contract-price proxy; no tick/order-book/15m mark",
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(scorecard.to_string(index=False))


if __name__ == "__main__":
    main()
