---
name: miniqmt-account
description: >-
  Default skill for F3_0425 miniQMT / XtQuantTrader account cash, balance,
  quota, asset, and live trading account status checks. Always load this first
  when the user asks about 账户额度、资金、余额、可用金额、持仓市值、总资产 or
  trading account connectivity.
---

# miniQMT 账户资金查询

## 默认触发

用户提到以下任意意图时，先按本 skill 执行，不要临时新写账户连接脚本：

- 当前账户额度 / 资金 / 余额 / 可用金额
- 总资产、现金、冻结资金、持仓市值
- miniQMT / 国金 QMT / XtQuantTrader 交易账户连接状态
- `query_stock_asset`、`account_id`、资金账号相关问题

## 前置条件

1. 已启动并登录 **国金 miniQMT / QMT**；`XtQuantTrader.connect()` 返回 `0` 才能查询交易账户。
2. 配置文件：`Config/qmt.json`
   - `qmt_install_path`
   - `userdata_folder_name`
   - `account_id`：自动发现失败时填写资金账号。

## 标准执行方式

在仓库根目录运行：

```bash
python scripts/check_account_quota.py
```

核心实现固定在：

- `qmt_account.build_account_quota_report()`：账户连接、账号解析、资产查询、报告格式化。
- `scripts/check_account_quota.py`：CLI 入口，只负责调用核心函数。

## 代码边界

- **行情 / 本地 datadir**：放在 `qmt_service.py`，不要求交易客户端登录。
- **账户 / 交易**：放在 `qmt_account.py`，必须通过 `XtQuantTrader` 且要求客户端已启动登录。
- 不要把交易连接逻辑堆到 `qmt_service.py`。
- 不要重复创建临时账户查询脚本；优先复用 `qmt_account.build_account_quota_report()`。

## 结果解读

| 现象 | 处理 |
|------|------|
| `QMT 进程可能已启动: False` | 提示用户启动并登录 miniQMT / 国金 QMT |
| `connect 返回值` 非 `0` | 客户端未连接成功，先启动并登录交易端 |
| 未获取到资金账号 | 在 `Config/qmt.json` 填写 `account_id` |
| `subscribe 返回值` 异常 | 检查账号类型、登录状态、资金账号 |
| `query_stock_asset 返回 None` | 检查订阅、登录、账号权限 |

## 常用资产字段

XtQuant 版本字段名可能不同，重点查看：

- `cash`
- `frozen_cash`
- `market_value`
- `total_asset`
- `fetch_balance`
- `enable_balance`
- `asset_balance`
- `current_balance`
- `avl_balance`

## 后续维护约定

账户额度查询相关修改应优先 review：

1. `qmt_account.py`
2. `scripts/check_account_quota.py`
3. `Config/qmt.json`
4. `.cursor/skills/miniqmt-account/SKILL.md`

修改后检查最近编辑文件的诊断问题；如只是运行查询，无需改代码。
