# 可配置策略平台目标架构

## 1. 标识与版本

| 标识 | 语义 | 示例 |
|---|---|---|
| `strategy_id` | 稳定的策略思想编号 | `S000001` |
| `strategy_version` | 会影响信号或目标仓位的代码版本 | `1.2.0` |
| `parameter_set_id` | 一份已保存的参数集 | `PS-S000001-A3F2` |
| `study_id` | 一次完整参数寻找与验证研究 | `STUDY-S000001-20260905` |
| `trial_id` | 批量任务中的一个参数组合 | `trial-00017` |
| `run_id` | 一次独立运行 | `BT-20260905-0001` |
| `batch_id` | Study 内一批待执行 Trial | `BATCH-20260905-01` |
| `dataset_id` | 可复现的数据快照 | `CN-D1-20260904` |
| `universe_id` | 可复现的每日标的池快照 | `ETF-POOL-V3` |

策略注册信息由策略自身显式声明。文件发现可以自动化，但不得根据文件排序重新编号。

## 2. 分层与依赖方向

```text
GUI / CLI / Notebook
        ↓
RunOrchestrator：生成 run_id、冻结配置、调度任务
        ↓
StrategyRegistry + DatasetSnapshot
        ↓
Strategy：SignalFrame → TargetPosition
        ├────────→ VectorEngine ← BatchRunner
        └────────→ EventEngine
                         ↓
ExecutionPlanner → RiskEngine → OMS
                         ↓
          MatchingEngine / BrokerGateway
                         ↓
Account + Position + Order + Trade
                         ↓
RunArtifacts → Report → K线买卖点

ParameterResearchEngine
        ↓ 提出 Trial、评价、缩小范围、晋级
BatchRunner → VectorEngine → TrialResult
        ↑______________________________|
```

依赖只能向下：GUI 不写策略逻辑；策略不读取 GUI 控件、不调用 MiniQMT、不写 Excel；报告模块不反向影响成交。

## 3. 核心合同

### RunConfig

至少包含：

```text
run_id, mode, strategy_id, strategy_version, strategy_params,
start, end, warmup_start, initial_capital,
dataset_id, universe_id, benchmark,
cost_model, slippage_model, fill_model, risk_profile, random_seed
```

创建后按不可变对象使用，并原样保存到运行目录。

### SignalFrame

策略对标的的判断，不等于订单。最低字段：

```text
datetime, symbol, score, signal, reason
```

`signal` 使用稳定枚举，例如 `LONG`、`SHORT`、`FLAT`、`EXIT`。A 股实盘是否允许执行 `SHORT` 由组合和风控层决定。

### TargetPosition

策略/组合层期望达到的最终仓位。最低字段：

```text
datetime, symbol, target_weight 或 target_volume, reason
```

组合层负责持仓数、权重、现金比例、行业和集中度约束；不负责模拟成交。

### ExecutionIntent / Order / Trade

```text
ExecutionIntent：symbol, side, volume, price_type, limit_price, reason
Order：order_id, client_order_id, symbol, side, price, volume, status
Trade：trade_id, order_id, symbol, datetime, price, volume, commission, tax, slippage
```

### Account / Position

```text
Account：cash, frozen_cash, market_value, total_asset
Position：symbol, volume, available, frozen, cost, market_value
```

`available` 必须独立于 `volume`，以表达 A 股 T+1。

## 4. StrategySpec 与参数模式

每个策略注册：

```text
strategy_id, strategy_version, display_name,
parameter_schema, supported_modes, asset_types,
required_fields, warmup_bars
```

参数 schema 要表达类型、默认值、范围、步长、枚举、说明、分组、是否可搜索、搜索尺度、条件参数以及跨字段约束。GUI 根据 schema 生成控件；`ParameterResearchEngine` 根据 schema 构造合法搜索空间；运行值通过 `RunConfig` 注入策略，不由策略模块在运行中读取全局 JSON。

推荐配置形态：

```yaml
strategy:
  id: S000001
  version: 1.1.0
  params:
    lookback_days: 25
    holdings_num: 3
    rebalance_days: 5

data:
  dataset_id: CN-D1-20260904
  universe_id: ETF-POOL-V3
  start: 2022-01-01
  end: 2025-12-31

execution:
  signal_time: close
  fill_time: next_open
  cost_model: ashare-default
  slippage_bps: 5
```

## 5. 两类回测

### VectorEngine

用途是因子研究、参数扫描和快速组合验证。输入完整面板与策略参数，输出信号、目标仓位、简化成本后的净值和指标。不得在策略专用 runner 中复制数据加载与报告逻辑。

### EventEngine

用途是验证接近实盘的状态变化：

```text
MarketEvent
→ Strategy
→ TargetPosition
→ ExecutionIntent
→ RiskDecision
→ Order
→ MatchingEngine
→ Fill/Trade
→ Account/Position 更新
```

同一事件按固定顺序处理，时间戳不得倒退；订单状态转换和成交回报必须可审计、可重放。

尚未实现上述链路的 EventEngine 必须返回 `NOT_IMPLEMENTED`，不能返回成功、零交易或零收益。GUI 只有在状态为 `SUCCEEDED` 时才可以生成/绑定策略报告并读取交易、股票列表、绩效和买卖点。

### MatchingEngine

模拟交易所/券商的成交行为。它接收订单与当时可见行情，输出成交、部分成交、拒绝或继续挂单。模型至少覆盖：

- 市价、限价、止损等基础订单语义。
- 下一 Bar 开盘、指定价触发和跳空处理。
- 停牌、涨跌停、价格笼子（适用时）。
- 成交量参与率和部分成交。
- 手续费、最低佣金、印花税、过户费、滑点。
- 资金、持仓与 T+1 可卖约束。

回测时使用 `SimulatedBroker + MatchingEngine`；实盘时换成 `MiniQmtBrokerGateway`，策略和交易领域对象保持不变。

## 6. 参数研究与批量策略回测

### 6.1 目标代码归属

参数相关代码建议按以下边界实现：

```text
quant/strategy/parameters.py       # ParameterSchema、ParameterSpace、TrialConfig
quant/engine/batch.py              # BatchRunner、断点恢复、失败隔离
quant/engine/research.py           # ParameterResearchEngine、Study 编排
quant/engine/samplers.py           # Grid/Random，后续 Optuna/TPE 适配
quant/report/stability.py           # StabilityAnalyzer、排行榜和研究报告
quant/strategy/promotion.py        # PromotionPolicy、ParameterCandidate
configs/strategies/                # 默认参数和可搜索空间
reports/batches/                   # 批量执行产物
reports/studies/                   # 参数研究产物
```

现有 `BackTest/factor_batch_job.py` 可作为研究功能的迁移来源，但不能继续把“因子批量评估”直接当作通用策略参数搜索；迁移时先包 Adapter，再逐步替换调用方。

参数寻找与批量执行必须分离：

- `ParameterResearchEngine`：定义 Study、调用 Sampler 提出参数、评价 Trial、执行 Walk-forward/稳定性分析并晋级候选参数。
- `BatchRunner`：接收明确的 Trial 列表，负责并行执行、失败隔离、断点恢复和结果持久化，不决定参数好坏。
- `VectorEngine`：执行单个 Trial 的快速回测。
- `EventEngine`：只验证少量已晋级候选参数，不承担全空间搜索。

```text
ParameterSpace
→ ParameterResearchEngine
→ Sampler（grid / random，后续可接 Optuna/TPE）
→ BatchRunner
→ VectorEngine 并行运行并返回 TrialResult
→ 样本内筛选
→ 样本外/Walk-forward
→ 参数邻域、稳定性与成本压力测试
→ 冻结 ParameterCandidate
→ Top K 进入 EventEngine
→ Leaderboard
```

每个 Study、Batch 和 Trial 保存完整配置及失败原因。排行榜至少包含年化收益、最大回撤、Sharpe、Calmar、换手率、交易数、平均持仓期、成本后收益、跨窗口稳定性、参数邻域稳定性和收益集中度。

参数选择优先寻找宽而平稳的平台，不选择孤立的单点最高收益。先应用最大回撤、最少交易数、样本外收益和成本后收益等硬约束，再做多目标/Pareto 或可解释综合排序。

线程池适合 I/O；CPU 密集因子与参数计算优先考虑进程池或引擎原生并行。共享只读数据快照和特征缓存，禁止多个 trial 修改同一个全局配置文件。

详细合同和采用顺序见 [parameter-research.md](parameter-research.md)。

## 7. 运行产物

```text
reports/runs/{run_id}/
├── config.json
├── metadata.json
├── metrics.json
├── signals.parquet
├── targets.parquet
├── orders.parquet
├── trades.parquet
├── positions.parquet
├── equity.parquet
└── report.html

reports/batches/{batch_id}/
├── search_space.json
├── trials.parquet
├── leaderboard.xlsx
└── selected_trials.json

reports/studies/{study_id}/
├── study_config.json
├── search_space.json
├── fold_metrics.parquet
├── pareto_front.parquet
├── stability_report.json
├── selected_candidates.json
└── failures.json
```

GUI 按 `run_id + symbol` 读取行情和 `trades`，不得通过“全局最新 Excel”猜测当前报告。

## 8. 迁移期间禁止继续扩大的做法

- 按策略类名在引擎中增加新的 `if/elif` 分支。
- 每个策略自建一套数据加载、成交、绩效和 Excel 代码。
- ETF 数据缺失时静默切换成个股策略。
- 使用当日收盘信号却按当日或昨日已知价格成交。
- 把参数直接固化在策略全局变量，或让批量 trial 修改共享 JSON。
- 让 BatchRunner 同时负责参数生成、执行和最终选择，导致搜索算法与回测执行耦合。
- 在最终测试区间反复调参，或只选择孤立的历史最高收益参数。
- 用 EventEngine 穷举全部参数，而不是用 VectorEngine 筛选后验证 Top K。
- 只记录成交，不记录信号、目标仓位、订单、拒单和账户状态。
- 用策略编号单独代表策略好坏，忽略版本、参数、数据和成本。

## 9. 参考框架中采用的原则

- Qlib：松耦合组件、配置驱动实例化、训练/验证/测试切分、每次 execution 记录产物。
  <https://qlib.readthedocs.io/en/latest/component/workflow.html>
- Backtrader：策略生命周期、参数化重复实例、Broker/Order/Trade 通知以及下一 Bar 成交语义。
  <https://www.backtrader.com/docu/strategy/>
- LEAN：参数在代码外注入、walk-forward、过拟合与未来函数控制，以及可替换的 Fill/Fee/Slippage/BuyingPower 模型。
  <https://www.quantconnect.com/docs/v2/writing-algorithms/optimization/parameters>
  <https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/key-concepts>
- Optuna：可插拔 TPE 采样、条件搜索空间、剪枝和 Study 持久化；在基础 Grid/Random 流程稳定后接入。
  <https://optuna.readthedocs.io/en/stable/>

只借鉴这些边界与合同，不要求在本项目直接引入整套第三方框架。
