---
name: quant-portfolio-risk-reporting
description: Use when building or reviewing quantitative portfolio performance reports, risk metrics, drawdown analysis, exposure attribution, turnover, benchmark comparison, tear sheets, and promotion-ready strategy evidence.
language: zh-CN
---

# Quant Portfolio Risk Reporting

## 何时使用

当用户需要输出或审查量化策略绩效报告时使用本 skill。适用场景包括：

- 为回测、paper trading 或实盘生成风险收益报告。
- 判断策略结果是否足够进入候选池或上线阶段。
- 对比 benchmark、现金、指数或已有策略。
- 找出收益来自 alpha、beta、杠杆、换手、尾部风险还是偶然窗口。

## 输入材料

先收集：

- 策略净值、收益率序列、持仓、交易、费用和现金序列。
- benchmark 或参考组合。
- 时间范围、频率、交易日历和年化规则。
- 策略限制：杠杆、做空、换手、容量、风险预算。
- 分组字段：资产、行业、因子、交易所、策略子模块或模型版本。

## 工作流程

1. 校验输入
   - 确认收益率频率、缺失日期、时区和年化因子。
   - 费用后收益和费用前收益分开。
   - 实际持仓收益和目标仓位收益分开。

2. 生成核心指标
   - 收益：累计收益、年化收益、月度/年度收益。
   - 风险：波动率、最大回撤、下行波动、尾部损失、VaR/ES 可选。
   - 风险调整：Sharpe、Sortino、Calmar、information ratio。
   - 交易质量：换手、胜率、盈亏比、持仓周期、滑点和费用占比。

3. 做回撤和尾部分析
   - 列出最大回撤区间、恢复时间和对应市场环境。
   - 分析最差日/周/月以及是否集中在少数事件。
   - 对策略做成本、延迟、成交率和波动放大压力测试。

4. 做暴露和归因
   - 按资产、行业、市场、因子、方向、杠杆拆分收益和风险。
   - 对 benchmark 输出 alpha、beta、跟踪误差和主动风险。
   - 标记收益是否来自单一资产、单一时段或单一参数。

5. 给出晋级结论
   - 报告不是只展示好看的 tear sheet；必须包含失败窗口。
   - 样本外、成本后、压力后仍成立才可给出候选判定。
   - 指标不足时输出 WARN/FAIL，而不是补图掩盖问题。

## 判断标准

- 报告能解释收益来源和亏损来源。
- 指标区分样本内、样本外、paper 和 live。
- 所有图表和指标都能回到原始收益、持仓或交易日志。
- 结论包含是否可晋级以及阻塞原因。

## 常见失败模式

- 只报告年化收益和 Sharpe，不报告回撤恢复时间。
- 使用费用前收益宣传策略。
- 用不同频率收益混算年化指标。
- benchmark 不匹配策略交易范围或风险暴露。
- 忽略换手、容量和滑点，导致实盘不可复制。

## 输出格式

输出应包含：

- Executive verdict: PASS/WARN/FAIL/BLOCKED。
- 核心指标表：收益、风险、风险调整、交易质量。
- 回撤表：开始、结束、谷底、恢复、深度、持续时间。
- 归因表：资产/因子/方向/时间段贡献。
- 晋级建议：继续研究、paper、small capital、拒绝或补证据。

## Bundled Resources

- `scripts/portfolio_report.py`: 标准库绩效报告脚本，读取收益率 CSV，输出 CAGR、波动、Sharpe、Sortino、最大回撤、Calmar 和月度收益。

当用户只有简单收益率序列时，先运行脚本得到最低限度可信指标：

```bash
python3 skills/quant-portfolio-risk-reporting/scripts/portfolio_report.py returns.csv --date-col date --return-col return
```

## Source Basis

本 skill 蒸馏自宽松许可证项目的公开工程模式，不复制源代码：

- ranaroussi/quantstats: https://github.com/ranaroussi/quantstats
- QuantConnect/Lean: https://github.com/QuantConnect/Lean
- microsoft/qlib: https://github.com/microsoft/qlib
