"""Dual-Layer attribution analysis.

Breaks down the DualLayerStrategy backtest into:
- Layer: Core vs Tactical
- Module: Breakout / Pullback / Mean Reversion
- Direction: Long vs Short
- Regime: Bull / Bear / Ranging / Compression / HighRisk
- Per-module: Win rate, PF, MaxDD, avg duration, max cons loss, MAE/MFE
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class ModuleStats:
    name: str = ""
    trades: int = 0
    pnl_total: float = 0.0
    pnl_pct_total: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_return: float = 0.0
    best: float = 0.0
    worst: float = 0.0
    max_consecutive_loss: int = 0
    avg_duration: str = ""
    avg_mae: float = 0.0  # avg max adverse excursion (%)
    avg_mfe: float = 0.0  # avg max favorable excursion (%)
    avg_mfe_mae_ratio: float = 0.0


def _tag_trades(trades: pd.DataFrame) -> pd.DataFrame:
    """Normalize trade tags.  If Tag is None, mark as 'untagged'."""
    df = trades.copy()
    if "Tag" not in df.columns:
        df["Tag"] = "untagged"
    df["Tag"] = df["Tag"].fillna("untagged")
    return df


def _compute_mae_mfe(trade: pd.Series, raw_df: pd.DataFrame) -> tuple[float, float]:
    """Return (MAE%, MFE%) for a single trade using raw OHLC data."""
    entry_time = trade["EntryTime"]
    exit_time = trade["ExitTime"]
    is_long = trade["Size"] > 0
    entry_price = float(trade["EntryPrice"])

    mask = (raw_df.index >= entry_time) & (raw_df.index <= exit_time)
    period = raw_df[mask]
    if period.empty:
        return 0.0, 0.0

    if is_long:
        mae = (period["Low"].min() - entry_price) / entry_price * 100
        mfe = (period["High"].max() - entry_price) / entry_price * 100
    else:
        mae = (entry_price - period["High"].max()) / entry_price * 100
        mfe = (entry_price - period["Low"].min()) / entry_price * 100

    return float(mae), float(mfe)


def _module_stats(name: str, trades: pd.DataFrame, raw_df: pd.DataFrame) -> ModuleStats:
    """Compute per-module statistics."""
    df = trades.copy()
    if df.empty:
        return ModuleStats(name=name)

    n = len(df)
    pnl_total = float(df["PnL"].sum())
    wins = df[df["PnL"] > 0]
    losses = df[df["PnL"] <= 0]
    n_wins = len(wins)
    n_losses = len(losses)

    win_rate = n_wins / n * 100 if n > 0 else 0.0
    avg_win = float(wins["PnL"].mean()) if n_wins > 0 else 0.0
    avg_loss = float(losses["PnL"].mean()) if n_losses > 0 else 0.0
    pf = wins["PnL"].sum() / abs(losses["PnL"].sum()) if n_losses > 0 and losses["PnL"].sum() != 0 else float("inf") if n_losses == 0 and n_wins > 0 else 0.0

    # PnL% relative to start equity of first trade
    start_eq = 100_000.0
    pnl_pct_total = pnl_total / start_eq * 100 if start_eq > 0 else 0.0

    best = float(df["ReturnPct"].max()) if n > 0 else 0.0
    worst = float(df["ReturnPct"].min()) if n > 0 else 0.0

    # Max consecutive loss
    cons_loss = 0
    max_cons_loss = 0
    for _, t in df.iterrows():
        if t["PnL"] <= 0:
            cons_loss += 1
            max_cons_loss = max(max_cons_loss, cons_loss)
        else:
            cons_loss = 0

    # Avg duration
    avg_dur = str(df["Duration"].mean()) if "Duration" in df.columns and n > 0 else "N/A"

    # MAE / MFE
    maes, mfes = [], []
    for _, t in df.iterrows():
        mae, mfe = _compute_mae_mfe(t, raw_df)
        maes.append(mae)
        mfes.append(mfe)
    avg_mae = float(np.mean(maes)) if maes else 0.0
    avg_mfe = float(np.mean(mfes)) if mfes else 0.0
    mfe_mae = avg_mfe / abs(avg_mae) if abs(avg_mae) > 0.001 else 0.0

    return ModuleStats(
        name=name,
        trades=n,
        pnl_total=pnl_total,
        pnl_pct_total=pnl_pct_total,
        win_rate=win_rate,
        profit_factor=pf,
        avg_return=pnl_total / n if n > 0 else 0.0,
        best=best,
        worst=worst,
        max_consecutive_loss=max_cons_loss,
        avg_duration=avg_dur,
        avg_mae=avg_mae,
        avg_mfe=avg_mfe,
        avg_mfe_mae_ratio=mfe_mae,
    )


def analyze(stats: pd.Series, raw_df: pd.DataFrame) -> dict:
    """Run full dual-layer attribution.

    Returns a dict with keys:
      - layer_stats: dict of ModuleStats by layer
      - module_stats: dict of ModuleStats by module
      - direction_stats: dict of ModuleStats by direction
      - regime_stats: dict of ModuleStats by regime
      - total_pnl: float
    """
    trades = stats.get("_trades")
    if trades is None or trades.empty:
        return {"error": "No trades found"}

    df = _tag_trades(trades)

    # ── Layer attribution ──
    core_tags = {"core", "core_add"}
    tac_tags = {"breakout", "pullback", "meanrev"}
    core_df = df[df["Tag"].isin(core_tags)]
    tac_df = df[df["Tag"].isin(tac_tags)]

    layer_stats = {
        "core": _module_stats("Core Long", core_df, raw_df),
        "tactical": _module_stats("Tactical", tac_df, raw_df),
    }

    # ── Module attribution ──
    module_stats = {}
    for tag in ["breakout", "pullback", "meanrev", "core"]:
        sub = df[df["Tag"] == tag] if tag != "core" else core_df
        module_stats[tag] = _module_stats(tag.capitalize(), sub, raw_df)

    # ── Direction attribution ──
    long_df = df[df["Size"] > 0]
    short_df = df[df["Size"] < 0]
    direction_stats = {
        "long": _module_stats("Long", long_df, raw_df),
        "short": _module_stats("Short", short_df, raw_df),
    }

    # ── Regime attribution (approximate: match by entry date) ──
    if "_regime" in raw_df.columns:
        # We don't have _regime in raw OHLC (it's computed in init).
        # Use a simplified classification from raw prices.
        regime_stats = _regime_attribution_simple(df, raw_df)
    else:
        regime_stats = {}

    total_pnl = float(df["PnL"].sum())

    return {
        "layer_stats": layer_stats,
        "module_stats": module_stats,
        "direction_stats": direction_stats,
        "regime_stats": regime_stats,
        "total_pnl": total_pnl,
        "total_trades": len(df),
    }


def _regime_attribution_simple(trades: pd.DataFrame, raw_df: pd.DataFrame) -> dict:
    """Approximate regime attribution using daily EMA direction from raw prices."""
    # Compute daily EMA169 direction
    d_ema = raw_df["Close"].ewm(span=169, adjust=False).mean()
    d_ema_pct = d_ema.pct_change().fillna(0)
    d_dir = np.where(d_ema_pct > 0.001, 1, np.where(d_ema_pct < -0.001, -1, 0))

    # Simplified regime: Bull=close>EMA+slope>0, Bear=close<EMA+slope<0, else Ranging
    bull = (raw_df["Close"] > d_ema) & (d_dir > 0)
    bear = (raw_df["Close"] < d_ema) & (d_dir < 0)
    regime_simple = pd.Series("Ranging", index=raw_df.index)
    regime_simple[bull] = "Bull"
    regime_simple[bear] = "Bear"

    stats = {}
    for r_name in ["Bull", "Bear", "Ranging"]:
        r_indices = regime_simple[regime_simple == r_name].index
        r_trades_list = []
        for _, t in trades.iterrows():
            if t["EntryTime"] in r_indices or any(
                abs((t["EntryTime"] - ri).total_seconds()) < 14400  # within 4h
                for ri in r_indices
            ):
                r_trades_list.append(t)
        if r_trades_list:
            r_df = pd.DataFrame(r_trades_list)
            stats[r_name] = _module_stats(r_name, r_df, raw_df)
        else:
            stats[r_name] = ModuleStats(name=r_name)

    return stats


def format_report(attribution: dict) -> str:
    """Return a formatted multiline attribution report string."""
    if "error" in attribution:
        return f"\n  Attribution error: {attribution['error']}\n"

    H = "=" * 105
    h = "-" * 105

    def _row(label: str, s: ModuleStats) -> str:
        return (
            f"  {label:<18} {s.trades:>5}  {s.pnl_total:>+10,.0f}  "
            f"{s.pnl_pct_total:>+7.2f}%  {s.win_rate:>5.1f}%  "
            f"{s.profit_factor:>5.2f}  {s.best:>+7.2f}%  {s.worst:>+7.2f}%  "
            f"{s.max_consecutive_loss:>4}  "
            f"{s.avg_mae:>+6.2f}%  {s.avg_mfe:>+6.2f}%  {s.avg_mfe_mae_ratio:>5.2f}"
        )

    header = (
        f"  {'Module':<18} {'Trds':>5}  {'PnL $':>10}  {'PnL %':>7}  "
        f"{'WR%':>5}  {'PF':>5}  {'Best%':>7}  {'Worst%':>7}  "
        f"{'MCL':>4}  {'MAE%':>6}  {'MFE%':>6}  {'MFE/MAE':>7}"
    )

    sections = [
        f"\n{H}",
        "  DUAL-LAYER ATTRIBUTION REPORT",
        H,
        f"\n  Total Trades: {attribution['total_trades']}  |  Total PnL: ${attribution['total_pnl']:,.0f}",
    ]

    # ── Layer ──
    sections.append(f"\n  {h}")
    sections.append("  LAYER ATTRIBUTION (Core vs Tactical)")
    sections.append(f"  {h}")
    sections.append(header)
    sections.append(f"  {'-'*103}")
    for key in ["core", "tactical"]:
        sections.append(_row(key.capitalize(), attribution["layer_stats"][key]))

    # ── Module ──
    sections.append(f"\n  {h}")
    sections.append("  MODULE ATTRIBUTION (by entry signal)")
    sections.append(f"  {h}")
    sections.append(header)
    sections.append(f"  {'-'*103}")
    for key in ["breakout", "pullback", "meanrev", "core"]:
        sections.append(_row(key.capitalize(), attribution["module_stats"][key]))

    # ── Direction ──
    sections.append(f"\n  {h}")
    sections.append("  DIRECTION ATTRIBUTION")
    sections.append(f"  {h}")
    sections.append(header)
    sections.append(f"  {'-'*103}")
    for key in ["long", "short"]:
        sections.append(_row(key.capitalize(), attribution["direction_stats"][key]))

    # ── Regime ──
    if attribution.get("regime_stats"):
        sections.append(f"\n  {h}")
        sections.append("  REGIME ATTRIBUTION (approximate, by entry bar)")
        sections.append(f"  {h}")
        sections.append(header)
        sections.append(f"  {'-'*103}")
        for key, s in attribution["regime_stats"].items():
            sections.append(_row(key, s))

    sections.append(f"\n{h}")
    sections.append(
        "  MCL = Max Consecutive Loss  |  MAE = Avg Max Adverse Excursion  |  "
        "MFE = Avg Max Favorable Excursion"
    )
    sections.append(H)

    return "\n".join(sections)
