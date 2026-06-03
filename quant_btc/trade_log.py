"""Trade-by-trade audit log.

Captures every trade's full lifecycle: entry → exit, with all parameters.
Outputs CSV and formatted console table.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class TradeLogEntry:
    trade_id: int
    entry_time: str
    exit_time: str
    duration: str
    direction: str  # "LONG" or "SHORT"
    module: str     # "core_long", "breakout_retest_long", etc.

    entry_price: float
    exit_price: float
    sl_price: float  # initial stop-loss
    tp_price: float  # initial take-profit (0 if none)

    position_size: float  # as fraction of equity
    position_value: float  # entry_price × |size| × equity / entry_price ≈ |size| × equity

    pnl: float
    pnl_pct: float  # PnL / position_value × 100
    return_r: float  # PnL / initial_risk

    max_mfe_pct: float  # max favorable excursion (%)
    max_mae_pct: float  # max adverse excursion (%)
    mfe_bar: int        # bar offset from entry to MFE
    mae_bar: int        # bar offset from entry to MAE

    entry_regime: str   # "Bull" / "Bear" / "Ranging" / "Compression" / "HighRisk"
    exit_reason: str    # "sl_hit" / "tp_hit" / "trail" / "time_stop" / "signal" / "trend_exit" / "giveback" / "v_reversal" / "waterfall"


def extract_trade_log(
    stats: pd.Series,
    raw_4h: pd.DataFrame,
    output_dir: str | Path = "backtest_results",
    run_name: str = "latest",
) -> tuple[list[TradeLogEntry], Path]:
    """Extract detailed trade log from backtest results.

    Returns list of TradeLogEntry and path to saved CSV.
    """
    trades = stats.get("_trades")
    if trades is None or trades.empty:
        return [], Path(".")

    equity_curve = stats.get("_equity_curve")
    entries = []

    for idx, t in trades.iterrows():
        # Basic fields
        entry_time = t["EntryTime"]
        exit_time = t["ExitTime"]
        dur = str(t.get("Duration", ""))
        direction = "LONG" if t["Size"] > 0 else "SHORT"
        module = str(t.get("Tag", "unknown"))
        entry_price = float(t["EntryPrice"])
        exit_price = float(t["ExitPrice"])
        size = float(t["Size"])
        pnl = float(t["PnL"])
        sl_price = float(t.get("SL", 0) or 0)
        tp_price = float(t.get("TP", 0) or 0)

        # Position value: size fraction × initial equity
        pos_value = abs(size) * 100_000.0

        # PnL %
        pnl_pct = (pnl / pos_value * 100) if pos_value > 0 else 0.0

        # Return in R (initial risk)
        risk_pct = abs(entry_price - sl_price) / entry_price if sl_price > 0 and entry_price > 0 else 0.01
        if risk_pct > 0:
            return_r = pnl_pct / risk_pct  # approximate
        else:
            return_r = 0.0

        # MAE / MFE from raw OHLC
        mask = (raw_4h.index >= entry_time) & (raw_4h.index <= exit_time)
        period = raw_4h[mask]
        mae_pct = 0.0; mfe_pct = 0.0; mfe_bar = 0; mae_bar = 0
        if len(period) > 1:
            if direction == "LONG":
                mfe_pct = (period["High"].max() - entry_price) / entry_price * 100
                mae_pct = (period["Low"].min() - entry_price) / entry_price * 100
                mfe_bar = period["High"].idxmax()
                mae_bar = period["Low"].idxmin()
            else:
                mfe_pct = (entry_price - period["Low"].min()) / entry_price * 100
                mae_pct = (entry_price - period["High"].max()) / entry_price * 100
                mfe_bar = period["Low"].idxmin()
                mae_bar = period["High"].idxmax()
            # Bar offsets (searchsorted avoids duplicate index issues)
            entry_pos = raw_4h.index.searchsorted(entry_time)
            mfe_bar_idx = raw_4h.index.searchsorted(mfe_bar)
            mae_bar_idx = raw_4h.index.searchsorted(mae_bar)
            mfe_bar = max(0, mfe_bar_idx - entry_pos)
            mae_bar = max(0, mae_bar_idx - entry_pos)

        # Exit reason (inferred from exit price relative to SL/TP)
        if sl_price > 0:
            if direction == "LONG" and exit_price <= sl_price * 1.005:
                exit_reason = "sl_hit"
            elif direction == "SHORT" and exit_price >= sl_price * 0.995:
                exit_reason = "sl_hit"
            elif tp_price > 0:
                if direction == "LONG" and exit_price >= tp_price * 0.995:
                    exit_reason = "tp_hit"
                elif direction == "SHORT" and exit_price <= tp_price * 1.005:
                    exit_reason = "tp_hit"
                else:
                    exit_reason = "trail_or_signal"
            else:
                exit_reason = "trail_or_signal"
        else:
            exit_reason = "trend_exit"

        # Entry regime (approximate from raw 4H: d_ema direction)
        d_ema = raw_4h["Close"].ewm(span=169, adjust=False).mean()
        d_dir_val = 0
        pos = raw_4h.index.searchsorted(entry_time)
        if 0 < pos < len(d_ema):
            d_ema_pct = d_ema.pct_change().fillna(0)
            d_dir_val = 1 if d_ema_pct.iloc[pos] > 0.001 else (-1 if d_ema_pct.iloc[pos] < -0.001 else 0)
        entry_regime = "Bull" if d_dir_val > 0 else ("Bear" if d_dir_val < 0 else "Ranging")

        entries.append(TradeLogEntry(
            trade_id=idx + 1,
            entry_time=str(entry_time),
            exit_time=str(exit_time),
            duration=dur,
            direction=direction,
            module=module,
            entry_price=entry_price,
            exit_price=exit_price,
            sl_price=sl_price,
            tp_price=tp_price,
            position_size=size,
            position_value=pos_value,
            pnl=pnl,
            pnl_pct=pnl_pct,
            return_r=return_r,
            max_mfe_pct=mfe_pct,
            max_mae_pct=mae_pct,
            mfe_bar=mfe_bar,
            mae_bar=mae_bar,
            entry_regime=entry_regime,
            exit_reason=exit_reason,
        ))

    # Save CSV
    output_path = Path(output_dir) / run_name
    output_path.mkdir(parents=True, exist_ok=True)
    csv_path = output_path / "trade_log.csv"

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=asdict(entries[0]).keys())
        writer.writeheader()
        for e in entries:
            writer.writerow(asdict(e))

    return entries, csv_path


def print_trade_summary(entries: list[TradeLogEntry], max_rows: int = 20):
    """Print a formatted trade-by-trade table."""
    if not entries:
        print("\n  (No trades)\n")
        return

    header = (
        f"{'#':>4} {'Entry':<19} {'Exit':<19} {'Dir':>5} {'Module':<28} "
        f"{'Entry$':>10} {'Exit$':>10} {'SL$':>8} {'TP$':>8} "
        f"{'Size%':>6} {'PnL$':>10} {'Ret%':>7} {'R':>6} "
        f"{'MFE%':>6} {'MAE%':>6} {'Reason':<16}"
    )
    sep = "=" * len(header)

    print(f"\n{'─' * len(header)}")
    print("  TRADE-BY-TRADE AUDIT LOG")
    print(f"{'─' * len(header)}")
    print(f"  {header}")
    print(f"  {sep}")

    for e in entries[:max_rows]:
        print(
            f"  {e.trade_id:>4} {e.entry_time:<19} {e.exit_time:<19} {e.direction:>5} {e.module:<28} "
            f"${e.entry_price:>9,.2f} ${e.exit_price:>9,.2f} ${e.sl_price:>7,.2f} ${e.tp_price:>7,.2f} "
            f"{e.position_size * 100:>5.1f}% ${e.pnl:>+9,.0f} {e.pnl_pct:>+6.2f}% {e.return_r:>+5.2f} "
            f"{e.max_mfe_pct:>+5.2f}% {e.max_mae_pct:>+5.2f}% {e.exit_reason:<16}"
        )

    if len(entries) > max_rows:
        print(f"  ... ({len(entries) - max_rows} more trades)")

    # Module summary
    print(f"\n{'─' * 90}")
    print("  MODULE SUMMARY")
    print(f"  {'Module':<30} {'Trades':>6} {'PnL':>12} {'WR%':>6} {'PF':>6} {'AvgR':>7}")
    print(f"  {'-'*65}")

    from collections import defaultdict
    mod_data = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0, "r_sum": 0.0})
    for e in entries:
        d = mod_data[e.module]
        d["trades"] += 1
        d["pnl"] += e.pnl
        if e.pnl > 0:
            d["wins"] += 1
        d["r_sum"] += e.return_r

    for mod, d in sorted(mod_data.items()):
        n = d["trades"]
        wr = d["wins"] / n * 100 if n > 0 else 0
        wins_pnl = sum(e.pnl for e in entries if e.module == mod and e.pnl > 0)
        losses_pnl = abs(sum(e.pnl for e in entries if e.module == mod and e.pnl <= 0))
        pf = wins_pnl / losses_pnl if losses_pnl > 0 else float("inf")
        pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"
        avg_r = d["r_sum"] / n if n > 0 else 0
        print(f"  {mod:<30} {n:>6} ${d['pnl']:>+10,.0f} {wr:>5.1f}% {pf_str:>6} {avg_r:>+6.2f}R")
