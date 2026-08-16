---
name: quant-order-execution-adapter
description: Use when designing or auditing order execution adapters, order intent schemas, exchange/broker connectors, idempotent order submission, partial fills, cancel-replace flows, retry policy, and reconciliation boundaries.
language: zh-CN
---

# Quant Order Execution Adapter

## 何时使用

当任务涉及订单执行、broker/exchange 适配、下单幂等或成交回报时使用本 skill。适用场景包括：

- 把策略目标仓位转换为实际订单。
- 接入券商、期货柜台、交易所或模拟 broker。
- 设计订单 id、重试、撤改单、部分成交、拒单和对账。
- 审查实盘执行链路是否会重复下单或状态漂移。

## 输入材料

先收集：

- 交易场所和账户类型。
- 支持的订单类型、有效期、最小数量、价格步长、费率和限频。
- 策略输出格式：目标仓位、目标权重、订单意图或直接订单。
- 现有订单表、成交表、持仓表和错误日志。
- API 的下单、撤单、查询、成交回报和限频文档。

## 工作流程

1. 定义订单意图
   - 上游只提交 `intent`：symbol、side、qty/value、order_type、limit_price、time_in_force、reason。
   - adapter 负责把 intent 转换为交易场所可接受的订单。
   - intent 必须带 strategy id、portfolio id、client order id 和生成时间。

2. 做交易所/券商规范化
   - 对价格步长、数量精度、最小名义金额和交易时段做本地校验。
   - 不满足规则的订单应在本地拒绝并记录原因。
   - 不同场所状态码要映射为统一状态：new、accepted、partially_filled、filled、cancelled、rejected、expired、unknown。

3. 设计幂等和重试
   - client order id 必须可重复生成或持久化。
   - 网络超时后先查询订单状态，再决定是否重试。
   - 禁止在未知状态下盲目提交同方向同数量订单。

4. 处理撤改单和部分成交
   - cancel/replace 要保留原订单链路。
   - 部分成交后，剩余数量、平均成交价、费用和持仓要增量更新。
   - 撤单失败时要进入 reconciliation，而不是直接假设成功。

5. 建立对账边界
   - 本地订单、成交、持仓和现金必须定期与远端状态对账。
   - 发现未知订单、缺失成交、仓位不一致时进入 safe mode。
   - adapter 只做执行和状态转换，不负责策略决策。

## 判断标准

- 下单链路幂等：同一意图不会因重试产生重复风险。
- 状态可恢复：进程重启后能从本地日志和远端查询恢复订单状态。
- 错误可分类：参数错误、余额不足、限频、网络、未知状态分开处理。
- 对账可停机：状态不一致时能阻断新订单。

## 常见失败模式

- 用交易所返回 id 作为唯一 id，提交前无法幂等。
- 网络 timeout 后直接再次下单。
- 忽略部分成交，把订单状态二分为成功/失败。
- 撤单成功与否没有确认，导致本地和远端持仓漂移。
- 策略层直接依赖某个交易所的私有字段。

## 输出格式

输出应包含：

- 订单意图 schema。
- 状态机：允许状态和状态转移。
- 错误分类和重试策略。
- 对账流程：触发条件、检查字段、停机条件。
- 适配器边界：上游策略和下游 API 各自负责什么。

## Bundled Resources

- `templates/order_intent_schema.json`: 订单意图 JSON schema 风格模板。
- `scripts/order_state_machine.py`: 标准库状态机和模拟器，用于验证订单状态转移、部分成交和撤单路径。

当用户要设计 adapter 时，先用模板固定字段；当用户要验证订单生命周期时，运行：

```bash
python3 skills/quant-order-execution-adapter/scripts/order_state_machine.py
```

## Source Basis

本 skill 蒸馏自宽松许可证项目的公开工程模式，不复制源代码：

- QuantConnect/Lean: https://github.com/QuantConnect/Lean
- vnpy/vnpy: https://github.com/vnpy/vnpy
- hummingbot/hummingbot: https://github.com/hummingbot/hummingbot
