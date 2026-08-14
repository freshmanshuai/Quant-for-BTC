"""Run the minimal RSI/EMA/volume/ATR linear-model experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from quant_btc.simple_ml import (
    ATR_FEATURE,
    EMA_FEATURE,
    RSI_FEATURE,
    VOLUME_FEATURE,
    SimpleMLConfig,
    build_simple_ml_features,
    ema_trend_baseline_positions,
    pooled_walk_forward_ridge,
    positions_from_prediction,
    simulate_open_boundary_strategy,
)
from quant_platform.data import clean_ohlcv_bars


ASSETS = ("BTC", "ETH", "SOL")
FEATURE_COLUMNS = {
    "ridge_ema": (EMA_FEATURE,),
    "ridge_ema_rsi": (EMA_FEATURE, RSI_FEATURE),
    "ridge_ema_rsi_volume": (EMA_FEATURE, RSI_FEATURE, VOLUME_FEATURE),
    "ridge_ema_rsi_volume_atr": (
        EMA_FEATURE,
        RSI_FEATURE,
        VOLUME_FEATURE,
        ATR_FEATURE,
    ),
}
PARENTS = {
    "ema_trend_rule": None,
    "ridge_ema": "ema_trend_rule",
    "ridge_ema_rsi": "ridge_ema",
    "ridge_ema_rsi_volume": "ridge_ema_rsi",
    "ridge_ema_rsi_volume_atr": "ridge_ema_rsi_volume",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--protocol", type=Path, default=Path("config/simple_ml_protocol.json")
    )
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        default=Path("audit_artifacts/backtest_research_20260715/data_snapshots"),
    )
    parser.add_argument("--derivatives-root", type=Path, default=Path("data/derivatives"))
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


def _paired_deltas(scorecard: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    metrics = ("total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe", "calmar")
    for _, candidate in scorecard.iterrows():
        parent = candidate["parent"]
        if not isinstance(parent, str) or not parent:
            continue
        baseline = scorecard[
            (scorecard["asset"] == candidate["asset"])
            & (scorecard["variant"] == parent)
            & (scorecard["split"] == candidate["split"])
        ]
        if baseline.empty:
            continue
        reference = baseline.iloc[0]
        row = {
            "asset": candidate["asset"],
            "variant": candidate["variant"],
            "parent": parent,
            "split": candidate["split"],
        }
        for metric in metrics:
            left = candidate[metric]
            right = reference[metric]
            row[f"delta_{metric}"] = left - right if pd.notna(left) and pd.notna(right) else None
        rows.append(row)
    return pd.DataFrame(rows)


def _forecast_diagnostics(
    score: pd.Series,
    realized: pd.Series,
    start: str,
    end: str,
) -> dict[str, float | None]:
    paired = pd.concat(
        [score.rename("score"), realized.rename("realized")], axis=1
    ).loc[start:end].replace([float("inf"), float("-inf")], pd.NA).dropna()
    if len(paired) < 2:
        return {"spearman_ic": None, "directional_accuracy": None}
    ranked_score = paired["score"].rank(method="average")
    ranked_realized = paired["realized"].rank(method="average")
    return {
        "spearman_ic": float(ranked_score.corr(ranked_realized)),
        "directional_accuracy": float(
            ((paired["score"] > 0) == (paired["realized"] > 0)).mean()
        ),
    }


def main() -> None:
    args = parse_args()
    protocol_bytes = args.protocol.read_bytes()
    protocol = json.loads(protocol_bytes.decode("utf-8"))
    model = protocol["model"]
    feature_config = protocol["features"]
    execution = protocol["execution"]
    config = SimpleMLConfig(
        ema_period=int(feature_config["ema_period"]),
        rsi_period=int(feature_config["rsi_period"]),
        volume_period=int(feature_config["volume_period"]),
        atr_period=int(feature_config["atr_period"]),
        prediction_horizon_bars=int(model["prediction_horizon_bars"]),
        ridge_alpha=float(model["ridge_alpha"]),
        minimum_training_rows_per_asset=int(model["minimum_training_rows_per_asset"]),
        bar_interval="15min" if protocol["timeframe"] == "15m" else protocol["timeframe"],
        entry_threshold=float(execution["entry_threshold"]),
    )
    split_map = {
        "validation": protocol["validation"],
        "research_holdout": protocol["research_holdout"],
    }

    bars_by_asset: dict[str, pd.DataFrame] = {}
    features_by_asset: dict[str, pd.DataFrame] = {}
    funding_by_asset: dict[str, pd.DataFrame] = {}
    data_hashes: dict[str, str] = {}
    for asset in ASSETS:
        bars_path = args.snapshot_root / f"binance_usdm_{asset}USDT_15m_through_2026-06.pkl"
        funding_path = args.derivatives_root / f"{asset}USDT_funding.csv"
        bars = clean_ohlcv_bars(_load_frame(bars_path), "15min", require_contiguous=True)
        bars_by_asset[asset] = bars
        features_by_asset[asset] = build_simple_ml_features(bars, config)
        funding_by_asset[asset] = _load_frame(funding_path)
        data_hashes[f"{asset}:ohlcv"] = _file_hash(bars_path)
        data_hashes[f"{asset}:funding"] = _file_hash(funding_path)

    prediction_start = protocol["validation"][0]
    prediction_end = protocol["research_holdout"][1]
    predictions: dict[str, dict[str, pd.Series]] = {}
    coefficient_frames: list[pd.DataFrame] = []
    for variant, columns in FEATURE_COLUMNS.items():
        result = pooled_walk_forward_ridge(
            features_by_asset,
            columns,
            prediction_start=prediction_start,
            prediction_end=prediction_end,
            config=config,
        )
        predictions[variant] = result.predictions
        coefficients = result.coefficients.copy()
        coefficients.insert(0, "variant", variant)
        coefficient_frames.append(coefficients)

    rows: list[dict[str, object]] = []
    for split, (start, end) in split_map.items():
        for asset in ASSETS:
            targets = {
                "ema_trend_rule": ema_trend_baseline_positions(bars_by_asset[asset])
            }
            targets.update(
                {
                    variant: positions_from_prediction(
                        predictions[variant][asset], config.entry_threshold
                    )
                    for variant in FEATURE_COLUMNS
                }
            )
            for variant, target in targets.items():
                metrics = simulate_open_boundary_strategy(
                    bars_by_asset[asset],
                    target,
                    start=start,
                    end=end,
                    fee_rate_per_fill=float(execution["fee_rate_per_fill"]),
                    slippage_bps_per_fill=float(execution["slippage_bps_per_fill"]),
                    funding=funding_by_asset[asset],
                    bar_interval=config.bar_interval,
                )
                forecast_score = (
                    targets["ema_trend_rule"]
                    if variant == "ema_trend_rule"
                    else predictions[variant][asset]
                )
                forecast = _forecast_diagnostics(
                    forecast_score,
                    features_by_asset[asset]["_ml_forward_open_return"],
                    start,
                    end,
                )
                rows.append(
                    {
                        "asset": asset,
                        "variant": variant,
                        "parent": PARENTS[variant],
                        "split": split,
                        **metrics,
                        **forecast,
                    }
                )

    args.output.mkdir(parents=True, exist_ok=True)
    scorecard = pd.DataFrame(rows)
    scorecard.to_csv(args.output / "scorecard.csv", index=False)
    _paired_deltas(scorecard).to_csv(args.output / "paired_delta.csv", index=False)
    pd.concat(coefficient_frames, ignore_index=True).to_csv(
        args.output / "coefficients.csv", index=False
    )

    final_variant = "ridge_ema_rsi_volume_atr"
    decisions: list[dict[str, object]] = []
    rule = protocol["promotion_rule"]
    for split in split_map:
        candidate = scorecard[(scorecard["variant"] == final_variant) & (scorecard["split"] == split)]
        baseline = scorecard[(scorecard["variant"] == "ema_trend_rule") & (scorecard["split"] == split)].set_index("asset")
        profitable_assets = int((candidate["total_return_pct"] > 0).sum())
        adequate_assets = int(
            (candidate["round_trip_equivalents"] >= float(rule["minimum_round_trip_equivalents_per_asset"])).sum()
        )
        beats_baseline_calmar = sum(
            pd.notna(row.calmar)
            and pd.notna(baseline.loc[row.asset, "calmar"])
            and row.calmar > baseline.loc[row.asset, "calmar"]
            for row in candidate.itertuples()
        )
        passed = (
            profitable_assets >= int(rule["minimum_profitable_assets"])
            and beats_baseline_calmar >= int(rule["minimum_assets_beating_ema_baseline_calmar"])
            and adequate_assets == len(ASSETS)
        )
        decisions.append(
            {
                "variant": final_variant,
                "split": split,
                "profitable_assets": profitable_assets,
                "assets_beating_ema_baseline_calmar": beats_baseline_calmar,
                "assets_with_minimum_trades": adequate_assets,
                "passed": passed,
            }
        )
    pd.DataFrame(decisions).to_csv(args.output / "gate_decision.csv", index=False)

    code_paths = [Path("quant_btc/simple_ml.py"), Path("scripts/run_simple_ml_intraday.py")]
    manifest = {
        "protocol": protocol,
        "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
        "data_sha256": data_hashes,
        "code_sha256": {str(path): _file_hash(path) for path in code_paths},
        "execution_limit": "15m next-open proxy; no tick, spread, depth, impact, or 15m mark archive",
        "selection_status": "research_only",
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(scorecard.to_string(index=False))


if __name__ == "__main__":
    main()
