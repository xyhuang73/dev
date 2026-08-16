---
name: quant-event-driven-backtest
description: Use when designing, implementing, or auditing event-driven backtest engines with market data events, signals, orders, fills, portfolio state, broker simulation, latency, fees, slippage, and realistic execution boundaries.
language: zh-CN
---

# Quant Event-Driven Backtest

## 何时使用

当用户需要设计或审查事件驱动回测系统时使用本 skill。适用场景包括：

- 把向量化回测改成更接近实盘的事件驱动回测。
- 设计 data event、signal、order、fill、portfolio 的流转。
- 检查 same-bar 成交、手续费、滑点、延迟、部分成交是否真实。
- 将策略研究结果接入模拟 broker 或实盘接口。

## 输入材料

先收集：

- 回测频率、交易品种、订单类型和撮合规则。
- 数据事件粒度：tick、bar、quote、order book、funding、corporate action。
- 策略决策时间、下单时间、撮合时间和组合记账时间。
- 手续费、滑点、成交量限制、最小下单量、价格步长、杠杆和保证金规则。
- 现有回测代码、交易日志、持仓日志和账户曲线。

## 工作流程

1. 分层事件流
   - MarketDataEvent: 新数据到达，只承载当时可见信息。
   - SignalEvent: 策略根据历史状态生成目标方向或目标仓位。
   - OrderEvent: 风控和组合层把信号转成订单意图。
   - FillEvent: broker simulator 根据规则返回成交。
   - PortfolioEvent: 账户、现金、持仓、保证金和 PnL 更新。

2. 固定事件顺序
   - 同一 bar 内先更新可见数据，再生成信号，再排队订单。
   - 默认禁止使用当前 bar close 生成并在同一 close 成交。
   - 若必须 same-bar，必须有 tick/quote 级数据和明确成交条件。

3. 建立 broker simulator
   - 实现价格边界、订单类型、部分成交、拒单、取消和过期。
   - 用成交量参与率或订单簿深度约束可成交数量。
   - 手续费、税费、资金费率、借券费和融资成本要进入账户。

4. 组合记账
   - 区分 target position、open orders、actual position。
   - 每个成交都要更新现金、持仓成本、已实现和未实现 PnL。
   - 多币种、多账户或保证金模式下，资产负债表要显式。

5. 审计回测真实性
   - 对比向量化结果和事件驱动结果，定位收益差异来源。
   - 对关键策略做延迟、滑点、成交率和流动性压力测试。
   - 输出不能成交、部分成交、风控拒单对收益的影响。

## 判断标准

- 事件顺序清晰，策略不能读到尚未发生的成交或价格。
- 订单生命周期完整，至少覆盖提交、接受、部分成交、成交、取消、拒绝。
- 账户状态由成交驱动，而不是直接把目标仓位写成实际持仓。
- 回测能解释为什么某个订单成交或未成交。

## 常见失败模式

- 用目标仓位直接计算收益，跳过订单和成交。
- 用收盘信号按同一收盘价成交。
- 忽略部分成交、最小下单量、价格步长和交易暂停。
- 只有收益曲线，没有订单日志和持仓日志。
- 把实盘 broker 行为简化成“永远成交”。

## 输出格式

输出应包含：

- 事件流图或步骤表。
- 回测真实性评级：PASS/WARN/FAIL/BLOCKED。
- 成交假设清单：价格、数量、延迟、费用、滑点。
- 必须保存的日志字段：event time、order id、symbol、side、qty、price、status、reason。

## Bundled Resources

- `templates/event_engine_skeleton.py`: 可运行的事件驱动回测骨架，包含 market event、signal、order、fill、portfolio 的最小闭环。

当用户要新建回测引擎或从向量化迁移时，先复制该模板，再按目标市场替换 broker simulator、费用和滑点模块。

## Source Basis

本 skill 蒸馏自宽松许可证项目的公开工程模式，不复制源代码：

- QuantConnect/Lean: https://github.com/QuantConnect/Lean
- vnpy/vnpy: https://github.com/vnpy/vnpy
- jesse-ai/jesse: https://github.com/jesse-ai/jesse
