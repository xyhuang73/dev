# 量化 Skills 简介

本项目当前包含 13 个量化相关 skills，位于 `skills/` 目录。它们不是同一种东西：有些偏“研究/审计流程”，有些偏“代码模板/脚本工具”，有些偏“RL 交易系统专项工程”。

## 快速选择

| 你要做什么 | 推荐 skill |
|---|---|
| 判断一个策略研究是否可信、证据链是否完整 | `quant-research-lifecycle` |
| 检查数据有没有未来函数、时间戳错位、缺失和重复 | `quant-data-pit-pipeline` |
| 写一个更接近实盘的事件驱动回测框架 | `quant-event-driven-backtest` |
| 写一个结构清楚的策略代码骨架 | `quant-strategy-template` |
| 把目标仓位安全地转成订单、处理撤单/部分成交/重试 | `quant-order-execution-adapter` |
| 准备 paper trading、小资金实盘、上线检查 | `quant-live-trading-ops` |
| 根据收益率 CSV 生成绩效和风险报告 | `quant-portfolio-risk-reporting` |
| 做因子、技术指标、ML 特征工程 | `quant-feature-engineering` |
| 构建 RL 交易环境、reward、成本和执行约束 | `quant-trading-env` |
| 做 MoE 混合专家 RL 交易系统 | `quant-moe-rl` |
| 做实盘风控、安全模式、对账、告警 | `quant-risk-execution` |
| 做 walk-forward、样本外、压力测试和 alpha 审计 | `quant-walk-forward-validation` |
| 对整个量化项目做对抗式审计 | `quant-project-audit` |

## 新增的 Rich Skills

### `quant-research-lifecycle`

用途：管理一个量化研究从想法到候选策略的完整证据链。

适合用在：你有一个策略、模型或研究仓库，想判断它是不是“可信研究”，而不是只看一条漂亮收益曲线。

包含资源：

- `templates/experiment_manifest.json`：实验登记模板。
- `scripts/validate_manifest.py`：检查实验登记是否缺关键字段。

### `quant-data-pit-pipeline`

用途：检查和设计防未来函数的数据管线。

适合用在：你有行情、因子、财报、宏观、跨资产数据，担心时间戳、可见时间、复权、缺失值、交易日历有问题。

包含资源：

- `templates/data_contract.json`：数据契约模板。
- `scripts/audit_pit_csv.py`：CSV 数据审计脚本。

### `quant-event-driven-backtest`

用途：搭建事件驱动回测框架，让回测更接近实盘交易过程。

适合用在：你不想只做向量化收益计算，而是要显式处理 market event、signal、order、fill、portfolio。

包含资源：

- `templates/event_engine_skeleton.py`：可运行的事件驱动回测骨架。

### `quant-strategy-template`

用途：生成或检查策略代码结构。

适合用在：你要把策略逻辑写成清楚的代码，把参数、状态、指标、信号、仓位、风控、订单更新分开。

包含资源：

- `templates/strategy_template.py`：策略类模板。
- `scripts/check_strategy_template.py`：静态检查脚本，检查策略生命周期方法和信号层是否混入下单逻辑。

### `quant-order-execution-adapter`

用途：设计订单执行适配层。

适合用在：你要接券商、交易所、模拟 broker，或需要处理 client order id、幂等下单、部分成交、撤改单、重试、对账。

包含资源：

- `templates/order_intent_schema.json`：订单意图模板。
- `scripts/order_state_machine.py`：订单状态机模拟脚本。

### `quant-live-trading-ops`

用途：实盘或 paper trading 上线前检查。

适合用在：你准备从回测进入 dry-run、paper、小资金或 live，要检查配置隔离、API key、限额、告警、对账、safe mode。

包含资源：

- `templates/live_config.example.json`：上线配置模板。
- `scripts/check_live_config.py`：配置安全检查脚本。

### `quant-portfolio-risk-reporting`

用途：生成策略绩效和风险报告。

适合用在：你有收益率 CSV，想快速得到 CAGR、波动、Sharpe、Sortino、最大回撤、Calmar、月度收益。

包含资源：

- `scripts/portfolio_report.py`：标准库绩效报告脚本。

## 原有专项 Skills

### `quant-feature-engineering`

用途：量化特征工程。

适合用在：构建 OHLCV 到技术指标、因子矩阵、ML 信号预测器的管线，重点是防 look-ahead bias、`shift(1)`、数据清洗和多资产参数化。

特点：内容偏工程 playbook，里面有大量特征工程代码范式和注意事项。

### `quant-trading-env`

用途：RL 交易环境设计。

适合用在：创建 Gymnasium 风格交易环境、设计 reward、成本建模、执行约束、训练/推理一致性。

特点：重点是四重执行约束、交易成本、资金费率、波动率目标杠杆和 feature mask。

### `quant-moe-rl`

用途：MoE 混合专家 RL 决策系统。

适合用在：不同市场状态下切换专家策略，例如 bear、high_vol、low_vol、fast_adapt 等。

特点：覆盖专家特化、门控路由、多阶段训练、温度参数和正则化。

### `quant-risk-execution`

用途：实盘风控和执行安全。

适合用在：给交易系统加分层限仓、幂等下单、持仓对账、SAFE_MODE、渐进放量和多渠道告警。

特点：比 `quant-live-trading-ops` 更偏实盘风控代码和执行安全细节。

### `quant-walk-forward-validation`

用途：Walk-forward 验证和 alpha 审计。

适合用在：检查策略样本外表现、压力测试、消融实验、bootstrap 显著性、gate 坍缩。

特点：重点是判断一个策略是否真有 alpha，而不是只在单个历史窗口有效。

### `quant-project-audit`

用途：整个量化项目的对抗式审计。

适合用在：你给一个完整仓库或策略系统，让 agent 查未来函数、幸存者偏差、数据泄漏、过拟合、执行不真实和上线风险。

特点：这是总审计 skill，会把数据、代码、模型、回测、执行、生产风险放在一起看。

## 建议使用顺序

如果你是从零做一个策略：

1. `quant-research-lifecycle`
2. `quant-data-pit-pipeline`
3. `quant-feature-engineering`
4. `quant-strategy-template`
5. `quant-event-driven-backtest`
6. `quant-walk-forward-validation`
7. `quant-portfolio-risk-reporting`
8. `quant-order-execution-adapter`
9. `quant-live-trading-ops`
10. `quant-risk-execution`

如果你是做 RL 或 MoE 交易系统：

1. `quant-feature-engineering`
2. `quant-trading-env`
3. `quant-moe-rl`
4. `quant-walk-forward-validation`
5. `quant-risk-execution`
6. `quant-live-trading-ops`

如果你是审查别人给你的量化仓库：

1. `quant-project-audit`
2. `quant-data-pit-pipeline`
3. `quant-event-driven-backtest`
4. `quant-walk-forward-validation`
5. `quant-portfolio-risk-reporting`
