from __future__ import annotations

import os
from dataclasses import dataclass

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

matplotlib.use("Agg")

plt.rcParams.update({
    "figure.facecolor": "#0d1117",
    "axes.facecolor": "#0d1117",
    "axes.edgecolor": "#30363d",
    "axes.labelcolor": "#c9d1d9",
    "text.color": "#c9d1d9",
    "xtick.color": "#8b949e",
    "ytick.color": "#8b949e",
    "grid.color": "#21262d",
    "legend.edgecolor": "#30363d",
    "legend.facecolor": "#161b22",
    "legend.labelcolor": "#c9d1d9",
    "figure.titlesize": 14,
    "axes.titlesize": 12,
    "savefig.dpi": 150,
    "savefig.bbox": "tight",
    "savefig.facecolor": "#0d1117",
})

SEP_DOUBLE = "=" * 120
SEP_SINGLE = "-" * 120
SEP_SECTION = "-" * 56


@dataclass
class TradeRecord:
    entry_time: str
    exit_time: str
    direction: str
    entry_price: float
    exit_price: float
    size_pct: float
    pnl: float
    pnl_pct: float
    is_win: bool
    duration_days: float = 0.0


def _extract_trades(stats: pd.Series) -> list[TradeRecord]:
    trades = []
    df = stats.get("_trades")
    if df is None or df.empty:
        return trades
    for _, t in df.iterrows():
        direction = "Long" if t["Size"] > 0 else "Short"
        pnl = float(t["PnL"])
        # Recalculate return% from PnL / entry-value since FractionalBacktest
        # modifies Size/EntryPrice *after* stats computation, leaving stale ReturnPct.
        entry_value = abs(float(t["EntryPrice"]) * float(t["Size"]))
        pnl_pct = (pnl / entry_value * 100) if entry_value > 0 else 0.0
        dur = t.get("Duration", pd.Timedelta(0))
        if isinstance(dur, pd.Timedelta):
            duration_days = dur.total_seconds() / 86400
        else:
            duration_days = float(dur) * 4 / 24
        trades.append(TradeRecord(
            entry_time=str(t["EntryTime"]),
            exit_time=str(t["ExitTime"]),
            direction=direction,
            entry_price=float(t["EntryPrice"]),
            exit_price=float(t["ExitPrice"]),
            size_pct=float(t["Size"]) * 100,
            pnl=pnl,
            pnl_pct=pnl_pct,
            is_win=pnl > 0,
            duration_days=duration_days,
        ))
    return trades


def _trade_table(trades: list[TradeRecord]) -> str:
    if not trades:
        return "\n  (No trades executed)\n"

    header = (
        f"{'#':>3}  {'Entry':<19}  {'Exit':<19}  {'Dir':>5}  "
        f"{'Entry$':>10}  {'Exit$':>10}  {'PnL$':>10}  {'Ret%':>8}  "
        f"{'Days':>7}  {'Win':>5}"
    )
    sep = "-" * len(header)
    lines = [f"\n  {header}", f"  {sep}"]

    for i, t in enumerate(trades, 1):
        lines.append(
            f"  {i:>3}  {t.entry_time:<19}  {t.exit_time:<19}  {t.direction:>5}  "
            f"{t.entry_price:>10.2f}  {t.exit_price:>10.2f}  {t.pnl:>+10.2f}  "
            f"{t.pnl_pct:>+7.2f}%  {t.duration_days:>6.1f}  {'Yes' if t.is_win else 'No':>5}"
        )
    return "\n".join(lines)


def _trade_summary(trades: list[TradeRecord]) -> str:
    if not trades:
        return ""

    n = len(trades)
    wins = [t for t in trades if t.is_win]
    losses = [t for t in trades if not t.is_win]
    longs = [t for t in trades if t.direction == "Long"]
    shorts = [t for t in trades if t.direction == "Short"]

    avg_win = np.mean([t.pnl_pct for t in wins]) if wins else 0
    avg_loss = np.mean([t.pnl_pct for t in losses]) if losses else 0
    best = max(trades, key=lambda t: t.pnl_pct)
    worst = min(trades, key=lambda t: t.pnl_pct)

    win_pnl_sum = sum(t.pnl for t in wins)
    loss_pnl_sum = sum(abs(t.pnl) for t in losses)

    # Win/Loss streaks
    streak = 0
    max_win_streak = 0
    max_loss_streak = 0
    for t in trades:
        if t.is_win:
            streak = streak + 1 if streak >= 0 else 1
            max_win_streak = max(max_win_streak, streak)
        else:
            streak = streak - 1 if streak <= 0 else -1
            max_loss_streak = max(max_loss_streak, -streak)

    lines = [
        "",
        f"  {SEP_SECTION} Trade Analysis {SEP_SECTION}",
        "",
        f"  Total Trades:  {n:>5}          "
        f"Long: {len(longs):>4} ({len(longs)/n*100:.0f}%)          "
        f"Short: {len(shorts):>4} ({len(shorts)/n*100:.0f}%)",
        "",
        f"  Win Rate:      {len(wins)/n*100:>5.1f}%         "
        f"Avg Win: {avg_win:>+8.2f}%          "
        f"Avg Loss: {avg_loss:>+8.2f}%",
        f"  Profit Factor:  {win_pnl_sum/loss_pnl_sum:>6.2f}" if losses else "  Profit Factor:  N/A (no losses)",
        f"  Best Trade:     {best.pnl_pct:>+8.2f}%  ({best.entry_time} | {best.direction})",
        f"  Worst Trade:    {worst.pnl_pct:>+8.2f}%  ({worst.entry_time} | {worst.direction})",
        f"  Max Win Streak:  {max_win_streak}          Max Loss Streak: {max_loss_streak}",
        "",
        f"  Avg Duration:    {np.mean([t.duration_days for t in trades]):.1f} days         "
        f"Total PnL: ${sum(t.pnl for t in trades):,.2f}",
    ]
    return "\n".join(lines)


def _equity_drawdown_chart(equity_curve: pd.Series, output_dir: str) -> str:
    peak = equity_curve.cummax()
    drawdown = (equity_curve - peak) / peak * 100

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 8), height_ratios=[2.5, 1],
                                   gridspec_kw={"hspace": 0.08})

    ax1.plot(equity_curve.index, equity_curve.values, color="#58a6ff", linewidth=1.2)
    ax1.fill_between(equity_curve.index, equity_curve.values, equity_curve.values[0],
                     alpha=0.15, color="#58a6ff")
    ax1.axhline(y=equity_curve.values[0], color="#8b949e", linewidth=0.8, linestyle="--", alpha=0.5)
    ax1.set_ylabel("Equity ($)", color="#c9d1d9")
    ax1.set_title("Equity Curve & Drawdown", color="#c9d1d9", fontweight="bold")
    ax1.grid(True, alpha=0.25)
    ax1.legend(["Equity", "Initial Capital"], loc="upper left",
               framealpha=0.85, fontsize=8)

    final_eq = equity_curve.values[-1]
    init_eq = equity_curve.values[0]
    ax1.annotate(f"${final_eq:,.0f}\n({(final_eq/init_eq-1)*100:+.1f}%)",
                xy=(equity_curve.index[-1], final_eq),
                xytext=(15, 0), textcoords="offset points",
                color="#58a6ff", fontsize=9, va="center",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#161b22", edgecolor="#30363d", alpha=0.9))

    ax2.fill_between(drawdown.index, drawdown.values, 0, color="#f85149", alpha=0.6)
    ax2.plot(drawdown.index, drawdown.values, color="#f85149", linewidth=0.8)
    ax2.set_ylabel("Drawdown (%)", color="#c9d1d9")
    ax2.set_xlabel("Date", color="#c9d1d9")
    ax2.grid(True, alpha=0.25)
    max_dd = drawdown.min()
    ax2.annotate(f"Max DD: {max_dd:.1f}%",
                xy=(drawdown.idxmin(), max_dd),
                xytext=(0, -18), textcoords="offset points",
                color="#f85149", fontsize=9, ha="center",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="#161b22", edgecolor="#30363d", alpha=0.9))

    path = os.path.join(output_dir, "equity_drawdown.png")
    fig.savefig(path)
    plt.close(fig)
    return path


def _monthly_returns_heatmap(equity_curve: pd.Series, output_dir: str) -> str | None:
    monthly = equity_curve.resample("ME").last().pct_change().dropna() * 100

    if len(monthly) < 2:
        return None

    monthly.index = monthly.index.tz_localize(None).to_period("M")
    df_ret = monthly.to_frame("Return")
    df_ret["Year"] = [m.year for m in monthly.index]
    df_ret["Month"] = [m.month for m in monthly.index]

    pivot = df_ret.pivot(index="Year", columns="Month", values="Return")
    pivot = pivot.reindex(columns=range(1, 13))

    fig, ax = plt.subplots(figsize=(14, max(3, len(pivot) * 0.9)))
    im = ax.imshow(pivot.values, cmap="RdYlGn", aspect="auto", vmin=-15, vmax=15)

    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    for y_idx in range(len(pivot)):
        for m_idx in range(12):
            val = pivot.values[y_idx, m_idx]
            if not np.isnan(val):
                color = "#0d1117" if abs(val) > 8 else "#c9d1d9"
                ax.text(m_idx, y_idx, f"{val:+.1f}%", ha="center", va="center",
                        fontsize=9, fontweight="bold", color=color)

    ax.set_xticks(range(12))
    ax.set_xticklabels(month_names)
    ax.set_yticks(range(len(pivot)))
    ax.set_yticklabels(pivot.index)
    ax.set_title("Monthly Returns Heatmap (%)", color="#c9d1d9", fontweight="bold")

    cbar = fig.colorbar(im, ax=ax, fraction=0.02, pad=0.04)
    cbar.ax.yaxis.set_tick_params(color="#8b949e")
    cbar.outline.set_edgecolor("#30363d")

    path = os.path.join(output_dir, "monthly_returns.png")
    fig.savefig(path)
    plt.close(fig)
    return path


def _rolling_sharpe_chart(equity_curve: pd.Series, window: int, output_dir: str) -> str | None:
    daily_ret = equity_curve.resample("24h").last().ffill().pct_change().dropna()
    if len(daily_ret) < window:
        return None

    rolling_sharpe = daily_ret.rolling(window).apply(
        lambda x: (x.mean() / x.std() * np.sqrt(365)) if x.std() > 0 else 0
    )

    fig, ax = plt.subplots(figsize=(16, 3.5))
    ax.plot(rolling_sharpe.index, rolling_sharpe.values, color="#7ee787", linewidth=1.2)
    ax.axhline(y=0, color="#8b949e", linewidth=0.8, linestyle="--", alpha=0.5)
    ax.fill_between(rolling_sharpe.index, rolling_sharpe.values, 0,
                    where=(rolling_sharpe.values >= 0), alpha=0.15, color="#7ee787")
    ax.fill_between(rolling_sharpe.index, rolling_sharpe.values, 0,
                    where=(rolling_sharpe.values < 0), alpha=0.15, color="#f85149")
    ax.set_ylabel("Sharpe", color="#c9d1d9")
    ax.set_title(f"Rolling {window}-Day Sharpe Ratio", color="#c9d1d9", fontweight="bold")
    ax.grid(True, alpha=0.25)

    path = os.path.join(output_dir, "rolling_sharpe.png")
    fig.savefig(path)
    plt.close(fig)
    return path


def _trade_pnl_distribution(trades: list[TradeRecord], output_dir: str) -> str | None:
    if len(trades) < 2:
        return None

    pnls = [t.pnl_pct for t in trades]
    colors = ["#f85149" if p < 0 else "#7ee787" for p in pnls]

    fig, ax = plt.subplots(figsize=(14, 4))
    ax.bar(range(len(pnls)), pnls, color=colors, alpha=0.85, edgecolor="#30363d", linewidth=0.5)
    ax.axhline(y=0, color="#8b949e", linewidth=0.8)
    ax.set_xlabel("Trade #", color="#c9d1d9")
    ax.set_ylabel("Return (%)", color="#c9d1d9")
    ax.set_title("Trade Returns Distribution", color="#c9d1d9", fontweight="bold")
    ax.grid(True, alpha=0.25, axis="y")

    path = os.path.join(output_dir, "trade_distribution.png")
    fig.savefig(path)
    plt.close(fig)
    return path


def generate_report(stats: pd.Series, bt, output_dir: str = "backtest_results") -> str:
    """Generate comprehensive backtest report with charts and formatted output.

    Returns the report as a formatted string and saves charts to output_dir.
    """
    os.makedirs(output_dir, exist_ok=True)

    trades = _extract_trades(stats)
    equity_curve = stats["_equity_curve"]["Equity"]
    init_equity = float(equity_curve.iloc[0])

    # -- Performance --
    perf_lines = [
        f"  Period:       {stats['Start']}  ->  {stats['End']}",
        f"  Duration:     {stats['Duration']}",
        f"  Exposure:     {stats['Exposure Time [%]']:.2f}%",
        f"  Start Equity: ${init_equity:,.2f}",
        f"  Final Equity: ${stats['Equity Final [$]']:,.2f}",
        f"  Equity Peak:  ${stats['Equity Peak [$]']:,.2f}",
        f"  Commission:   ${stats['Commissions [$]']:,.2f}",
    ]

    # -- Returns --
    ret_lines = [
        f"  Total Return:       {stats['Return [%]']:>+10.2f}%",
        f"  Buy & Hold Return:  {stats['Buy & Hold Return [%]']:>+10.2f}%",
        f"  Annual Return:      {stats['Return (Ann.) [%]']:>+10.2f}%",
        f"  CAGR:               {stats['CAGR [%]']:>+10.2f}%",
        f"  Alpha:              {stats['Alpha [%]']:>+10.2f}%",
        f"  Beta:               {stats['Beta']:>10.4f}",
    ]

    # -- Risk --
    risk_lines = [
        f"  Sharpe Ratio:       {stats['Sharpe Ratio']:>10.4f}",
        f"  Sortino Ratio:      {stats['Sortino Ratio']:>10.4f}",
        f"  Calmar Ratio:       {stats['Calmar Ratio']:>10.4f}",
        f"  Max Drawdown:       {stats['Max. Drawdown [%]']:>+10.2f}%",
        f"  Avg Drawdown:       {stats['Avg. Drawdown [%]']:>+10.2f}%",
        f"  Max DD Duration:    {str(stats['Max. Drawdown Duration']):>10s}",
        f"  Avg DD Duration:    {str(stats['Avg. Drawdown Duration']):>10s}",
        f"  Volatility (Ann.):  {stats['Volatility (Ann.) [%]']:>10.2f}%",
    ]

    # -- Trade Stats --
    trade_lines = [
        f"  Total Trades:       {stats['# Trades']:>10.0f}",
        f"  Win Rate:           {stats['Win Rate [%]']:>10.2f}%",
        f"  Best Trade:         {stats['Best Trade [%]']:>+10.2f}%",
        f"  Worst Trade:        {stats['Worst Trade [%]']:>+10.2f}%",
        f"  Avg Trade:          {stats['Avg. Trade [%]']:>+10.2f}%",
        f"  Max Trade Duration: {str(stats['Max. Trade Duration']):>10s}",
        f"  Avg Trade Duration: {str(stats['Avg. Trade Duration']):>10s}",
        f"  Profit Factor:      {stats['Profit Factor']:>10.2f}",
        f"  Expectancy:         {stats['Expectancy [%]']:>+10.2f}%",
        f"  SQN:                {stats['SQN']:>10.4f}",
    ]

    # -- Build report --
    sections = [
        f"\n{SEP_DOUBLE}",
        "  BITCOIN QUANTITATIVE STRATEGY -- BACKTEST REPORT",
        "  Strategy: WeightedSignalStrategy | Symbol: BTC/USDT",
        "  Config:   EMA(55/69/144/169) + MACD(12/26/9) | HTF: Daily(169) + Weekly(169)",
        SEP_DOUBLE,

        f"\n  {SEP_SECTION} PERFORMANCE {SEP_SECTION}",
        "\n".join(perf_lines),

        f"\n  {SEP_SECTION} RETURNS {SEP_SECTION}",
        "\n".join(ret_lines),

        f"\n  {SEP_SECTION} RISK {SEP_SECTION}",
        "\n".join(risk_lines),

        f"\n  {SEP_SECTION} TRADE STATS {SEP_SECTION}",
        "\n".join(trade_lines),

        f"\n  {SEP_SECTION} TRADE LOG {SEP_SECTION}",
        _trade_table(trades),
        _trade_summary(trades),

        f"\n  {SEP_SECTION} CHARTS {SEP_SECTION}",
    ]

    # Generate charts
    chart_results = []

    for name, fn in [
        ("Equity & Drawdown", lambda: _equity_drawdown_chart(equity_curve, output_dir)),
        ("Monthly Returns", lambda: _monthly_returns_heatmap(equity_curve, output_dir)),
        ("Rolling Sharpe (30D)", lambda: _rolling_sharpe_chart(equity_curve, 30, output_dir)),
        ("Trade Distribution", lambda: _trade_pnl_distribution(trades, output_dir)),
    ]:
        try:
            path = fn()
            if path:
                chart_results.append(f"    {name:<22} {path}")
        except Exception as exc:
            chart_results.append(f"    {name:<22} ERROR: {exc}")

    sections.append("\n".join(chart_results))

    sections.append(f"\n{SEP_DOUBLE}")
    sections.append(f"  Charts saved to: {os.path.abspath(output_dir)}")
    sections.append(SEP_DOUBLE)

    return "\n".join(sections)
