"""Short system metrics analysis."""
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
raw_close = raw["Close"]

print("=" * 90)
print("  SHORT SYSTEM METRICS")
print("=" * 90)

# 1. Top Watch signals
top_score = df["_top_exhaustion_score"] if "_top_exhaustion_score" in df.columns else pd.Series(dtype=float)
dt_signal = df["_double_top_signal"] if "_double_top_signal" in df.columns else pd.Series(dtype=bool)
bull_guard = df["_bull_guard"] if "_bull_guard" in df.columns else pd.Series(dtype=bool)
top_watch = (top_score >= 70) & dt_signal
print("\n1. Top Watch Signals")
print(f"   Double top + neckline break:     {int(dt_signal.sum()):>6}")
print(f"   Score >= 70 + DT + NL:           {int(top_watch.sum()):>6}")
print(f"   Active Bull Guard bars:          {int(bull_guard.sum()):>6} ({(bull_guard.sum()/len(bull_guard)*100):.1f}%)")
if top_watch.sum() > 0:
    blocked = (top_watch & bull_guard).sum()
    print(f"   Top Watch blocked by Bull Guard: {int(blocked):>6}")

# 2. Probe Short stats
bear_cores = shorts[shorts["Tag"] == "bear_core"] if "Tag" in shorts.columns and len(shorts) > 0 else pd.DataFrame()
crashes = shorts[shorts["Tag"] == "crash"] if "Tag" in shorts.columns and len(shorts) > 0 else pd.DataFrame()

if len(bear_cores) > 0:
    bear_cores = bear_cores.sort_values("EntryTime")
    # Probes = first entry in each cluster (entries within 5 bars)
    probes_list = []
    confs_list = []
    last_entry_bar = -100
    for _, t in bear_cores.iterrows():
        bar_idx = df.index.get_loc(t["EntryTime"]) if t["EntryTime"] in df.index else -1
        if bar_idx - last_entry_bar > 5:
            probes_list.append(t)
            last_entry_bar = bar_idx
        else:
            confs_list.append(t)
    probes = pd.DataFrame(probes_list) if probes_list else pd.DataFrame()
    confirms = pd.DataFrame(confs_list) if confs_list else pd.DataFrame()

    print("\n2. Probe Short Stats")
    print(f"   Bear core trades:                {len(bear_cores):>6}")
    print(f"   Probe entries (Stage 1):         {len(probes):>6}")
    print(f"   Confirm/Add entries:             {len(confirms):>6}")
    if len(probes) > 0:
        probe_wins = int((probes["PnL"] > 0).sum())
        probe_losses = int((probes["PnL"] <= 0).sum())
        print(f"   Probe win rate:                  {probe_wins/len(probes)*100:>5.1f}%")
        if probe_wins > 0:
            print(f"   Probe avg win:                  ${probes[probes['PnL']>0]['PnL'].mean():>8,.0f}")
        if probe_losses > 0:
            print(f"   Probe avg loss:                 ${probes[probes['PnL']<=0]['PnL'].mean():>8,.0f}")
        print(f"   Probe total PnL:                ${probes['PnL'].sum():>8,.0f}")

    # 3. Probe -> Bear Core conversion
    print("\n3. Probe -> Bear Core Conversion")
    if len(probes) > 0:
        print(f"   Probes followed by confirms:     {len(confirms):>6}")
        print(f"   Conversion rate:                 {len(confirms)/len(probes)*100:>5.1f}%")

# 4. Bear Core avg holding time
print("\n4. Bear Core Duration")
if len(bear_cores) > 0:
    bc_dur = bear_cores["Duration"].mean()
    print(f"   Avg holding time:                {str(bc_dur)[:19]}")
    print(f"   Max holding time:                {str(bear_cores['Duration'].max())[:19]}")
    print(f"   Min holding time:                {str(bear_cores['Duration'].min())[:19]}")

# 5. Bear Core capture ratio
print("\n5. Bear Core Drawdown Capture (top 5 by capture rate)")
captures_data = []
for _, t in bear_cores.iterrows():
    entry_t = t["EntryTime"]; exit_t = t["ExitTime"]
    mask = (raw.index >= entry_t) & (raw.index <= exit_t)
    period = raw[mask]
    if len(period) > 1:
        entry_price = float(period["Close"].iloc[0])
        min_price = float(period["Low"].min())
        exit_price = float(period["Close"].iloc[-1])
        max_drop = (entry_price - min_price) / entry_price * 100
        actual = (entry_price - exit_price) / entry_price * 100
        capture = actual / max_drop * 100 if max_drop > 0 else 0
        captures_data.append((entry_t, max_drop, actual, capture))

captures_data.sort(key=lambda x: abs(x[3]), reverse=True)
for entry_t, md, act, cap in captures_data[:8]:
    print(f"  {str(entry_t)[:19]} maxDrop={md:+.1f}% actual={act:+.1f}% capture={cap:.0f}%")
if captures_data:
    avg_cap = np.mean([c[3] for c in captures_data])
    print(f"  AVERAGE capture rate: {avg_cap:.0f}%")

# 6. MFE capture rate
print("\n6. MFE Capture Rate (Actual / Max Favorable)")
all_captures = []
for _, t in shorts.iterrows():
    entry_p = float(t["EntryPrice"]); exit_p = float(t["ExitPrice"])
    entry_t = t["EntryTime"]; exit_t = t["ExitTime"]
    mask = (raw.index >= entry_t) & (raw.index <= exit_t)
    period = raw[mask]
    if len(period) > 1:
        mfe_price = float(period["Low"].min())
        mfe = (entry_p - mfe_price) / entry_p * 100
        actual = (entry_p - exit_p) / entry_p * 100
        capture = actual / mfe * 100 if mfe > 0 else 0
        all_captures.append(capture)
        tag = str(t.get("Tag", "?"))
        print(f"  {tag:<12} {str(entry_t)[:19]} MFE={mfe:+.1f}% actual={actual:+.1f}% capture={capture:.0f}%")
if all_captures:
    print(f"  AVERAGE MFE capture: {np.mean(all_captures):.0f}%")

# 7. After exit continuation
print("\n7. Post-Exit Continuation")
if len(shorts) > 0:
    cont = 0; rev = 0; total = 0
    for _, t in shorts.iterrows():
        exit_t = t["ExitTime"]; exit_p = float(t["ExitPrice"])
        future = raw[raw.index > exit_t].head(20)
        if len(future) > 5:
            total += 1
            if float(future["Low"].min()) < exit_p * 0.98:
                cont += 1
            elif float(future["High"].max()) > exit_p * 1.02:
                rev += 1
    print(f"   Continued decline (>2%):         {cont:>6}")
    print(f"   Reversed rally (>2%):            {rev:>6}")
    if cont + rev > 0:
        print(f"   Continuation rate:               {cont/(cont+rev)*100:>5.1f}%")

# 8. After SL, re-signal rate
print("\n8. After Stop-Loss, Re-Signal Rate")
sl_exits = shorts[shorts["PnL"] < 0].copy()
if len(sl_exits) > 0:
    re_signaled = 0
    for _, t in sl_exits.iterrows():
        exit_t = t["ExitTime"]
        tag = str(t.get("Tag", ""))
        # Check if same tag fires again within 50 bars
        future_bars = df[df.index > exit_t].head(50)
        if len(future_bars) > 0:
            if tag == "bear_core" and future_bars["_double_top_signal"].any():
                re_signaled += 1
            elif tag == "crash" and (future_bars["score_crash_short"] >= 75).any():
                re_signaled += 1
    print(f"   SL exits:                        {len(sl_exits):>6}")
    print(f"   Re-signaled within 50 bars:      {re_signaled:>6}")
    print(f"   Re-signal rate:                  {re_signaled/len(sl_exits)*100:>5.1f}%")

# 9. Bull market false shorts
print("\n9. Bull Market False Short Losses")
d_ema = df["d_ema"]
d_dir = pd.Series(
    np.where(d_ema.pct_change(1).fillna(0) > 0.001, 1,
             np.where(d_ema.pct_change(1).fillna(0) < -0.001, -1, 0)),
    index=df.index,
)
bull_entry_losses = 0.0
bull_entry_count = 0
for _, t in shorts.iterrows():
    entry_t = t["EntryTime"]
    if entry_t in d_dir.index and d_dir.get(entry_t, 0) > 0 and t["PnL"] < 0:
        bull_entry_losses += float(t["PnL"])
        bull_entry_count += 1
print(f"   Shorts entered when dEMA rising: {bull_entry_count:>6}")
print(f"   Total loss from these:           ${bull_entry_losses:>8,.0f}")
all_short_losses = shorts[shorts["PnL"] < 0]["PnL"].sum()
if all_short_losses != 0:
    print(f"   All short losses:                ${all_short_losses:>8,.0f}")
    print(f"   Bull-entry % of all losses:      {abs(bull_entry_losses/all_short_losses)*100:>5.1f}%")
