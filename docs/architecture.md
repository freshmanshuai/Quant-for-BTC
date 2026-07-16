# 架构与目录治理

## 唯一正式链路

```text
已完成 OHLCV + funding settlements
  -> 数据质量门禁
  -> point-in-time 特征
  -> retained expert modules
  -> portfolio/risk hard gates
  -> next-open execution
  -> fee/slippage/funding/margin/liquidation ledger
  -> trades/equity/summary
```

`run_backtest.py` 是唯一正式入口。`quant_platform` 是可复用内核，`quant_btc/retained_strategy.py` 只负责规则候选。策略不得直接操作成交状态；只有 fill、funding 和 liquidation 现金流可以改变实际账户。

## 模块边界

| 目录 | 责任 | 不应包含 |
|---|---|---|
| `quant_platform/` | 市场数据、因果特征、信号契约、风险、组合、执行和账本 | BTC 硬编码阈值 |
| `quant_btc/` | 加密规则和兼容适配 | 交易所网络实现、网页服务 |
| `config/` | 可审计参数快照和模块启停 | 密钥、运行缓存 |
| `tests/` | 因果、资金守恒、强平和行为回归 | 历史结果图片 |
| `scripts/` | 明确标为 legacy 的一次性研究入口 | 正式默认命令 |
| `audit_artifacts/` | 冻结审阅证据 | 日常运行产物 |
| `artifacts/` | 可再生结果 | 需要版本控制的源码 |

## 本轮删除

- 版本库内的 `.venv/`、`.webvenv/` 和临时安装包；
- `__pycache__/` 与 `*.pyc`；
- 历史 `backtest_results/` 图片和缓存；
- `data/*.pkl` 本地行情缓存；
- webserver 日志、编辑器/本机设置；
- 已被正式审阅产物取代的根目录 short 分析脚本。

删除对象均为可再生环境、缓存或一次性产物。冻结审阅报告、数据快照、正式源码、测试、配置和 Pine parity 资产保留。

## 后续迁移

1. 补齐 BTC/ETH/SOL 全窗口 funding 与 mark-price 快照，再发布永续净绩效；
2. 将逐标的实时 leverage bracket 固化为 run manifest，替换示例第一档参数；
3. 给正式链路增加 IS/验证/OOS 和 walk-forward 注册；
4. legacy 30 个夹具修复后，完成一个研究周期消融，再删除 `quant_btc/strategy.py` 和 legacy 测试。
