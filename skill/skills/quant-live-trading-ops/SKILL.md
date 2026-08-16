---
name: quant-live-trading-ops
description: Use when preparing quantitative trading systems for paper trading or live deployment with dry-run mode, configuration isolation, secrets handling, logging, monitoring, alerting, kill switches, recovery, and pre-launch readiness checks.
language: zh-CN
---

# Quant Live Trading Ops

## 何时使用

当用户要上线、试运行或审查实盘量化系统时使用本 skill。适用场景包括：

- 从回测进入 paper trading、dry-run 或小资金实盘。
- 设计运行配置、日志、监控、告警、停机和恢复流程。
- 审查 API key、账户权限、部署机器和操作风险。
- 排查实盘和回测行为不一致。

## 输入材料

先收集：

- 部署方式：本机、服务器、Docker、云服务或托管平台。
- 环境清单：research、backtest、paper、live。
- 账户和权限：只读、交易、提现、IP 白名单、子账户。
- 配置文件：策略参数、交易品种、费率、限额、风控、日志路径。
- 运行日志：行情、信号、订单、成交、持仓、异常、告警。
- 人工操作流程：启动、暂停、恢复、撤单、清仓、停机。

## 工作流程

1. 隔离环境
   - research/backtest/paper/live 配置必须分开。
   - live 配置不得从 notebook 或开发默认值继承。
   - 每次启动输出配置摘要，但不得打印 secret。

2. 设置 dry-run 到 live 阶梯
   - Dry-run: 不真实下单，只验证信号、订单意图和日志。
   - Paper: 使用模拟账户或交易所 paper 环境，验证订单生命周期。
   - Shadow: 真实行情和真实账户查询，但订单阻断。
   - Small capital: 小额度、低频率、硬限额。
   - Live: 通过监控、回滚、停机和人工接管门槛后才允许。

3. 建立运行观测
   - 核心日志必须包括 data heartbeat、signal、order intent、order status、fill、position、cash、risk event。
   - 监控指标包括数据延迟、订单失败率、未确认订单数、持仓漂移、PnL、回撤、API 错误率。
   - 告警要分级：info、warning、critical、stop-trading。

4. 做安全控制
   - API key 禁止提现权限，优先使用 IP 白名单和子账户。
   - 设置单笔、单品种、组合、日内亏损和最大订单频率限制。
   - kill switch 必须能阻断新订单；清仓动作要单独确认。

5. 设计恢复流程
   - 进程重启后先加载本地状态，再查询远端订单、成交、持仓。
   - 状态不一致时进入 safe mode，只允许撤单、查询和人工处理。
   - 所有手动干预要写入操作日志。

## 判断标准

- 上线前可以完整跑通 dry-run/paper/small-capital 阶梯。
- 任何未知订单或持仓漂移都会阻断新交易。
- secret 不进入日志、报告、git 或错误堆栈。
- 人工能在 5 分钟内判断系统状态并执行停机流程。

## 常见失败模式

- paper 和 live 使用同一配置文件，只靠布尔开关区分。
- 只有策略日志，没有订单、成交和风控日志。
- API key 权限过大，包含提现或跨账户权限。
- 进程重启后直接继续交易，未做远端对账。
- 监控只看 PnL，不看数据延迟和订单状态。

## 输出格式

输出应包含：

- 上线阶段判定：dry-run / paper / shadow / small-capital / live / blocked。
- Pre-launch checklist。
- 运行指标和告警规则。
- 停机与恢复流程。
- 当前最大上线风险和必须先修复项。

## Bundled Resources

- `templates/live_config.example.json`: 实盘配置模板，显式区分 stage、limits、alerts、secrets policy。
- `scripts/check_live_config.py`: 标准库配置审计脚本，检查 live 配置是否缺少风控、告警、secret 边界或 dry-run 阶段。

当用户准备上线或 paper trading 时，运行：

```bash
python3 skills/quant-live-trading-ops/scripts/check_live_config.py path/to/live_config.json
```

## Source Basis

本 skill 蒸馏自宽松许可证项目的公开工程模式，不复制源代码：

- hummingbot/hummingbot: https://github.com/hummingbot/hummingbot
- vnpy/vnpy: https://github.com/vnpy/vnpy
- QuantConnect/Lean: https://github.com/QuantConnect/Lean
