# quant-walk-forward-validation

## 名称

quant-walk-forward-validation

## 描述

Walk-Forward 验证与 Alpha 审计 — 样本外验证 + 场景压测 + 消融实验 + 判定体系。用于对量化交易策略进行严格的样本外验证、多维度压力测试、组件消融分析，并输出四级判定结果（PASS / WARN / FAIL / BLOCKED）。

## 何时使用

当用户需要以下任一场景时触发本技能：

- 对交易策略进行 Walk-Forward 样本外验证
- 对策略运行场景压测（信号延迟、成本上升、执行扰动等）
- 执行消融实验以量化各组件贡献
- 构建完整的 Alpha 审计框架与判定体系
- 检测 Gate 坍缩、Bootstrap 显著性等统计问题
- 评估策略在真实成本与执行约束下的鲁棒性

---

## A. Expanding Window 折叠验证 (Walk-Forward Validation)

### 核心模式

采用 **Anchored Expanding Window**：训练起点固定在最早日期，训练终点逐年递增，测试期为训练终点之后的下一个时间段。每个折叠独立训练新模型，在测试集上评估。

### 折叠结构示例

| Fold   | 训练截止       | 测试期            |
|--------|---------------|-------------------|
| fold_1 | 2021-12-31    | 2022 全年          |
| fold_2 | 2022-12-31    | 2023 全年          |
| fold_3 | 2023-12-31    | 2024 全年          |
| fold_4 | 2024-12-31    | 2025 全年          |
| fold_5 | 2025-12-31    | 2026 年 1-5 月     |

### 关键原则

1. **每折独立训练**：每个折叠从头训练新模型，禁止复用其他折叠的模型权重
2. **Temperature 扫描**：每折测试 `[0.5, 0.6, 0.68, 0.8, 1.0, 1.5, 2.0]`，在验证集上选取最优值
3. **零数据泄漏**：测试数据在训练阶段完全不可见
4. **输出结构**：每折输出 `metrics.json`，汇总至 `summary/` 目录

### Walk-Forward 折叠编排模板

```python
from datetime import date
from pathlib import Path
import json

WALK_FORWARD_FOLDS = [
    {"fold": "fold_1", "train_end": date(2021, 12, 31), "test_start": date(2022, 1, 1),  "test_end": date(2022, 12, 31)},
    {"fold": "fold_2", "train_end": date(2022, 12, 31), "test_start": date(2023, 1, 1),  "test_end": date(2023, 12, 31)},
    {"fold": "fold_3", "train_end": date(2023, 12, 31), "test_start": date(2024, 1, 1),  "test_end": date(2024, 12, 31)},
    {"fold": "fold_4", "train_end": date(2024, 12, 31), "test_start": date(2025, 1, 1),  "test_end": date(2025, 12, 31)},
    {"fold": "fold_5", "train_end": date(2025, 12, 31), "test_start": date(2026, 1, 1),  "test_end": date(2026, 5, 10)},
]

TEMPERATURE_GRID = [0.5, 0.6, 0.68, 0.8, 1.0, 1.5, 2.0]

def run_walk_forward(base_data_dir: str, output_dir: str):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    for fold_cfg in WALK_FORWARD_FOLDS:
        fold_name = fold_cfg["fold"]
        fold_dir = output_path / fold_name
        fold_dir.mkdir(exist_ok=True)

        best_temp = None
        best_val_metric = float("-inf")

        for temp in TEMPERATURE_GRID:
            metrics = train_and_evaluate_fold(
                data_dir=base_data_dir,
                train_end=fold_cfg["train_end"],
                test_start=fold_cfg["test_start"],
                test_end=fold_cfg["test_end"],
                temperature=temp,
            )
            val_score = metrics.get("validation_sharpe", float("-inf"))
            if val_score > best_val_metric:
                best_val_metric = val_score
                best_temp = temp

        final_metrics = train_and_evaluate_fold(
            data_dir=base_data_dir,
            train_end=fold_cfg["train_end"],
            test_start=fold_cfg["test_start"],
            test_end=fold_cfg["test_end"],
            temperature=best_temp,
        )
        final_metrics["selected_temperature"] = best_temp

        with open(fold_dir / "metrics.json", "w") as f:
            json.dump(final_metrics, f, indent=2, default=str)

    summarize_walk_forward(output_path)


def summarize_walk_forward(output_path: Path):
    summary_dir = output_path / "summary"
    summary_dir.mkdir(exist_ok=True)
    all_metrics = []

    for fold_cfg in WALK_FORWARD_FOLDS:
        metrics_file = output_path / fold_cfg["fold"] / "metrics.json"
        if metrics_file.exists():
            with open(metrics_file) as f:
                all_metrics.append(json.load(f))

    if not all_metrics:
        return

    avg_metrics = {}
    numeric_keys = [k for k in all_metrics[0] if isinstance(all_metrics[0][k], (int, float))]
    for key in numeric_keys:
        values = [m[key] for m in all_metrics if key in m and isinstance(m[key], (int, float))]
        if values:
            avg_metrics[key] = sum(values) / len(values)

    with open(summary_dir / "walk_forward_summary.json", "w") as f:
        json.dump({"per_fold": all_metrics, "average": avg_metrics}, f, indent=2, default=str)
```

---

## B. 场景压测 (Scenario Stress Testing)

### 压测场景定义

#### 信号鲁棒性测试

| 场景 ID            | 描述                                          |
|--------------------|-----------------------------------------------|
| `signal_delay_1d`  | Signal_Proba 延迟 1 天 → 测试信号延迟后策略是否仍有效 |
| `signal_neutral_0_5` | Signal_Proba 设为 0.5 → 测试策略是否过度依赖 ML 信号  |

#### 成本压力测试

| 场景 ID        | 描述                                          |
|---------------|-----------------------------------------------|
| `cost_2x`     | 手续费率 ×2 → 测试更高成本下的盈利能力            |
| `cost_3x`     | 手续费率 ×3 → 测试极端成本下的盈利能力            |
| `funding_2x`  | 资金费率 ×2 → 测试持仓成本敏感度                  |
| `funding_3x`  | 资金费率 ×3 → 测试极端持仓成本下的存活能力         |

#### 执行扰动测试

| 场景 ID           | 描述                                          |
|------------------|-----------------------------------------------|
| `tau_0_5x`       | 滞后阈值 ×0.5 → 更敏感的执行触发                 |
| `tau_2x`         | 滞后阈值 ×2 → 更迟钝的执行触发                   |
| `delta_max_0_5x` | 仓位调整速率上限 ×0.5 → 更保守的仓位调整          |
| `delta_max_2x`   | 仓位调整速率上限 ×2 → 更激进的仓位调整            |
| `cooldown_1`     | 冷却期 1 天 → 测试反转频率影响                   |
| `cooldown_5`     | 冷却期 5 天 → 测试较长冷却期影响                  |
| `cooldown_7`     | 冷却期 7 天 → 测试极端冷却期影响                  |

#### Gate 温度敏感性

| 场景 ID              | 描述                                          |
|---------------------|-----------------------------------------------|
| `temperature_0_5`   | Gate 温度 0.5 → 更尖锐的路由分布               |
| `temperature_0_6`   | Gate 温度 0.6                                  |
| `temperature_0_68`  | Gate 温度 0.68                                 |
| `temperature_0_8`   | Gate 温度 0.8                                  |
| `temperature_1_0`   | Gate 温度 1.0（默认）                          |
| `temperature_1_5`   | Gate 温度 1.5                                  |
| `temperature_2_0`   | Gate 温度 2.0 → 更均匀的路由分布               |

#### 随机基线

| 场景 ID           | 描述                                          |
|------------------|-----------------------------------------------|
| `random_baseline` | N 次随机动作策略运行 → 建立收益下界              |

### 场景构建器模板

```python
from dataclasses import dataclass, field
from typing import Dict, Optional

@dataclass
class StressScenario:
    scenario_id: str
    description: str
    overrides: Dict[str, float] = field(default_factory=dict)
    n_runs: int = 1

def build_all_scenarios() -> list[StressScenario]:
    scenarios = [
        StressScenario("signal_delay_1d", "信号延迟1天", {"signal_delay_days": 1.0}),
        StressScenario("signal_neutral_0_5", "信号置为中性0.5", {"signal_override": 0.5}),

        StressScenario("cost_2x", "手续费×2", {"fee_rate_multiplier": 2.0}),
        StressScenario("cost_3x", "手续费×3", {"fee_rate_multiplier": 3.0}),
        StressScenario("funding_2x", "资金费率×2", {"funding_rate_multiplier": 2.0}),
        StressScenario("funding_3x", "资金费率×3", {"funding_rate_multiplier": 3.0}),

        StressScenario("tau_0_5x", "滞后阈值×0.5", {"tau_multiplier": 0.5}),
        StressScenario("tau_2x", "滞后阈值×2", {"tau_multiplier": 2.0}),
        StressScenario("delta_max_0_5x", "仓位调整速率×0.5", {"delta_max_multiplier": 0.5}),
        StressScenario("delta_max_2x", "仓位调整速率×2", {"delta_max_multiplier": 2.0}),
        StressScenario("cooldown_1", "冷却期1天", {"cooldown_days": 1.0}),
        StressScenario("cooldown_5", "冷却期5天", {"cooldown_days": 5.0}),
        StressScenario("cooldown_7", "冷却期7天", {"cooldown_days": 7.0}),
    ]

    for temp in [0.5, 0.6, 0.68, 0.8, 1.0, 1.5, 2.0]:
        scenarios.append(StressScenario(
            f"temperature_{str(temp).replace('.', '_')}",
            f"Gate温度{temp}",
            {"gate_temperature": temp},
        ))

    scenarios.append(StressScenario(
        "random_baseline", "随机动作基线", {"random_actions": 1.0}, n_runs=20,
    ))

    return scenarios
```

---

## C. 消融实验 (Ablation Studies)

### 消融场景定义

| 消融 ID              | 描述                                              | 验证目标                     |
|---------------------|---------------------------------------------------|------------------------------|
| `uniform_gate`      | 用均匀权重 (1/N) 替换学习到的 Gate 权重            | Gate 是否真正贡献价值         |
| `average_experts`   | 对专家动作取等权平均（不加权）                      | Gate 路由是否有区分度         |
| `drop_top_contributor` | 移除贡献最大的专家                                | 系统对单专家依赖的鲁棒性      |

每个消融实验与 `stable_oos` 基线对比，量化各组件的边际贡献。

### 消融对比模板

```python
@dataclass
class AblationResult:
    ablation_id: str
    description: str
    metrics: Dict[str, float]
    delta_vs_baseline: Dict[str, float]

def run_ablation_study(baseline_metrics: Dict[str, float], data_config: dict) -> list[AblationResult]:
    results = []

    ablation_configs = [
        {"id": "uniform_gate", "desc": "均匀Gate权重", "override": {"gate_mode": "uniform"}},
        {"id": "average_experts", "desc": "等权平均专家", "override": {"gate_mode": "average"}},
        {"id": "drop_top_contributor", "desc": "移除最大贡献专家", "override": {"drop_top_expert": True}},
    ]

    for cfg in ablation_configs:
        metrics = run_backtest_with_overrides(data_config, cfg["override"])
        delta = {k: metrics.get(k, 0.0) - baseline_metrics.get(k, 0.0) for k in baseline_metrics}
        results.append(AblationResult(
            ablation_id=cfg["id"],
            description=cfg["desc"],
            metrics=metrics,
            delta_vs_baseline=delta,
        ))

    return results
```

---

## D. 四级判定体系 (Four-Level Verdict System)

### 判定等级

| 等级      | 含义                         | 后续动作                     |
|----------|------------------------------|------------------------------|
| PASS     | 所有检查通过                  | 可进入实盘部署               |
| WARN     | 存在隐患但非致命              | 需记录并持续监控              |
| FAIL     | 存在致命问题                  | 禁止部署，需修复后重新验证    |
| BLOCKED  | 缺失必要产物或执行错误        | 无法完成判定，需补充数据/修复 |

### 判定逻辑

```python
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class VerdictItem:
    level: str          # "BLOCKED" | "FAIL" | "WARN" | "PASS"
    category: str       # 检查类别
    message: str        # 具体描述
    detail: str = ""    # 补充细节

@dataclass
class VerdictResult:
    status: str         # "BLOCKED" | "FAIL" | "WARN" | "PASS"
    items: List[VerdictItem] = field(default_factory=list)

def evaluate_validation_results(
    scenarios: dict,
    walk_forward_summary: dict,
    missing_artifacts: list,
    single_oos_metrics: Optional[dict] = None,
    gate_weights_history: Optional[object] = None,
    bootstrap_ci: Optional[tuple] = None,
) -> VerdictResult:
    blocking_items = []
    failures = []
    warnings = []
    passes = []

    # --- BLOCKED 检查 ---
    for artifact in missing_artifacts:
        blocking_items.append(VerdictItem("BLOCKED", "缺失产物", f"缺少必要产物: {artifact}"))

    for sid, result in scenarios.items():
        if result.get("error"):
            blocking_items.append(VerdictItem("BLOCKED", "场景执行错误", f"场景 {sid} 执行失败: {result['error']}"))

    if blocking_items:
        return VerdictResult("BLOCKED", blocking_items + failures + warnings + passes)

    # --- FAIL 检查 ---
    random_result = scenarios.get("random_baseline", {})
    if random_result.get("total_return", 0) > 0.05:
        failures.append(VerdictItem("FAIL", "随机基线", f"随机基线总收益 {random_result['total_return']:.2%} > 5%，框架存在正偏"))

    cost_2x = scenarios.get("cost_2x", {})
    if cost_2x.get("alpha", 1) < 0 and cost_2x.get("max_drawdown", 0) > scenarios.get("stable_oos", {}).get("max_drawdown", 0):
        failures.append(VerdictItem("FAIL", "成本压测", "成本×2时 alpha 翻负且回撤恶化，策略在真实成本下不可行"))

    if failures:
        return VerdictResult("FAIL", blocking_items + failures + warnings + passes)

    # --- WARN 检查 ---
    delay_result = scenarios.get("signal_delay_1d", {})
    baseline_return = scenarios.get("stable_oos", {}).get("total_return", 0)
    if delay_result.get("total_return", 0) < baseline_return * 0.5:
        warnings.append(VerdictItem("WARN", "信号延迟", "信号延迟1天使收益下降超过50%，策略对信号时效性高度敏感"))

    temp_returns = []
    for temp in [0.5, 0.6, 0.68, 0.8, 1.0, 1.5, 2.0]:
        key = f"temperature_{str(temp).replace('.', '_')}"
        if key in scenarios:
            temp_returns.append(scenarios[key].get("total_return", 0))
    if temp_returns and (max(temp_returns) - min(temp_returns)) > 0.50:
        warnings.append(VerdictItem("WARN", "温度敏感性", f"温度扰动收益范围 {max(temp_returns)-min(temp_returns):.0%} > 50pp，路由稳定性不足"))

    wf_folds = walk_forward_summary.get("per_fold", [])
    if len(wf_folds) < 3:
        warnings.append(VerdictItem("WARN", "Walk-Fold不足", f"Walk-Forward 仅有 {len(wf_folds)} 折，建议至少3折"))
    if walk_forward_summary.get("average", {}).get("alpha", 0) <= 0:
        warnings.append(VerdictItem("WARN", "WF Alpha", "Walk-Forward 平均 alpha 非正，策略可能无真实超额收益"))

    if single_oos_metrics and walk_forward_summary.get("average"):
        oos_alpha = single_oos_metrics.get("alpha", 0)
        wf_avg_alpha = walk_forward_summary["average"].get("alpha", 0)
        if wf_avg_alpha > 0 and oos_alpha > wf_avg_alpha * 2:
            warnings.append(VerdictItem("WARN", "OOS偏强", "单次OOS alpha 显著强于 WF 均值，可能存在过拟合"))

    if gate_weights_history is not None:
        collapse_msg = check_gate_collapse(gate_weights_history)
        if collapse_msg:
            warnings.append(VerdictItem("WARN", "Gate坍缩", collapse_msg))

    if bootstrap_ci is not None and bootstrap_ci[0] < 0:
        warnings.append(VerdictItem("WARN", "Bootstrap CI", f"Bootstrap CI 下界 {bootstrap_ci[0]:.4f} < 0，收益可能不显著为正"))

    # --- PASS 检查 ---
    if not warnings:
        passes.append(VerdictItem("PASS", "全量检查", "所有验证检查通过"))
    if random_result.get("total_return", 1) <= 0.02:
        passes.append(VerdictItem("PASS", "随机基线", "随机基线收益接近零，框架无正偏"))
    if cost_2x.get("alpha", -1) > 0:
        passes.append(VerdictItem("PASS", "成本鲁棒", "成本×2时 alpha 仍为正"))

    # --- 最终判定 ---
    if blocking_items:
        status = "BLOCKED"
    elif failures:
        status = "FAIL"
    elif warnings:
        status = "WARN"
    else:
        status = "PASS"

    return VerdictResult(status, blocking_items + failures + warnings + passes)
```

---

## E. Gate 坍缩检测 (Gate Collapse Detection)

当 Gate 权重长期集中在单一专家时，MoE 系统退化为单专家模型，失去路由多样性优势。

```python
import numpy as np

def check_gate_collapse(gate_weights_history: np.ndarray, threshold: float = 0.8) -> str | None:
    """
    gate_weights_history: shape (n_steps, n_experts)
    threshold: 单专家 EMA 权重超过此值视为坍缩
    """
    if gate_weights_history.ndim != 2:
        return None

    n_steps, n_experts = gate_weights_history.shape
    ema_alpha = 0.1
    ema = np.zeros_like(gate_weights_history)
    ema[0] = gate_weights_history[0]

    for t in range(1, n_steps):
        ema[t] = ema_alpha * gate_weights_history[t] + (1 - ema_alpha) * ema[t - 1]

    for expert_idx in range(n_experts):
        collapse_steps = np.sum(ema[:, expert_idx] > threshold)
        if collapse_steps > 0.5 * n_steps:
            return f"Gate坍缩: 专家 {expert_idx} EMA权重 > {threshold} 的步数占比 {collapse_steps/n_steps:.1%} > 50%"

    return None
```

---

## F. Bootstrap 显著性检验 (Bootstrap Significance Test)

通过重采样估计收益均值的置信区间，判断策略收益是否显著为正。

```python
import numpy as np

def bootstrap_confidence_interval(
    returns: np.ndarray,
    n_bootstrap: int = 1000,
    ci: float = 0.95,
    seed: int = 42,
) -> tuple[float, float]:
    """
    returns: 日度收益率序列
    n_bootstrap: 重采样次数
    ci: 置信水平
    返回: (下界, 上界)
    """
    rng = np.random.default_rng(seed)
    means = np.empty(n_bootstrap)

    for i in range(n_bootstrap):
        sample = rng.choice(returns, size=len(returns), replace=True)
        means[i] = np.mean(sample)

    alpha = 1.0 - ci
    lower = float(np.percentile(means, 100.0 * alpha / 2.0))
    upper = float(np.percentile(means, 100.0 * (1.0 - alpha / 2.0)))
    return (lower, upper)
```

**判定规则**：若 CI 下界 < 0 → 收益可能不显著为正，触发 WARN。

---

## G. 完整性能指标体系 (Performance Metrics)

### 核心收益指标

| 指标               | 计算方式                                    |
|--------------------|---------------------------------------------|
| `total_return`     | `(final_nw / initial_nw) - 1`              |
| `benchmark_return` | 买入持有收益率                               |
| `alpha`            | `total_return - benchmark_return`           |
| `max_drawdown`     | `max((peak - current) / peak)`              |
| `sharpe`           | 年化 Sharpe（√252 缩放）                    |
| `sortino`          | 年化 Sortino（仅下行偏差）                   |
| `calmar`           | 年化收益 / 最大回撤                          |

### 成本指标

| 指标             | 计算方式                        |
|------------------|---------------------------------|
| `turnover`       | 仓位变动绝对值之和               |
| `trade_cost`     | 总交易手续费                     |
| `funding_cost`   | 总资金费率成本                   |

### 暴露指标

| 指标              | 计算方式                       |
|-------------------|--------------------------------|
| `exposure`        | `mean(abs(position))`          |
| `long_exposure`   | `mean(max(position, 0))`       |
| `short_exposure`  | `mean(max(-position, 0))`      |

### 统计检验

| 指标                         | 说明                              |
|------------------------------|-----------------------------------|
| `bootstrap_confidence_interval` | 收益均值的 Bootstrap 置信区间   |

### 指标计算模板

```python
import numpy as np

def compute_performance_metrics(
    equity_curve: np.ndarray,
    positions: np.ndarray,
    benchmark_curve: np.ndarray,
    fee_rate: float = 0.0006,
    funding_rates: np.ndarray | None = None,
    risk_free_rate: float = 0.0,
) -> dict:
    n = len(equity_curve)
    daily_returns = np.diff(equity_curve) / equity_curve[:-1]

    total_return = equity_curve[-1] / equity_curve[0] - 1
    benchmark_return = benchmark_curve[-1] / benchmark_curve[0] - 1
    alpha = total_return - benchmark_return

    peak = np.maximum.accumulate(equity_curve)
    drawdowns = (peak - equity_curve) / peak
    max_drawdown = float(np.max(drawdowns))

    excess_returns = daily_returns - risk_free_rate / 252
    sharpe = float(np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252)) if np.std(excess_returns) > 0 else 0.0

    downside = excess_returns[excess_returns < 0]
    sortino = float(np.mean(excess_returns) / np.std(downside) * np.sqrt(252)) if len(downside) > 0 and np.std(downside) > 0 else 0.0

    annualized_return = (1 + total_return) ** (252 / max(n - 1, 1)) - 1
    calmar = annualized_return / max_drawdown if max_drawdown > 0 else 0.0

    position_changes = np.abs(np.diff(positions))
    turnover = float(np.sum(position_changes))
    trade_cost = float(turnover * fee_rate)

    funding_cost = 0.0
    if funding_rates is not None:
        funding_cost = float(np.sum(np.abs(positions[1:]) * funding_rates))

    exposure = float(np.mean(np.abs(positions[1:])))
    long_exposure = float(np.mean(np.maximum(positions[1:], 0)))
    short_exposure = float(np.mean(np.maximum(-positions[1:], 0)))

    ci_lower, ci_upper = bootstrap_confidence_interval(daily_returns)

    return {
        "total_return": total_return,
        "benchmark_return": benchmark_return,
        "alpha": alpha,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "turnover": turnover,
        "trade_cost": trade_cost,
        "funding_cost": funding_cost,
        "exposure": exposure,
        "long_exposure": long_exposure,
        "short_exposure": short_exposure,
        "bootstrap_ci_lower": ci_lower,
        "bootstrap_ci_upper": ci_upper,
    }
```

---

## 常见陷阱

1. **随机划分训练/测试集**：必须按时间顺序划分，随机划分会导致未来信息泄漏（look-ahead bias）
2. **不扫描 Gate Temperature**：不同时间段的最优温度可能不同，固定温度会导致路由次优
3. **仅在单一 OOS 期测试**：单一 OOS 期可能恰好适合策略，Walk-Forward 多折验证才能降低过拟合风险
4. **忽略随机基线**：不建立随机基线就无法区分策略技能与运气
5. **不测试成本敏感度**：策略在零成本假设下可能盈利，但真实成本下可能亏损
6. **接受单一 OOS 结果而无 Walk-Forward**：单一 OOS 结果可能存在幸存者偏差，需多折验证确认
7. **忽视 Gate 坍缩**：Gate 权重集中到单一专家时，MoE 退化为单模型，失去多样性优势
8. **Bootstrap CI 下界为负时仍声称显著**：CI 下界 < 0 意味着收益可能不显著为正，必须记录为 WARN
