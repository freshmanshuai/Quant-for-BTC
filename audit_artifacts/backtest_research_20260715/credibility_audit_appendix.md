# 回测可信度、策略与风险审计附录

> 审计日期：2026-07-15  
> 审计基准提交：`2d8713a9d30fd0ad7a0e0d3791640a129a77dd3d`  
> 审计范围：当前仓库中的 BTC legacy/dual 回测入口、数据缓存与 CCXT 适配器、特征和市场状态模型、信号模块、仓位与风险逻辑、报告及相关测试。  
> 审计方式：代码静态检查、固定缓存数据质量检查、前缀因果性检查，以及一次不写文件的 BTC Dual 诊断运行。除本附录外未授权修改任何业务代码。

## A.1 结论与使用限制

当前回测不能作为资金配置、模拟盘准入或实盘准入的证据。主要原因不是“指标不够好”，而是存在会改变交易时点、仓位、资金占用和成交结果的 P0 级缺陷：

1. 日线/周线特征使用了尚未完成的高周期收盘数据，存在明确前视偏差。
2. Dual-layer 声称同时管理 core、bear core 和 tactical，但实际回测器启用了 `exclusive_orders=True`，且分层权益比例与实际交易单位混算，组合账本不成立。
3. CLI 展示的杠杆没有进入保证金模型；资金费率配置没有进入当前执行路径；无维持保证金和强平模型。
4. 数据抓取分页会生成重复 bar，缓存中已实际发现重复、断档和未完成 K 线。
5. 策略用信号 bar 的收盘价计算止损和仓位，却默认在下一根 bar 开盘成交；移动止损还存在“用本 bar 高点更新、再用本 bar 低点判断触发”的路径不确定性。

因此，本附录中的 `+302.82%` 等数值仅用于证明账本和交易记录异常，属于**失真条件下的诊断输出**，严禁称为可信收益、历史业绩或预期收益。

## A.2 十四项回测可信度审计

| # | 检查项 | 判定 | 证据及代码位置 | 可能影响 | 优先级 | 推荐修复 |
|---|---|---|---|---|---|---|
| 1 | 未来函数或前视偏差 | **已确认存在** | `quant_platform/features.py:550-553` 对完整序列执行 `resample(rule).last()` 后直接向 4H 索引前向填充；`quant_platform/regimes.py:110-115` 将结果用于 regime。前缀检查显示：仅使用截至 `2024-03-15 08:00 UTC` 的数据计算时，该日 EMA169 为 `45187.00`；使用完整数据计算同一历史时点变为 `45207.40`，原因是读取了当日 `20:00` close | 市场状态、方向过滤、score、core/bear-core 入场均可能提前知道当日最终收盘；所有收益和风险指标失去可信基础 | **P0** | 为每个高周期值增加 `available_at`；仅在高周期 K 线闭合后的下一根基础周期可见。新增“完整数据 vs 任意历史前缀”结果完全一致的因果性测试 |
| 2 | 高周期数据映射泄漏 | **已确认存在，并伴随方向状态错误** | 相同泄漏还见 `quant_btc/strategy.py:155-158,318-325`。`quant_platform/regimes.py:114-115,165-169` 先把日/周 EMA 填充成 4H step series，再做 1 个 4H bar 的 `pct_change`；`quant_btc/signal_modules.py:604-613` 的打分方向也一样 | 日/周斜率通常只在周期边界的第一个 4H bar 非零，其余 bar 大量变成 0；趋势与震荡样本分配错误。15m 窗口 `strategy.py:1309-1316` 在“4H 收盘决策、下一开盘成交”语义下可条件性成立，但没有 availability-time 约束，且尾部含未完成 15m bar，仍需验证 | **P0** | 在原生日/周序列上先计算 EMA 和 slope，再把已完成值 as-of join 到 4H；明确 `closed`、`label`、UTC 边界。15m 只允许读取 decision time 前已闭合 bar |
| 3 | 幸存者偏差 | **需要验证；存在事后选样风险** | `config/markets.json:2-35` 只登记当前 BTC 与 AAPL，无 point-in-time 可交易币种集合、历史上下架或退市合约；CLI 是单标的入口 | 单独研究 BTC/ETH/SOL 不等于传统股票组合幸存者偏差，但若以当前头部币种事后选样证明泛化，结论会偏乐观；SOL 的可用历史也天然更短 | **P2** | 同时报告“各自完整历史”和“三标的共同重叠窗口”；记录标的选择时间与规则。组合研究引入历史上市、下架、交易所可用性数据 |
| 4 | 数据断档或重复 | **已确认存在** | `quant_platform/connectors_ccxt.py:274-280` 将上一页最早时间戳原样作为下一页 `endTime`，没有减 1ms；`ohlcv_rows_to_frame()` 在 `43-46` 仅 set index，未排序、去重或验证。固定缓存中已发现 4H/15m 重复和 spot 断档 | 重复 bar 被指标重复计权，shift/rolling/交易持续时间被污染；缺口附近的 ATR、突破和止损不可靠 | **P0** | 抓取后强制 `sort_index`、唯一索引、严格递增、OHLC 合法性和期望频率校验；分页游标改为排他边界；输出 gap manifest，禁止静默填补 |
| 5 | 未完成 K 线被提前使用 | **已确认存在** | `connectors_ccxt.py:127-129` 原样返回交易所 OHLCV，没有按 `bar_open + timeframe <= data_cutoff` 过滤；`quant_btc/data.py:155-171` 缓存命中后也原样返回。当前最后一根 swap 4H bar `2026-05-17 04:00` 只对应 11/16 根 15m bar | 尾部 OHLCV、实时信号、最终强制平仓和最近一期指标会随抓取时刻变化 | **P0** | 保存 fetch cutoff；只持久化闭合 bar；forming bar 放入独立实时缓存，不允许进入历史回测 |
| 6 | 过度拟合 | **高风险；尚不能用独立 OOS 实验证实或排除** | `RiskConfig` 有 109 个字段，`BacktestConfig` 有 21 个字段，共 **130 个配置字段**，另有代码内阈值；`README.md:260-282` 记录在同一 BTC 历史上逐步叠加规则并汇报改善 | 有效自由度远高于独立市场周期数量，BTC 表面改善可能是数据挖掘结果 | **P1** | 冻结研究协议和参数候选集合；嵌套 walk-forward、参数稳定区间、模块消融、bootstrap/Monte Carlo，并记录全部失败实验及总试验次数 |
| 7 | 参数选择偏差 | **已确认高风险** | Dual 选择器在 `signal_modules.py:321-327` 硬编码阈值，绕过配置；例如 `pb_th_s=999` 实际关闭 pullback short。配置与实际生效参数不是单一真源 | 可以通过修改代码阈值选择最好历史结果，失败实验和最终选择过程不可追踪；标的横向比较可能使用不同隐含规则 | **P1** | 所有有效参数进入版本化配置；run manifest 保存完整解析后参数；测试集一次性解封，研究日志保存候选数和选择准则 |
| 8 | 样本内与样本外混用 | **已确认没有隔离机制** | CLI 无 start/end、train/validation/test 参数；`run_backtest.py:88-105` 对全量数据一次性 feature + backtest。仓库搜索未发现 walk-forward、purged split 或 embargo 实现 | README 中的规则选择和最终指标来自同一历史，无法证明泛化；BTC 到 ETH/SOL 的迁移也可能只是追加事后检验 | **P1** | 固定 IS/validation/OOS 时间边界；采用 rolling 或 anchored walk-forward；三标的分别做 OOS，并做统一共同窗口和跨标的留一验证 |
| 9 | 手续费、滑点和资金费率低估 | **已确认** | 当前 runner 只传固定 `commission=0.0004`，见 `quant_btc/config.py:176-177`、`strategy.py:2509-2517`，未传 spread/slippage。`config.py:145-147` 声称扣除 funding，但当前执行路径没有使用这两个字段。通用引擎虽有 `fee_rate/slippage_bps`，见 `quant_platform/backtest.py:43-57`，legacy CLI 没有调用它 | 高频模块、空头和长期永续仓位收益被系统性高估；无法评估成本恶化后的存活性 | **P0** | 使用交易所/账户级 maker-taker 费率、半点差、方向性滑点和成交量冲击；按实际 funding timestamp、方向和名义敞口结算；至少执行 1×/2×/3× 成本压力 |
| 10 | 信号价格与实际成交价格不一致 | **已确认** | 单模块在 `strategy.py:852-870` 使用当前 close 计算 entry/SL/TP/size，随后在 `893-896` 下 market order；`FractionalBacktest` 调用 `2509-2517` 没有设置 `trade_on_close`，当前本地 `backtesting==0.6.5` 默认下一根 open 成交。Dual 同样在 `2243-2257` 用 close 规划、`2289-2301` 下单 | gap 后实际风险金额、RR 和仓位偏离记录值；保护单甚至可能相对实际成交价无效 | **P0** | 明确 decision time、submit time、fill time；next-open 成交时在 fill 后基于实际价格重新验证/缩放数量和保护单；日志分别记录 signal、fill、slippage price |
| 11 | 止损、止盈和移动止损成交不现实 | **已确认** | `portfolio_model.py:600-649` 先用当前 bar high/low 更新 trailing stop，再用同一 bar low/high 判断命中；`1505-1526` tactical trail 相同。手工命中后 `strategy.py:805-818,1463-1504` 只调用 `position.close()`，即下一 open 市价退出。partial TP 在 `portfolio_model.py:530-546` 只看 close | 无法知道同一根 bar 先创新高还是先跌破新 stop；止损/止盈成交价和触发顺序失真，归因也无法区分真实 exit reason | **P0** | 新 trailing stop 下一 bar 才生效；使用真实 stop/limit order 状态；同 bar SL/TP 冲突采用保守路径或更细粒度数据；禁止事后以 exit price 推断 exit reason |
| 12 | 杠杆、保证金和爆仓风险建模 | **已确认缺失** | `run_backtest.py:168` 构造 `RiskConfig(leverage=...)`，但执行路径没有引用该字段；`strategy.py:2509-2517` 未向 Backtest 传 `margin`，当前环境实际为 1x，尽管 CLI 在 `run_backtest.py:213-235` 打印 5x。仓库当前 runner 无 maintenance margin、mark price 或 liquidation | “5x 回测”标签与实际模型不符；年化收益不能归因于杠杆，尾部风险和爆仓概率也无法评价 | **P0** | 建立保证金账户模型：初始/维持保证金、mark price、逐仓/全仓、强平手续费、funding、保险基金/ADL；测试 leverage=1/2/5 必须产生不同资金约束和结果 |
| 13 | 多模块同时持仓时的资金占用 | **已确认严重错误** | Dual 文档声明 core+tactical 共存，见 `strategy.py:1091-1105`，但 runner 设置 `exclusive_orders=True`，见 `2509-2516`，当前库会让新 entry 关闭旧 trade。另有量纲错误：`_core_size/_tac_size` 是权益比例，`self.position.size` 是交易单位；`strategy.py:1510-1538` 经 `portfolio_model.py:823-830` 将二者相除做 partial close | 分层状态与真实持仓脱节；关层时经常只关闭最小 1 satoshi；core/tactical 资金占用、组合风险、交易数和模块贡献全部错误 | **P0** | 停止用 aggregate Position 模拟多层；每个 sleeve 使用独立 position/order ID、quantity、avg price、reserved margin、stop、PnL；组合账本统一汇总 cash、margin、risk |
| 14 | 固定数据和固定环境复现 | **不充分** | BTC pickle 已被 Git 跟踪，这是有限的正面基础；但 `requirements.txt:1-7` 全为下限版本，无 lock。缓存键 `quant_btc/data.py:27-34` 不含日期、hash、cutoff 或 schema；`155-171` 命中即返回。`report.py:290-397` 只保存图片并返回字符串，未保存 commit/config/data/dependency manifest；`351-353` 还硬编码 BTC/Weighted 标题 | 同一命令会因本地 Parquet/pickle、抓取时间和依赖版本不同得到不同结果；ETH/SOL 首次抓取尤其无法复现 | **P0** | 每个运行保存 `run_manifest.json`：git SHA/dirty、解析后配置、Python/精确依赖、数据 SHA256/行数/范围/cutoff、引擎版本、随机种子和输出 hash；锁定依赖并冻结 OOS 数据快照 |

## A.3 固定缓存数据质量与哈希

### A.3.1 数据质量统计

| 文件 | 行数 | 时间范围 | 重复时间戳 | 断档/异常 | SHA256 |
|---|---:|---|---:|---|---|
| `data/binance_swap_BTC_USDT_4h.pkl` | 14,670 | 2019-09-08 16:00 — 2026-05-17 04:00 UTC | **14 组**，均为内容完全相同的分页边界重复 | 去重后 14,656；没有大于 4H 的间隔 | `4a4130fd657eb9a58d13ab50a0f7888458bacab77758099744b6fb22dd9ce951` |
| `data/binance_swap_BTC_USDT_15m.pkl` | 100,000 | 2023-07-11 15:30 — 2026-05-17 06:30 UTC | **99 组**，均为内容完全相同的分页边界重复 | 去重后 99,901；与约 100 页抓取边界吻合；仅从 2023 年开始，早期回测没有 MTF bonus | `fd9a0782ea6af33e82b2ea14f01e31a3e81dc006e6c5e776a26e6b0183a73a2f` |
| `data/binanceus_spot_BTC_USDT_4h.pkl` | 14,540 | 2019-09-23 08:00 — 2026-05-11 04:00 UTC | **14 组** | **4 处断点、约缺 6 根 4H bar**：2020-04-28、2020-07-09、2021-06-22、2023-02-06 | `e44ee75e661459019c3fe8d5a87fba32ed91a17c6c77cf7f182d454915687285` |
| `data/binance_derivatives_BTC_USDT.pkl` | 399 | 2026-03-06 00:00 — 2026-05-11 08:00 UTC | 0 | 只覆盖约 66 天，不能支撑 2019—2026 的衍生品 Alpha 归因 | `fac9876822e3ea46c92ec32361021565d6026e70f9cccf043125d667ced9e945` |

OHLCV 基础检查未发现 NaN、负 volume 或明显 `High/Low` 关系错误；这不能抵消重复、缺口和未完成 bar 问题。

### A.3.2 未完成尾部 K 线证据

最后一根 swap 4H bar 的开盘时间为 `2026-05-17 04:00 UTC`。对应 15m 缓存只覆盖到 `06:30 UTC`，在 `[04:00, 08:00)` 内只有 **11/16** 根 15m bar。该 4H bar 的 OHLCV 与这 11 根 15m 的不完整聚合基本吻合，因此它是抓取时的 forming bar 快照，而不是最终闭合 K 线。

## A.4 Dual-layer 只读诊断运行证据

### A.4.1 运行口径

- 使用当前提交及 Git 中 BTC swap 4H/15m/derivatives 缓存。
- 使用当前默认 `BacktestConfig()`、`RiskConfig()` 和 `DualLayerStrategy`。
- 按当前代码执行 `prepare_features`、derivative bonus 和 `run_backtest`。
- 不写报告或数据文件。
- 输入保留了当前代码会实际读取的重复 bar、未完成尾部 bar、HTF 前视和错误组合账本。

### A.4.2 诊断输出及其含义

| 诊断项 | 数量 |
|---|---:|
| 当前引擎输出的表面 return | `+302.82%` |
| 当前引擎输出的 max drawdown | `-18.66%` |
| 交易记录总数 | 464 |
| 当前引擎计入的 commission | `$19,227.82` |
| `abs(Size) == 1e-8 BTC` 的幽灵碎片 | **118，占 25.4%** |
| 按 EntryTime 排序后，前一笔 ExitTime 晚于当前 EntryTime 的相邻重叠计数 | **133** |

上述 return 和 drawdown 是**失真条件下的诊断输出，不是可信收益或可信风险指标**。其中：

- 118 个 `1e-8 BTC` 交易与 `layer_size / position_units` 的量纲错误直接一致，说明关层操作大量退化成只关闭一个最小单位。
- “133 个相邻重叠”是用于发现交易区间和 partial-close 分片异常的诊断计数，不等同于 133 个真实独立并发仓位，也不能证明组合资金占用正确。
- 幽灵碎片本身的直接 PnL 很小，但它们证明层级状态、trade count、持有期、胜率和连续亏损统计已被污染；更大的问题是实际大仓位是否被按预期关闭无法保证。

### A.4.3 当前交易标签分布

| 模块标签 | 笔数 |
|---|---:|
| `core_long` | 195 |
| `pullback_struct_long` | 138 |
| `bear_core` | 52 |
| `sweep_reversal_long` | 39 |
| `sweep_reversal_short` | 13 |
| `crash_short` | 12 |
| `breakout_retest_long` | 6 |
| `dip_buy_long` | 4 |
| `core_add_long` | 2 |
| `bull_trap_short` | 2 |
| `meanrev_range_long` | 1 |
| pullback short / meanrev short / failed bounce | 0 |

这些数量不能作为模块有效性排名：新单强制换仓、partial-close 分片、HTF 泄漏和退出归因错误会共同改变标签对应的交易生命周期。但它们足以说明多个声称启用的模块实际上没有产生可评价样本。

## A.5 测试、依赖和复现审计

### A.5.1 现有正面基础

- 仓库有较多 component/unit tests，覆盖 feature、signal、risk、portfolio 和通用 event backtest。
- 通用 event backtest 对 fee、slippage、funding、intrabar stop/target 有局部测试，例如 `tests/test_platform_backtest.py:1268,1311,1471,2452`。
- BTC 固定 pickle 已被 Git 跟踪，能够为修复前后的同数据对比提供起点。

### A.5.2 关键测试缺口

仓库搜索未发现以下针对当前 legacy/Dual 生产回测路径的验收测试：

1. HTF/full-prefix 因果一致性测试。
2. 严格唯一时间索引、期望频率、缺口和未完成 bar 拒绝测试。
3. core/tactical/bear-core 独立账本及 `sum(layer quantities) == account position` 不变量测试。
4. 禁止最小单位幽灵碎片、禁止意外 overlap 的集成测试。
5. CLI `--leverage 1/2/5` 必须改变 margin、可用资金和强平结果的测试。
6. legacy runner 确实扣除 funding、slippage、spread 的端到端测试。
7. 同 bar 同时触及 SL/TP、更新 trailing stop 后反向触发的事件顺序测试。
8. spot 市场 short 必须被拒绝的集成测试。
9. 完整 run manifest 与输出 hash 的确定性复现测试。
10. IS/validation/OOS、walk-forward、成本压力、参数敏感度和模块消融测试。

`tests/test_platform_features.py:153-178` 目前只验证 HTF 列存在，没有验证其因果性；`tests/test_platform_regimes.py:21-76` 验证 label 范围与优先级，也未做 prefix-invariance。因而现有测试通过不能证明当前历史回测无前视或组合账本正确。

### A.5.3 依赖与环境问题

`requirements.txt` 使用：

```text
ccxt>=4.4.0
pandas>=2.0.0
numpy>=1.24.0
backtesting>=0.3.3
matplotlib>=3.0
flask>=2.0
pyarrow>=15.0
```

全部是开放下限。审计环境实际 `backtesting==0.6.5`，而 `>=0.3.3` 允许跨多个版本安装；成交顺序、统计字段、FractionalBacktest 行为或年化实现都可能变化。仓库未发现 lock file、容器镜像 digest 或 CI workflow。

最低复现要求：

- 精确锁定 Python、pandas、numpy、backtesting、ccxt、pyarrow 等版本。
- 保存 git commit 和 dirty diff hash。
- 保存所有输入数据 SHA256、行数、起止时间、timezone、exchange、market type、fetch cutoff 和 schema version。
- 保存解析后的完整策略/风险/成本配置，而非仅保存 CLI 参数。
- 保存每次运行的 stdout/stderr、trade ledger、equity curve、订单事件和最终报告 hash。

## A.6 策略、风险和研究缺陷分级

### A.6.1 P0：修复前禁止重新宣称策略业绩

#### 策略与组合

- **HTF 前视与 regime slope 错误**：`features.py:550-553`、`regimes.py:110-115,165-169`。
- **Dual-layer 并非真实多层组合**：`strategy.py:1091-1105,2509-2516`。
- **分层 close 量纲错误**：`strategy.py:1510-1538`、`portfolio_model.py:823-830`。
- **策略状态与实际 broker state 分离**：core/tactical/bear-core 使用多组布尔状态和权益比例，但 broker 只有 aggregate position；外部 close 清理 `portfolio_model.py:194-218` 甚至不包含 bear-core 状态。

#### 风险与成交

- **RiskEngine 默认不具否决权**：`strategy.py:374,547-551` 的 `_ENFORCE_PLATFORM_RISK_ENGINE=False`。
- **杠杆/保证金/强平缺失**：CLI 杠杆是显示字段，不进入 Backtest margin。
- **funding、spread、slippage 未进入当前 runner**。
- **信号 close 规划、next-open 成交但不重算风险**。
- **移动止损同 bar 更新/触发，手工退出延迟到 next open**。
- **形成中 K 线和重复数据直接进入回测**。

#### 研究与复现

- **无可信 run manifest**。
- **缓存优先级和内容可能因机器不同而改变**：`data.py:155-171` 先尝试本地 Parquet，再尝试 pickle，但没有验证二者内容相同。
- **模块归因基础 trade ledger 已失真**，不能用当前 attribution 决策保留/删除模块。

### A.6.2 P1：P0 修复后必须完成，才能评价泛化

#### 策略

- `signal_modules.py:321-327` 的硬编码阈值绕过配置；`pb_th_s=999` 使 pullback short 成为死模块。
- Mean reversion 的实现和 regime 声明冲突：strong/weak bull 可选 long meanrev，而 range 分支没有选择已计算的 meanrev short，见 `signal_modules.py:345-400,808-809`。
- Core 初始 allocation 使用 `risk_core_alloc=0.40`，add target 又使用 `core_allocation=0.55`，口径分裂。
- 各模块反复叠加相同 `market/momentum/risk` score，见 `signal_modules.py:594-826`，信号高度相关且重复计权。
- Core long 本质是择时后的 BTC beta，应从 tactical Alpha 中独立列示。

#### 风险

- Circuit breaker 在 `strategy.py:630-650` 只在日期/周切换时检查已实现 PnL，不是实时账户 equity drawdown。
- 初始日/周权益在 `strategy.py:430-431` 硬编码为 100,000，不跟随 `BacktestConfig.initial_cash`。
- `strategy.py:1157` 的 `_bear_group_max_loss_pct=0.006` 没有执行引用。
- Core 没有明确 stop，`strategy.py:1865-1878` 只依赖手工趋势退出；其尾部风险未进入组合 risk budget。
- spot 与 swap 共用可卖空 legacy 引擎，市场能力约束没有落实。

#### 研究

- 无 IS/validation/OOS、walk-forward、purge/embargo。
- 130 个配置字段加代码阈值，没有参数稳定性和多重试验校正。
- 衍生品数据仅 399 行，不能做全历史模块归因。
- 缺少统一共同窗口和跨标的留一检验。

### A.6.3 P2：可信框架建立后治理

- 建立 point-in-time universe，控制事后选择 BTC/ETH/SOL 的样本偏差。
- 增加 listing 初期、极低流动性、交易所停机、下架和合约规则变更处理。
- 建立特征 warm-up 标准；当前大量 EMA/rolling 使用 `min_periods=1`，上市早期指标不稳定。
- 修复报告硬编码：`report.py:351-353` 无论 ETH/SOL 都显示 Bitcoin、WeightedSignalStrategy、BTC/USDT。
- 将报告中的 position size、notional、R multiple 改为直接来自真实 ledger。当前 `trade_log.py:74-88` 把 BTC 数量当权益比例，仓位百分比和 R 计算错误。

## A.7 模块保留、重构和停用建议

| 处理 | 模块/能力 | 理由与条件 |
|---|---|---|
| 保留为基础设施原语 | EMA、ATR、ADX、Donchian、Bollinger、volume | 经济含义明确，但必须先通过 causal/prefix-invariance 测试 |
| 保留为研究假设 | Breakout/trend following | 有趋势延续逻辑；需要在无 HTF 泄漏、真实成本和 OOS 下重测 |
| 保留并重构 | Pullback long、sweep reversal | 可能改善入场或捕捉流动性回补，但必须证明对 breakout 的增量贡献和低相关性 |
| 独立成 benchmark sleeve | Core long | 主要是 BTC beta/择时，不应计作独立 Alpha；需单独风险预算和 B&H 对照 |
| 全面重构 | Regime model | 修复 HTF availability、持续 slope、资产归一化和 transition 定义 |
| 全面重构 | Dual portfolio / risk / execution | 必须使用独立 layer ledger、订单状态、实际 fill、margin 和统一 RiskEngine |
| 暂停生产候选 | Mean reversion | 当前 Dual 只有 1 笔 long、0 笔 short，且 regime 实现冲突，无有效样本 |
| 暂停生产候选 | Pullback short、failed bounce | 前者被 `999` 阈值关闭，后者当前 0 笔；先删除死路径或返回研究分支 |
| 暂停生产候选 | Bull trap、dip buy | 当前诊断样本分别只有 2/4 笔，不足以支持有效性 |
| 暂停生产候选 | Derivative bonus | 历史只有约 66 天，且当前未同时结算真实 funding 成本 |
| 删除生产依赖、保留对照 | 手写 0—100 混合 score | 共享市场、动量、风险分数重复计权；用明确规则或经 OOS 校准的概率/预期收益替代 |
| 删除并替换 | legacy 手工 trailing、partial-close、多层模拟 | 同 bar 路径和量纲错误无法靠局部补丁保证一致性 |

## A.8 P0 验收门槛

只有同时满足以下条件，才允许重新生成并引用 BTC/ETH/SOL 的收益、Sharpe、最大回撤和模块贡献：

1. 任意历史 cutoff 的 feature/regime/signal 与完整数据相同历史前缀完全一致。
2. 所有输入索引唯一、严格递增；缺口有 manifest；最后一根 K 线已闭合。
3. 每笔订单有唯一 ID；每个 layer 有独立 quantity、average price、margin、risk 和 PnL；无 `1e-8` 幽灵碎片。
4. `sum(layer quantity/notional/risk)` 与账户/交易所状态逐 bar 对账一致。
5. RiskEngine 可以实际否决信号，并在 entry、add、reverse、partial close 后重新计算组合风险。
6. leverage、fee、spread、slippage、funding、maintenance margin 和 liquidation 均进入现金流。
7. 同 bar SL/TP/trailing 的处理规则固定、保守、可测试，并与 paper engine 一致。
8. 同一 commit、config、data hash 和 lock environment 重跑得到完全相同的 orders、trades、equity 和 metrics。

P0 通过后，仍必须完成 P1 的 OOS、walk-forward、参数敏感度、成本压力、Monte Carlo、多标的共同窗口和模块消融，才能评价策略是否具备跨标的泛化能力。

## A.9 最终审计意见

- 当前系统值得继续投入的部分是：特征/信号模块化方向、通用 RiskEngine/Event Backtest 的基础骨架、固定数据与较多组件测试。
- 当前 Dual 历史曲线不值得继续调参；继续在现有 ledger 和 HTF 映射上优化只会放大错误和过拟合。
- 在 P0 全部关闭之前：**不进入模拟盘，不进入实盘，不依据诊断 return 提高杠杆或资金规模。**
- 修复后必须从原始固定数据重新生成 BTC、ETH、SOL 全部结果，旧报告只能留作缺陷复现对照，不能与修复后的结果混合比较。
