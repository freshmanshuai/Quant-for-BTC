"""Reproduce the 2026-07-15 BTC/ETH/SOL repository backtest audit.

This script intentionally lives outside the application source tree.  It uses
the repository's strategy and backtest engine unchanged, while sourcing fixed
monthly Binance USD-M archives and writing every generated artifact below this
audit directory.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import platform
import subprocess
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import requests


AUDIT_DIR = Path(__file__).resolve().parent
SNAPSHOT_DIR = AUDIT_DIR / "data_snapshots"
RESULTS_DIR = AUDIT_DIR / "results"
SOURCE_BASE = "https://data.binance.vision/data/futures/um/monthly/klines"
DAILY_SOURCE_BASE = "https://data.binance.vision/data/futures/um/daily/klines"
ASSETS = ("BTC", "ETH", "SOL")
END_MONTH = "2026-06"
RT_COST_BPS = (4, 8, 12, 20)
REUSE_EXISTING_CASES = False


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def month_range(start: str, end: str) -> list[str]:
    return [str(value) for value in pd.period_range(start, end, freq="M")]


def archive_url(symbol: str, timeframe: str, month: str) -> str:
    name = f"{symbol}-{timeframe}-{month}.zip"
    return f"{SOURCE_BASE}/{symbol}/{timeframe}/{name}"


def fetch_archive(task: tuple[str, str, str]) -> tuple[dict, bytes | None]:
    symbol, timeframe, month = task
    url = archive_url(symbol, timeframe, month)
    last_error = None
    for attempt in range(1, 4):
        try:
            response = requests.get(url, timeout=60)
            record = {
                "archive_type": "monthly",
                "symbol": symbol,
                "timeframe": timeframe,
                "month": month,
                "url": url,
                "http_status": int(response.status_code),
                "attempt": attempt,
            }
            if response.status_code == 404:
                return record, None
            response.raise_for_status()
            payload = response.content
            record.update({"bytes": len(payload), "sha256": sha256_bytes(payload)})
            return record, payload
        except Exception as exc:  # pragma: no cover - network diagnostics
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(attempt)
    raise RuntimeError(f"failed to download {url}: {last_error}")


def fetch_daily_archive(symbol: str, timeframe: str, day: str) -> tuple[dict, bytes | None]:
    name = f"{symbol}-{timeframe}-{day}.zip"
    url = f"{DAILY_SOURCE_BASE}/{symbol}/{timeframe}/{name}"
    response = requests.get(url, timeout=60)
    record = {
        "archive_type": "daily_gap_fill",
        "symbol": symbol,
        "timeframe": timeframe,
        "month": day,
        "url": url,
        "http_status": int(response.status_code),
        "attempt": 1,
    }
    if response.status_code == 404:
        return record, None
    response.raise_for_status()
    payload = response.content
    record.update({"bytes": len(payload), "sha256": sha256_bytes(payload)})
    return record, payload


def parse_archive(payload: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        if len(names) != 1:
            raise ValueError(f"expected one CSV in archive, found {names}")
        raw = pd.read_csv(archive.open(names[0]), header=None, low_memory=False)

    timestamp = pd.to_numeric(raw.iloc[:, 0], errors="coerce")
    raw = raw.loc[timestamp.notna()].copy()
    timestamp = timestamp.loc[timestamp.notna()].astype("int64")
    unit = "us" if int(timestamp.median()) > 100_000_000_000_000 else "ms"
    index = pd.to_datetime(timestamp, unit=unit, utc=True)
    frame = pd.DataFrame(
        {
            "Open": pd.to_numeric(raw.iloc[:, 1], errors="coerce").to_numpy(),
            "High": pd.to_numeric(raw.iloc[:, 2], errors="coerce").to_numpy(),
            "Low": pd.to_numeric(raw.iloc[:, 3], errors="coerce").to_numpy(),
            "Close": pd.to_numeric(raw.iloc[:, 4], errors="coerce").to_numpy(),
            "Volume": pd.to_numeric(raw.iloc[:, 5], errors="coerce").to_numpy(),
        },
        index=index,
    )
    frame.index.name = "timestamp"
    return frame.dropna()


def integrity_record(frame_before: pd.DataFrame, frame: pd.DataFrame, timeframe: str) -> dict:
    expected = pd.Timedelta(timeframe)
    diffs = frame.index.to_series().diff().dropna()
    missing_bars = int(sum(max(int(delta / expected) - 1, 0) for delta in diffs if delta > expected))
    irregular = int(sum(delta <= pd.Timedelta(0) or delta % expected != pd.Timedelta(0) for delta in diffs))
    invalid_ohlc = (
        (frame["High"] < frame[["Open", "Close", "Low"]].max(axis=1))
        | (frame["Low"] > frame[["Open", "Close", "High"]].min(axis=1))
    )
    return {
        "rows_before_dedup": int(len(frame_before)),
        "duplicate_timestamps_before": int(frame_before.index.duplicated().sum()),
        "rows": int(len(frame)),
        "start": str(frame.index[0]),
        "end": str(frame.index[-1]),
        "timezone": str(frame.index.tz),
        "monotonic": bool(frame.index.is_monotonic_increasing),
        "missing_expected_bars": missing_bars,
        "irregular_intervals": irregular,
        "invalid_ohlc_rows": int(invalid_ohlc.sum()),
        "nonpositive_price_rows": int((frame[["Open", "High", "Low", "Close"]] <= 0).any(axis=1).sum()),
        "negative_volume_rows": int((frame["Volume"] < 0).sum()),
        "zero_volume_rows": int((frame["Volume"] == 0).sum()),
    }


def download_snapshots() -> dict:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    tasks: list[tuple[str, str, str]] = []
    all_months = month_range("2019-09", END_MONTH)
    mtf_months = month_range("2023-01", END_MONTH)
    for asset in ASSETS:
        symbol = f"{asset}USDT"
        tasks.extend((symbol, "4h", month) for month in all_months)
        tasks.extend((symbol, "15m", month) for month in mtf_months)

    payloads: dict[tuple[str, str], list[tuple[str, bytes]]] = {}
    source_manifest: list[dict] = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(fetch_archive, task): task for task in tasks}
        for future in as_completed(futures):
            record, payload = future.result()
            source_manifest.append(record)
            if payload is not None:
                key = (record["symbol"], record["timeframe"])
                payloads.setdefault(key, []).append((record["month"], payload))

    datasets: dict[str, dict] = {}
    for asset in ASSETS:
        symbol = f"{asset}USDT"
        for timeframe in ("4h", "15m"):
            parts = [
                parse_archive(payload)
                for _, payload in sorted(payloads[(symbol, timeframe)], key=lambda item: item[0])
            ]
            monthly_before = pd.concat(parts).sort_index(kind="stable")
            deduped_monthly = monthly_before.loc[~monthly_before.index.duplicated(keep="last")].sort_index()

            # Some sealed monthly packages omit bars that are present in the
            # corresponding sealed daily package.  Fill only exact expected
            # timestamp gaps, preserve daily URL/hash provenance, then validate
            # continuity again.  The 2022 SOL 4h omissions are one such case.
            expected = pd.Timedelta(timeframe)
            missing = pd.date_range(deduped_monthly.index[0], deduped_monthly.index[-1], freq=expected).difference(
                deduped_monthly.index
            )
            daily_parts = []
            for day in sorted({timestamp.strftime("%Y-%m-%d") for timestamp in missing}):
                daily_record, daily_payload = fetch_daily_archive(symbol, timeframe, day)
                source_manifest.append(daily_record)
                if daily_payload is not None:
                    daily_parts.append(parse_archive(daily_payload))
            before = pd.concat([monthly_before, *daily_parts]).sort_index(kind="stable")
            deduped = before.loc[~before.index.duplicated(keep="last")].sort_index()
            if timeframe == "15m":
                deduped = deduped.tail(100_000)
            record = integrity_record(before, deduped, timeframe)
            record.update(
                {
                    "monthly_rows_before_gap_fill": int(len(monthly_before)),
                    "monthly_missing_expected_bars": int(len(missing)),
                    "daily_gap_fill_archives": int(len(daily_parts)),
                    "daily_gap_fill_rows": int(sum(len(part) for part in daily_parts)),
                }
            )
            path = SNAPSHOT_DIR / f"binance_usdm_{symbol}_{timeframe}_through_{END_MONTH}.pkl"
            deduped.to_pickle(path, protocol=5)
            record.update(
                {
                    "path": str(path.relative_to(AUDIT_DIR)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
            datasets[f"{asset}_{timeframe}"] = record

    source_manifest.sort(key=lambda row: (row["symbol"], row["timeframe"], row["month"]))
    (SNAPSHOT_DIR / "monthly_archive_manifest.json").write_text(
        json.dumps(source_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (SNAPSHOT_DIR / "dataset_manifest.json").write_text(
        json.dumps(datasets, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return datasets


def load_snapshots() -> dict[str, dict[str, pd.DataFrame]]:
    datasets: dict[str, dict[str, pd.DataFrame]] = {}
    for asset in ASSETS:
        datasets[asset] = {}
        for timeframe in ("4h", "15m"):
            path = SNAPSHOT_DIR / f"binance_usdm_{asset}USDT_{timeframe}_through_{END_MONTH}.pkl"
            if not path.exists():
                raise FileNotFoundError(f"missing snapshot: {path}; run with --download first")
            datasets[asset][timeframe] = pd.read_pickle(path)
    return datasets


def json_value(value):
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, pd.Timedelta)):
        return str(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    return value


def profit_stats(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {
            "trades": 0,
            "pnl": 0.0,
            "win_rate_pct": None,
            "profit_factor": None,
            "avg_win_loss_ratio": None,
            "max_consecutive_losses": 0,
            "avg_trade_pct": None,
        }
    pnl = trades["PnL"].astype(float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    gross_win = float(wins.sum())
    gross_loss = abs(float(losses.sum()))
    max_streak = streak = 0
    for loss in (pnl <= 0):
        streak = streak + 1 if bool(loss) else 0
        max_streak = max(max_streak, streak)
    entry_value = (trades["EntryPrice"].astype(float) * trades["Size"].astype(float)).abs()
    trade_pct = pnl.div(entry_value.replace(0, np.nan)) * 100
    return {
        "trades": int(len(trades)),
        "pnl": float(pnl.sum()),
        "win_rate_pct": float((pnl > 0).mean() * 100),
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else None,
        "avg_win_loss_ratio": float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) else None,
        "max_consecutive_losses": int(max_streak),
        "avg_trade_pct": float(trade_pct.mean()),
    }


def annual_returns(equity: pd.Series, initial_cash: float) -> list[dict]:
    rows = []
    previous = initial_cash
    for year, values in equity.groupby(equity.index.year):
        ending = float(values.iloc[-1])
        rows.append(
            {
                "year": int(year),
                "return_pct": (ending / previous - 1) * 100,
                "ending_equity": ending,
                "bars": int(len(values)),
                "partial_year": bool(values.index[0].month != 1 or values.index[-1].month != 12),
            }
        )
        previous = ending
    return rows


def conditional_return_stats(returns: pd.Series) -> dict:
    clean = returns.dropna()
    if clean.empty:
        return {"bars": 0, "compounded_return_pct": None, "mean_bps_per_bar": None, "sharpe": None}
    volatility = float(clean.std(ddof=1))
    sharpe = float(clean.mean() / volatility * math.sqrt(6 * 365)) if volatility > 0 else None
    return {
        "bars": int(len(clean)),
        "compounded_return_pct": float(((1 + clean).prod() - 1) * 100),
        "mean_bps_per_bar": float(clean.mean() * 10_000),
        "positive_bar_pct": float((clean > 0).mean() * 100),
        "sharpe": sharpe,
    }


def buy_hold_benchmark(asset: str, start: str, end: str) -> dict:
    path = SNAPSHOT_DIR / f"binance_usdm_{asset}USDT_4h_through_{END_MONTH}.pkl"
    bars = pd.read_pickle(path).loc[pd.Timestamp(start) : pd.Timestamp(end)]
    close = bars["Close"].astype(float)
    returns = close.pct_change(fill_method=None).dropna()
    years = (close.index[-1] - close.index[0]).total_seconds() / (365.25 * 86400)
    total_return = float(close.iloc[-1] / close.iloc[0] - 1)
    cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 else None
    drawdown = close / close.cummax() - 1
    max_drawdown = float(drawdown.min())
    volatility = float(returns.std(ddof=1) * math.sqrt(6 * 365))
    sharpe = float(returns.mean() / returns.std(ddof=1) * math.sqrt(6 * 365)) if returns.std(ddof=1) > 0 else None
    downside = returns[returns < 0]
    sortino = float(returns.mean() / downside.std(ddof=1) * math.sqrt(6 * 365)) if downside.std(ddof=1) > 0 else None

    longest = pd.Timedelta(0)
    underwater_start = None
    for timestamp, value in drawdown.items():
        if value < 0 and underwater_start is None:
            underwater_start = timestamp
        elif value >= 0 and underwater_start is not None:
            longest = max(longest, timestamp - underwater_start)
            underwater_start = None
    if underwater_start is not None:
        longest = max(longest, drawdown.index[-1] - underwater_start)

    return {
        "benchmark": "unlevered buy-and-hold close-to-close",
        "start": str(close.index[0]),
        "end": str(close.index[-1]),
        "return_pct": total_return * 100,
        "cagr_pct": cagr * 100 if cagr is not None else None,
        "volatility_pct": volatility * 100,
        "max_drawdown_pct": max_drawdown * 100,
        "max_drawdown_duration": str(longest),
        "sharpe_arithmetic_4h": sharpe,
        "sortino_arithmetic_4h": sortino,
        "calmar": cagr / abs(max_drawdown) if cagr is not None and max_drawdown < 0 else None,
    }


def independent_market_environment(record: dict) -> list[dict]:
    """Causal, strategy-independent market-state proxy for robustness review.

    Every state variable is shifted one 4H bar before conditioning the next
    equity return.  It does not reuse the repository's leaking daily/weekly
    regime labels.
    """
    from quant_platform.features import adx, atr, rolling_pct_rank

    asset = record["asset"]
    bars_path = SNAPSHOT_DIR / f"binance_usdm_{asset}USDT_4h_through_{END_MONTH}.pkl"
    bars = pd.read_pickle(bars_path)
    case_path = RESULTS_DIR / "cases" / record["case_id"] / "equity.csv"
    equity_frame = pd.read_csv(case_path, index_col=0, parse_dates=True)
    equity = equity_frame["Equity"].astype(float)
    bars = bars.reindex(equity.index)
    strategy_returns = equity.pct_change(fill_method=None)

    trailing_180d = bars["Close"].pct_change(6 * 180, fill_method=None).shift(1)
    adx_value = adx(bars["High"], bars["Low"], bars["Close"], 14).shift(1)
    atr_ratio = atr(bars["High"], bars["Low"], bars["Close"], 14) / bars["Close"]
    volatility_rank = rolling_pct_rank(atr_ratio, 120).shift(1)

    conditions = {
        "bull_180d_gt_20pct": trailing_180d > 0.20,
        "bear_180d_lt_minus20pct": trailing_180d < -0.20,
        "sideways_180d_between_plusminus20pct": trailing_180d.between(-0.20, 0.20, inclusive="both"),
        "trend_adx_ge_25": adx_value >= 25,
        "choppy_adx_lt_20": adx_value < 20,
        "high_volatility_rank_ge_90pct": volatility_rank >= 0.90,
        "low_volatility_rank_le_30pct": volatility_rank <= 0.30,
    }
    rows = []
    for label, mask in conditions.items():
        rows.append({"environment_proxy": label, **conditional_return_stats(strategy_returns[mask])})
    return rows


def concentration_stats(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {}
    pnl = trades["PnL"].astype(float).sort_values(ascending=False)
    positive = pnl[pnl > 0]
    gross_profit = float(positive.sum())
    net_profit = float(pnl.sum())
    cumulative = positive.cumsum()

    def count_to(fraction: float) -> int | None:
        if gross_profit <= 0:
            return None
        return int((cumulative < gross_profit * fraction).sum() + 1)

    row = {"gross_profit": gross_profit, "net_profit": net_profit, "winning_trades": int(len(positive))}
    for n in (1, 5, 10):
        top = float(positive.head(n).sum())
        row[f"top_{n}_pnl"] = top
        row[f"top_{n}_share_gross_profit_pct"] = top / gross_profit * 100 if gross_profit > 0 else None
        row[f"top_{n}_share_net_profit_pct"] = top / net_profit * 100 if net_profit != 0 else None
    row["winners_to_50pct_gross_profit"] = count_to(0.50)
    row["winners_to_80pct_gross_profit"] = count_to(0.80)
    return row


def trade_diagnostics(trades: pd.DataFrame, material_threshold: float = 1e-7) -> dict:
    """Quantify zero/tiny-size records and overlapping lifecycle intervals."""
    if trades.empty:
        return {
            "raw_trade_count": 0,
            "material_trade_count": 0,
            "ghost_count": 0,
            "ghost_pct": 0.0,
            "material_size_threshold": material_threshold,
            "adjacent_interval_overlap_count": 0,
            "any_interval_overlap_count": 0,
        }
    ordered = trades.sort_values(["EntryTime", "ExitTime"], kind="stable")
    material = ordered["Size"].astype(float).abs() > material_threshold
    adjacent_overlap = 0
    active_exit = None
    any_overlap = 0
    for row in ordered.itertuples():
        entry = pd.Timestamp(row.EntryTime)
        exit_time = pd.Timestamp(row.ExitTime)
        if active_exit is not None and entry < active_exit:
            any_overlap += 1
        active_exit = exit_time if active_exit is None else max(active_exit, exit_time)
    previous_exit = pd.to_datetime(ordered["ExitTime"]).shift(1)
    adjacent_overlap = int((pd.to_datetime(ordered["EntryTime"]) < previous_exit).fillna(False).sum())
    ghosts = int((~material).sum())
    return {
        "raw_trade_count": int(len(ordered)),
        "material_trade_count": int(material.sum()),
        "ghost_count": ghosts,
        "ghost_pct": ghosts / len(ordered) * 100,
        "material_size_threshold": material_threshold,
        "adjacent_interval_overlap_count": adjacent_overlap,
        "any_interval_overlap_count": int(any_overlap),
    }


def funding_estimate(trades: pd.DataFrame, annual_rate: float = 0.10) -> dict:
    if trades.empty:
        return {"annual_rate": annual_rate, "all_positions_pay": 0.0, "positive_rate_signed": 0.0}
    duration_years = (pd.to_datetime(trades["ExitTime"]) - pd.to_datetime(trades["EntryTime"])).dt.total_seconds() / (365.25 * 86400)
    notional = (trades["EntryPrice"].astype(float) * trades["Size"].astype(float)).abs()
    carry = notional * duration_years * annual_rate
    signed = np.where(trades["Size"].astype(float) > 0, carry, -carry)
    return {
        "annual_rate": annual_rate,
        "all_positions_pay": float(carry.sum()),
        "positive_rate_signed": float(np.sum(signed)),
        "method": "ex-post approximation: abs(entry_price*size)*holding_years*rate; partial closes may overstate",
    }


def install_fast_mtf_slice(datasets: dict[str, dict[str, pd.DataFrame]]) -> dict:
    from quant_btc.strategy import DualLayerStrategy

    checks = 0
    for asset in ASSETS:
        mtf = datasets[asset]["15m"]
        test_points = datasets[asset]["4h"].index[:: max(1, len(datasets[asset]["4h"]) // 200)]
        for timestamp in test_points:
            end = timestamp + pd.Timedelta(hours=4)
            old = mtf[(mtf.index >= timestamp) & (mtf.index < end)]
            left = mtf.index.searchsorted(timestamp, side="left")
            right = mtf.index.searchsorted(end, side="left")
            new = mtf.iloc[left:right]
            pd.testing.assert_frame_equal(old, new)
            checks += 1

    def fast_slice(self):
        mtf = DualLayerStrategy._mtf_15m
        if mtf is None or mtf.empty:
            return None
        timestamp = self.data.df.index[-1]
        end = timestamp + pd.Timedelta(hours=4)
        left = mtf.index.searchsorted(timestamp, side="left")
        right = mtf.index.searchsorted(end, side="left")
        return mtf.iloc[left:right]

    DualLayerStrategy._mtf_15m_bars = fast_slice
    return {
        "optimization": "runtime-only monkeypatch of DualLayerStrategy._mtf_15m_bars using DatetimeIndex.searchsorted",
        "logic_change": False,
        "equivalence_assertions": checks,
    }


def analyze_result(
    stats: pd.Series,
    prepared: pd.DataFrame,
    initial_cash: float,
    *,
    causal_guard: bool = False,
) -> dict:
    from quant_btc.config import RiskConfig
    from quant_btc.regime_model import build_btc_regime_model

    trades = stats["_trades"].copy().sort_values(["ExitTime", "EntryTime"], kind="stable")
    material_trades = trades[trades["Size"].astype(float).abs() > 1e-7].copy()
    equity_frame = stats["_equity_curve"].copy()
    equity = equity_frame["Equity"].astype(float)
    result = {
        "metrics": {
            key: json_value(stats.get(key))
            for key in [
                "Start", "End", "Duration", "Exposure Time [%]", "Equity Final [$]", "Equity Peak [$]",
                "Return [%]", "Buy & Hold Return [%]", "Return (Ann.) [%]", "Volatility (Ann.) [%]",
                "Sharpe Ratio", "Sortino Ratio", "Calmar Ratio", "Alpha [%]", "Beta",
                "Max. Drawdown [%]", "Avg. Drawdown [%]", "Max. Drawdown Duration", "Avg. Drawdown Duration",
                "# Trades", "Win Rate [%]", "Best Trade [%]", "Worst Trade [%]", "Avg. Trade [%]",
                "Max. Trade Duration", "Avg. Trade Duration", "Profit Factor", "Expectancy [%]", "SQN",
            ]
        },
        "trade_stats": profit_stats(trades),
        "material_trade_stats": profit_stats(material_trades),
        "trade_diagnostics": trade_diagnostics(trades),
        "annual_returns": annual_returns(equity, initial_cash),
        "concentration": concentration_stats(material_trades),
        "funding_estimate": funding_estimate(material_trades),
    }

    result["direction"] = {}
    for label, subset in (("long", material_trades[material_trades["Size"] > 0]), ("short", material_trades[material_trades["Size"] < 0])):
        result["direction"][label] = profit_stats(subset)

    result["modules"] = {}
    tags = material_trades["Tag"].fillna("untagged") if "Tag" in material_trades else pd.Series("untagged", index=material_trades.index)
    for tag in sorted(tags.astype(str).unique()):
        result["modules"][tag] = profit_stats(material_trades[tags.astype(str) == tag])

    regime = build_btc_regime_model(RiskConfig()).classify(prepared)
    labels = {0: "ranging", 1: "bull", 2: "bear", 3: "compression", 4: "high_risk"}
    equity_returns = equity.pct_change(fill_method=None)
    aligned_regime = regime["_regime"].reindex(equity.index, method="ffill")
    environment = {}
    for value, label in labels.items():
        environment[label] = conditional_return_stats(equity_returns[aligned_regime == value])
    environment["trend"] = conditional_return_stats(equity_returns[aligned_regime.isin([1, 2])])
    environment["nontrend"] = conditional_return_stats(equity_returns[aligned_regime.isin([0, 3])])
    atr_pct = regime["_atr_pct"].reindex(equity.index, method="ffill")
    environment["high_volatility"] = conditional_return_stats(equity_returns[atr_pct >= 0.90])
    environment["low_volatility"] = conditional_return_stats(equity_returns[atr_pct <= 0.30])
    result["environment"] = environment

    if causal_guard:
        result["environment_diagnostic_note"] = (
            "causal_guard_sensitivity_only: completed daily/weekly values are shifted by one full period; "
            "this is a conservative runtime sensitivity, not a validated production fix"
        )
    else:
        result["environment_diagnostic_note"] = (
            "diagnostic_contaminated_by_htf_leak: this uses the repository RegimeModel, whose daily/weekly "
            "resample maps period-final closes into earlier bars; environment figures are descriptive only"
        )

    entry_regime = regime["_regime"].reindex(pd.DatetimeIndex(material_trades["EntryTime"]), method="ffill")
    result["trade_entry_regime"] = {}
    for value, label in labels.items():
        mask = np.asarray(entry_regime == value)
        result["trade_entry_regime"][label] = profit_stats(material_trades.iloc[np.flatnonzero(mask)])
    return result


def prepare_inputs(datasets: dict[str, dict[str, pd.DataFrame]]):
    from quant_btc.config import BacktestConfig
    from quant_btc.strategy import prepare_features

    prepared_full = {}
    for asset in ASSETS:
        raw = datasets[asset]["4h"]
        config = BacktestConfig(symbol=f"{asset}/USDT", timeframe="4h")
        features = prepare_features(raw, config)
        features["_short_deriv_bonus"] = 0.0
        features["_perp_crowding_long_bonus"] = 0.0
        prepared_full[asset] = (raw, features)

    # Preserve every asset's available feature warm-up, then apply one identical
    # tradable start.  This avoids recomputing BTC/ETH indicators from SOL's
    # listing date and records the exact common cutoff from actual prepared data.
    common_start = max(features.index.min() for _, features in prepared_full.values())
    prepared_common = {
        asset: (raw.loc[raw.index >= common_start], features.loc[features.index >= common_start])
        for asset, (raw, features) in prepared_full.items()
    }
    return prepared_full, prepared_common, common_start


def run_case(
    *,
    asset: str,
    datasets: dict[str, dict[str, pd.DataFrame]],
    raw: pd.DataFrame,
    prepared: pd.DataFrame,
    strategy_name: str,
    window: str,
    roundtrip_cost_bps: int,
    common_start: pd.Timestamp,
) -> dict:
    from quant_btc.config import BacktestConfig, RiskConfig
    from quant_btc.strategy import DualLayerStrategy, run_backtest

    case_id = f"{asset.lower()}_{strategy_name}_{window}_rt{roundtrip_cost_bps}bps"
    case_dir = RESULTS_DIR / "cases" / case_id
    summary_path = case_dir / "summary.json"
    if REUSE_EXISTING_CASES and summary_path.exists():
        print(f"[reuse] {case_id}", flush=True)
        return json.loads(summary_path.read_text(encoding="utf-8"))

    commission_per_side = roundtrip_cost_bps / 2 / 10_000
    config = BacktestConfig(
        symbol=f"{asset}/USDT",
        timeframe="4h",
        initial_cash=100_000,
        commission=commission_per_side,
        market_type="swap",
        exchange_id="binance",
    )
    risk = RiskConfig(leverage=5)
    mtf = datasets[asset]["15m"]
    if window == "common":
        mtf = mtf.loc[mtf.index >= common_start]
    DualLayerStrategy._mtf_15m = mtf

    print(f"[run] {case_id}: {len(prepared)} x 4h bars, {len(mtf)} x 15m bars", flush=True)
    started = time.time()
    stats, _ = run_backtest(prepared.copy(), config, strategy_name=strategy_name, risk_cfg=risk)
    elapsed = time.time() - started
    analysis = analyze_result(
        stats,
        prepared,
        config.initial_cash,
        causal_guard="causal_guard" in window,
    )
    print(
        f"[done] {case_id}: return={analysis['metrics']['Return [%]']:.2f}% "
        f"mdd={analysis['metrics']['Max. Drawdown [%]']:.2f}% "
        f"trades={analysis['metrics']['# Trades']} elapsed={elapsed:.1f}s",
        flush=True,
    )
    case_dir.mkdir(parents=True, exist_ok=True)
    trades = stats["_trades"].copy()
    equity = stats["_equity_curve"].copy()
    trades.to_csv(case_dir / "trades.csv", index=False)
    equity.to_csv(case_dir / "equity.csv")
    record = {
        "case_id": case_id,
        "asset": asset,
        "strategy": strategy_name,
        "window": window,
        "common_start": str(common_start),
        "raw_start": str(raw.index[0]),
        "raw_end": str(raw.index[-1]),
        "raw_bars": int(len(raw)),
        "prepared_start": str(prepared.index[0]),
        "prepared_end": str(prepared.index[-1]),
        "prepared_bars": int(len(prepared)),
        "mtf_start": str(mtf.index[0]),
        "mtf_end": str(mtf.index[-1]),
        "mtf_bars": int(len(mtf)),
        "initial_cash": config.initial_cash,
        "configured_leverage": risk.leverage,
        "commission_per_side": commission_per_side,
        "roundtrip_cost_bps": roundtrip_cost_bps,
        "slippage_model": "none; higher round-trip cost cases proxy additive slippage",
        "funding_in_engine": False,
        "derivative_bonus": 0,
        "elapsed_seconds": elapsed,
        "analysis": analysis,
    }
    (case_dir / "summary.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def flatten_outputs(records: list[dict], *, prefix: str = "") -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{prefix}_" if prefix else ""
    (RESULTS_DIR / f"{stem}all_cases.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    summary_rows = []
    yearly_rows = []
    direction_rows = []
    module_rows = []
    environment_rows = []
    concentration_rows = []
    benchmark_rows = []
    causal_environment_rows = []
    for record in records:
        base = {key: record[key] for key in ("case_id", "asset", "strategy", "window", "roundtrip_cost_bps")}
        summary_rows.append({
            **base,
            **record["analysis"]["metrics"],
            **record["analysis"]["trade_stats"],
            **{f"material_{key}": value for key, value in record["analysis"]["material_trade_stats"].items()},
            **record["analysis"]["trade_diagnostics"],
        })
        yearly_rows.extend({**base, **row} for row in record["analysis"]["annual_returns"])
        direction_rows.extend({**base, "direction": label, **row} for label, row in record["analysis"]["direction"].items())
        module_rows.extend({**base, "module": label, **row} for label, row in record["analysis"]["modules"].items())
        environment_rows.extend({**base, "environment": label, **row} for label, row in record["analysis"]["environment"].items())
        concentration_rows.append({**base, **record["analysis"]["concentration"]})
        benchmark_rows.append(
            {
                **base,
                **buy_hold_benchmark(
                    record["asset"],
                    record["analysis"]["metrics"]["Start"],
                    record["analysis"]["metrics"]["End"],
                ),
            }
        )
        causal_environment_rows.extend({**base, **row} for row in independent_market_environment(record))

    pd.DataFrame(summary_rows).to_csv(RESULTS_DIR / f"{stem}summary.csv", index=False)
    pd.DataFrame(yearly_rows).to_csv(RESULTS_DIR / f"{stem}yearly_returns.csv", index=False)
    pd.DataFrame(direction_rows).to_csv(RESULTS_DIR / f"{stem}direction_attribution.csv", index=False)
    pd.DataFrame(module_rows).to_csv(RESULTS_DIR / f"{stem}module_attribution.csv", index=False)
    pd.DataFrame(environment_rows).to_csv(RESULTS_DIR / f"{stem}market_environment.csv", index=False)
    pd.DataFrame(concentration_rows).to_csv(RESULTS_DIR / f"{stem}profit_concentration.csv", index=False)
    pd.DataFrame(benchmark_rows).to_csv(RESULTS_DIR / f"{stem}buy_hold_benchmark.csv", index=False)
    pd.DataFrame(causal_environment_rows).to_csv(
        RESULTS_DIR / f"{stem}causal_market_proxy.csv", index=False
    )


def environment_manifest(mtf_patch: dict) -> dict:
    from importlib.metadata import version
    from quant_btc.config import BacktestConfig, RiskConfig

    packages = {}
    for name in ("numpy", "pandas", "backtesting", "ccxt", "matplotlib", "pyarrow", "requests"):
        try:
            packages[name] = version(name)
        except Exception:
            packages[name] = None
    try:
        git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        git_commit = None
    return {
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "packages": packages,
        "git_commit": git_commit,
        "script": str(Path(__file__).resolve().relative_to(AUDIT_DIR)),
        "script_sha256": sha256_file(Path(__file__).resolve()),
        "backtest_config_defaults": asdict(BacktestConfig()),
        "risk_config_defaults": asdict(RiskConfig()),
        "data_cutoff": "2026-06-30 20:00:00+00:00 (last completed 4h bar in sealed monthly archive)",
        "derivative_bonus_policy": "forced to zero for all three assets because equal-coverage funding/OI history is unavailable",
        "mtf_optimization": mtf_patch,
        "command": " ".join(sys.argv),
    }


def install_causal_htf_guard(datasets: dict[str, dict[str, pd.DataFrame]]) -> dict:
    """Install a conservative completed-period HTF sensitivity at runtime.

    Both the feature engine and the regime model resolve their module-level
    ``htf_ema`` function at call time.  Replacing those two references is enough
    to move every daily/weekly aggregate one *complete* period backward without
    editing application source.  This deliberately over-delays weekly data and
    is therefore reported only as a guardrail sensitivity, not as a final fix.
    """
    import quant_platform.features as feature_module
    import quant_platform.regimes as regime_module

    def completed_period_htf_ema(close: pd.Series, rule: str, length: int) -> pd.Series:
        completed_close = close.resample(rule).last().ffill()
        completed_ema = feature_module.ema(completed_close, length).shift(1)
        return completed_ema.reindex(close.index, method="ffill")

    feature_module.htf_ema = completed_period_htf_ema
    regime_module.htf_ema = completed_period_htf_ema

    # Truncation invariance: a value observed at time t must equal the value
    # produced when all bars after t are physically unavailable.  Test across
    # assets, daily/weekly rules, and regularly spaced historical cutoffs.
    checks = 0
    for asset in ASSETS:
        close = datasets[asset]["4h"]["Close"]
        sample = close.index[:: max(1, len(close) // 24)][2:]
        for rule in ("1D", "1W"):
            full = completed_period_htf_ema(close, rule, 169)
            for timestamp in sample:
                truncated = completed_period_htf_ema(close.loc[:timestamp], rule, 169)
                left = full.loc[timestamp]
                right = truncated.loc[timestamp]
                if pd.isna(left) and pd.isna(right):
                    checks += 1
                    continue
                np.testing.assert_allclose(left, right, rtol=0, atol=1e-12)
                checks += 1
    return {
        "name": "completed_period_htf_ema_runtime_guard",
        "status": "sensitivity_only_not_final_fix",
        "daily_mapping": "daily final close/EMA shifted by one full daily bin",
        "weekly_mapping": "weekly final close/EMA shifted by one full weekly bin",
        "future_truncation_invariance_assertions": checks,
        "source_files_modified": False,
    }


def run_causal_guard(*, resume: bool = False) -> list[dict]:
    global REUSE_EXISTING_CASES
    REUSE_EXISTING_CASES = resume
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    datasets = load_snapshots()
    mtf_patch = install_fast_mtf_slice(datasets)
    causal_patch = install_causal_htf_guard(datasets)
    manifest = environment_manifest(mtf_patch)
    manifest["causal_guard"] = causal_patch
    (RESULTS_DIR / "causal_guard_environment.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    prepared_full, _, common_start = prepare_inputs(datasets)
    records = []
    for asset in ASSETS:
        raw, prepared = prepared_full[asset]
        records.append(
            run_case(
                asset=asset,
                datasets=datasets,
                raw=raw,
                prepared=prepared,
                strategy_name="dual",
                window="full_causal_guard",
                roundtrip_cost_bps=8,
                common_start=common_start,
            )
        )
    flatten_outputs(records, prefix="causal_guard")
    return records


def run_repo_cache_duplicate_sensitivity() -> list[dict]:
    """Isolate the effect of duplicate timestamps in the repository BTC cache."""
    from quant_btc.config import BacktestConfig, RiskConfig
    from quant_btc.strategy import DualLayerStrategy, prepare_features, run_backtest

    repository_root = AUDIT_DIR.parent.parent
    source_4h = repository_root / "data" / "binance_swap_BTC_USDT_4h.pkl"
    source_15m = repository_root / "data" / "binance_swap_BTC_USDT_15m.pkl"
    raw_4h = pd.read_pickle(source_4h)
    raw_15m = pd.read_pickle(source_15m)
    install_fast_mtf_slice(load_snapshots())
    records = []
    for label, deduplicate in (("raw_with_duplicates", False), ("deduplicated_keep_last", True)):
        bars = raw_4h
        mtf = raw_15m
        if deduplicate:
            bars = bars.loc[~bars.index.duplicated(keep="last")].sort_index()
            mtf = mtf.loc[~mtf.index.duplicated(keep="last")].sort_index()
        config = BacktestConfig(symbol="BTC/USDT", timeframe="4h", commission=0.0004)
        features = prepare_features(bars, config)
        features["_short_deriv_bonus"] = 0.0
        features["_perp_crowding_long_bonus"] = 0.0
        DualLayerStrategy._mtf_15m = mtf
        started = time.time()
        stats, _ = run_backtest(features, config, strategy_name="dual", risk_cfg=RiskConfig(leverage=5))
        trades = stats["_trades"].copy()
        record = {
            "case": label,
            "deduplicated": deduplicate,
            "source_4h": str(source_4h.relative_to(repository_root)),
            "source_15m": str(source_15m.relative_to(repository_root)),
            "source_4h_sha256": sha256_file(source_4h),
            "source_15m_sha256": sha256_file(source_15m),
            "bars_4h": int(len(bars)),
            "bars_15m": int(len(mtf)),
            "duplicate_4h": int(bars.index.duplicated().sum()),
            "duplicate_15m": int(mtf.index.duplicated().sum()),
            "derivative_bonus": 0,
            "roundtrip_cost_bps": 8,
            "elapsed_seconds": time.time() - started,
            "metrics": {
                key: json_value(stats.get(key))
                for key in (
                    "Start", "End", "Return [%]", "Return (Ann.) [%]", "Max. Drawdown [%]",
                    "Max. Drawdown Duration", "Sharpe Ratio", "Sortino Ratio", "Calmar Ratio",
                    "# Trades", "Win Rate [%]", "Profit Factor", "Equity Final [$]",
                )
            },
            "trade_diagnostics": trade_diagnostics(trades),
            "material_trade_stats": profit_stats(trades[trades["Size"].astype(float).abs() > 1e-7]),
        }
        print(
            f"[cache sensitivity] {label}: return={record['metrics']['Return [%]']:.2f}% "
            f"mdd={record['metrics']['Max. Drawdown [%]']:.2f}% trades={record['metrics']['# Trades']}",
            flush=True,
        )
        records.append(record)
    (RESULTS_DIR / "repo_cache_duplicate_sensitivity.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return records


def run_backtests(*, resume: bool = False) -> list[dict]:
    global REUSE_EXISTING_CASES
    REUSE_EXISTING_CASES = resume
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    datasets = load_snapshots()
    mtf_patch = install_fast_mtf_slice(datasets)
    (RESULTS_DIR / "environment.json").write_text(
        json.dumps(environment_manifest(mtf_patch), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    prepared_full, prepared_common, common_start = prepare_inputs(datasets)
    records: list[dict] = []

    # Priority order keeps the decision-critical cases available even if a
    # later sensitivity run is interrupted: full baseline, common baseline,
    # then cost stress, then the literal CLI-default HTF control.
    for asset in ASSETS:
        raw, prepared = prepared_full[asset]
        records.append(
            run_case(
                asset=asset,
                datasets=datasets,
                raw=raw,
                prepared=prepared,
                strategy_name="dual",
                window="full",
                roundtrip_cost_bps=8,
                common_start=common_start,
            )
        )

    for asset in ASSETS:
        raw_common, prepared = prepared_common[asset]
        records.append(
            run_case(
                asset=asset,
                datasets=datasets,
                raw=raw_common,
                prepared=prepared,
                strategy_name="dual",
                window="common",
                roundtrip_cost_bps=8,
                common_start=common_start,
            )
        )

    for cost in (4, 12, 20):
        for asset in ASSETS:
            raw, prepared = prepared_full[asset]
            records.append(
                run_case(
                    asset=asset,
                    datasets=datasets,
                    raw=raw,
                    prepared=prepared,
                    strategy_name="dual",
                    window="full",
                    roundtrip_cost_bps=cost,
                    common_start=common_start,
                )
            )

    htf_errors = []
    for asset in ASSETS:
        raw, prepared = prepared_full[asset]
        try:
            records.append(
                run_case(
                    asset=asset,
                    datasets=datasets,
                    raw=raw,
                    prepared=prepared,
                    strategy_name="htf",
                    window="full",
                    roundtrip_cost_bps=8,
                    common_start=common_start,
                )
            )
        except Exception as exc:
            error = {
                "asset": asset,
                "strategy": "htf",
                "window": "full",
                "roundtrip_cost_bps": 8,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "status": "literal CLI default is not runnable without source-code repair",
            }
            print(f"[blocked] {asset.lower()}_htf_full_rt8bps: {error['error_type']}: {error['error']}", flush=True)
            htf_errors.append(error)

    flatten_outputs(records)
    (RESULTS_DIR / "blocked_cases.json").write_text(
        json.dumps(htf_errors, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return records


def aggregate_existing_results() -> list[dict]:
    records = []
    for path in sorted((RESULTS_DIR / "cases").glob("*/summary.json")):
        if "causal_guard" not in path.parent.name:
            records.append(json.loads(path.read_text(encoding="utf-8")))
    flatten_outputs(records)
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true", help="download and freeze Binance monthly snapshots")
    parser.add_argument("--run", action="store_true", help="run all backtest cases")
    parser.add_argument("--resume", action="store_true", help="reuse completed case summaries and continue missing cases")
    parser.add_argument("--aggregate-existing", action="store_true", help="rebuild tabular outputs from completed cases")
    parser.add_argument(
        "--causal-guard",
        action="store_true",
        help="run conservative completed-period daily/weekly HTF sensitivity (full RT8 only)",
    )
    parser.add_argument(
        "--cache-duplicate-sensitivity",
        action="store_true",
        help="compare the repository BTC cache before/after timestamp de-duplication",
    )
    args = parser.parse_args()
    if (
        not args.download
        and not args.run
        and not args.aggregate_existing
        and not args.causal_guard
        and not args.cache_duplicate_sensitivity
    ):
        args.download = args.run = True
    if args.download:
        download_snapshots()
    if args.run:
        run_backtests(resume=args.resume)
    if args.aggregate_existing:
        aggregate_existing_results()
    if args.causal_guard:
        run_causal_guard(resume=args.resume)
    if args.cache_duplicate_sensitivity:
        run_repo_cache_duplicate_sensitivity()


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    main()
