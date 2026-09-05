# F3_test 可配置策略平台路线图

## 状态规则

- `未开始`：没有可验证产物。
- `进行中`：已有部分代码，但验收条件未全部满足。
- `完成`：代码、兼容性和测试均通过，证据记录在本文件。
- 每次只推进一个可闭环里程碑；完成后更新“当前状态”和“验证证据”。

## 创建时基线（2026-09-05）

- 已有 `S000001`、`S000002` 注册项及向量回测专用 runner。
- 已有因子批量评估，但没有通用策略参数 Trial/BatchRunner。
- `BacktestJobConfig` 只包含资金、日期、因子、策略和模式。
- S000001 参数主要硬编码，S000002 使用独立配置，尚无统一参数 schema。
- VectorEngine 按策略类名硬编码分发。
- EventEngine 是占位实现，尚无真实 MatchingEngine。
- 报告格式按策略分裂，GUI 部分功能依赖“最新报告”。
- 已有少量 `tests/`，但创建时尚未按 unit/integration/fixtures 分层，策略注册、参数合同和按钮链路覆盖不足。

## 当前状态

| 里程碑 | 状态 | 验证证据 |
|---|---|---|
| M0 基线与测试骨架 | 完成 | 2026-09-05：`tests/unit`、`tests/integration`、固定 fixtures；项目 `.venv311` 下 12 项测试通过，包含真实 GUI 按钮接线冒烟测试。 |
| M1 核心合同与 RunConfig | 完成 | 2026-09-05：新增 `quant/engine/contracts.py` 和旧 `BacktestJobConfig` 适配器；日期、资金、参数范围及序列化行为有测试。 |
| M2 稳定注册与参数 schema | 完成 | 2026-09-05：S000001/S000002 改为显式 `StrategySpec`，参数 Schema 可发现/校验，VectorEngine 不再按类名硬编码分发。 |
| M3 S000001 统一输出适配 | 完成 | 2026-09-05：旁路采集动量排名、LONG/FLAT/EXIT 原因和固定手数目标；真实回测输出 2301 条 SignalRecord、290 条 TargetPositionRecord，D 日信号→D+1 开盘基线保持通过。 |
| M4 S000002 统一输出适配 | 完成 | 2026-09-05：SLSS 阈值/截面模式统一输出；研究 SHORT 与 A 股现货目标归零分离；真实回测输出 9173 条信号和 9173 条目标。 |
| M4.5 运行状态与占位门禁 | 未开始 | 已确认缺陷：EventEngine 占位通过 `BacktestResult(True, ...)` 被 GUI 当作成功运行，继而生成无交易 Excel 并显示“股票 0 只”。 |
| M5 通用 VectorEngine 与运行产物 | 未开始 | — |
| M6A BatchRunner 执行器 | 未开始 | — |
| M6B ParameterResearchEngine | 未开始 | — |
| M6C Walk-forward 与稳定性分析 | 未开始 | — |
| M6D 候选参数冻结与晋级 | 未开始 | — |
| M7 交易领域核心 | 未开始 | — |
| M8 MatchingEngine | 未开始 | — |
| M9 EventEngine | 未开始 | — |
| M10 GUI 参数与运行结果 | 进行中 | 2026-09-05：组合净值图标题展示组合六项指标；个股 K 线按当前股票行情与同一报告 BUY/SELL 成交重建单股择时指标并展示买卖点。离屏渲染标题完整，项目 `.venv311` 下 21 项测试通过；动态参数控件、批量运行和 run_id 历史查询仍未实现。 |
| M11 Paper/Live 接入 | 未开始 | — |

下一步默认从 **M4.5 运行状态与占位门禁** 开始；完成后进入 M5。

## M0 基线与测试骨架

目标：在重构前固定现有输入输出和已知问题，建立最小测试运行方式。

测试是长期保留的自动化验收代码，不是回测业务实现。测试文件名必须表达被保护的业务行为，避免使用含义宽泛的 `test_models.py`、`test_config.py` 或只有模块名、没有行为含义的命名。推荐逐步整理为：

```text
tests/
├── unit/
│   ├── test_backtest_run_config_validation.py
│   ├── test_strategy_id_stability_and_resolution.py
│   └── test_trade_action_marker_normalization.py
├── integration/
│   ├── test_s000001_vector_backtest_regression.py
│   └── test_s000002_vector_backtest_regression.py
└── fixtures/
    ├── market_data/
    │   ├── s000001_next_open_execution_case.csv
    │   └── s000002_cross_section_selection_case.csv
    └── expected/
        ├── s000001_vector_expected.json
        └── s000002_vector_expected.json
```

命名语义：

- `validation`：输入字段、范围和跨字段约束验证。
- `stability_and_resolution`：策略 ID 不随扫描顺序变化，并能正确解析到策略。
- `marker_normalization`：报告中的中英文买卖动作统一为标准枚举。
- `regression`：使用固定行情和参数保护现有策略的信号、成交、净值和指标结果。
- `fixtures/market_data`：最小、确定、离线的输入行情，不使用实时 MiniQMT 数据。
- `fixtures/expected`：预期结果快照；只固化确认正确的行为，不固化未来函数或错误成交语义。

现有测试先保持可运行，通过新增测试逐步迁移到上述结构；只有导入路径和统一测试命令验证通过后才重命名或移动旧文件。

交付物：

- 创建 `tests/` 基础结构和统一测试命令。
- 为策略注册解析、现有 `BacktestJobConfig`、S000001/S000002 最小运行入口建立基线测试或固定样例。
- 记录已知不合理行为，不把未来函数或错误成交语义固化为“正确测试”。
- 确认未提交修改的归属并避免覆盖。

验收：测试命令可重复运行；至少一个合同测试能在修改字段或注册行为时可靠失败。

## M1 核心合同与 RunConfig

目标：先定义稳定语言，不改变策略经济逻辑。

交付物：

- `RunConfig`、`RunResult`。
- `SignalFrame`、`TargetPosition`。
- 基础枚举：运行模式、信号方向、订单方向、状态。
- 数据校验和序列化测试。
- 旧 `BacktestJobConfig` 到 `RunConfig` 的兼容适配器。

验收：两个现有策略都能构造同一 `RunConfig`；非法日期、权重、信号和缺失字段会被明确拒绝。

## M2 稳定注册与参数 schema

目标：让策略 ID 稳定，并让 GUI/批量任务能发现参数。

交付物：

- `StrategySpec` 与 `ParameterSchema`。
- S000001/S000002 显式声明稳定 ID、版本、支持模式、资产类型和 warmup。
- 类型、范围、步长、枚举及跨字段校验。
- 兼容旧 `inner_registry.json` 的迁移层。

验收：新增/重命名策略文件不会改变已有策略 ID；无效参数不能启动回测；参数可序列化为配置快照。

## M3 S000001 统一输出适配

目标：保留现有 S000001 算法，通过适配器输出 `SignalFrame/TargetPosition`。

交付物：

- 动量得分和过滤结果写入 SignalFrame，包含 reason。
- 排名与持仓数规则转换为 TargetPosition。
- 去除 ETF→个股静默回退，或将个股版本拆为独立策略 ID。
- 修正信号时间与成交时间边界的测试。

验收：给定固定行情和参数，输出确定、可解释、无未来数据；权重合法且总和符合组合约束。

## M4 S000002 统一输出适配

目标：让 S000002 使用同一合同，保留因子组合和分层逻辑。

交付物：

- 合成因子结果写入 SignalFrame。
- 截面选股/权重转换为 TargetPosition。
- 明确研究用 long-short 与 A 股可交易 long-only 的模式差异。
- 参数不再在模块导入时冻结。

验收：S000001、S000002 能由同一调用方运行；输出 schema 和时间语义一致。

## M4.5 运行状态与占位门禁

目标：消除“事件回测未执行却显示成功、生成报告并加载 0 只股票”的假成功路径，不提前实现 M7-M9。

交付物：

- 为回测结果增加稳定状态：`SUCCEEDED`、`FAILED`、`NOT_IMPLEMENTED`、`CANCELLED`；兼容期保留 `ok`，但只有 `SUCCEEDED` 才能为 true。
- EventEngine 占位返回 `NOT_IMPLEMENTED`，说明缺少 M7 交易核心、M8 MatchingEngine 和 M9 事件循环。
- GUI 仅在 `SUCCEEDED` 时补写/绑定报告、刷新股票列表、绩效和买卖点；其他状态清空本次绑定并显示明确原因。
- 通用报告导出器拒绝把 `NOT_IMPLEMENTED` 写成成功策略报告；如未来需要诊断产物，应使用独立诊断文件名和状态。
- 增加按钮级集成测试：事件占位不生成 Excel、不加载股票；S000001/S000002 向量成功路径保持原行为。

验收：点击事件回测只显示“尚未实现”，不会出现“Excel 报告已生成”或“本次筛选无成功股票”；向量回测与现有报告无回归。

## M5 通用 VectorEngine 与运行产物

目标：取消策略专用引擎分支和策略专用报告主流程。

交付物：

- VectorEngine 通过 StrategyRegistry/StrategySpec 实例化策略。
- 统一数据加载、warmup、成本、净值和指标接口。
- 标准化 `reports/runs/{run_id}` 产物。
- 保留旧 Excel 的兼容导出器。

验收：新增满足合同的策略无需修改 VectorEngine；两个策略均输出统一指标和运行目录。

## M6A BatchRunner 执行器

目标：可靠执行给定的策略参数 Trial，而不仅是因子批量评估；本阶段不负责主动寻找下一组参数。

交付物：

- ParameterSpace、TrialConfig、BatchConfig、BatchResult。
- Trial 参数快照隔离，不修改策略全局变量或共享 JSON。
- 并行调度、失败隔离、超时、取消和可恢复运行。
- TrialStore 状态持久化和确定性随机种子。
- 统一调用 VectorEngine 的单 Trial 接口。

验收：同一数据快照和参数下结果可复现；成功 Trial 不重复计算；失败 Trial 有明确原因；中断后可继续未完成任务。

## M6B ParameterResearchEngine

目标：实现主动提出、寻找和缩小策略参数范围的研究编排层。

交付物：

- StudyConfig、ParameterResearchEngine、Sampler 接口。
- 合法 ParameterSpace 和跨字段约束。
- GridSampler、RandomSampler；固定 random seed。
- Objective、硬约束和 Trial 评价解释。
- 预留 Optuna/TPE 适配接口；基础流程稳定前不设为必需依赖。

验收：搜索器只产生合法参数；同一 StudyConfig 可复现 Trial 序列；更换 Sampler 不修改策略、BatchRunner 或 VectorEngine。

## M6C Walk-forward 与稳定性分析

目标：从“最高历史收益”升级为寻找样本外和参数邻域稳定的参数区域。

交付物：

- train/validation/test 切分和 walk-forward folds。
- StabilityAnalyzer：跨 fold、中位/最差表现、离散度和相邻参数稳定性。
- 手续费、滑点、成交量和标的池扰动压力测试。
- 多目标/Pareto 或配置化综合评分；原始指标全部保留。
- 剪枝规则及被剪枝原因。

验收：最终测试区间未参与搜索；能够识别孤立绩效尖峰并降低其排名；成本提高和相邻参数结果出现在稳定性报告中。

## M6D 候选参数冻结与晋级

目标：把研究结果转换成可追溯、可进入事件回测的参数候选。

交付物：

- ParameterCandidate 与稳定 `parameter_set_id`。
- PromotionPolicy：硬约束、Top K、人工确认状态。
- `reports/studies/{study_id}` 研究产物和候选清单。
- 与 M9 EventEngine 的候选输入合同。

验收：候选参数包含策略版本、数据/标的池快照和完整验证指标；未通过样本外或稳定性门槛的参数不能晋级；测试区间只评价一次。

## M7 交易领域核心

目标：建立事件回测、模拟盘和实盘共享的状态模型。

交付物：

- Account、Position、ExecutionIntent、RiskDecision、Order、Trade。
- 订单状态机、仓位和现金记账。
- T+1、100 股一手、资金/可卖不足、费用模型。
- 幂等和序列化测试。

验收：成交回放后现金、持仓和总资产守恒；非法状态转换被拒绝；重放同一成交不会重复记账。

## M8 MatchingEngine

目标：将订单与历史行情转为现实的成交或拒单。

交付物：

- Market/Limit/Stop 基础撮合。
- next-open、跳空、涨跌停、停牌、滑点和费用。
- 成交量参与率、部分成交和未成交订单。
- 可插拔 FillModel、SlippageModel、CostModel。

验收：用固定 OHLC 场景覆盖正常成交、高低开、涨跌停、停牌、资金不足和部分成交。

## M9 EventEngine

目标：按时间顺序运行完整交易链路。

交付物：

- 事件队列或确定性逐 Bar 循环。
- Market→Signal→Target→Risk→Order→Fill→Account 流程。
- 每日净值、订单、成交、持仓、拒单和审计产物。
- 同一策略与向量结果的信号一致性测试。

验收：事件时间单调、无未来数据；同一配置重复运行结果一致；已覆盖 A 股关键规则。

## M10 GUI 参数与运行结果

目标：让用户选择策略后自动调参、运行、比较并看买卖点。

交付物：

- 根据 ParameterSchema 动态生成控件。
- 单次运行、批量运行、Top K 事件验证入口。
- 参数 Study 配置、搜索进度、排行榜、Pareto/稳定区域和候选参数选择。
- 运行历史按 run_id/batch_id 查询。
- K 线读取标准 Trade，兼容 BUY/SELL 与旧报告别名。

验收：切换策略会切换参数而不污染其他策略；Study/Trial/Run 关联可追溯；股票列表、K 线、买卖点来自同一 run_id。

## M11 Paper/Live 接入

目标：在事件核心稳定后复用到模拟盘和实盘。

交付物：

- PaperBroker 和 MiniQmtBrokerGateway。
- OMS、RiskEngine、账户/持仓同步、审计和告警。
- `paper`、`live_shadow`、`live_small` 分阶段准入。

验收：模拟盘可对账；重启先同步券商状态；任何实盘订单都经过风控和 OMS；没有明确授权时不得触发真实下单。
