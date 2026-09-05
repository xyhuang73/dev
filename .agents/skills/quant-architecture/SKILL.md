---
name: quant-architecture
description: >-
  Default skill for F3_0425 quant trading architecture design, refactoring,
  offline data research, backtesting, paper trading, live trading, risk control,
  MiniQMT gateway boundary, and strategy lifecycle work. Always load this first
  when the user asks about 量化交易架构、回测、实盘模拟、实盘交易、策略研发流水线、风控、OMS、数据层 or 架构重构.
---

# F3_0425 主流量化交易架构约定

## 默认触发

用户提到以下任意意图时，先按本 skill 执行：

- 量化交易系统架构、重构、目录设计
- 离线数据、数据清洗、因子数据、Feature Store
- 历史回测、向量化回测、事件驱动回测
- 实盘模拟、Paper Trading、仿真撮合
- 实盘交易、OMS、订单状态机、风控、监控、审计
- MiniQMT / XtQuant 在系统中的边界
- 策略从研究到实盘的流水线

## 主设计文档

优先参考并维护：

- `docs/MiniQMT量化交易系统规划.md`

该文档是项目目标架构的主说明，后续涉及量化交易架构的设计、代码迁移和模块拆分，应尽量与文档保持一致。

## 总体架构原则

系统按以下层次设计：

1. 应用入口层：CLI / GUI / Notebook / Scheduler
2. 业务编排层：研究任务、回测任务、模拟盘任务、实盘任务、复盘任务
3. 策略层：Signal / Alpha / Portfolio / RiskRule
4. 引擎层：ResearchEngine / BacktestEngine / PaperEngine / LiveEngine
5. 交易核心层：Account / Position / Order / Trade / OMS / Risk
6. 网关层：MarketDataGateway / BrokerGateway / StorageGateway
7. 数据层：Raw Data / Clean Data / Feature Store / Calendar / Metadata
8. 基础设施层：Config / Logging / Audit / Monitor / Alert

## 关键边界

- 系统主要针对 A 股，必须显式处理 A 股交易规则，而不是散落在策略脚本里。
- 策略不得直接调用 MiniQMT / XtQuant 下单。
- MiniQMT 只属于网关层：
  - `xtdata`、本地 `datadir`、历史行情下载属于行情网关。
  - `XtQuantTrader`、下单、撤单、成交、持仓、资金属于交易网关。
- 回测不得依赖实盘账户连接。
- 实盘不得绕过风控和 OMS。
- 订单、成交、资金、持仓、风控结果必须可持久化和可复盘。
- 每次任务运行必须有任务 ID、配置快照和日志。

## A 股专项要求

A 股相关设计必须优先考虑：

- 交易日历、交易时段、午休、集合竞价、连续竞价。
- T+1 可卖限制，`Position.available` 必须独立于 `Position.volume`。
- 股票买入 100 股一手、零股卖出约束。
- 主板、创业板、科创板、北交所、ST 等不同涨跌幅限制。
- 停牌、复牌、ST、退市整理、新股和次新股过滤。
- 佣金、印花税、过户费、最低佣金等成本模型。
- 复权价用于研究信号，真实价格用于成交模拟。
- 标的池应独立构建并保存每日快照，记录剔除原因。
- A 股真实做空受限，多空回测结果不能直接等同可交易收益。

## 推荐目标目录

新架构优先使用以下目录思想：

```text
apps/                # CLI / GUI / Scheduler
quant/data/          # 数据源、清洗、存储、交易日历、特征库
quant/strategy/      # alpha、signal、portfolio、策略注册
quant/engine/        # research、backtest、paper、live
quant/trading/       # account、position、order、trade、oms、risk
quant/gateway/       # local_data、miniqmt_market、miniqmt_broker
quant/report/        # 回测、模拟、实盘报告
quant/infra/         # 配置、日志、审计、监控、告警
configs/             # data、risk、backtest、paper、live 配置
data/                # raw、clean、feature、backtest 本地数据
reports/             # 任务输出、报告、快照
tests/               # 单元测试、集成测试、回放测试
```

当前项目无需一次性推倒重写。新功能优先按目标结构设计，旧模块通过适配层迁移。

## 模块化落代码要求

后续根据交易系统规划直接写代码时，必须优先参考 `docs/MiniQMT量化交易系统规划.md` 的 `## 16. 模块化落代码规格：目录、输入、输出、接口一一对应`。

编码前必须明确：

1. 模块所属目录和架构层级。
2. 输入对象、输入字段和来源。
3. 输出对象、输出字段和消费方。
4. 是否依赖 MiniQMT；如依赖，只能放在网关层。
5. 是否处理 A 股交易规则。
6. 是否需要持久化、日志、审计和报告。
7. 是否可以被回测、模拟、实盘复用。

核心对象语义应保持稳定：

- `RunConfig`：任务运行配置，包含 `run_id`、`mode`、`strategy_id`、时间范围、账户信息。
- `Instrument` / `Bar` / `Tick`：标准行情对象。
- `SignalFrame`：策略信号输出。
- `TargetPosition`：组合层目标仓位输出。
- `ExecutionIntent`：执行层下单意图。
- `RiskDecision`：风控输出，必须是 `PASS`、`REJECT` 或 `ADJUST`。
- `Order` / `Trade`：OMS 与网关统一订单成交模型。
- `Position` / `Account`：统一持仓账户模型。
- `RunResult`：引擎输出结果，包含状态、指标、报告路径和错误信息。

接口边界：

- 行情统一通过 `MarketDataGateway`。
- 交易统一通过 `BrokerGateway`。
- 策略统一通过 `Strategy.generate_signals()` 和 `Strategy.build_targets()`。
- 风控统一通过 `RiskRule.check()`。
- 引擎统一通过 `Engine.run(config)`。

## 当前项目迁移参考

| 当前模块 | 目标位置 | 迁移方式 |
|----------|----------|----------|
| `qmt_service.py` | `quant/gateway/miniqmt_market.py` | 包成行情网关 |
| `qmt_account.py` | `quant/gateway/miniqmt_broker.py` 或账户工具 | 账户查询继续复用，交易进入 BrokerGateway |
| `BackTest` | `quant/engine/backtest.py`、`quant/report/` | 抽出引擎和报告 |
| `OuterStrategies` | `quant/strategy/` | 通过注册表管理 |
| `Prepare` | `quant/data/source/`、`quant/data/storage/` | 数据下载与清洗分离 |
| `Config` | `configs/` | 逐步统一命名与模式隔离 |
| `reports` | `reports/` | 增加任务 ID、配置快照 |

## 回测要求

回测应至少考虑：

- 手续费、印花税、滑点
- 涨跌停、停牌、T+1、最小交易单位
- 资金不足、仓位上限、成交价格假设
- 配置快照、数据快照、策略版本、净值、持仓、资金、委托、成交、风控拒单、指标报告

优先支持两类回测：

- 向量化回测：用于因子验证、参数扫描、快速研究。
- 事件驱动回测：用于接近实盘的订单、成交、持仓、资金验证。

## 策略研发流水线要求

A 股策略研发必须按阶段准入，不应只看单次回测收益。

标准流程：

```text
策略想法 → A 股规则确认 → 数据准备与标的池构建 → 因子/信号研究
→ 组合构建与调仓规则 → 样本内验证 → 样本外/滚动验证
→ 向量化回测 → 事件驱动回测 → 压力测试
→ 实盘模拟 → 小资金实盘灰度 → 稳定运行与复盘
```

各阶段要求：

- 策略想法：明确收益来源、适用品种、交易周期、失效条件和容量预估。
- 数据准备：维护 `universe_id`、每日标的池快照、剔除原因，防止未来函数。
- 因子研究：检查 IC、Rank IC、分层收益、因子衰减、覆盖率、行业/市值中性后表现。
- 组合构建：信号先转 `TargetPosition`，再由执行层转 `ExecutionIntent`。
- 样本外验证：检查参数稳定性、市场阶段稳定性、成本敏感性和收益集中度。
- 向量化回测：输出绩效、换手、交易成本、行业贡献、风格暴露和参数扫描。
- 事件驱动回测：覆盖订单、成交、撤单、拒单、部分成交、资金不足、可卖不足、涨跌停和停牌。
- 压力测试：上调滑点和费用，限制成交量，模拟连续涨跌停、停牌、网关断线和参数扰动。
- 实盘模拟：验证行情、策略触发、风控、OMS、资金持仓更新、日志、报告和告警。
- 小资金实盘：单策略、单账户、低仓位优先，每日盘前检查、盘中监控、盘后对账。

策略状态建议：

```text
research → backtest → event_backtest → paper → live_shadow → live_small → live_full → disabled
```

策略进入实盘前至少满足：完整回测报告、样本外验证、参数和数据快照、事件驱动回测通过、压力测试通过、模拟盘观察通过、明确风控边界、异常处理方案和停机条件。

## 实盘模拟要求

实盘模拟用于验证从行情到策略、风控、订单、成交、持仓、资金、日志、报告的完整链路。可支持：

- 历史回放模拟
- 实时本地模拟
- 券商模拟盘

## 实盘要求

实盘必须包含：

- `LiveEngine`
- `MiniQmtMarketGateway`
- `MiniQmtBrokerGateway`
- `OMS`
- `RiskEngine`
- `PortfolioSync`
- `AuditLogger`
- `Monitor`

实盘启动前必须确认账户、资金、持仓、交易日、时间窗口、配置和风控状态。异常重启后必须先同步券商真实状态。

## 账户额度查询特殊约定

如果用户问账户额度、资金、余额、可用金额、持仓市值、总资产、交易账户连接状态，应优先使用 `miniqmt-account` skill，并复用：

```bash
python scripts/check_account_quota.py
```

不要创建临时账户查询脚本。
