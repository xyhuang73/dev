---
name: quant-strategy-roadmap
description: >-
  Guide the staged implementation of the F3_test configurable strategy
  platform: stable strategy IDs, parameter schemas, shared
  SignalFrame/TargetPosition contracts, active parameter discovery, batch
  vector backtests, realistic matching and event backtests, standardized run
  artifacts, GUI integration, and later paper/live reuse. Use when the user
  asks to start, continue, review, or complete a roadmap step. Do not use for
  account balance checks or an isolated strategy-performance diagnosis.
---

# F3_test 可配置策略平台实施路线

## 目标

在保留 `S000001`、`S000002` 等策略编号的前提下，逐步实现：

```text
策略参数可配置
→ 参数空间定义与主动挖掘
→ 批量向量回测筛选
→ 样本外/滚动验证
→ 事件回测验证真实成交
→ GUI 查看运行结果和买卖点
→ 模拟盘与实盘复用
```

先加载项目的 `quant-architecture` skill，并以 `docs/MiniQMT量化交易系统规划.md`，尤其是第 16 节为上位设计约束。

## 按需读取

- 涉及模块边界、对象字段、参数配置、报告结构或行业参考时，读取 [references/architecture.md](references/architecture.md)。
- 涉及参数搜索空间、Grid/Random/Optuna、评价目标、剪枝、Walk-forward、稳定区域或候选参数晋级时，读取 [references/parameter-research.md](references/parameter-research.md)。
- 涉及“开始第一步”“继续下一步”“当前做到哪里”或阶段验收时，读取并维护 [references/roadmap.md](references/roadmap.md)。

## 不可破坏的语义

1. `strategy_id` 标识策略思想，必须显式声明且长期稳定；不得再由文件扫描顺序生成。
2. 参数组合不是新策略。用 `parameter_set_id` 或 `trial_id` 区分；代码行为改变则提升 `strategy_version`。
3. `study_id` 标识一次完整参数研究，`batch_id` 标识其中一批执行任务，`run_id` 标识一次运行。任何好坏比较必须同时记录策略版本、参数、数据、标的池、成本和时间范围。
4. 策略输出统一为 `SignalFrame` 和 `TargetPosition`；策略不得直接调用 MiniQMT，也不得自行维护成交账户。
5. 向量和事件回测复用同一策略定义与参数，但允许使用不同适配器：向量引擎负责快速矩阵计算，事件引擎负责逐事件执行验证。
6. `MatchingEngine` 只判断订单能否以及如何成交，不生成买卖信号。
7. A 股交易规则进入执行、风控、撮合和数据层，不散落到各策略 runner。
8. `ParameterResearchEngine` 负责提出和筛选参数，`BatchRunner` 只负责执行 Trial；搜索器不得直接修改策略全局参数或共享 JSON。
9. 迁移期间优先增加兼容适配器，除非用户明确授权，不一次性推翻现有 GUI、报告或策略文件。
10. 未实际执行策略与成交链路的占位引擎不得返回成功。`NOT_IMPLEMENTED`、`FAILED`、`CANCELLED` 必须与 `SUCCEEDED` 区分；GUI 只能为成功运行加载交易、股票列表和绩效，不得把“未实现”显示为“筛选 0 只”。

## 占位引擎与 GUI 门禁

在 EventEngine、MatchingEngine 或某个策略模式尚未实现时：

- 引擎应返回明确的 `RunStatus.NOT_IMPLEMENTED`，并令兼容字段 `ok=False`。
- 占位结果可以展示说明，但不得生成带有“回测成功”含义的报告。
- GUI 不得调用交易明细、股票列表、K 线买卖点或绩效加载流程。
- 不得用空 `Trade`、空股票列表或零收益冒充一次有效运行。
- 正式 EventEngine 只有在 Market→Signal→Target→Risk→Order→Fill→Account 链路执行完成且产物校验通过后，才能返回 `SUCCEEDED`。
- 为这些分支保留按钮级集成测试，保证向量回测成功路径不受影响。

## 推荐目标目录

目标目录是渐进迁移的归属约定，不要求一次性创建或搬空旧目录。新功能优先进入以下位置：

```text
apps/                 # GUI、CLI、定时任务和用户交互
quant/
  data/               # 行情、清洗、股票池、交易日历、特征
  strategy/           # 策略、因子、信号、组合、注册表和参数 schema
  engine/             # orchestrator、vector、batch、event、paper、live
  trading/            # account、position、order、trade、OMS、risk、matching
  gateway/            # 本地数据、MiniQMT 行情/交易、存储适配
  report/             # 指标、交易记录、运行产物和导出
  infra/              # 配置、日志、审计、监控和告警
configs/              # 按 data/strategies/backtest/risk/paper/live 分类
data/                 # 数据快照和股票池快照
reports/              # runs/{run_id}、batches/{batch_id}、studies/{study_id}
tests/                # unit、integration、replay
```

当前 `BackTest/`、`InnerStrategy/`、`Prepare/`、`MinQmtRun/` 等目录是迁移来源，不是新的长期边界。开始任何路线图阶段时，先确认当前文件实际职责，再用 Adapter 或 Facade 接入目标模块；验收通过后再缩减旧实现。禁止为了“目录看起来统一”而进行无测试的大规模搬家。

## 循序渐进的代码改造原则

每次改造必须形成一个可回滚、可验证的小闭环：

1. 先记录现有行为和测试基线，再定义本阶段合同。
2. 先增加新合同、适配器或并行实现，再切换一个调用方。
3. 保持 `S000001`、`S000002` 的现有经济含义和旧报告兼容，除非用户明确批准策略变更。
4. 新旧路径并存期间，用同一组固定数据比较信号、目标仓位、成交和指标。
5. 测试通过后才扩大迁移范围；未通过不得删除旧代码或标记里程碑完成。
6. 每个阶段只处理一个主要边界：合同、注册/参数、向量、批量、交易核心、撮合、事件、GUI、实盘按顺序推进。

优先采用以下顺序：

```text
基线测试
→ RunSpec/SignalFrame/TargetPosition
→ 稳定注册和参数 schema
→ 旧策略适配
→ 运行状态与占位 GUI 门禁
→ 通用 VectorEngine
→ BatchRunner
→ ParameterResearchEngine
→ Walk-forward/稳定性与候选晋级
→ Account/Order/Trade/Risk/OMS
→ MatchingEngine
→ EventEngine
→ GUI
→ Paper/Live
```

## 调参与寻参模块边界

“调参”与“寻参”必须分开：

- `ParameterSchema`：声明参数类型、默认值、范围、步长、枚举、条件约束和是否可搜索；GUI 根据它生成单次运行控件。
- `ParameterSpace`：把可搜索参数转换为合法搜索空间，不读取或修改全局 JSON。
- `BatchRunner`：执行已经明确给出的 `TrialConfig` 列表，负责并行、失败隔离、断点恢复和结果持久化，不决定参数优劣。
- `ParameterResearchEngine`：创建 Study，使用 Grid/Random（后续可接 Optuna/TPE）提出 Trial，调用 `BatchRunner`，根据目标函数、硬约束、Walk-forward 和稳定性分析缩小范围。
- `StabilityAnalyzer`：检查跨窗口、相邻参数、成本压力和标的池扰动，避免只选历史最高收益的孤立参数。
- `PromotionPolicy`：将通过样本外和稳定性门槛的结果冻结为 `parameter_set_id`，仅把少量候选交给 `EventEngine`。

调参/寻参链路必须是：

```text
StrategySpec + ParameterSchema
→ ParameterSpace
→ ParameterResearchEngine/Sampler
→ BatchRunner
→ VectorEngine
→ TrialResult/Leaderboard
→ Walk-forward + StabilityAnalyzer
→ PromotionPolicy
→ EventEngine 验证 Top K
```

每个 `study_id`、`batch_id`、`trial_id` 和 `parameter_set_id` 都必须保存策略版本、完整参数、数据/标的池快照、成本模型、时间区间、随机种子、指标和失败原因。寻参不能直接修改策略模块的全局参数，也不能把最终测试区间用于反复选择参数。

## 每次继续路线图时

1. 读取路线图状态、相关实现和测试，检查工作区未提交改动；不得把文件存在视为阶段完成。
2. 选择最早一个未通过验收的里程碑。若用户指定阶段，只做该阶段及其必要前置修复。
3. 开工前说明本次层级、输入、输出、消费方、兼容范围和验收命令。
4. 保持任务小而闭环。不要在领域对象尚未稳定时同时重写 GUI、事件引擎和实盘网关。
5. 为新合同增加单元测试；为跨模块链路增加最小集成测试。测试必须覆盖行为，不只检查文件或字段存在。
6. 验证通过后，更新路线图中的状态、证据和下一步；未通过不得标记完成。
7. 最终汇报已完成内容、验证结果、兼容性影响、遗留风险和下一里程碑。

## 回测准入规则

- 批量参数搜索先走向量引擎；只把样本外稳定的 Top K 送入事件回测。
- 参数优化区间与最终测试区间必须隔离，或使用 walk-forward；禁止在同一区间选参又宣称样本外有效。
- 优先选择跨窗口和相邻参数都稳定的参数区域，不选择孤立的单点最高收益。
- 事件回测至少覆盖现金、持仓、T+1、100 股一手、费用税费、滑点、停牌、涨跌停、资金/可卖数量不足。
- 收益排名不得只看总收益或 Sharpe；至少联合最大回撤、换手、交易数、成本敏感度和跨窗口稳定性。
- 使用当日收盘信息生成的信号，默认下一可成交时点执行；任何同 Bar 成交假设必须显式说明并证明数据在当时可得。

## 停止条件

- 若当前阶段需要改变策略经济含义、历史报告口径或实盘权限，而用户未明确授权，停止并说明决策点。
- 若工作区已有与本阶段重叠的未提交修改，先分析能否兼容；不能安全合并时请求用户决定。
- 不因后续阶段很重要而越过当前验收门槛。
