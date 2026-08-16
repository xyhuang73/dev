---
name: quant-research-lifecycle
description: Use when designing or auditing a quantitative research lifecycle from data preparation through experiment configuration, model training, backtesting, result recording, promotion gates, and reproducibility controls across multi-market quant projects.
language: zh-CN
---

# Quant Research Lifecycle

## 何时使用

当用户要建立、重构或审查量化研究流程时使用本 skill。适用场景包括：

- 从研究想法走到可复现实验、回测和候选策略。
- 为 ML/AI quant 项目设计数据、模型、回测、报告的闭环。
- 判断某个策略是否可以进入 paper trading、small capital 或生产候选池。
- 整理研究产物，避免 notebook、脚本、结果文件互相脱节。

本 skill 关注流程治理，不替代具体特征工程、交易环境或风控实现。

## 输入材料

先收集这些材料；缺失时要把结论标成条件性结论：

- 研究假设：预测目标、交易频率、资产范围、持仓周期、预期边际。
- 数据说明：供应商、时间范围、字段、复权/PIT 处理、交易日历。
- 实验配置：模型、特征集、标签、训练/验证切分、随机种子、参数搜索范围。
- 回测配置：手续费、滑点、成交假设、调仓频率、容量限制。
- 结果文件：指标表、交易日志、持仓曲线、回撤图、失败样本。
- 代码入口：数据准备、训练、推理、回测、报告生成命令。

## 工作流程

1. 固定研究问题
   - 写清楚策略试图捕捉的经济或行为机制。
   - 把预测问题和交易问题分开：预测准确不等于可交易 alpha。
   - 明确决策时间点：信号在何时可见，订单在何时可执行。

2. 建立实验登记
   - 每次实验必须有唯一 id、代码版本、数据版本、配置快照和运行时间。
   - 配置优先使用声明式文件或可序列化结构，不依赖 notebook 隐式状态。
   - 记录失败实验；不要只保留最优结果。

3. 串联研究闭环
   - Data: 原始数据到研究数据集要有可复现脚本。
   - Feature: 每个特征要能追溯到可用时间点和输入字段。
   - Model: 训练、验证、推理必须使用同一套特征定义。
   - Backtest: 回测只读取模型在当时可产生的信号。
   - Report: 输出指标、图表、参数、样本外区间和失败原因。

4. 设置晋级门槛
   - Research idea: 假设清楚，数据可得。
   - Candidate: 样本外为正，成本后仍有效，无明显泄漏。
   - Paper trading: 可实时生成信号，订单/风控链路可观测。
   - Small capital: 真实成交和模拟成交差异可解释。
   - Production: 有回滚、监控、限额和停机机制。

5. 做负向审计
   - 主动寻找泄漏、数据窥探、参数过拟合和幸存者偏差。
   - 做延迟、成本、滑点、缺失数据、样本切换的压力测试。
   - 对最强结果要求最强证据；不允许只展示单次最优回测。

## 判断标准

- 可复现：另一台机器能从配置和数据版本复现主要结果。
- 可解释：研究假设、模型输出和交易行为之间存在可说明的链路。
- 可审计：每个收益贡献能回到信号、订单、成交和持仓。
- 可拒绝：流程能明确给出 FAIL/BLOCKED，而不是总能产出漂亮报告。
- 可晋级：每一阶段有进入下一阶段的硬条件。

## 常见失败模式

- Notebook 里人工挑选窗口或参数，结果无法复现。
- 把全样本标准化、特征选择或调参泄漏进训练期。
- 回测配置和训练配置分离，推理时使用了不同字段或频率。
- 只看收益曲线，不保存交易日志、持仓变化和失败样本。
- 用生产术语包装研究原型，跳过 paper trading 和小资金验证。

## 输出格式

输出应包含：

- 当前阶段判定：`idea` / `candidate` / `paper-ready` / `small-capital-ready` / `blocked`。
- 证据链表：数据版本、代码版本、配置、命令、结果文件。
- 晋级缺口：进入下一阶段前必须补齐的事项。
- 拒绝理由：若 BLOCKED，写清楚是数据、方法、执行还是复现问题。
- 下一步最小动作：只列 1-3 个最能提高可信度的动作。

## Bundled Resources

- `templates/experiment_manifest.json`: 研究实验登记模板，用于固定数据、代码、配置、回测和报告证据链。
- `scripts/validate_manifest.py`: 标准库脚本，用于检查实验登记是否缺少关键字段。

当用户已有实验目录时，优先让 agent 复制模板并填充真实路径；当用户要求审计研究可信度时，运行：

```bash
python3 skills/quant-research-lifecycle/scripts/validate_manifest.py path/to/experiment_manifest.json
```

## Source Basis

本 skill 蒸馏自宽松许可证项目的公开工程模式，不复制源代码：

- microsoft/qlib: https://github.com/microsoft/qlib
- QuantConnect/Lean: https://github.com/QuantConnect/Lean
