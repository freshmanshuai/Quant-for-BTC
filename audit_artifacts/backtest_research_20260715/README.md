# BTC / ETH / SOL 可复现回测审计产物

本目录是 2026-07-15 对当前仓库交易系统的独立、只读源码回测产物。应用源码未修改；所有新增文件均位于本目录。

## 一键复现

在仓库根目录使用 PowerShell：

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONPATH = (Get-Location).Path
& .\.venv\Scripts\python.exe audit_artifacts\backtest_research_20260715\reproduce_backtests.py --download --run
& .\.venv\Scripts\python.exe audit_artifacts\backtest_research_20260715\reproduce_backtests.py --causal-guard
```

中断后可复用已完成 case：

```powershell
& .\.venv\Scripts\python.exe audit_artifacts\backtest_research_20260715\reproduce_backtests.py --run --resume
& .\.venv\Scripts\python.exe audit_artifacts\backtest_research_20260715\reproduce_backtests.py --causal-guard --resume
& .\.venv\Scripts\python.exe audit_artifacts\backtest_research_20260715\reproduce_backtests.py --aggregate-existing
```

## 固定环境与口径

- 代码：Git commit `2d8713a9d30fd0ad7a0e0d3791640a129a77dd3d`。
- Python：3.10.9；关键版本见 `results/environment.json`。
- 行情：Binance 官方 `data.binance.vision`，USD-M 永续合约月度归档；每个实际下载 URL、HTTP 状态、字节数和 ZIP SHA256 均在 `data_snapshots/monthly_archive_manifest.json`。
- 截止：封存月包 2026-06；4H 最后一根为 `2026-06-30 20:00 UTC`，15m 最后一根为 `2026-06-30 23:45 UTC`，不含 2026-07 未封存或未完成 K 线。
- 4H 范围：BTC/ETH `2020-01-01` 起（2019-09 至 2019-12 月包均为 404）；SOL `2020-09-14` 起。这里的“全样本”指固定来源中连续可得的封存月包样本，不等于合约绝对完整历史。
- 15m 范围：每个标的保留最近 100,000 根，即 `2023-08-24 08:00` 至 `2026-06-30 23:45 UTC`，与仓库 `load_mtf_data()` 的默认上限一致；更早时期 15m 确认缺失，策略按当前逻辑退化执行。
- 数据处理：排序后按时间戳 `keep=last` 去重。官方月包本身没有重复；仓库原有 CCXT BTC cache 的 4H/15m 则分别有 14/99 个重复时间戳，未进入主对比。
- SOL 月包缺 30 根 4H：2022-02-26 至 02-28 和 2022-04-01 至 04-02。已用同源 sealed daily archives 的 5 个日包补齐；URL/SHA256 也在同一 manifest。修复后所有三标 4H/15m 均为 0 缺口、0 非法间隔、0 非法 OHLC。
- 主策略：`dual`，因为 README 将其定义为“complete system”。字面 CLI 默认却是 `htf`，且三个标的都在首根 `next()` 因 `HTFStopStrategy` 缺 `_USE_REGIME_GATE` 而崩溃；见 `results/blocked_cases.json`。
- 初始资金：100,000 USDT。`RiskConfig(leverage=5)` 保持默认，但源码从未读取该字段；`FractionalBacktest` 也未设置保证金/爆仓模型，因此结果不能解释为真实 5 倍杠杆回测。
- 手续费：代码默认每边 4 bps，即往返 8 bps。成本场景为往返 4/8/12/20 bps；12/20 bps 可理解为默认费率加额外滑点代理，但引擎没有独立滑点模型。
- 资金费率：实际引擎扣除为 0。`funding_rate_deduction=True` 与 `funding_rate_annual=10%` 仅存在于配置、没有执行路径。结果 JSON 另给 10% 年率的 ex-post 粗略估计，不是净值重算。
- 衍生数据 bonus：三标统一强制为 0。仓库只有 BTC 2026-03 至 2026-05 的短期 funding/OI cache，若只给 BTC 使用会破坏横向比较。这是主三标唯一研究输入调整。
- 参数：其余策略和风险参数完全相同，未为 ETH/SOL 调参。代码中的 BTC 语义、硬编码信号 symbol/tag 也原样迁移，因此这是一项“未经资产适配的泛化压力测试”。

## 主结果：各自全样本、往返 8 bps

| 标的 | 可交易期 | 总收益 | CAGR | MDD | Sharpe | Sortino | Calmar | PF（引擎/有效美元PnL） | 原始/有效交易 | 有效胜率 | 最大连续亏损 | 最长回撤 | 买持收益 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | 2020-01-05—2026-06-30 | 308.77% | 24.23% | -21.65% | 1.117 | 2.106 | 1.119 | 1.506 / 1.942 | 473 / 349 | 48.14% | 7 | 629.7 天 | 684.00% |
| ETH | 2020-01-05—2026-06-30 | 402.03% | 28.22% | -30.57% | 0.852 | 1.638 | 0.923 | 1.296 / 1.550 | 453 / 314 | 47.45% | 7 | 770.7 天 | 1054.64% |
| SOL | 2020-09-20—2026-06-30 | 679.12% | 42.64% | -26.75% | 0.930 | 2.336 | 1.594 | 1.649 / 1.511 | 340 / 239 | 46.03% | 8 | 847.3 天 | 2429.02% |

“有效交易”定义为 `abs(Size) > 1e-7`。引擎输出中有 26.2%/30.7%/29.7% 的零或极小 size ghost trade；因此 backtesting.py 原始胜率与交易数会污染研究结论。策略收益、CAGR、MDD、Sharpe 等仍来自引擎净值；交易级 PF、胜率、盈亏比和连续亏损应优先看有效交易列/CSV。

有效交易的平均盈利/平均亏损绝对值比为 BTC 2.09、ETH 1.72、SOL 1.77。逐 case 的 best/worst trade、平均持有期、敞口时间、SQN 等完整指标在 `results/summary.csv` 与各 `summary.json`。

买持风险基准见 `results/buy_hold_benchmark.csv`：BTC/ETH/SOL 买持 MDD 分别为 -77.08%/-81.16%/-96.60%，Calmar 为 0.485/0.565/0.776。策略降低了回撤，但三个标的最终收益均远低于买持；ETH/SOL 的策略 Sharpe 也低于买持的 0.875/1.058。

## 同一窗口：2020-09-20 起、往返 8 bps

所有标的先用各自完整历史计算 feature，再从三者共同的首个可交易时间统一裁切。注意：`Strategy.init()` 仍会按当前引擎在裁切后的输入上重算 regime，因此共同窗口的 signal feature 保留历史 warm-up，但 regime 状态会在共同起点重新初始化；这是当前引擎限制，不应解读为完全无冷启动偏差。

| 标的 | 总收益 | CAGR | MDD | Sharpe | Sortino | Calmar | PF | 买持收益 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | 278.49% | 25.89% | -18.82% | 1.314 | 2.770 | 1.376 | 1.601 | 435.67% |
| ETH | 206.88% | 21.41% | -27.69% | 0.762 | 1.420 | 0.773 | 1.249 | 312.33% |
| SOL | 679.12% | 42.64% | -26.75% | 0.930 | 2.336 | 1.594 | 1.649 | 2429.02% |

ETH 全样本收益高度依赖 2020 年早期；共同窗口后从 402.03% 降至 206.88%。SOL 的高收益又高度集中于 2021 年（该年 +601.98%），2022 和 2024 分别为 -9.77% 和 -9.17%。

## 成本压力

| 标的 | 往返 4 bps | 8 bps（默认） | 12 bps | 20 bps |
|---|---:|---:|---:|---:|
| BTC 总收益 | 331.78% | 308.77% | 293.71% | 265.26% |
| ETH 总收益 | 419.08% | 402.03% | 385.55% | 354.20% |
| SOL 总收益 | 698.37% | 679.12% | 660.33% | 624.12% |

成本提高到往返 20 bps 后仍为正，但 BTC/ETH/SOL 相对默认总收益分别少 43.51/47.83/55.00 个百分点。该压力只改变佣金，不含盘口冲击、延迟、部分成交、强平和真实资金费率。

若对每个有效 trade 以 `|entry notional| × 持有年数 × 10%` 粗略外推资金占用成本，则 BTC/ETH/SOL 分别约 28.05k/49.69k/55.01k USDT；假设正 funding 下多头支付、空头收取，净估计约 22.18k/42.73k/47.89k。由于 partial close trade 可能重复覆盖持有区间，这些数字可能高估，只用于显示“引擎零 funding”并非无关紧要，不能直接从最终净值相减替代逐时资金费率重放。

## 模块、方向与利润集中度

- `core_long` 贡献 BTC/ETH/SOL 净利润的约 91.2%/85.5%/84.7%；全部多头贡献约 93.3%/95.4%/90.3%。系统收益主体是核心 beta，不是多模块均衡 Alpha。
- `breakout_retest_long` 只有 5/1/1 笔有效交易；`meanrev_range_long` 仅 BTC 1 笔且亏损。复杂模块多数没有形成足够样本。
- `pullback_struct_long` 三标均正贡献；`sweep_reversal_long` 在 BTC/SOL 为负；`sweep_reversal_short` 仅 BTC 为正，ETH/SOL 为负。
- 前 10 笔盈利占净利润 BTC 63.0%、ETH 94.7%、SOL 131.4%；SOL 最大单笔占净利润 35.8%。少数大交易依赖显著，尤其 SOL。
- 最长回撤约 1.7/2.1/2.3 年，无法以“最终盈利”替代稳定性评价。

## HTF 因果护栏敏感性

仓库 `htf_ema()` 把当日最终收盘聚合到当日早期 4H bar，存在高周期 availability leak。`--causal-guard` 仅在运行时将 feature engine 与 RegimeModel 的日/周 HTF EMA 整体后移一个完整周期；138 个“截断未来后当前值不变”断言通过。15m 切片只做 `searchsorted` 性能等价替换，并对约 600 个旧/新切片做 frame equality。应用源码、其他信号、参数、成本均未更改。

| 标的 | 原总收益 | 护栏总收益 | 护栏 CAGR | 原 MDD | 护栏 MDD | 原 Sharpe | 护栏 Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | 308.77% | 184.96% | 17.57% | -21.65% | -19.46% | 1.117 | 0.931 |
| ETH | 402.03% | 222.00% | 19.81% | -30.57% | -31.47% | 0.852 | 0.646 |
| SOL | 679.12% | 430.34% | 33.58% | -26.75% | -46.97% | 0.930 | 0.780 |

这不是最终修复，只是保守敏感性；但收益大幅下降、SOL 回撤近乎翻倍，足以否决“原始结果已可信”的判断。正式修复必须明确 bar timestamp 语义、闭合边界、日/周 label/closed 规则，并用逐时截断测试证明所有 HTF feature 的 point-in-time 正确性。

## 独立、因果的市场环境代理

为避免继续引用受 HTF leak 污染的仓库 regime，`causal_market_proxy.csv` 另用仅依赖历史、并整体后移一根 4H bar 的代理状态：180 天动量大于 +20% 为牛市、小于 -20% 为熊市；ADX≥25 为趋势、ADX<20 为震荡；120-bar ATR 排名≥90%/≤30% 为高/低波动。下表采用更保守的 causal-guard 净值，数字为落在该状态下的条件复合收益；不同维度会重叠，不能横向相加。

| 环境 | BTC | ETH | SOL |
|---|---:|---:|---:|
| 牛市（180d > +20%） | 111.96% | 112.68% | 209.61% |
| 熊市（180d < -20%） | 13.12% | 11.75% | -12.61% |
| 横盘（±20%） | 18.38% | 20.86% | 4.56% |
| 趋势（ADX≥25） | 120.66% | 196.44% | 382.90% |
| 震荡（ADX<20） | -1.83% | -8.43% | 15.75% |
| 高波动（ATR rank≥90%） | 15.62% | 57.52% | 138.23% |
| 低波动（ATR rank≤30%） | 65.81% | 71.20% | -25.40% |

较稳健的结论是系统偏好牛市/趋势；熊市收益很弱，SOL 熊市为负；BTC/ETH 震荡无效，SOL 低波动无效。SOL 的高波动收益与 2021 年大行情高度重合，不能独立视为稳定 Alpha。

## 输出索引

- `data_snapshots/dataset_manifest.json`：合并快照的范围、质量检查、SHA256。
- `data_snapshots/monthly_archive_manifest.json`：每个月包/补缺日包的 URL、状态、SHA256。
- `results/all_cases.json`、`summary.csv`：15 个主 dual case。
- `results/yearly_returns.csv`：逐年收益。
- `results/direction_attribution.csv`、`module_attribution.csv`：有效交易方向/模块归因。
- `results/profit_concentration.csv`：Top-N 利润集中度。
- `results/market_environment.csv`：基于当前 RegimeModel 的条件表现；基线版本受 HTF leak 污染，只能描述、不能证明。
- `results/causal_market_proxy.csv`：不复用 HTF regime、状态后移一根 bar 的独立市场环境代理；`causal_guard_causal_market_proxy.csv` 是保守护栏版本。
- `results/buy_hold_benchmark.csv`：买持 CAGR、MDD、回撤时长、Sharpe/Sortino/Calmar。
- `results/blocked_cases.json`：字面 CLI 默认 HTF 控制组的崩溃证据。
- `results/cases/*/trades.csv`、`equity.csv`、`summary.json`：逐 case 审计轨迹。
- `results/causal_guard_*`：三标 HTF 因果护栏敏感性，独立于主结果，未覆盖基线。

## 直接结论

这些结果可以支持继续研究，但不能支持进入模拟盘：主结果存在已证实的 HTF availability leak，字面默认入口不可运行，约三成交易记录为 ghost，资金费率/滑点/保证金/爆仓均未真实建模，且盈利主要来自 core long 与少数大交易。应先修复因果性与交易账本，再重跑固定数据的样本外、walk-forward、成本和执行压力测试。
