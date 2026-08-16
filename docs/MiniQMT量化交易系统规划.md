# 主流量化交易系统架构设计

> 本文档用于替代当前零散架构思路，给出一套更接近主流量化平台的目标架构。系统覆盖 **离线数据研究、历史回测、实盘模拟、实盘交易、风控、监控、复盘**。MiniQMT / XtQuant 只作为 A 股行情与交易网关之一，不应侵入策略、回测和研究层。

---

## 1. 建设目标

- 建立可长期演进的量化交易平台，而不是脚本集合。
- 策略逻辑与数据源、撮合方式、交易通道解耦。
- 同一策略尽量复用于离线研究、历史回测、实盘模拟、实盘交易。
- 所有信号、订单、成交、持仓、资金、风控结果可追踪、可复盘。
- 本地优先，后续可扩展到数据库、服务化、Web 控制台和多账户。

非目标：不一开始做大型分布式平台；不把 GUI 作为核心逻辑入口；不把 MiniQMT 专有 API 写进策略内部；不在实盘链路依赖临时脚本。

---

## 2. 总体分层架构

```text
┌──────────────────────────────────────────────────────────────┐
│ 应用入口层 Application：CLI / GUI / Notebook / Scheduler       │
├──────────────────────────────────────────────────────────────┤
│ 业务编排层 Orchestration：研究 / 回测 / 模拟 / 实盘 / 复盘任务   │
├──────────────────────────────────────────────────────────────┤
│ 策略层 Strategy：Signal / Alpha / Portfolio / RiskRule         │
├──────────────────────────────────────────────────────────────┤
│ 引擎层 Engine：Research / Backtest / Paper / Live              │
├──────────────────────────────────────────────────────────────┤
│ 交易核心层 Trading Core：Account / Position / Order / OMS / Risk│
├──────────────────────────────────────────────────────────────┤
│ 网关层 Gateway：MarketDataGateway / BrokerGateway / Storage    │
├──────────────────────────────────────────────────────────────┤
│ 数据层 Data：Raw / Clean / Feature Store / Calendar / Metadata │
├──────────────────────────────────────────────────────────────┤
│ 基础设施层 Infra：Config / Logging / Audit / Monitor / Alert    │
└──────────────────────────────────────────────────────────────┘
```

### 分层原则

| 层级 | 职责 | 约束 |
|------|------|------|
| 应用入口层 | CLI、GUI、定时任务、Notebook | 不写核心交易逻辑 |
| 业务编排层 | 组合数据、策略、引擎、配置 | 负责流程，不负责算法 |
| 策略层 | 生成信号、目标仓位、交易意图 | 不直接调用 MiniQMT 下单 |
| 引擎层 | 时间推进、事件处理、撮合语义 | 回测、模拟、实盘共享领域模型 |
| 交易核心层 | 订单、成交、持仓、资金、风控、OMS | 必须可测试、可复盘 |
| 网关层 | 适配行情、交易、存储外部系统 | 外部 API 只出现在此层 |
| 数据层 | 数据采集、清洗、特征、元数据 | 统一口径，避免未来函数 |
| 基础设施层 | 配置、日志、监控、告警、审计 | 实盘必需 |

---

## 3. 推荐目录结构

```text
F3_0425/
├── apps/                         # CLI / GUI / Scheduler 入口
├── quant/
│   ├── data/                     # 数据源、清洗、存储、交易日历、特征库
│   ├── strategy/                 # alpha、signal、portfolio、策略注册
│   ├── engine/                   # research、backtest、paper、live 引擎
│   ├── trading/                  # account、position、order、trade、oms、risk
│   ├── gateway/                  # local_data、miniqmt_market、miniqmt_broker
│   ├── report/                   # 回测、模拟、实盘报告
│   └── infra/                    # 配置、日志、审计、监控、告警
├── configs/                      # data / risk / backtest / paper / live 配置
├── data/                         # raw / clean / feature / backtest 本地数据
├── reports/                      # 任务输出、报告、快照
├── docs/                         # 设计文档
└── tests/                        # 单元测试、集成测试、回放测试
```

当前项目可逐步迁移，不需要一次性重构。新功能优先进入目标结构，旧模块通过适配层接入。

---

## 4. 核心领域模型

系统应围绕稳定领域模型设计，而不是围绕某个券商 API 设计。

### 行情模型

| 模型 | 字段示例 | 说明 |
|------|----------|------|
| `Instrument` | symbol, exchange, name, type, lot_size | 标的基础信息 |
| `Bar` | symbol, datetime, open, high, low, close, volume, amount | K 线 |
| `Tick` | symbol, datetime, last_price, bid, ask, volume | Tick 行情 |
| `CorporateAction` | symbol, ex_date, dividend, split | 复权与公司行为 |
| `TradingCalendar` | date, is_open, session | 交易日历 |

### 交易模型

| 模型 | 字段示例 | 说明 |
|------|----------|------|
| `Account` | cash, frozen_cash, market_value, total_asset | 账户资产 |
| `Position` | symbol, volume, available, cost, pnl | 持仓 |
| `Order` | order_id, symbol, side, price, volume, status | 委托 |
| `Trade` | trade_id, order_id, price, volume, commission | 成交 |
| `TargetPosition` | symbol, target_weight / target_volume | 目标仓位 |
| `ExecutionIntent` | symbol, side, volume, price, reason | 下单意图 |

策略建议分三层输出：`Signal` → `PortfolioTarget` → `ExecutionIntent`。这样离线研究和回测主要复用前两层，模拟和实盘复用完整交易链路。

### A 股专项建模优化

本系统主要针对 A 股，应在领域模型、数据层、回测和实盘风控中显式处理以下规则，不要把它们散落在策略脚本里：

| 主题 | A 股约束 | 架构处理建议 |
|------|----------|--------------|
| 证券代码 | 沪深京市场代码、ETF、可转债、指数代码格式不同 | `Instrument` 增加 `exchange`、`asset_type`、`board`、`lot_size` |
| 交易日历 | 法定节假日、临时休市、半日市较少但需兼容 | 独立 `TradingCalendar`，所有引擎统一使用 |
| 交易时段 | 9:30-11:30、13:00-15:00，集合竞价与连续竞价规则不同 | `Session` 模型区分开盘集合竞价、连续竞价、收盘集合竞价 |
| 最小交易单位 | 股票买入通常 100 股一手，卖出可有零股限制 | 下单前由 `ExecutionEngine` 或 `RiskEngine` 调整 |
| T+1 | 股票当日买入通常不可当日卖出 | `Position.available` 与 `Position.volume` 分离 |
| 涨跌停 | 主板、科创板、创业板、ST 等涨跌幅限制不同 | 数据层提供涨跌停价，撮合和风控共同使用 |
| 停复牌 | 停牌不可成交，复牌首日规则可能不同 | 数据层维护停牌状态，回测与实盘统一校验 |
| ST/退市整理 | 风险标的通常默认禁止买入 | 标的池和风控规则双重过滤 |
| 新股与次新股 | 流动性、涨跌幅和风险特征特殊 | 标的池支持上市天数过滤 |
| 手续费税费 | 佣金、印花税、过户费、最低佣金 | `CostModel` 按市场和交易方向配置 |
| 数据复权 | 前复权、后复权、不复权影响信号和成交价 | 研究用复权价，撮合和实盘对齐真实价格 |
| 行业与风格暴露 | A 股行业轮动明显，个股集中风险高 | 组合层和风控层增加行业、主题、风格暴露限制 |

关键优化点：

- 回测成交价、涨跌停价、复权价必须区分，避免用复权价模拟真实成交。
- `available` 可卖数量必须独立建模，不能简单等于持仓数量。
- 标的池构建要前置，策略不应在每次信号计算时临时过滤大量交易规则。
- MiniQMT 实盘返回的账户、持仓、委托状态应转换为统一模型后再进入 OMS。
- A 股策略优先支持日频和分钟频，Tick 级能力可作为后续增强。

---

## 5. 离线数据与研究

### 数据分层

```text
Raw Data       原始数据，尽量不改动
   ↓
Clean Data     清洗后数据，处理字段、时区、缺失、停牌、复权
   ↓
Feature Store  因子、特征、标签、训练样本
   ↓
Dataset        回测或模型训练专用数据集快照
```

### 本地存储建议

| 阶段 | 推荐存储 | 说明 |
|------|----------|------|
| 初期 | Parquet + SQLite | 简单、快、可维护 |
| 中期 | DuckDB + Parquet | 适合本地分析和批量查询 |
| 后期 | PostgreSQL / ClickHouse | 多任务、多用户、大数据量 |

### 数据质量规则

- 记录数据源、更新时间、复权方式、字段说明。
- 回测数据集生成快照，确保结果可复现。
- 因子计算必须防止未来函数。
- 财务数据、成分股数据使用 `as_of_date` 语义。
- 标的池过滤规则显式记录，例如 ST、停牌、新股、涨跌停、流动性。

---

## 6. 离线回测架构

回测不只是计算收益，还要验证真实交易约束：手续费、印花税、滑点、涨跌停、停牌、T+1、最小交易单位、资金不足、仓位上限、成交价格假设。

### 两类回测引擎

| 类型 | 适合场景 | 特点 |
|------|----------|------|
| 向量化回测 | 因子验证、大批量参数扫描、横截面选股 | 速度快，但订单状态和部分成交模拟较弱 |
| 事件驱动回测 | 更接近实盘、验证订单/成交/持仓/资金 | 较慢，但可复用到模拟盘和实盘 |

事件驱动典型事件流：

```text
MarketEvent → StrategyEvent → SignalEvent → RiskEvent → OrderEvent → FillEvent → PortfolioUpdate
```

### 回测组件

| 组件 | 职责 |
|------|------|
| `DataReplay` | 按时间推进历史行情 |
| `StrategyRunner` | 调用策略生成信号或目标仓位 |
| `PortfolioSimulator` | 维护现金、持仓、净值 |
| `MatchingEngine` | 根据成交模型撮合订单 |
| `CostModel` | 计算手续费、税费、滑点 |
| `RiskEngine` | 执行与实盘一致的风控规则 |
| `PerformanceAnalyzer` | 计算指标并生成报告 |

每次回测至少输出配置快照、数据快照、策略版本、净值曲线、每日持仓、资金、委托、成交、交易成本、风控拒单、指标报告。

---

## 7. 实盘模拟架构

实盘模拟用于填补历史回测与真实实盘之间的差距。

| 类型 | 数据 | 成交 | 用途 |
|------|------|------|------|
| 历史回放模拟 | 历史行情 | 本地撮合 | 压力测试、链路测试 |
| 实时本地模拟 | 实时行情 | 本地撮合 | 观察策略当日行为 |
| 券商模拟盘 | 券商模拟柜台 | 柜台成交 | 最接近实盘接口 |

实时本地模拟流程：

```text
启动任务 → 加载配置和模拟账户 → 订阅行情 → 策略生成目标仓位
→ 风控检查 → 本地撮合 → 更新模拟持仓和资金 → 写日志和报告
```

模拟盘必须验证：策略稳定性、行情缺失降级、风控拒单、订单状态机、配置日志报告告警、交易频率是否合理。

---

## 8. 实盘交易架构

实盘链路：

```text
行情接入 → 策略计算 → 目标仓位 → 组合差异计算 → 交易前风控
→ 订单生成 → OMS 状态管理 → BrokerGateway 下单
→ 委托/成交/撤单回报 → 持仓资金同步 → 审计监控复盘
```

### 实盘关键模块

| 模块 | 职责 |
|------|------|
| `LiveEngine` | 实盘主循环、事件分发、生命周期管理 |
| `MiniQmtMarketGateway` | 对接 `xtdata` 行情 |
| `MiniQmtBrokerGateway` | 对接 `XtQuantTrader` 交易 |
| `OMS` | 订单状态、幂等、撤单、重试 |
| `RiskEngine` | 交易前、交易中、交易后风控 |
| `PortfolioSync` | 同步券商真实持仓和资金 |
| `AuditLogger` | 记录决策、订单、回报、异常 |
| `Monitor` | 心跳、延迟、资金、持仓、订单异常监控 |

### 实盘安全原则

- 所有实盘订单必须经过风控和 OMS。
- 所有下单必须有唯一 `client_order_id`，避免重复下单。
- 启动前必须确认账户、资金、持仓、交易日、时间窗口。
- 异常重启后先同步券商真实订单、成交、持仓、资金。
- 断线时停止新增订单，恢复后重新同步状态。
- 实盘配置与回测配置分离，防止误用。
- GUI 操作需二次确认，尤其是启动实盘、全撤、清仓。

---

## 9. 风控架构

| 阶段 | 检查内容 |
|------|----------|
| 交易前 | 白名单、黑名单、仓位上限、资金充足、涨跌停、停牌、交易时间 |
| 交易中 | 订单频率、撤单频率、成交偏离、滑点异常、连接状态 |
| 交易后 | 持仓集中度、行业暴露、回撤、当日亏损、账户资产偏离 |

常用规则：单票最大仓位、总仓位上限、单笔最大金额、单日最大成交金额、单日最大亏损、最大回撤停机、禁止买入 ST/退市整理/停牌/新股、订单价格偏离拒单、非交易时段拒单。

风控输出统一为：`PASS`、`REJECT`、`ADJUST`，并记录规则名称、输入订单、账户状态、原因、处理时间。

---

## 10. 策略研发流水线

A 股策略研发不能只看单次回测收益，应建立从想法、数据、研究、回测、模拟到实盘的分阶段准入流程。每一阶段都要有明确输入、输出、通过标准和可追溯记录。

### 10.1 总体流程

```text
策略想法
  ↓
A 股市场假设与交易规则确认
  ↓
数据准备与标的池构建
  ↓
因子 / 信号研究
  ↓
组合构建与调仓规则
  ↓
样本内验证
  ↓
样本外验证 / 滚动验证
  ↓
向量化回测
  ↓
事件驱动回测
  ↓
压力测试与参数稳定性测试
  ↓
实盘模拟 / Paper Trading
  ↓
小资金实盘灰度
  ↓
稳定运行、监控、复盘、迭代
```

### 10.2 阶段 1：策略想法与假设定义

目标是把模糊想法变成可验证的交易假设。

| 项目 | 内容 |
|------|------|
| 输入 | 市场观察、因子假设、交易经验、研究论文、历史异常现象 |
| 输出 | 策略说明、预期收益来源、适用品种、适用周期、失效条件 |
| 关键问题 | 收益来自风险溢价、行为偏差、流动性补偿、事件驱动还是统计规律 |

A 股策略假设需要额外说明：

- 是选股、择时、轮动、套利、网格、打板、低吸还是事件策略。
- 适用主板、创业板、科创板、北交所、ETF、可转债中的哪些品种。
- 是否受 T+1、涨跌停、停牌、集合竞价影响。
- 是否依赖融资融券、融券券源、打新、中签、可转债权限等账户能力。
- 预期容量是多少，是否容易被成交冲击和流动性吞噬。

### 10.3 阶段 2：数据准备与标的池构建

A 股策略质量高度依赖标的池和数据口径。标的池应独立于策略信号维护，避免策略脚本里临时过滤。

| 数据/规则 | 必要处理 |
|-----------|----------|
| 行情数据 | 日线、分钟线、成交额、成交量、换手率、复权价、真实成交价 |
| 基础信息 | 上市日期、退市日期、市场、板块、行业、证券类型 |
| 交易状态 | 停牌、涨跌停、ST、退市整理、风险警示 |
| 财务数据 | 使用公告日或可得日期，防止未来函数 |
| 指数成分 | 使用调入调出日期，不能用未来成分股 |
| 行业分类 | 记录分类版本，避免行业口径漂移 |

常用 A 股标的池过滤：

- 剔除 ST、`*ST`、退市整理、长期停牌。
- 剔除上市未满指定天数的新股或次新股。
- 剔除成交额过低、换手过低、流动性不足标的。
- 剔除当日不可交易或无法合理成交的标的。
- 根据策略限定指数成分、行业、ETF、可转债或自定义股票池。

输出应包括：`universe_id`、标的池生成配置、每日标的池快照、被剔除标的及原因。

### 10.4 阶段 3：因子 / 信号研究

研究阶段主要验证信号是否有稳定解释力，而不是直接追求最优参数。

常见研究任务：

- IC、Rank IC、ICIR。
- 分层收益、Top/Bottom 组合收益。
- 多空组合收益，但 A 股真实做空受限，需要单独标注。
- 因子衰减周期。
- 因子覆盖率和缺失率。
- 行业中性、市值中性后的表现。
- 与已有因子的相关性和冗余度。
- 极端行情、牛熊震荡行情分段表现。

A 股注意事项：财务因子必须按公告可得时间计算；小市值和低流动性因子要额外评估容量；多空回测不能直接等同真实收益；分钟信号要考虑午休、集合竞价、涨跌停封单和撤单限制。

### 10.5 阶段 4：组合构建与调仓规则

信号不能直接下单，应先转换为目标组合。

| 设计项 | 示例 |
|--------|------|
| 选股数量 | Top 10、Top 50、Top 100 |
| 权重方式 | 等权、市值权重、风险平价、因子得分权重 |
| 调仓周期 | 日频、周频、月频、分钟级触发 |
| 换手控制 | 最大换手率、最小调仓阈值、缓冲区 |
| 仓位控制 | 总仓位、单票上限、行业上限、现金保留 |
| 交易约束 | 100 股一手、T+1、涨跌停、停牌、可卖数量 |

组合层应输出 `TargetPosition`，由执行层根据当前持仓和交易规则转换成 `ExecutionIntent`。

### 10.6 阶段 5：样本内、样本外与滚动验证

建议至少拆分为：

```text
样本内训练 / 参数选择 → 样本外验证 → 滚动窗口验证 → 最近行情回放验证
```

评估重点：参数是否过拟合；不同市场阶段是否稳定；收益是否集中在少数月份或少数股票；换手率、交易成本、冲击成本是否可承受；回撤和亏损是否符合资金规模和心理承受能力。

通过标准建议：样本外表现不能明显劣化；参数邻域内结果相对稳定；成交成本上调后仍不过度失效；不依赖单一行业、单一风格或极少数异常交易日。

### 10.7 阶段 6：向量化回测

向量化回测用于快速验证组合收益和参数空间。必须输出年化收益、最大回撤、夏普、卡玛、波动率、分年度收益、换手率、交易次数、平均持仓周期、单票贡献、行业贡献、风格暴露、交易成本敏感性和参数扫描结果。

A 股向量化回测不得忽略：涨跌停不可成交、停牌不可成交、T+1 可卖限制、100 股交易单位、印花税、佣金、过户费、最低佣金，以及复权价用于信号但真实价格用于成交模拟。

### 10.8 阶段 7：事件驱动回测

事件驱动回测用于验证接近实盘的订单、成交、持仓和资金状态。必须覆盖 `MarketEvent`、`SignalEvent`、`OrderEvent`、`FillEvent`、`RiskEvent`，并验证部分成交、未成交、撤单、拒单、资金不足、持仓不足、可卖不足、涨跌停、停牌、价格偏离、订单状态机和 OMS 幂等逻辑。

通过事件驱动回测后，策略才允许进入实盘模拟。

### 10.9 阶段 8：压力测试与鲁棒性测试

建议测试：手续费和滑点上调；成交量按比例限制；大幅低开、高开、连续跌停、连续涨停；停牌、复牌、退市、ST 风险；行情缺失、数据延迟、交易网关断线；参数扰动、标的池扰动、行业暴露扰动；资金规模扩大后的容量变化。

### 10.10 阶段 9：实盘模拟 / Paper Trading

实盘模拟验证完整链路，而不是再次验证收益曲线。必须验证实时行情接入、策略触发时间、目标仓位、订单意图、风控拒单、OMS 状态机、模拟持仓、资金、净值、日志、报告、告警，以及盘后复盘是否能还原当日所有决策。

模拟盘通过标准：连续运行一段观察期无严重异常；每日订单、成交、持仓、资金可对账；策略行为与回测预期一致；异常场景有明确告警和处理方式。

### 10.11 阶段 10：小资金实盘灰度

小资金实盘的目标是验证真实交易摩擦、接口稳定性和风控有效性。

灰度原则：从极小仓位开始；单策略、单账户、低频优先；每日盘前检查账户、资金、持仓、行情、交易日、配置；盘中监控订单、成交、撤单、拒单、连接状态；盘后执行成交、持仓、资金、净值、日志复盘；达到稳定标准后再逐步增加资金或策略数量。

小资金实盘期间禁止：临时改策略后不回测直接上线；绕过风控手工补单进入系统账；多个入口同时对同一账户下单而不经过 OMS；未完成对账就启动下一交易日实盘。

### 10.12 阶段 11：稳定运行与迭代

每日流程：

```text
盘前检查 → 盘中监控 → 盘后对账 → 绩效归因 → 异常复盘 → 参数/策略评审
```

必须保留策略版本、配置快照、数据快照、订单和成交流水、风控记录、账户和持仓快照、异常和人工干预记录。任何影响交易行为的改动都应视为新版本，并重新经过必要的回测、模拟和审批流程。

### 10.13 策略注册与准入状态

策略注册信息建议包含：

| 字段 | 说明 |
|------|------|
| `strategy_id` | 全局唯一策略编号 |
| `name` | 策略名称 |
| `owner` | 负责人 |
| `asset_scope` | 股票、ETF、可转债等 |
| `frequency` | 日频、分钟频、Tick |
| `universe_id` | 标的池编号 |
| `parameters` | 参数配置 |
| `risk_profile` | 风险等级 |
| `capacity_estimate` | 预估资金容量 |
| `cost_model_id` | 成本模型编号 |
| `data_snapshot_id` | 数据快照编号 |
| `status` | research / backtest / paper / live / disabled |

策略状态流转：

```text
research → backtest → event_backtest → paper → live_shadow → live_small → live_full → disabled
```

进入实盘前至少满足：完整回测报告、样本外验证、参数和数据快照、事件驱动回测通过、压力测试通过、模拟盘观察通过、明确风控边界、异常处理方案、停机条件。

---

## 11. 配置、日志、监控

配置建议：

```text
configs/
├── env.local.yaml
├── data.yaml
├── account.yaml
├── risk.yaml
├── backtest/
├── paper/
└── live/
```

原则：回测、模拟、实盘配置分开；敏感信息不提交；每次运行保存配置快照；实盘配置必须显式声明 `mode: live`。

日志至少包括：系统、行情、策略、风控、订单、成交、账户。监控至少包括：行情更新时间、交易网关连接、账户同步时间、未完成订单、拒单数量、当日成交金额、当日盈亏、策略心跳、异常次数。

---

## 12. MiniQMT 在架构中的位置

MiniQMT 只放在网关层，不进入策略层和回测核心层。

- `xtdata` 行情、本地 `datadir` 读取、历史数据下载归入 `MarketDataGateway`。
- `XtQuantTrader` 只在 `MiniQmtBrokerGateway` 内部使用。
- 下单、撤单、查询资金、查询持仓都通过统一 `BrokerGateway` 接口。
- 账户额度与交易连接检查继续复用 `qmt_account.py` 和 `scripts/check_account_quota.py`，不要创建临时查询脚本。

建议接口：

```python
class MarketDataGateway:
    def get_bars(self, symbols, start, end, frequency): ...
    def subscribe(self, symbols, frequency, callback): ...
    def get_latest(self, symbols): ...

class BrokerGateway:
    def connect(self): ...
    def query_account(self): ...
    def query_positions(self): ...
    def send_order(self, order): ...
    def cancel_order(self, order_id): ...
    def sync(self): ...
```

---

## 13. 当前项目迁移建议

| 当前模块 | 目标位置 | 迁移方式 |
|----------|----------|----------|
| `qmt_service.py` | `quant/gateway/miniqmt_market.py` | 包成行情网关 |
| `qmt_account.py` | `quant/gateway/miniqmt_broker.py` 或账户工具 | 账户查询继续复用，交易进入 BrokerGateway |
| `BackTest` | `quant/engine/backtest.py`、`quant/report/` | 抽出引擎和报告 |
| `OuterStrategies` | `quant/strategy/` | 通过注册表管理 |
| `Prepare` | `quant/data/source/`、`quant/data/storage/` | 数据下载与清洗分离 |
| `Config` | `configs/` | 逐步统一命名与模式隔离 |
| `reports` | `reports/` | 增加任务 ID、配置快照 |

迁移原则：新代码使用目标架构；旧代码只做适配；先统一数据和领域模型，再动实盘交易链路；实盘相关改动必须小步、可回滚、可验证。

---

## 14. MVP 路线图

```text
本地日线数据 → 策略注册 → 向量化回测 → 事件驱动回测
→ 模拟盘 → MiniQMT 小资金实盘 → 日报与复盘
```

阶段建议：

1. 建立 `quant/trading` 领域模型。
2. 建立 `quant/gateway` 抽象接口。
3. 标准化本地日线数据。
4. 建立策略注册表。
5. 实现向量化回测 MVP。
6. 实现事件驱动回测 MVP。
7. 实现 PaperBroker。
8. 实现 MiniQMT BrokerGateway。
9. 接入风控、日志、报告、监控。
10. 将现有 GUI 和报表接到新架构上。

---

## 15. 关键设计约束

1. 策略不得直接调用 MiniQMT 下单。
2. 回测不得依赖实盘账户连接。
3. 实盘不得绕过风控和 OMS。
4. 订单、成交、资金、持仓必须持久化。
5. 每次运行必须有任务 ID、配置快照和日志。
6. 实盘启动必须执行账户、行情、时间、配置、风控检查。
7. 任何实盘异常必须可追踪到原始日志。
8. 所有新功能优先按目标架构放置。

---

## 16. 模块化落代码规格：目录、输入、输出、接口一一对应

本节用于指导后续直接落盘代码。任何新模块在创建前，都应先确认它属于哪个层级、接收什么输入、输出什么结果、依赖哪些接口、禁止依赖哪些对象。

### 16.1 落代码总原则

1. 先定义领域模型和接口，再实现具体 MiniQMT 或本地数据适配。
2. 每个模块必须有明确输入和输出，避免隐式读取全局变量。
3. 策略只输出信号、目标仓位或交易意图，不直接查询账户、不直接下单。
4. 回测、模拟、实盘尽量共享 quant/trading 领域模型。
5. MiniQMT API 只能出现在 quant/gateway/miniqmt_market.py 和 quant/gateway/miniqmt_broker.py 等网关实现中。
6. 所有任务入口必须生成 run_id，并保存配置快照、日志、报告。
7. A 股交易规则优先放入数据、撮合、风控、执行模块，不要分散在策略里。

### 16.2 模块与代码目录对应表

| 架构模块 | 目标代码位置 | 主要输入 | 主要输出 | 说明 |
|----------|--------------|----------|----------|------|
| 应用入口 | apps/cli/, apps/gui/, apps/scheduler/ | 用户参数、配置文件、任务类型 | 任务执行结果、日志、报告路径 | 只负责启动任务，不写核心逻辑 |
| 任务编排 | quant/infra/task.py, quant/engine/* | RunConfig、策略 ID、数据范围 | RunResult、报告、快照 | 连接数据、策略、引擎、网关 |
| 配置管理 | quant/infra/config.py, configs/ | YAML/JSON、环境变量 | DataConfig、BacktestConfig、LiveConfig | 回测、模拟、实盘配置必须分离 |
| 日志审计 | quant/infra/logging.py, quant/infra/audit.py | 事件、订单、风控结果、异常 | 日志文件、审计流水 | 实盘必须启用 |
| 行情领域模型 | quant/data/models.py, quant/trading/models.py | 原始行情、证券信息 | Instrument、Bar、Tick | 不依赖任何外部 API |
| 数据源适配 | quant/data/source/ | MiniQMT datadir、CSV、第三方数据 | 原始数据表或 DataFrame | 只负责读取，不做策略判断 |
| 数据清洗存储 | quant/data/storage/, quant/data/adjust/ | Raw Data、清洗配置 | Clean Data、复权数据、快照 ID | 提供可复现数据集 |
| 交易日历 | quant/data/calendar/ | 交易所日历、配置 | 交易日、交易时段、session | 所有引擎统一使用 |
| 标的池 | quant/data/universe.py | 基础信息、交易状态、过滤规则 | UniverseSnapshot | 保存每日成分和剔除原因 |
| 特征库 | quant/data/feature_store/ | Clean Data、因子定义 | 因子表、标签表、特征快照 | 防止未来函数 |
| 策略注册 | quant/strategy/registry.py | 策略类、元数据 | 策略实例、策略清单 | 管理策略生命周期 |
| 因子/信号 | quant/strategy/alpha/, quant/strategy/signal/ | 行情、特征、上下文 | SignalFrame | 不直接下单 |
| 组合构建 | quant/strategy/portfolio/ | 信号、约束、当前持仓 | TargetPosition | 控制权重、换手、行业暴露 |
| 执行意图生成 | quant/trading/execution.py | 目标仓位、当前持仓、价格、规则 | ExecutionIntent | 处理最小交易单位、可卖数量 |
| 风控 | quant/trading/risk.py | 订单意图、账户、持仓、行情、规则 | RiskDecision | 输出 PASS/REJECT/ADJUST |
| OMS | quant/trading/oms.py | 风控通过的订单、成交回报、撤单请求 | Order 状态、Trade、事件 | 实盘和事件回测共用状态机 |
| 撮合引擎 | quant/engine/matching.py | 订单、历史行情、成交模型 | FillEvent、Trade | 回测和本地模拟使用 |
| 回测引擎 | quant/engine/backtest.py | BacktestConfig、数据集、策略 | BacktestResult | 支持向量和事件驱动扩展 |
| 研究引擎 | quant/engine/research.py | 特征、因子、标的池、评估配置 | 因子评估报告 | 不需要交易账户 |
| 模拟盘引擎 | quant/engine/paper.py | 实时/回放行情、策略、模拟账户 | PaperResult、模拟订单成交 | 验证完整链路 |
| 实盘引擎 | quant/engine/live.py | 实盘配置、策略、行情网关、交易网关 | LiveResult、实盘流水 | 必须经过风控和 OMS |
| 行情网关接口 | quant/gateway/market_data.py | 查询请求、订阅请求 | Bar、Tick、最新价 | 抽象接口 |
| 本地数据网关 | quant/gateway/local_data.py | 数据路径、查询条件 | 标准行情模型 | 回测优先使用 |
| MiniQMT 行情网关 | quant/gateway/miniqmt_market.py | MiniQMT 配置、订阅参数 | 标准行情模型 | 封装 xtdata |
| 交易网关接口 | quant/gateway/broker.py | 订单、撤单、查询请求 | 账户、持仓、委托、成交 | 抽象接口 |
| MiniQMT 交易网关 | quant/gateway/miniqmt_broker.py | 账户配置、订单请求 | 标准交易模型 | 封装 XtQuantTrader |
| 报告 | quant/report/ | 回测/模拟/实盘结果 | Excel、HTML、JSON、图表 | 统一输出 |

### 16.3 核心数据对象输入输出

| 对象 | 来源 | 消费方 | 必备字段 |
|------|------|--------|----------|
| RunConfig | 应用入口、配置文件 | 所有 Engine | run_id、mode、strategy_id、start、end、account_id |
| Instrument | 数据源、证券信息表 | 数据层、风控、撮合 | symbol、exchange、asset_type、board、lot_size |
| Bar | 行情网关、本地数据 | 策略、回测、撮合 | symbol、datetime、open、high、low、close、volume、amount |
| SignalFrame | 策略信号模块 | 组合构建 | datetime、symbol、score、signal、reason |
| TargetPosition | 组合构建 | 执行意图生成 | symbol、target_weight 或 target_volume、reason |
| ExecutionIntent | 执行模块 | 风控、OMS | symbol、side、volume、price_type、limit_price、reason |
| RiskDecision | 风控模块 | OMS、报告、审计 | decision、rule_name、reason、adjusted_intent |
| Order | OMS、交易网关 | OMS、报告、审计 | order_id、client_order_id、symbol、side、price、volume、status |
| Trade | 撮合引擎、交易网关 | 持仓、账户、报告 | trade_id、order_id、symbol、price、volume、commission |
| Position | 持仓模块、交易网关 | 策略、风控、执行 | symbol、volume、available、cost、market_value |
| Account | 账户模块、交易网关 | 风控、执行、报告 | cash、frozen_cash、market_value、total_asset |
| RunResult | Engine | 应用入口、报告 | run_id、status、metrics、report_paths、error |

### 16.4 推荐接口草案

后续落代码时，接口名可以微调，但输入输出语义应保持稳定。

~~~python
class MarketDataGateway:
    def get_bars(self, symbols, start, end, frequency): ...
    def get_latest(self, symbols): ...
    def subscribe(self, symbols, frequency, callback): ...
    def unsubscribe(self, symbols): ...

class BrokerGateway:
    def connect(self): ...
    def disconnect(self): ...
    def query_account(self): ...
    def query_positions(self): ...
    def query_orders(self): ...
    def query_trades(self): ...
    def send_order(self, order_request): ...
    def cancel_order(self, order_id): ...
    def sync(self): ...

class Strategy:
    def on_init(self, context): ...
    def generate_signals(self, data, context): ...
    def build_targets(self, signals, context): ...

class RiskRule:
    def check(self, intent, account, positions, market_snapshot, context): ...

class Engine:
    def run(self, config): ...
~~~

### 16.5 运行模式输入输出

| 模式 | 输入 | 处理流程 | 输出 |
|------|------|----------|------|
| 研究 | 因子配置、标的池、历史数据 | 加载数据 → 计算因子 → 评估 IC/分层/覆盖率 | 因子报告、特征快照 |
| 向量化回测 | 回测配置、数据集、策略 | 信号 → 目标仓位 → 成本扣减 → 净值计算 | 回测指标、净值、持仓、交易摘要 |
| 事件驱动回测 | 回放数据、策略、撮合模型、风控 | 行情事件 → 信号 → 风控 → 订单 → 撮合 → 持仓资金更新 | 委托、成交、资金、持仓、风控、报告 |
| 历史回放模拟 | 历史数据、模拟账户、实盘式链路 | 使用 PaperEngine 跑完整事件流 | 模拟订单、成交、净值、链路报告 |
| 实时模拟 | 实时行情、模拟账户、策略 | 实时行情 → 策略 → 风控 → 本地撮合 | 当日模拟流水、盘后报告 |
| 实盘 | 实盘配置、MiniQMT 行情网关、MiniQMT 交易网关 | 行情 → 策略 → 风控 → OMS → 下单 → 回报同步 | 实盘订单、成交、持仓、资金、审计日志 |

### 16.6 A 股交易规则落点

| 规则 | 主要落点 | 说明 |
|------|----------|------|
| 交易日、交易时段、午休 | quant/data/calendar/、quant/engine/* | 引擎统一判断是否可运行 |
| 集合竞价、连续竞价 | quant/data/calendar/、quant/engine/matching.py | 撮合模型区分 session |
| T+1 可卖 | quant/trading/position.py、quant/trading/execution.py | available 单独维护 |
| 100 股一手 | quant/trading/execution.py、quant/trading/risk.py | 生成订单前调整或拒绝 |
| 涨跌停 | quant/data/source/、quant/trading/risk.py、quant/engine/matching.py | 风控和撮合同时使用 |
| 停牌 | quant/data/universe.py、quant/trading/risk.py | 标的池过滤和下单拒绝 |
| ST/退市整理 | quant/data/universe.py、quant/trading/risk.py | 默认禁止买入 |
| 费用税费 | quant/trading/cost.py、quant/engine/matching.py | 按买卖方向计算 |
| 复权价/真实价 | quant/data/adjust/、quant/engine/backtest.py | 信号用复权，成交用真实价 |
| 行业/风格暴露 | quant/strategy/portfolio/、quant/trading/risk.py | 组合和风控双层限制 |

### 16.7 后续编码前检查清单

每次新增模块或落代码前，先回答以下问题：

1. 该模块属于哪个目录和层级？
2. 输入对象是什么？字段是否明确？
3. 输出对象是什么？是否能被下一层直接消费？
4. 是否错误地依赖了 MiniQMT、GUI 或全局配置？
5. 是否处理了 A 股必要交易规则？
6. 是否需要持久化？持久化到哪里？
7. 是否需要写入审计日志？
8. 是否能在回测、模拟、实盘之间复用？
9. 是否有对应测试或回放验证方案？
10. 是否更新了本文档或相关 skill？