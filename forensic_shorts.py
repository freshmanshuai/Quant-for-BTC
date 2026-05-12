"""Forensic analysis of worst short trades."""
from quant_btc.config import RiskConfig, BacktestConfig
from quant_btc.data import fetch_ohlcv, fetch_derivative_data
from quant_btc.strategy import prepare_features, run_backtest, compute_derivative_bonus
import pandas as pd, numpy as np, warnings; warnings.filterwarnings("ignore")

raw = fetch_ohlcv("BTC/USDT", "4h", market_type="swap", exchange_id="binance", proxy_url="http://127.0.0.1:7897")
df = prepare_features(raw, BacktestConfig())
deriv = fetch_derivative_data("BTC/USDT", exchange_id="binance", proxy_url="http://127.0.0.1:7897")
df["_short_deriv_bonus"] = compute_derivative_bonus(df, deriv)

stats, _ = run_backtest(df, BacktestConfig(), strategy_name="dual", risk_cfg=RiskConfig())
trades = stats.get("_trades")
shorts = trades[trades["Size"] < 0].copy() if trades is not None else pd.DataFrame()

# Find 2 worst shorts by PnL
shorts_sorted = shorts.sort_values("PnL")
worst2 = shorts_sorted.head(2)

print("=" * 100)
print("  FORENSIC ANALYSIS — TWO WORST SHORT TRADES")
print("=" * 100)

# For each trade, compute all metrics
for idx, (_, t) in enumerate(worst2.iterrows()):
    entry_time = t["EntryTime"]
    exit_time = t["ExitTime"]
    entry_price = float(t["EntryPrice"])
    exit_price = float(t["ExitPrice"])
    pnl = float(t["PnL"])
    size = float(t["Size"])
    tag = str(t.get("Tag", "?"))
    dur = str(t["Duration"])[:19]

    # Find the bar indices
    mask = (raw.index >= entry_time) & (raw.index <= exit_time)
    period = raw[mask]
    entry_bar_idx = raw.index.get_loc(entry_time) if entry_time in raw.index else -1
    exit_bar_idx = raw.index.get_loc(exit_time) if exit_time in raw.index else -1
    bars_held = exit_bar_idx - entry_bar_idx if entry_bar_idx >= 0 and exit_bar_idx >= 0 else len(period)

    # Compute R multiples
    # Initial risk = |entry - SL| * size (in dollar terms)
    # For shorts: SL is above entry
    # Estimate SL from position sizing: size * entry = position_value
    # risk_pct typically ~0.20% for bear core (0.50% × 0.40)
    # risk_amount = equity × risk_pct
    # But we need the ACTUAL SL that was set. We don't have it saved, so estimate.
    # From the position sizing formula: size = risk_pct / stop_pct
    # stop_pct = risk_pct / size  (approximately)
    est_risk_pct = 0.0020  # 0.20% for bear core probe
    est_stop_pct = est_risk_pct / abs(size) if abs(size) > 0 else 0.05
    est_sl_price = entry_price * (1 + est_stop_pct)
    est_risk_amount = abs(size) * entry_price * est_stop_pct
    # Better: use the actual PnL and estimate from there
    # For a short: PnL = (entry - exit) * units
    # units = abs(size) * equity_at_entry / entry
    # We don't have equity_at_entry, so let's use the backtest's initial equity
    init_eq = 100_000
    est_units = abs(size) * init_eq / entry_price  # approximate
    est_risk_amount = abs(pnl)  # not useful

    # Actually, let's compute MFE/MAE directly from price data
    if len(period) > 0:
        mfe_price = float(period["Low"].min())   # best price for short
        mae_price = float(period["High"].max())   # worst price for short
        mfe_pct = (entry_price - mfe_price) / entry_price * 100
        mae_pct = (entry_price - mae_price) / entry_price * 100
        realized_pct = (entry_price - exit_price) / entry_price * 100

        # Find bars to MFE and MAE
        mfe_bar = period["Low"].idxmin()
        mae_bar = period["High"].idxmax()
        bars_to_mfe = raw.index.get_loc(mfe_bar) - raw.index.get_loc(entry_time) if mfe_bar in raw.index and entry_time in raw.index else -1
        bars_to_mae = raw.index.get_loc(mae_bar) - raw.index.get_loc(entry_time) if mae_bar in raw.index and entry_time in raw.index else -1

    # Regime at entry
    entry_regime = "?"
    if entry_time in df.index:
        if "_bull_guard" in df.columns and df["_bull_guard"].get(entry_time, False):
            entry_regime = "Bull Guard (should have blocked!)"
        else:
            # Check d_ema direction
            d_ema = df["d_ema"]
            d_dir = pd.Series(
                np.where(d_ema.pct_change(1).fillna(0) > 0.001, 1,
                         np.where(d_ema.pct_change(1).fillna(0) < -0.001, -1, 0)),
                index=df.index,
            )
            dd = d_dir.get(entry_time, 0)
            # Also check weekly via resampled daily
            entry_regime = f"dEMA_dir={dd}"

    # Check if trade had a profitable period before losing
    had_profit = mfe_pct > 0.5 if len(period) > 0 else False
    profit_then_lost = had_profit and realized_pct < 0

    # Check if loss expanded after add
    # (multiple bear_core entries on same day suggest stage adds)
    same_day_shorts = shorts[
        (shorts["EntryTime"].dt.date == entry_time.date()) &
        (shorts.index != t.name)
    ] if hasattr(shorts["EntryTime"], 'dt') else pd.DataFrame()
    had_add = len(same_day_shorts) > 0

    # Estimate R multiples from price moves
    est_atr = 500.0  # rough ATR at BTC prices
    if len(period) > 1:
        actual_atr = (period["High"] - period["Low"]).mean()
        if actual_atr > 0:
            est_atr = actual_atr
    est_sl_distance = 2.5 * est_atr  # bear core SL
    est_sl = entry_price + est_sl_distance
    est_initial_risk_R = 1.0
    realized_R = mae_pct / (est_sl_distance / entry_price * 100) if est_sl_distance > 0 else 0
    max_mfe_R = mfe_pct / (est_sl_distance / entry_price * 100) if est_sl_distance > 0 else 0
    max_mae_R = mae_pct / (est_sl_distance / entry_price * 100) if est_sl_distance > 0 else 0

    print(f"\n{'─' * 100}")
    print(f"  TRADE #{idx+1}: {tag} @ {str(entry_time)[:19]}")
    print(f"{'─' * 100}")
    print(f"  entry_time:        {entry_time}")
    print(f"  exit_time:         {exit_time}")
    print(f"  module / stage:    {tag}")
    print(f"  entry_price:       ${entry_price:,.2f}")
    print(f"  exit_price:        ${exit_price:,.2f}")
    print(f"  est_sl (2.5xATR):  ${est_sl:,.0f}  (ATR≈${est_atr:,.0f})")
    print(f"  position_size:     {size:.4f} ({abs(size)*100:.1f}% equity)")
    print(f"  realized PnL:      ${pnl:,.0f}")
    print(f"  realized %:        {realized_pct:+.2f}%")
    print(f"  max_MFE:           {mfe_pct:+.2f}%  (at bar {bars_to_mfe})")
    print(f"  max_MAE:           {mae_pct:+.2f}%  (at bar {bars_to_mae})")
    print(f"  max_MFE_R:         {max_mfe_R:+.2f}R")
    print(f"  max_MAE_R:         {max_mae_R:+.2f}R")
    print(f"  realized_R:        {realized_R:+.2f}R  (approx)")
    print(f"  bars_held:         {bars_held}")
    print(f"  bars_to_MAE:       {bars_to_mae}")
    print(f"  bars_to_MFE:       {bars_to_mfe}")
    print(f"  entry_regime:      {entry_regime}")
    print(f"  had_profit_then_lost: {profit_then_lost}")
    print(f"  had_add_on_same_day:  {had_add}")
    print(f"  exit_reason:       {'SL hit?' if mae_pct > 3 else 'trail/exit signal'}")

    # Diagnostic
    print(f"\n  DIAGNOSTIC:")
    rr = abs(realized_R)
    if rr < 1.5:
        print(f"  → realized_R={rr:.1f}R < 1.5R: 止损逻辑正常，问题主要是仓位/E")
    elif rr >= 1.5:
        print(f"  → realized_R={rr:.1f}R >= 1.5R: 止损执行/滑点/回测撮合有问题")

    if max_mfe_R < 0.5 and realized_pct < -1:
        print(f"  → max_MFE_R={max_mfe_R:.1f}R < 0.5R 且大亏: 入场后从未验证方向，需要 early abort")
    elif max_mfe_R > 1.0 and realized_pct < -1:
        print(f"  → max_MFE_R={max_mfe_R:.1f}R > 1R 后大亏: 出场保护有问题，需要 MFE giveback guard")

    if had_add and pnl < -1000:
        print(f"  → 亏损发生在 confirm/add 之后: 加仓规则有问题")

    # Price path analysis
    if len(period) > 3:
        prices = period["Close"].values
        print(f"\n  PRICE PATH (first 10 bars, last 5 bars):")
        for j, p in enumerate(prices[:10]):
            pct = (entry_price - p) / entry_price * 100
            print(f"    bar {j:>3}: ${p:>10,.2f}  ({pct:+.2f}%)")
        if len(prices) > 15:
            print(f"    ...")
            for j, p in enumerate(prices[-5:]):
                idx_j = len(prices) - 5 + j
                pct = (entry_price - p) / entry_price * 100
                print(f"    bar {idx_j:>3}: ${p:>10,.2f}  ({pct:+.2f}%)")

print(f"\n{'═' * 100}")
print("  SUMMARY & RECOMMENDATIONS")
print(f"{'═' * 100}")
