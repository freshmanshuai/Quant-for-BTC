"""Canonical causal backtest entry point for the retained expert system."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from quant_btc.data import fetch_derivative_data, fetch_ohlcv
from quant_btc.retained_strategy import (
    BearTrendModule,
    CoreTrendModule,
    PullbackLongModule,
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the causal retained-module backtest")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--market-type", choices=("swap", "spot"), default="swap")
    parser.add_argument("--timeframe", default="4h")
    parser.add_argument("--bars", type=Path, help="CSV, pickle, or parquet OHLCV file")
    parser.add_argument("--funding", type=Path, help="CSV, pickle, or parquet funding ledger")
    parser.add_argument("--refresh-data", action="store_true")
    parser.add_argument("--cash", type=float, default=100_000.0)
    parser.add_argument("--leverage", type=float, default=1.0)
    parser.add_argument("--fee-rate", type=float, default=0.0005)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--spread-column", help="Observed absolute bid/ask spread feature")
    parser.add_argument("--mark-price-column", help="Historical mark-price/open feature")
    parser.add_argument("--mark-high-column", help="Historical intrabar mark high feature")
    parser.add_argument("--mark-low-column", help="Historical intrabar mark low feature")
    parser.add_argument("--funding-mark-column", help="Mark price aligned to funding cash flows")
    parser.add_argument("--maintenance-margin-rate", type=float, default=0.004)
    parser.add_argument("--maintenance-amount", type=float, default=0.0)
    parser.add_argument("--liquidation-fee-rate", type=float, default=0.0125)
    parser.add_argument("--output", type=Path, default=Path("artifacts/backtests/latest"))
    return parser.parse_args()


def load_frame(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".pkl", ".pickle"}:
        frame = pd.read_pickle(path)
    elif suffix == ".parquet":
        frame = pd.read_parquet(path)
    elif suffix == ".csv":
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
    else:
        raise ValueError(f"unsupported data file: {path}")
    frame.index = pd.to_datetime(frame.index, utc=True)
    return frame


def build_market(args: argparse.Namespace) -> MarketSpec:
    base, quote = args.symbol.split("/", 1)
    return MarketSpec(
        asset=AssetSpec(symbol=args.symbol, base=base, quote=quote),
        exchange=args.exchange,
        market_type=args.market_type,
        fee_rate=args.fee_rate,
        contract_multiplier=1.0,
        correlation_group="crypto_beta",
        supports_short=args.market_type == "swap",
        supports_leverage=args.market_type == "swap",
        max_leverage=args.leverage,
        maintenance_margin_rate=args.maintenance_margin_rate,
        maintenance_amount=args.maintenance_amount,
        liquidation_fee_rate=args.liquidation_fee_rate,
    )


def run(args: argparse.Namespace):
    bars = (
        load_frame(args.bars)
        if args.bars
        else fetch_ohlcv(
            symbol=args.symbol,
            timeframe=args.timeframe,
            market_type=args.market_type,
            exchange_id=args.exchange,
            refresh=args.refresh_data,
        )
    )
    bars = clean_ohlcv_bars(bars, args.timeframe, require_contiguous=True)
    required_execution_columns = [
        name
        for name in (
            args.spread_column,
            args.mark_price_column,
            args.mark_high_column,
            args.mark_low_column,
            args.funding_mark_column,
        )
        if name
    ]
    missing_execution_columns = [name for name in required_execution_columns if name not in bars]
    if missing_execution_columns:
        raise ValueError(
            "missing execution columns: " + ", ".join(missing_execution_columns)
        )

    derivatives = None
    if args.market_type == "swap":
        derivatives = (
            load_frame(args.funding)
            if args.funding
            else fetch_derivative_data(
                args.symbol,
                exchange_id=args.exchange,
                refresh=args.refresh_data,
            )
        )
        validate_funding_coverage(bars, derivatives)

    features = prepare_retained_features(bars, derivatives)
    market = build_market(args)
    markets = {args.symbol: market}
    pipeline = SignalPipeline(
        signal_runner=SignalModuleRunner(
            [CoreTrendModule(), BearTrendModule(), PullbackLongModule()]
        ),
        risk_engine=RiskEngine(
            RiskLimits(
                risk_per_trade=0.01,
                max_position_fraction=1.0,
                max_leverage=args.leverage,
                enforce_initial_margin=True,
                portfolio_risk_budget=0.02,
                max_module_risk=0.01,
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
    engine = EventDrivenBacktest(
        pipeline=pipeline,
        account=AccountState(equity=args.cash),
        execution=BacktestExecutionConfig(
            slippage_bps=args.slippage_bps,
            intrabar_stop_target=True,
            fill_price_column="Open",
            min_order_age_bars=1,
            funding_rate_feature="funding_rate" if args.market_type == "swap" else None,
            funding_mark_price_feature=args.funding_mark_column,
            leverage=args.leverage,
            maintenance_margin_rate=args.maintenance_margin_rate,
            maintenance_amount=args.maintenance_amount,
            liquidation_fee_rate=args.liquidation_fee_rate,
            entry_spread_feature=args.spread_column,
            exit_spread_feature=args.spread_column,
            mark_price_column=args.mark_price_column,
            mark_high_column=args.mark_high_column,
            mark_low_column=args.mark_low_column,
            finalize_positions=True,
        ),
        markets_by_symbol=markets,
    )
    return engine.run({args.symbol: features})


def write_result(result, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    summary = asdict(result.performance_summary)
    summary.update(
        liquidation_count=result.liquidation_count,
        liquidation_fees_paid=result.liquidation_fees_paid,
    )
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                **asdict(trade),
                "direction": trade.direction.value,
            }
            for trade in result.trades
        ]
    ).to_csv(output / "trades.csv", index=False)
    pd.DataFrame([asdict(point) for point in result.equity_curve]).to_csv(
        output / "equity.csv", index=False
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


def main() -> None:
    args = parse_args()
    write_result(run(args), args.output)


if __name__ == "__main__":
    main()
