# 参数寻找与挖掘架构

## 1. 目标与边界

参数研究的目标不是找到历史收益最高的单个参数，而是找到在不同时间窗口、相邻参数、成本变化和标的池扰动下仍然稳定的可执行参数区域。

职责必须分开：

```text
ParameterResearchEngine：决定搜索什么、下一组参数是什么、如何评价和晋级
BatchRunner：可靠执行一批 Trial、并行、失败隔离、断点恢复
VectorEngine：计算一个 Trial 的信号、目标仓位、净值和指标
EventEngine：验证少量候选参数的真实订单和成交约束
```

参数研究属于研究/编排层，不进入策略、撮合、OMS 或 MiniQMT 网关。

## 2. 推荐模块

```text
quant/research/parameter_search/
├── models.py          # StudyConfig、TrialConfig、TrialResult、ParameterCandidate
├── space.py           # 参数范围、步长、枚举和条件约束
├── samplers.py        # Grid、Random、Optuna/TPE 适配器
├── objective.py       # 硬约束、单目标、多目标和评分解释
├── pruning.py         # 低质量 Trial 的提前终止策略
├── walk_forward.py    # 训练/验证/测试及滚动窗口
├── stability.py       # 参数邻域、跨窗口和成本稳定性
├── promotion.py       # Top K 与 ParameterSet 冻结规则
└── service.py         # ParameterResearchEngine 编排

quant/infra/trial_store.py   # Study/Trial 状态及断点恢复
quant/engine/vector.py       # 单个 Trial 的快速计算
```

GUI 只提交 `StudyConfig` 并展示进度与结果，不包含搜索算法。

## 3. 核心对象

### StudyConfig

```text
study_id, strategy_id, strategy_version,
base_run_config, parameter_space, sampler,
train_windows, validation_windows, test_window,
objective, constraints, max_trials, random_seed,
pruner, promotion_policy
```

### ParameterSpace

每个参数至少描述：

```text
name, type, low/high 或 choices, step/log,
searchable, condition, description
```

支持跨字段约束，例如：

```text
short_window < long_window
stop_loss < take_profit
holdings_num <= universe_min_size
```

无法满足约束的组合在运行回测前直接拒绝，不消耗 Trial。

### TrialConfig / TrialResult

```text
TrialConfig：trial_id, study_id, parameter_values, fold_id, run_config
TrialResult：trial_id, status, metrics, duration, artifacts, failure_reason
```

每个 Trial 必须使用独立的不可变参数快照，不得改写 `Config/*.json` 或策略模块全局变量。

### ParameterCandidate

```text
parameter_set_id, strategy_id, strategy_version,
parameter_values, selected_from_study,
validation_metrics, stability_metrics,
event_backtest_status, approval_status
```

只有通过样本外、稳定性和事件回测的候选参数才能标记为可用于模拟盘。

## 4. 搜索器采用顺序

### 第一阶段：GridSampler

用于参数少、离散范围明确的情况。结果容易解释，可用于验证 ParameterSpace、TrialStore 和排行榜是否正确。

### 第二阶段：RandomSampler

用于维度较多或参数范围较宽的情况。必须固定 `random_seed`，支持重复运行和补充采样。

### 第三阶段：Optuna/TPE 适配器

在 Grid/Random、断点恢复和目标函数稳定后再引入 Optuna。通过统一 `Sampler` 接口接入，策略和 VectorEngine 不得直接 import Optuna。

优先使用：

- TPE 搜索连续/离散/条件参数。
- SQLite 或项目 TrialStore 持久化 Study。
- Pruner 提前停止明显不合格的 Trial。
- 多目标 Study 输出 Pareto 前沿。

初期不优先引入遗传算法或强化学习搜索；它们增加调试和过拟合成本，却不修复数据、成交或评价口径问题。

## 5. 搜索与验证流程

```text
定义有经济含义的参数范围
→ 粗粒度 Grid/Random 搜索
→ 样本内硬约束过滤
→ 验证集评分
→ 在稳定区域缩小范围
→ Walk-forward 重复验证
→ 成本与标的池压力测试
→ 冻结候选 ParameterSet
→ Top K 进入 EventEngine
→ 独立测试区间只评价一次
```

禁止：

- 在最终测试区间反复调参。
- 用全样本选出参数后，再把全样本结果当作样本外证明。
- 因事件回测更真实，就直接用事件引擎搜索全部参数。
- 运行失败时静默丢弃，从而让排行榜产生选择偏差。

## 6. 目标函数与硬约束

先应用硬约束，再排序。例如：

```text
max_drawdown <= 20%
n_trades >= 30
validation_return > 0
double_cost_return > 0
```

不要默认只优化总收益或 Sharpe。支持两种模式：

1. 多目标/Pareto：同时最大化收益和稳定性，最小化回撤与换手。
2. 可解释综合评分：例如跨 fold 的中位 Calmar，减去离散度、换手、成本敏感度和收益集中度惩罚。

具体权重必须写入 `StudyConfig`，不得藏在代码常量中。报告必须展示原始指标，不能只保存最终分数。

## 7. 稳定区域选择

`StabilityAnalyzer` 至少检查：

- Walk-forward 各 fold 的中位数、最差值和离散程度。
- 相邻参数组合的绩效变化，识别平台与尖峰。
- 按年度、牛熊/震荡阶段的表现。
- 手续费、滑点和成交量限制上调后的衰减。
- 标的池轻微扰动后的稳定性。
- 收益是否集中于少数月份、股票或交易。

推荐选择宽而平稳的参数平台，不选择只有一个格点特别高的尖峰。参数邻域定义随参数类型配置，不硬编码统一距离。

## 8. 剪枝原则

剪枝只用于节约计算，不得改变最终评价口径。

可安全提前终止的例子：

- 已违反不可恢复的最大回撤硬约束。
- 有效交易数或数据覆盖明显不足。
- 中间 fold 已失败且按 StudyConfig 不允许容错。
- Trial 参数或输出出现 NaN/非法状态。

不要仅因前几个交易日收益较低就剪枝；交易策略的收益路径不平稳，过度激进的剪枝会系统性排除慢启动策略。

## 9. 产物与恢复

```text
reports/studies/{study_id}/
├── study_config.json
├── search_space.json
├── trials.parquet
├── fold_metrics.parquet
├── leaderboard.xlsx
├── pareto_front.parquet
├── stability_report.json
├── selected_candidates.json
└── failures.json
```

TrialStore 记录 `PENDING/RUNNING/SUCCEEDED/FAILED/PRUNED`。进程异常重启后，只重跑未完成或按策略允许重试的 Trial；成功 Trial 不重复计算。

## 10. 与路线图的关系

- M2：ParameterSchema 增加 `searchable`、范围、步长、条件和约束。
- M5：VectorEngine 提供稳定的单 Trial 评价接口。
- M6A：BatchRunner 负责执行。
- M6B：ParameterResearchEngine 与 Grid/Random/Optuna 采样。
- M6C：Walk-forward、稳定区域和压力测试。
- M6D：候选参数冻结与 Top K 晋级。
- M9：EventEngine 对候选参数做成交真实性验证。
- M10：GUI 提供 Study 配置、进度、排行榜、参数邻域和候选选择。

参考 Optuna 文档：<https://optuna.readthedocs.io/en/stable/>。是否安装及何时接入由 M6B 决定，在此前不得让它成为 M0-M5 的前置依赖。
