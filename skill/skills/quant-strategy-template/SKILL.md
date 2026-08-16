---
name: quant-strategy-template
description: Use when creating or refactoring quantitative strategy templates with initialization, parameters, indicators, signal generation, position sizing, exits, state isolation, multi-asset handling, and reproducible research-to-live behavior.
language: zh-CN
---

# Quant Strategy Template

## 何时使用

当用户要写、整理或审查策略模板时使用本 skill。适用场景包括：

- 将策略想法转换成可回测、可优化、可实盘迁移的结构。
- 统一不同策略的初始化、指标、信号、仓位和退出逻辑。
- 避免策略代码把研究状态、全局变量和交易状态混在一起。
- 为 agent 生成策略骨架或审查已有策略结构。

## 输入材料

先确认：

- 策略类型：趋势、均值回复、套利、截面、多因子、ML/RL 信号。
- 交易范围：资产、频率、做多/做空、杠杆、市场时段。
- 输入数据：bar、tick、订单簿、因子、模型预测、外部事件。
- 风险规则：单笔风险、组合风险、止损止盈、最大仓位、最大换手。
- 输出目标：研究脚本、框架策略类、伪代码或生产接口。

## 工作流程

1. 分离策略组成
   - Parameters: 所有可调参数集中声明，带默认值和合理范围。
   - State: 持仓状态、挂单状态、冷却状态和统计缓存显式存放。
   - Indicators: 只基于历史可见数据更新。
   - Signals: 只表达方向、强度或目标权重，不直接下单。
   - Sizing: 把信号转为仓位，处理风险预算和约束。
   - Exits: 止损、止盈、时间退出、信号反转和风控退出分开。

2. 固定策略生命周期
   - `initialize`: 声明参数、订阅数据、设置风险和日志。
   - `on_data`: 更新指标和模型输入，只处理当前可见数据。
   - `generate_signal`: 输出方向或 score。
   - `build_target`: 计算目标仓位或订单意图。
   - `risk_check`: 应用限仓、冷却、杠杆、换手和停机规则。
   - `on_order_update`: 更新挂单和成交状态。
   - `on_end`: 输出指标和诊断信息。

3. 保持研究和实盘一致
   - 回测和实盘必须调用同一个信号函数。
   - 参数优化不能改变数据可见性或执行假设。
   - 模型推理要固定特征顺序、缺失值策略和版本号。

4. 支持多资产
   - 每个资产维护独立指标和状态。
   - 组合层统一处理资金分配、风险预算和相关性暴露。
   - 不要在单资产策略里隐式读取全局组合状态。

5. 生成审计信息
   - 每次下单都能解释：信号、目标仓位、风险约束、最终订单。
   - 保存参数快照、信号序列、目标仓位、实际持仓和退出原因。

## 判断标准

- 策略模板能在研究和实盘路径复用核心信号逻辑。
- 参数、状态、信号、下单、风控边界清晰。
- 没有全局隐式状态、人工调试开关或 notebook 专属依赖。
- 每个交易动作都能从输入数据和参数中重放解释。

## 常见失败模式

- 指标函数在内部读取未来 candle 或全局 dataframe。
- 策略里直接调用交易所下单，绕过组合和风控层。
- 参数散落在函数体中，优化和复现困难。
- 止损止盈和信号反转互相覆盖，退出原因不可解释。
- 多资产策略把不同资产状态混进同一变量。

## 输出格式

输出应包含：

- 策略骨架：生命周期函数和职责说明。
- 参数表：名称、默认值、范围、含义。
- 状态表：变量、更新时机、是否可持久化。
- 审计字段：signal、target、order、fill、exit_reason。
- 风险提示：模板中仍需由外部风控层承担的事项。

## Bundled Resources

- `templates/strategy_template.py`: 可运行策略类模板，分离参数、状态、指标、信号、仓位和退出原因。
- `scripts/check_strategy_template.py`: 静态检查脚本，用于发现策略模板缺少生命周期方法或把下单逻辑混进信号层。

当用户要生成策略代码时，先复制模板；当用户给出已有策略文件时，运行：

```bash
python3 skills/quant-strategy-template/scripts/check_strategy_template.py path/to/strategy.py
```

## Source Basis

本 skill 蒸馏自宽松许可证项目的公开工程模式，不复制源代码：

- jesse-ai/jesse: https://github.com/jesse-ai/jesse
- QuantConnect/Lean: https://github.com/QuantConnect/Lean
- microsoft/qlib: https://github.com/microsoft/qlib
