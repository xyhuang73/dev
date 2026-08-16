---
name: quant-data-pit-pipeline
description: Use when building or reviewing point-in-time quantitative data pipelines, timestamp alignment, adjusted prices, missing data handling, trading calendars, and cross-asset datasets for backtests, ML training, or live signal generation.
language: zh-CN
---

# Quant Data PIT Pipeline

## 何时使用

当任务涉及量化数据准备、PIT 数据、跨资产对齐或防未来函数数据管线时使用本 skill。适用场景包括：

- 构建 OHLCV、基本面、因子、宏观、另类数据的研究数据集。
- 审查训练集和回测集是否存在时间错配。
- 处理复权、停牌、退市、合约换月、交易日历和缺失字段。
- 将离线研究数据迁移到实时信号生成管线。

## 输入材料

要求用户或仓库提供：

- 原始数据样例和字段字典。
- 数据供应商、下载时间、数据快照路径或 hash。
- 每个字段的可见时间：交易前、盘中、收盘后、公告后或修订后。
- 资产 universe 构造规则和生效时间。
- 价格复权、币种换算、合约连续化、分红拆股处理规则。
- 下游用途：训练、回测、实盘信号、报告或风控。

## 工作流程

1. 建立时间语义
   - 为每条数据区分 `event_time`、`available_time`、`ingest_time`。
   - 交易决策只能使用 `available_time <= decision_time` 的字段。
   - 财报、宏观、评级、成分股变更必须按发布日期或可得时间入库。

2. 固定 universe
   - 股票要处理退市、停牌、指数成分历史和幸存者偏差。
   - 期货要定义主力、连续合约、换月、夜盘和保证金字段。
   - 加密要定义交易所、交易对、稳定币计价、资金费率和永续合约字段。
   - 多市场数据不得默认共享交易日历。

3. 设计数据层级
   - Raw: 不改字段含义，只做完整保存和版本记录。
   - Clean: 类型、时区、重复、异常值和缺失值处理。
   - PIT: 按可见时间组织，支持历史回放。
   - Feature-ready: 下游模型可用，但仍保留数据来源和时间戳。

4. 做对齐和滞后
   - 滚动指标、横截面 rank、标准化、缺失值填充都必须在训练窗口内完成。
   - 收盘价产生的信号默认下一 bar 执行；不要 same-bar fill。
   - 跨资产特征要按各自市场日历对齐，禁止前向填充尚未开盘市场的数据。

5. 写数据质量门
   - 覆盖率、重复率、缺失率、极值、价格跳变、成交量异常必须有阈值。
   - 数据缺口影响回测时，输出 `BLOCKED` 或缩小样本，不得静默补齐。
   - 每次数据刷新要生成差异报告。

## 判断标准

- PIT 正确：字段有明确可见时间，回测时不会读到未来版本。
- 可追溯：每个特征能回到原始字段、处理规则和数据版本。
- 可迁移：离线训练和线上推理使用同一字段定义和时区规则。
- 可失败：缺失关键资产或字段时，管线会停止而不是产出伪结果。

## 常见失败模式

- 用当前指数成分回测历史，造成幸存者偏差。
- 对全样本做标准化、winsorize、缺失填充或特征选择。
- 财报字段按报告期入库，而不是按公告可见时间入库。
- 多资产数据按日期简单 join，忽略交易时段和时区。
- 删除缺失值后无意改变 universe 或提高流动性质量。

## 输出格式

输出应包含：

- 数据血缘表：字段、来源、时间语义、处理规则、下游用途。
- PIT 风险清单：明确哪些字段可能泄漏。
- 质量门结果：PASS/WARN/FAIL/BLOCKED。
- 最小修复建议：优先修复会改变回测结论的数据问题。

## Bundled Resources

- `templates/data_contract.json`: PIT 数据契约模板，用于记录字段、时间语义、供应商和质量门。
- `scripts/audit_pit_csv.py`: 标准库 CSV 审计脚本，检查时间戳、重复键、缺失值和明显 PIT 风险。

当用户给出 CSV 样本或数据导出时，运行：

```bash
python3 skills/quant-data-pit-pipeline/scripts/audit_pit_csv.py data.csv --symbol-col symbol --time-col event_time --available-col available_time
```

## Source Basis

本 skill 蒸馏自宽松许可证项目的公开工程模式，不复制源代码：

- microsoft/qlib: https://github.com/microsoft/qlib
- QuantConnect/Lean: https://github.com/QuantConnect/Lean
- vnpy/vnpy: https://github.com/vnpy/vnpy
