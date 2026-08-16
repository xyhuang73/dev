# quant-risk-execution

## 描述

量化风控与执行安全 — 分层限仓 + 幂等下单 + 持仓对账 + SAFE_MODE + 渐进放量 + 多渠道告警

## 何时使用

当用户需要以下场景时触发本技能：

- 为实盘交易系统添加风控层（回撤限仓、仓位上限）
- 实现幂等下单机制，防止网络重试导致重复下单
- 构建持仓对账系统，检测本地与交易所状态漂移
- 设计 SAFE_MODE 安全模式，在异常时自动降级
- 实现模型渐进放量与自动回滚机制
- 搭建多渠道告警（企业微信/钉钉/飞书）
- 任何涉及实盘资金安全的量化交易系统开发

---

## A. 分层回撤限仓 (Tiered Drawdown Position Limits)

### 核心思想

根据当前回撤幅度，**渐进式**收缩新开仓规模，而非硬性清仓。保留方向信号，只压缩仓位大小。

### 代码模板

```python
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RiskConfig:
    tier1_drawdown: float = 0.05
    tier1_cap: float = 0.8
    tier2_drawdown: float = 0.10
    tier2_cap: float = 0.5
    tier3_drawdown: float = 0.15
    tier3_cap: float = 0.2
    freeze_periods: int = 0


class RiskManager:
    def __init__(self, config: RiskConfig):
        self.config = config
        self.freeze_counter = config.freeze_periods

    def check_risk(self, current_drawdown: float, proposed_action: float) -> Optional[float]:
        if self.freeze_counter > 0:
            self.freeze_counter -= 1
            return 0.0

        cap = 1.0
        if current_drawdown > self.config.tier3_drawdown:
            cap = self.config.tier3_cap
        elif current_drawdown > self.config.tier2_drawdown:
            cap = self.config.tier2_cap
        elif current_drawdown > self.config.tier1_drawdown:
            cap = self.config.tier1_cap

        if abs(proposed_action) > cap:
            return cap * (1 if proposed_action > 0 else -1)
        return None

    def reset_freeze(self, periods: int = 0):
        self.freeze_counter = periods


def build_risk_manager_from_config(config_dict: dict) -> RiskManager:
    config = RiskConfig(
        tier1_drawdown=config_dict.get("tier1_drawdown", 0.05),
        tier1_cap=config_dict.get("tier1_cap", 0.8),
        tier2_drawdown=config_dict.get("tier2_drawdown", 0.10),
        tier2_cap=config_dict.get("tier2_cap", 0.5),
        tier3_drawdown=config_dict.get("tier3_drawdown", 0.15),
        tier3_cap=config_dict.get("tier3_cap", 0.2),
        freeze_periods=config_dict.get("freeze_periods", 0),
    )
    return RiskManager(config)
```

### 设计原则

1. **软上限（Soft Caps）**：保留方向，不强制平仓。回撤 10% 时将新仓位压缩到 50%，但不翻转也不清仓
2. **只影响未来仓位**：不触碰已有持仓，仅限制新动作的规模
3. **可配置阈值**：通过 `RiskConfig` dataclass 统一管理，`build_risk_manager_from_config()` 确保单一数据源
4. **冻结期**：极端事件后可设置 `freeze_periods`，期间所有动作为 0

---

## B. 幂等下单 (Idempotent Order Execution)

### 核心思想

每次下单动作生成唯一 Action ID，通过状态机追踪订单生命周期，防止网络重试导致重复成交。

### Action ID 生成

```python
import hashlib
import time


def generate_action_id(symbol: str, target_position: float, timestamp: float, run_id: str) -> str:
    target_bucket = int(round(target_position * 100))
    ts_bucket = int(timestamp // 300) * 300
    run_id_short = run_id[:8]
    hash_suffix = hashlib.md5(
        f"{symbol}:{target_bucket}:{ts_bucket}:{run_id}".encode()
    ).hexdigest()[:6]
    return f"{symbol}_{target_bucket}_{ts_bucket}_{run_id_short}_{hash_suffix}"
```

**设计要点**：
- `target_bucket`：将目标仓位离散化到 0.01 精度，同一目标仓位在同一时间桶内生成相同 ID
- `ts_bucket`：5 分钟时间桶，同一桶内相同目标不会重复下单
- `hash_suffix`：防碰撞，确保不同 run 不会混淆

### 订单状态机

```
IDLE ──→ PLACED ──→ PARTIAL ──→ FILLED
  │         │
  │         ├──→ TIMEOUT ──→ MARKET_FALLBACK ──→ FILLED
  │         ├──→ CANCELED
  │         └──→ FAILED
```

### 状态追踪

```python
from enum import Enum
from typing import Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime


class OrderState(Enum):
    IDLE = "idle"
    PLACED = "placed"
    PARTIAL = "partial"
    FILLED = "filled"
    TIMEOUT = "timeout"
    MARKET_FALLBACK = "market_fallback"
    CANCELED = "canceled"
    FAILED = "failed"


TERMINAL_STATES = {OrderState.FILLED, OrderState.CANCELED, OrderState.FAILED}


@dataclass
class ActionRecord:
    action_id: str
    state: OrderState = OrderState.IDLE
    target_position: float = 0.0
    order_id: Optional[str] = None
    fill_price: Optional[float] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class ActionTracker:
    def __init__(self):
        self.actions: Dict[str, ActionRecord] = {}

    def is_action_pending(self, action_id: str) -> bool:
        record = self.actions.get(action_id)
        if record is None:
            return False
        return record.state not in TERMINAL_STATES

    def is_action_completed(self, action_id: str) -> bool:
        record = self.actions.get(action_id)
        if record is None:
            return False
        return record.state in TERMINAL_STATES

    def register_action(self, action_id: str, target_position: float) -> ActionRecord:
        if action_id in self.actions:
            return self.actions[action_id]
        record = ActionRecord(action_id=action_id, target_position=target_position)
        self.actions[action_id] = record
        return record

    def update_action_status(self, action_id: str, new_state: OrderState, order_id: Optional[str] = None):
        record = self.actions.get(action_id)
        if record is None:
            return
        record.state = new_state
        record.updated_at = datetime.utcnow().isoformat()
        if order_id is not None:
            record.order_id = order_id

    def complete_action(self, action_id: str, fill_price: float):
        record = self.actions.get(action_id)
        if record is None:
            return
        record.state = OrderState.FILLED
        record.fill_price = fill_price
        record.updated_at = datetime.utcnow().isoformat()
```

### 幂等下单流程

```python
def execute_trade(symbol, target_position, run_id, tracker, exchange_client):
    action_id = generate_action_id(symbol, target_position, time.time(), run_id)

    if tracker.is_action_completed(action_id):
        return {"status": "already_completed", "action_id": action_id}

    if tracker.is_action_pending(action_id):
        return {"status": "pending", "action_id": action_id}

    tracker.register_action(action_id, target_position)
    tracker.update_action_status(action_id, OrderState.PLACED)

    try:
        order_result = exchange_client.place_order(symbol, target_position)
        tracker.update_action_status(action_id, OrderState.FILLED, order_result["order_id"])
        tracker.complete_action(action_id, order_result["fill_price"])
        return {"status": "filled", "action_id": action_id}
    except Exception as e:
        tracker.update_action_status(action_id, OrderState.FAILED)
        return {"status": "failed", "action_id": action_id, "error": str(e)}
```

---

## C. 持仓对账与 SAFE_MODE (Reconciliation & SAFE_MODE)

### 持仓对账

```python
from typing import List, Tuple


def reconcile(
    exchange_position: float,
    local_position: float,
    open_orders: list,
    state,
    tolerance: float = 0.01,
) -> Tuple[bool, List[str]]:
    discrepancies = []

    if abs(exchange_position - local_position) > tolerance:
        discrepancies.append(
            f"Position mismatch: exchange={exchange_position:.4f}, local={local_position:.4f}"
        )

    if open_orders and state.order_state.get("state") == "idle":
        discrepancies.append(
            f"Unexpected open orders: {len(open_orders)} orders while state is idle"
        )

    if discrepancies:
        enter_safe_mode(f"Reconciliation failed: {'; '.join(discrepancies)}")
        return False, discrepancies

    return True, []
```

### SAFE_MODE 设计

**触发条件**：
- 对账失败（持仓不一致）
- API 连续失败 ≥ 3 次
- 时钟漂移 > 30 秒
- 手动触发

**核心原则：只限开仓/加仓，减仓永远允许**

```python
import time
from dataclasses import dataclass, field
from typing import Optional


MAX_API_FAILURES = 3
MAX_CLOCK_DRIFT_SECONDS = 30


@dataclass
class SafetyState:
    safe_mode: bool = False
    safe_mode_reason: Optional[str] = None
    safe_mode_entered_at: Optional[float] = None
    api_fail_count: int = 0
    last_api_success: Optional[float] = None
    clock_drift: float = 0.0


class SafetyManager:
    def __init__(self):
        self.state = SafetyState()

    def enter_safe_mode(self, reason: str):
        self.state.safe_mode = True
        self.state.safe_mode_reason = reason
        self.state.safe_mode_entered_at = time.time()

    def exit_safe_mode(self):
        self.state.safe_mode = False
        self.state.safe_mode_reason = None
        self.state.safe_mode_entered_at = None

    def can_execute_action(self, current_position: float, target_position: float) -> bool:
        if not self.state.safe_mode:
            return True

        if abs(target_position) < abs(current_position):
            return True

        if target_position == 0.0:
            return True

        if abs(target_position) <= abs(current_position) and target_position * current_position >= 0:
            return True

        return False

    def record_api_success(self):
        self.state.api_fail_count = 0
        self.state.last_api_success = time.time()

    def record_api_failure(self):
        self.state.api_fail_count += 1
        if self.state.api_fail_count >= MAX_API_FAILURES:
            self.enter_safe_mode(f"API consecutive failures: {self.state.api_fail_count}")

    def check_clock_drift(self, exchange_timestamp: float):
        self.state.clock_drift = abs(time.time() - exchange_timestamp / 1000)
        if self.state.clock_drift > MAX_CLOCK_DRIFT_SECONDS:
            self.enter_safe_mode(f"Clock drift: {self.state.clock_drift:.1f}s")

    def maybe_auto_recover(self, reconcile_ok: bool):
        if self.state.safe_mode and self.state.safe_mode_reason and "Reconciliation" in self.state.safe_mode_reason:
            if reconcile_ok:
                self.exit_safe_mode()
```

### API 健康监控

```python
class APIHealthMonitor:
    def __init__(self, safety_manager: SafetyManager):
        self.safety = safety_manager

    def on_success(self):
        self.safety.record_api_success()

    def on_failure(self):
        self.safety.record_api_failure()

    def check_drift(self, exchange_server_time_ms: float):
        self.safety.check_clock_drift(exchange_server_time_ms)
```

---

## D. 渐进放量与自动回滚 (Gradual Rollout & Auto-Rollback)

### 放量级别与 KPI 阈值

```python
ROLLOUT_LEVELS = [0.25, 0.5, 1.0]
MIN_DAYS_PER_LEVEL = 3
MIN_TRADES_PER_LEVEL = 6

MAX_SLIPPAGE_THRESHOLD = 0.005
MIN_FILL_RATE = 0.9
MAX_RECONCILE_ERRORS = 2
```

### RolloutController

```python
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timedelta


@dataclass
class RolloutKPIs:
    total_trades: int = 0
    filled_trades: int = 0
    total_slippage: float = 0.0
    reconcile_errors: int = 0
    level_start_time: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class RolloutController:
    def __init__(self):
        self.stable_run_id: Optional[str] = None
        self.stable_model_path: Optional[str] = None
        self.candidate_run_id: Optional[str] = None
        self.candidate_model_path: Optional[str] = None
        self.rollout_level: float = 0.0
        self.rollout_level_index: int = -1
        self.kpis = RolloutKPIs()
        self.is_rolling_out = False

    def start_rollout(self, candidate_run_id: str, candidate_model_path: str):
        self.candidate_run_id = candidate_run_id
        self.candidate_model_path = candidate_model_path
        self.rollout_level_index = 0
        self.rollout_level = ROLLOUT_LEVELS[0]
        self.kpis = RolloutKPIs()
        self.is_rolling_out = True

    def record_trade(self, filled: bool, slippage: float, reconcile_ok: bool):
        self.kpis.total_trades += 1
        if filled:
            self.kpis.filled_trades += 1
            self.kpis.total_slippage += abs(slippage)
        if not reconcile_ok:
            self.kpis.reconcile_errors += 1

    def _check_kpis(self) -> bool:
        if self.kpis.total_trades == 0:
            return False
        avg_slippage = self.kpis.total_slippage / max(self.kpis.filled_trades, 1)
        fill_rate = self.kpis.filled_trades / self.kpis.total_trades
        return (
            avg_slippage <= MAX_SLIPPAGE_THRESHOLD
            and fill_rate >= MIN_FILL_RATE
            and self.kpis.reconcile_errors <= MAX_RECONCILE_ERRORS
        )

    def _check_time_and_volume(self) -> bool:
        start = datetime.fromisoformat(self.kpis.level_start_time)
        days_elapsed = (datetime.utcnow() - start).days
        return days_elapsed >= MIN_DAYS_PER_LEVEL and self.kpis.total_trades >= MIN_TRADES_PER_LEVEL

    def maybe_promote(self) -> Optional[str]:
        if not self.is_rolling_out:
            return None
        if not self._check_time_and_volume():
            return None
        if not self._check_kpis():
            return None

        next_index = self.rollout_level_index + 1
        if next_index >= len(ROLLOUT_LEVELS):
            return self.finalize_rollout()

        self.rollout_level_index = next_index
        self.rollout_level = ROLLOUT_LEVELS[next_index]
        self.kpis = RolloutKPIs()
        return f"promoted_to_{self.rollout_level}"

    def demote_rollout(self) -> str:
        if self.rollout_level_index <= 0:
            return self.rollback_to_stable()

        self.rollout_level_index -= 1
        self.rollout_level = ROLLOUT_LEVELS[self.rollout_level_index]
        self.kpis = RolloutKPIs()
        return f"demoted_to_{self.rollout_level}"

    def rollback_to_stable(self) -> str:
        self.candidate_run_id = None
        self.candidate_model_path = None
        self.rollout_level = 0.0
        self.rollout_level_index = -1
        self.is_rolling_out = False
        self.kpis = RolloutKPIs()
        return "rolled_back_to_stable"

    def finalize_rollout(self) -> str:
        self.stable_run_id = self.candidate_run_id
        self.stable_model_path = self.candidate_model_path
        self.candidate_run_id = None
        self.candidate_model_path = None
        self.rollout_level = 1.0
        self.rollout_level_index = len(ROLLOUT_LEVELS) - 1
        self.is_rolling_out = False
        self.kpis = RolloutKPIs()
        return "finalized_candidate_is_now_stable"

    def get_position_multiplier(self) -> float:
        if not self.is_rolling_out:
            return 1.0
        return self.rollout_level
```

### 放量流程

```
1. start_rollout(candidate_run_id, candidate_model_path) → level 0.25x
2. record_trade(filled, slippage, reconcile_ok) → 每次执行后记录
3. maybe_promote() → 检查最低交易数 + 最低天数 + KPIs → 晋级
4. KPIs 不达标 → demote_rollout() → 降一级
5. 最低级别仍不达标 → rollback_to_stable() → 完全回滚
6. 达到 1.0x 且通过 → finalize_rollout() → candidate 成为 stable
```

---

## E. 多渠道告警 (Multi-Channel Alerting)

### 告警级别

| 级别 | 场景 | 示例 |
|------|------|------|
| INFO | 日常执行摘要、仓位变动 | "BTC 仓位从 0.3 调整至 0.5" |
| WARNING | 回撤触及 5%/10%、API 异常 | "回撤 10.2%，仓位上限降至 50%" |
| CRITICAL | 回撤 ≥ 15% 生存模式、权益异常 > 5% | "进入生存模式，回撤 16.1%" |

### AlertManager

```python
import os
import json
import logging
import requests
from enum import Enum
from typing import Optional


class AlertLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertManager:
    def __init__(self):
        self.wechat_webhook = os.environ.get("WECHAT_WEBHOOK_URL")
        self.dingtalk_webhook = os.environ.get("DINGTALK_WEBHOOK_URL")
        self.feishu_webhook = os.environ.get("FEISHU_WEBHOOK_URL")
        self.logger = logging.getLogger("alert")

    def send(self, level: AlertLevel, message: str):
        formatted = self._format_message(level, message)
        self.logger.info(formatted)

        if self.wechat_webhook:
            self._send_wechat(level, formatted)
        if self.dingtalk_webhook:
            self._send_dingtalk(level, formatted)
        if self.feishu_webhook:
            self._send_feishu(level, formatted)

    def _format_message(self, level: AlertLevel, message: str) -> str:
        prefix = {
            AlertLevel.INFO: "ℹ️",
            AlertLevel.WARNING: "⚠️",
            AlertLevel.CRITICAL: "🚨",
        }
        return f"{prefix.get(level, '')} [{level.value.upper()}] {message}"

    def _send_wechat(self, level: AlertLevel, message: str):
        try:
            payload = {
                "msgtype": "markdown",
                "markdown": {"content": message},
            }
            requests.post(self.wechat_webhook, json=payload, timeout=5)
        except Exception as e:
            self.logger.error(f"WeChat alert failed: {e}")

    def _send_dingtalk(self, level: AlertLevel, message: str):
        try:
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": f"[{level.value.upper()}]",
                    "text": message,
                },
            }
            requests.post(self.dingtalk_webhook, json=payload, timeout=5)
        except Exception as e:
            self.logger.error(f"DingTalk alert failed: {e}")

    def _send_feishu(self, level: AlertLevel, message: str):
        try:
            payload = {
                "msg_type": "interactive",
                "card": {
                    "header": {
                        "title": {"tag": "plain_text", "content": f"[{level.value.upper()}]"},
                    },
                    "elements": [{"tag": "markdown", "content": message}],
                },
            }
            requests.post(self.feishu_webhook, json=payload, timeout=5)
        except Exception as e:
            self.logger.error(f"Feishu alert failed: {e}")
```

---

## F. 状态持久化 (State Persistence)

### TradingState 数据结构

```python
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any
import json
import os
import fcntl
import tempfile


@dataclass
class OrderStateRecord:
    current_order_id: Optional[str] = None
    state: str = "idle"
    action_id: Optional[str] = None
    target_position: float = 0.0


@dataclass
class ReconcileRecord:
    timestamp: float = 0.0
    is_consistent: bool = True
    exchange_position: float = 0.0
    local_position: float = 0.0


@dataclass
class HealthRecord:
    api_fail_count: int = 0
    last_api_success: Optional[float] = None
    clock_drift: float = 0.0


@dataclass
class TradingState:
    last_flip_timestamp: float = 0.0
    run_id: str = ""
    safe_mode: bool = False
    safe_mode_reason: Optional[str] = None
    safe_mode_entered_at: Optional[float] = None
    pending_actions: Dict[str, str] = field(default_factory=dict)
    order_state: Dict[str, Any] = field(default_factory=lambda: asdict(OrderStateRecord()))
    last_reconcile: Dict[str, Any] = field(default_factory=lambda: asdict(ReconcileRecord()))
    health: Dict[str, Any] = field(default_factory=lambda: asdict(HealthRecord()))
    local_position: float = 0.0
```

### 原子写入

```python
def save_state_atomic(state: TradingState, filepath: str):
    tmp_path = filepath + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            json.dump(asdict(state), f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        os.rename(tmp_path, filepath)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def load_state(filepath: str) -> TradingState:
    if not os.path.exists(filepath):
        return TradingState()
    try:
        with open(filepath, "r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            data = json.load(f)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return TradingState(**data)
    except (json.JSONDecodeError, KeyError):
        backup = filepath + ".corrupted"
        if os.path.exists(filepath):
            os.rename(filepath, backup)
        return TradingState()
```

**设计要点**：
- 写入 `.tmp` 文件后 `os.rename()`，利用操作系统原子性保证崩溃安全
- `fcntl.flock` 文件锁防止并发读写冲突
- 读损坏文件时自动备份为 `.corrupted` 并返回空状态
- `os.fsync()` 确保数据落盘后再 rename

---

## 常见陷阱

| 陷阱 | 后果 | 正确做法 |
|------|------|----------|
| 不使用幂等 Action ID | 网络重试导致重复下单 | `generate_action_id()` + 状态机追踪 |
| 硬上限强制平仓 | 在最差时点被强平 | 软上限：保留方向，只压缩规模 |
| 不定期对账 | 本地与交易所状态漂移 | 每次执行前对账 + 定时对账 |
| SAFE_MODE 阻断所有操作 | 无法减仓避险 | 减仓永远允许，只限开仓/加仓 |
| 新模型全量上线 | 坏模型导致灾难性亏损 | 渐进放量：25% → 50% → 100% |
| 非原子写入状态文件 | 崩溃时状态损坏 | `.tmp` + `rename` + `fsync` |
| 告警通道单一 | 通道故障时无告警 | 多渠道冗余：企业微信 + 钉钉 + 飞书 |

---

## 完整集成示例

```python
class TradingEngine:
    def __init__(self, config: dict, state_path: str):
        self.risk_manager = build_risk_manager_from_config(config.get("risk", {}))
        self.safety = SafetyManager()
        self.tracker = ActionTracker()
        self.rollout = RolloutController()
        self.alerts = AlertManager()
        self.state_path = state_path
        self.state = load_state(state_path)
        self._restore_safety_state()

    def _restore_safety_state(self):
        self.safety.state.safe_mode = self.state.safe_mode
        self.safety.state.safe_mode_reason = self.state.safe_mode_reason
        self.safety.state.safe_mode_entered_at = self.state.safe_mode_entered_at
        self.safety.state.api_fail_count = self.state.health.get("api_fail_count", 0)

    def _persist_state(self):
        self.state.safe_mode = self.safety.state.safe_mode
        self.state.safe_mode_reason = self.safety.state.safe_mode_reason
        self.state.safe_mode_entered_at = self.safety.state.safe_mode_entered_at
        self.state.health = {
            "api_fail_count": self.safety.state.api_fail_count,
            "last_api_success": self.safety.state.last_api_success,
            "clock_drift": self.safety.state.clock_drift,
        }
        save_state_atomic(self.state, self.state_path)

    def execute(self, symbol: str, target_position: float, current_drawdown: float):
        adjusted = self.risk_manager.check_risk(current_drawdown, target_position)
        if adjusted is not None:
            target_position = adjusted

        multiplier = self.rollout.get_position_multiplier()
        target_position *= multiplier

        if not self.safety.can_execute_action(self.state.local_position, target_position):
            self.alerts.send(AlertLevel.WARNING, f"SAFE_MODE blocked action: target={target_position}")
            return {"status": "blocked_by_safe_mode"}

        action_id = generate_action_id(symbol, target_position, time.time(), self.state.run_id)

        if self.tracker.is_action_completed(action_id):
            return {"status": "already_completed", "action_id": action_id}

        if self.tracker.is_action_pending(action_id):
            return {"status": "pending", "action_id": action_id}

        self.tracker.register_action(action_id, target_position)
        self._persist_state()

        self.alerts.send(AlertLevel.INFO, f"Executing: {symbol} target={target_position:.4f}")
        return {"status": "registered", "action_id": action_id, "target": target_position}
```
