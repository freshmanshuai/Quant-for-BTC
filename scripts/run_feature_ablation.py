"""Run pre-registered BTC/ETH/SOL continuous-feature ablations."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import pandas as pd

from quant_btc.retained_strategy import (
    BearTrendModule,
    CoreTrendModule,
    PullbackLongModule,
    RetainedStrategyConfig,
    prepare_retained_features,
    validate_funding_coverage,
)
from quant_platform.backtest import BacktestExecutionConfig, EventDrivenBacktest
from quant_platform.core import AssetSpec, MarketSpec
from quant_platform.data import clean_ohlcv_bars
from quant_platform.pipeline import SignalPipeline
from quant_platform.portfolio import PortfolioEngine
from quant_platform.risk import AccountState, RiskEngine, RiskLimits
from quant_platform.signal_modules import SignalModuleRunner


ASSET_FILES = {
    "BTC": "binance_usdm_BTCUSDT_4h_through_2026-06.pkl",
    "ETH": "binance_usdm_ETHUSDT_4h_through_2026-06.pkl",
    "SOL": "binance_usdm_SOLUSDT_4h_through_2026-06.pkl",
}

VARIANTS = {
    "baseline_full": {"parent": None, "trend_model": "ema", "features": (), "pullback": True},
    "ema_core_bear": {
        "parent": "baseline_full",
        "trend_model": "ema",
        "features": (),
        "pullback": False,
    },
    "sequence_core_bear": {
        "parent": "ema_core_bear",
        "trend_model": "sequence",
        "features": (),
        "pullback": False,
    },
    "sequence_support_resistance": {
        "parent": "sequence_core_bear",
        "trend_model": "sequence",
        "features": ("support_resistance",),
        "pullback": False,
    },
    "sequence_jump_risk": {
        "parent": "sequence_core_bear",
        "trend_model": "sequence",
        "features": ("jump_risk",),
        "pullback": False,
    },
    "ema_continuous_strength": {
        "parent": "baseline_full",
        "trend_model": "ema",
        "features": ("ema_strength",),
        "pullback": True,
    },
    "ema_support_resistance": {
        "parent": "baseline_full",
        "trend_model": "ema",
        "features": ("support_resistance",),
        "pullback": True,
    },
    "ema_jump_risk": {
        "parent": "baseline_full",
        "trend_model": "ema",
        "features": ("jump_risk",),
        "pullback": True,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--protocol", type=Path, default=Path("config/feature_research_protocol.json")
    )
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        default=Path("audit_artifacts/backtest_research_20260715/data_snapshots"),
    )
    parser.add_argument("--derivatives-root", type=Path, default=Path("data/derivatives"))
    parser.add_argument("--variants", default=",".join(VARIANTS))
    parser.add_argument("--splits", default="validation")
    parser.add_argument("--leverages", default="1")
    parser.add_argument("--cash", type=float, default=100_000.0)
    parser.add_argument("--risk-scale-mode", choices=("fixed", "linear"), default="fixed")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-price-only-proxy", action="store_true")
    return parser.parse_args()


def _load_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".pkl", ".pickle"}:
        frame = pd.read_pickle(path)
    else:
        frame = pd.read_csv(path, index_col=0)
    frame.index = pd.to_datetime(frame.index, format="mixed", utc=True)
    return frame.sort_index()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _variant_config(name: str) -> tuple[RetainedStrategyConfig, list[object]]:
    definition = VARIANTS[name]
    config = RetainedStrategyConfig(
        trend_model=str(definition["trend_model"]),
        confidence_features=tuple(definition["features"]),
    )
    modules: list[object] = [CoreTrendModule(config), BearTrendModule(config)]
    if bool(definition["pullback"]):
        modules.append(PullbackLongModule(config))
    return config, modules


def _load_derivatives(root: Path, asset: str) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    symbol = f"{asset}USDT"
    funding_path = root / f"{symbol}_funding.csv"
    mark_path = root / f"{symbol}_mark_4h.csv"
    funding = _load_frame(funding_path) if funding_path.exists() else None
    marks = _load_frame(mark_path) if mark_path.exists() else None
    return funding, marks


def _attach_marks(features: pd.DataFrame, marks: pd.DataFrame | None) -> tuple[pd.DataFrame, int]:
    out = features.copy()
    fallbacks = 0
    mapping = {
        "MarkOpen": "Open",
        "MarkHigh": "High",
        "MarkLow": "Low",
        "MarkClose": "Close",
    }
    for mark_column, fallback_column in mapping.items():
        aligned = (
            pd.to_numeric(marks[mark_column], errors="coerce").reindex(out.index)
            if marks is not None and mark_column in marks
            else pd.Series(index=out.index, dtype=float)
        )
        if mark_column == "MarkOpen":
            fallbacks = int(aligned.isna().sum())
        out[mark_column] = aligned.fillna(pd.to_numeric(out[fallback_column], errors="coerce"))
    return out, fallbacks


def _pipeline(
    symbol: str,
    leverage: float,
    modules: list[object],
    market: MarketSpec,
    *,
    risk_scale_mode: str,
) -> SignalPipeline:
    markets = {symbol: market}
    risk_scale = leverage if risk_scale_mode == "linear" else 1.0
    return SignalPipeline(
        signal_runner=SignalModuleRunner(modules),
        risk_engine=RiskEngine(
            RiskLimits(
                risk_per_trade=0.01 * risk_scale,
                max_position_fraction=1.0,
                max_leverage=leverage,
                enforce_initial_margin=True,
                use_signal_confidence=True,
                portfolio_risk_budget=0.02 * risk_scale,
                max_module_risk=0.01 * risk_scale,
                module_risk_multipliers={"bear_core": 0.5, "pullback_long": 0.35},
            ),
            markets_by_symbol=markets,
        ),
        portfolio_engine=PortfolioEngine(
            layer_by_module={
                "core_long": "core",
                "bear_core": "core",
                "pullback_long": "tactical",
            },
            markets_by_symbol=markets,
            allow_hedging=False,
            max_positions_per_symbol=2,
            close_on_opposite_signal=True,
            precreate_positions=False,
        ),
        markets_by_symbol=markets,
    )


def _metrics(
    result,
    *,
    asset: str,
    variant: str,
    split: str,
    leverage: float,
    risk_scale_mode: str,
    mark_proxy_bars: int,
    bar_count: int,
):
    summary = result.performance_summary
    equity = pd.Series(
        [point.equity for point in result.equity_curve],
        index=pd.DatetimeIndex([point.timestamp for point in result.equity_curve]),
        dtype=float,
    )
    daily = equity.resample("1D").last().dropna()
    daily_returns = daily.pct_change().dropna()
    volatility = float(daily_returns.std(ddof=1)) if len(daily_returns) > 1 else 0.0
    sharpe = (
        float(daily_returns.mean() / volatility * math.sqrt(365.0)) if volatility > 0 else None
    )
    downside = daily_returns[daily_returns < 0]
    downside_volatility = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    sortino = (
        float(daily_returns.mean() / downside_volatility * math.sqrt(365.0))
        if downside_volatility > 0
        else None
    )
    elapsed_days = max((equity.index.max() - equity.index.min()).total_seconds() / 86400.0, 1.0)
    if summary.final_equity > 0:
        cagr = (summary.final_equity / summary.initial_equity) ** (365.0 / elapsed_days) - 1.0
    else:
        cagr = -1.0
    calmar = cagr / summary.max_drawdown_pct if summary.max_drawdown_pct > 0 else None
    peak_gross_leverage = max(
        (
            exposure.gross_notional / point.equity
            if point.equity > 0
            else float("inf")
        )
        for exposure, point in zip(result.exposure_curve, result.equity_curve)
    )
    margin_ratios = [
        point.available_margin / point.equity
        for point in result.equity_curve
        if point.equity > 0
    ]
    profitable = sorted((trade.net_pnl for trade in result.trades if trade.net_pnl > 0), reverse=True)
    total_profit = sum(profitable)
    return {
        "asset": asset,
        "variant": variant,
        "parent": VARIANTS[variant]["parent"],
        "split": split,
        "configured_leverage": leverage,
        "risk_scale_mode": risk_scale_mode,
        "start": str(equity.index.min()),
        "end": str(equity.index.max()),
        "bars": bar_count,
        "equity_points": len(equity),
        "final_equity": summary.final_equity,
        "total_return_pct": 100.0 * summary.total_return_pct,
        "cagr_pct": 100.0 * cagr,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown_pct": 100.0 * summary.max_drawdown_pct,
        "calmar": calmar,
        "trade_count": summary.trade_count,
        "win_rate_pct": 100.0 * summary.win_rate,
        "profit_factor": summary.profit_factor,
        "turnover_ratio": summary.realized_turnover_ratio,
        "fees_paid": summary.fees_paid,
        "funding_paid": summary.funding_paid,
        "liquidation_count": result.liquidation_count,
        "liquidation_fees_paid": result.liquidation_fees_paid,
        "peak_gross_leverage": peak_gross_leverage,
        "min_available_margin_ratio": min(margin_ratios) if margin_ratios else None,
        "top1_profit_concentration": profitable[0] / total_profit if total_profit else None,
        "top5_profit_concentration": sum(profitable[:5]) / total_profit if total_profit else None,
        "mark_proxy_bars": mark_proxy_bars,
    }


def _paired_deltas(scorecard: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    metrics = ("cagr_pct", "sharpe", "max_drawdown_pct", "calmar", "total_return_pct")
    for _, candidate in scorecard.iterrows():
        parent = candidate["parent"]
        if not isinstance(parent, str) or not parent:
            continue
        match = scorecard[
            (scorecard["asset"] == candidate["asset"])
            & (scorecard["variant"] == parent)
            & (scorecard["split"] == candidate["split"])
            & (scorecard["configured_leverage"] == candidate["configured_leverage"])
            & (scorecard["risk_scale_mode"] == candidate["risk_scale_mode"])
        ]
        if match.empty:
            continue
        baseline = match.iloc[0]
        row = {
            "asset": candidate["asset"],
            "variant": candidate["variant"],
            "parent": parent,
            "split": candidate["split"],
            "configured_leverage": candidate["configured_leverage"],
            "risk_scale_mode": candidate["risk_scale_mode"],
        }
        for metric in metrics:
            left, right = candidate[metric], baseline[metric]
            row[f"delta_{metric}"] = left - right if pd.notna(left) and pd.notna(right) else None
        rows.append(row)
    return pd.DataFrame(rows)


def _gate_decisions(
    scorecard: pd.DataFrame,
    paired_delta: pd.DataFrame,
    promotion_rule: dict[str, object],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if paired_delta.empty:
        return pd.DataFrame(rows)
    group_columns = [
        "variant",
        "parent",
        "split",
        "configured_leverage",
        "risk_scale_mode",
    ]
    for keys, deltas in paired_delta.groupby(group_columns, dropna=False):
        variant, parent, split, leverage, risk_scale_mode = keys
        candidates = scorecard[
            (scorecard["variant"] == variant)
            & (scorecard["split"] == split)
            & (scorecard["configured_leverage"] == leverage)
            & (scorecard["risk_scale_mode"] == risk_scale_mode)
        ]
        positive_assets = int((deltas["delta_calmar"] > 0).sum())
        median_delta_calmar = float(deltas["delta_calmar"].median())
        worst_delta_cagr = float(deltas["delta_cagr_pct"].min())
        max_drawdown_deterioration = float(deltas["delta_max_drawdown_pct"].max())
        pooled_trades = int(candidates["trade_count"].sum())
        minimum_asset_trades = int(candidates["trade_count"].min())
        passed = (
            positive_assets >= int(promotion_rule["minimum_positive_assets"])
            and median_delta_calmar >= float(promotion_rule["median_delta_calmar"])
            and worst_delta_cagr
            >= float(promotion_rule["worst_delta_cagr_percentage_points"])
            and max_drawdown_deterioration
            <= float(
                promotion_rule["maximum_drawdown_deterioration_percentage_points"]
            )
            and pooled_trades >= int(promotion_rule["minimum_trades_pooled"])
            and minimum_asset_trades >= int(promotion_rule["minimum_trades_per_asset"])
        )
        rows.append(
            {
                "variant": variant,
                "parent": parent,
                "split": split,
                "configured_leverage": leverage,
                "risk_scale_mode": risk_scale_mode,
                "positive_delta_calmar_assets": positive_assets,
                "median_delta_calmar": median_delta_calmar,
                "worst_delta_cagr_pct_points": worst_delta_cagr,
                "max_drawdown_deterioration_pct_points": max_drawdown_deterioration,
                "pooled_trades": pooled_trades,
                "minimum_asset_trades": minimum_asset_trades,
                "passed": passed,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    protocol_bytes = args.protocol.read_bytes()
    protocol = json.loads(protocol_bytes.decode("utf-8"))
    split_map = {
        "development": protocol["development"],
        "validation": protocol["validation"],
        "research_holdout": protocol["research_holdout"],
    }
    variants = args.variants.split(",")
    unknown = [name for name in variants if name not in VARIANTS]
    if unknown:
        raise ValueError(f"unknown variants: {unknown}")
    splits = args.splits.split(",")
    leverages = [float(value) for value in args.leverages.split(",")]
    execution = protocol["execution"]
    rows: list[dict[str, object]] = []
    data_hashes: dict[str, str] = {}
    price_only_proxy = False
    mark_proxy_by_asset_split: dict[str, int] = {}

    for asset, filename in ASSET_FILES.items():
        bars_path = args.snapshot_root / filename
        data_hashes[asset] = _file_hash(bars_path)
        bars = clean_ohlcv_bars(_load_frame(bars_path), "4h", require_contiguous=True)
        funding, marks = _load_derivatives(args.derivatives_root, asset)
        price_only_proxy = price_only_proxy or funding is None or marks is None
        if (funding is None or marks is None) and not args.allow_price_only_proxy:
            raise ValueError(
                f"{asset} requires funding and mark history; use --allow-price-only-proxy to downgrade"
            )
        for variant in variants:
            strategy_config, modules = _variant_config(variant)
            features = prepare_retained_features(bars, funding, config=strategy_config)
            features, _ = _attach_marks(features, marks)
            for split in splits:
                start, end = split_map[split]
                evaluation = features.loc[start:end].copy()
                if evaluation.empty:
                    raise ValueError(f"empty {asset} {split} interval")
                if funding is not None:
                    validate_funding_coverage(evaluation, funding)
                mark_proxy_bars = int(
                    evaluation.index.difference(marks.index).size if marks is not None else len(evaluation)
                )
                mark_proxy_by_asset_split[f"{asset}:{split}"] = mark_proxy_bars
                price_only_proxy = price_only_proxy or mark_proxy_bars > 0
                if mark_proxy_bars and not args.allow_price_only_proxy:
                    raise ValueError(
                        f"{asset} {split} is missing {mark_proxy_bars} mark bars; "
                        "use --allow-price-only-proxy to disclose and permit fallback"
                    )
                for leverage in leverages:
                    symbol = f"{asset}/USDT"
                    market = MarketSpec(
                        asset=AssetSpec(symbol=symbol, base=asset, quote="USDT"),
                        exchange="binance",
                        market_type="swap",
                        fee_rate=float(execution["fee_rate_per_fill"]),
                        correlation_group="crypto_beta",
                        supports_short=True,
                        supports_leverage=True,
                        max_leverage=leverage,
                        maintenance_margin_rate=float(execution["maintenance_margin_rate"]),
                        maintenance_amount=float(execution["maintenance_amount"]),
                        liquidation_fee_rate=float(execution["liquidation_fee_rate"]),
                    )
                    engine = EventDrivenBacktest(
                        pipeline=_pipeline(
                            symbol,
                            leverage,
                            modules,
                            market,
                            risk_scale_mode=args.risk_scale_mode,
                        ),
                        account=AccountState(equity=args.cash),
                        execution=BacktestExecutionConfig(
                            slippage_bps=float(execution["slippage_bps_per_fill"]),
                            intrabar_stop_target=True,
                            fill_price_column="Open",
                            min_order_age_bars=1,
                            funding_rate_feature="funding_rate" if funding is not None else None,
                            funding_mark_price_feature="MarkOpen",
                            leverage=leverage,
                            maintenance_margin_rate=float(execution["maintenance_margin_rate"]),
                            maintenance_amount=float(execution["maintenance_amount"]),
                            liquidation_fee_rate=float(execution["liquidation_fee_rate"]),
                            mark_price_column="MarkOpen",
                            mark_close_column="MarkClose",
                            mark_high_column="MarkHigh",
                            mark_low_column="MarkLow",
                            finalize_positions=True,
                        ),
                        markets_by_symbol={symbol: market},
                    )
                    result = engine.run({symbol: evaluation})
                    rows.append(
                        _metrics(
                            result,
                            asset=asset,
                            variant=variant,
                            split=split,
                            leverage=leverage,
                            risk_scale_mode=args.risk_scale_mode,
                            mark_proxy_bars=mark_proxy_bars,
                            bar_count=len(evaluation),
                        )
                    )
                    print(asset, variant, split, leverage, rows[-1]["total_return_pct"])

    args.output.mkdir(parents=True, exist_ok=True)
    scorecard = pd.DataFrame(rows)
    scorecard.to_csv(args.output / "scorecard.csv", index=False)
    paired_delta = _paired_deltas(scorecard)
    paired_delta.to_csv(args.output / "paired_delta.csv", index=False)
    _gate_decisions(scorecard, paired_delta, protocol["promotion_rule"]).to_csv(
        args.output / "gate_decision.csv", index=False
    )
    derivative_manifest = args.derivatives_root / "manifest.json"
    code_paths = [
        Path("scripts/run_feature_ablation.py"),
        Path("quant_btc/price_action.py"),
        Path("quant_btc/retained_strategy.py"),
        Path("quant_platform/backtest.py"),
        Path("quant_platform/risk.py"),
    ]
    manifest = {
        "protocol": protocol,
        "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
        "variants": {name: VARIANTS[name] for name in variants},
        "splits": splits,
        "leverages": leverages,
        "risk_scale_mode": args.risk_scale_mode,
        "data_sha256": data_hashes,
        "derivatives_manifest": str(derivative_manifest),
        "derivatives_manifest_sha256": (
            _file_hash(derivative_manifest) if derivative_manifest.exists() else None
        ),
        "code_sha256": {str(path): _file_hash(path) for path in code_paths},
        "price_only_proxy": price_only_proxy,
        "mark_proxy_bars_by_asset_split": mark_proxy_by_asset_split,
        "profit_factor_scope": "trade net PnL includes fees but excludes funding allocation",
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(scorecard.to_string(index=False))


if __name__ == "__main__":
    main()
