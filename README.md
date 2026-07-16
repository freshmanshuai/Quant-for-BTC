# Quant-for-BTC

面向 BTC/ETH/SOL 的规则专家系统研究仓库。正式 Alpha 候选已从 legacy Dual 策略收敛为三个可解释模块：

- `core_long`：趋势 Beta sleeve；
- `bear_core`：低权重、对称的熊趋势 sleeve；
- `pullback_long`：低权重多头回调 overlay。

`breakout`、`sweep_*`、`dip_buy`、`core_add`、`meanrev`、`bulltrap`、`failed_bounce`、`crash`、derivative bonus 和手写综合分数均不进入正式风险预算。完整决策见 [`config/production_strategy.json`](config/production_strategy.json)。

## 可信回测语义

- 高周期指标只使用上一根已完成的高周期 K 线；
- 形成中的 K 线被排除，重复行去重，OHLC 非法值和可选连续性检查 fail closed；
- 当前 bar 收盘生成信号，最早下一 bar 开盘成交；
- 手续费和滑点逐笔进入现金账本；
- 永续合约必须提供覆盖完整窗口的历史 funding settlement ledger，缺失时拒绝运行；
- funding 按方向处理：正费率多头支付、空头收取；
- 逐仓初始保证金、维持保证金、风险档 maintenance amount、强平价、强平滑点和 liquidation clearance fee 进入回测；
- 期末持仓强制结算，交易账本与最终权益闭合。

Binance 手续费取决于账户 VIP/BNB 设置，维持保证金和强平费取决于标的与名义价值档位。仓库默认值只是 2026-07-16 固定的普通账户/第一档研究快照；正式运行必须用账户和标的实际参数覆盖。

## 运行

现货烟雾回测（不需要 funding）：

```powershell
python run_backtest.py --market-type spot --bars path\to\bars.pkl
```

USD-M 永续可信回测：

```powershell
python run_backtest.py `
  --bars path\to\BTCUSDT_4h.pkl `
  --funding path\to\BTCUSDT_funding.pkl `
  --fee-rate 0.0005 `
  --slippage-bps 2 `
  --spread-column bid_ask_spread `
  --mark-price-column MarkOpen `
  --mark-high-column MarkHigh `
  --mark-low-column MarkLow `
  --funding-mark-column FundingMarkPrice `
  --leverage 2 `
  --maintenance-margin-rate 0.004 `
  --maintenance-amount 0 `
  --liquidation-fee-rate 0.0125
```

若行情文件含历史盘口点差和 mark-price OHLC，请使用上述列参数；缺列时正式入口会拒绝运行。没有 mark 数据时，强平路径退化为合约 OHLC 的保守代理，并应在报告中明确标记。固定 `--slippage-bps` 应来自 paper/live 成交偏差统计，而不是回测调参。

输出位于 `artifacts/backtests/`，包含 `summary.json`、`trades.csv` 和 `equity.csv`。旧 Dual 回测仅作为受控对照保留在 `scripts/run_legacy_backtest.py`，不得作为模拟盘或实盘准入结果。

## 目录

```text
Quant-for-BTC/
├─ config/                  # 市场、正式策略和研究配置
├─ quant_btc/               # BTC/加密策略适配；正式候选在 retained_strategy.py
├─ quant_platform/          # 数据、特征、信号、组合、风险和事件回测内核
├─ tests/                   # 单元、因果、账本和连接器测试
├─ scripts/                 # legacy/诊断入口，不属于正式运行链路
├─ pine/                    # TradingView parity 研究资产
├─ serve/                   # 只读研究预览服务
├─ docs/                    # 架构和迁移说明
├─ audit_artifacts/         # 2026-07-15 审阅证据与冻结快照
├─ artifacts/               # 运行产物（忽略，不入库）
└─ run_backtest.py          # 唯一正式回测入口
```

目录边界和删除清单见 [`docs/architecture.md`](docs/architecture.md)。

## 验证

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

当前 legacy `backtesting.py` 夹具仍有 30 个已知错误，原因是测试直接写入新版依赖的只读 `Strategy.data` 属性；正式事件引擎和本次新增的因果/账本测试独立通过。该 legacy 债务不应阻断正式内核，但在删除 legacy 代码前应单独修复或废止相应测试。
