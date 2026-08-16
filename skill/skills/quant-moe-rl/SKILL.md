---
name: quant-moe-rl
description: MoE 混合专家 RL 决策 — 门控路由 + 专家特化 + 多阶段训练 + 正则化
version: 1.0.0
language: zh-CN
---

# quant-moe-rl: MoE 混合专家 RL 决策系统

## 何时使用

当用户需要以下任一场景时，激活本技能：

- 构建多专家自适应交易系统，在不同市场状态下切换策略
- 实现门控路由（Gate Routing）机制，动态分配专家权重
- 设计特化 RL 专家（defensive / volatility / carry / fast-adapt 等）
- 训练 Mixture-of-Experts 强化学习模型用于金融决策
- 处理市场状态切分、专家配置管理、温度参数扫描等 MoE 工程问题
- 从现有交易系统提取可迁移的 MoE-RL 模式

---

## A. 专家特化设计 (Expert Specialization)

### 市场状态切分

使用 20 日动量（ROC_20）和 ATR% 对市场状态进行分类，基于分位数切分：

| 状态 | 切分条件 | 含义 |
|------|----------|------|
| `bull` | momentum > 65th percentile | 牛市：强势上涨 |
| `bear` | momentum < 35th percentile | 熊市：持续下跌 |
| `range` | \|momentum\| < 40th percentile | 震荡：无明显趋势 |
| `high_vol` | ATR% > 70th percentile | 高波动：风险加大 |
| `low_vol` | ATR% < 30th percentile | 低波动：适合carry |

关键原则：

- 每个专家**仅**在自己对应的市场切片上训练 → 强制特化
- 若切片为空，回退使用完整数据集
- 切片之间允许重叠（如 `bear` 和 `high_vol` 可同时满足），这有助于专家在边界区域获得经验

### 专家独立配置

每个专家拥有独立的五元配置：

1. **Algorithm**: PPO（稳定，适用大多数场景）、SAC（连续动作，适合对冲）、A2C（快速，适合频繁切换）
2. **Data slice**: 训练时使用的市场状态切片
3. **Feature mask**: 专家可观测的特征维度子集
4. **Reward profile**: 奖励组件加权（return / sortino / drawdown / turnover）
5. **Training timesteps**: 典型值 PPO 150K，SAC 180K

### 专家设计模板

| 专家 | 算法 | 切片 | 特征掩码 | 奖励配置 (return/sortino/drawdown/turnover) |
|------|------|------|----------|---------------------------------------------|
| 防守型 (Defensive) | PPO | bear | risk | 1.0 / 1.20 / **1.60** / 0.0 |
| 波动型 (Volatility) | PPO | high_vol | risk | 1.0 / 1.10 / **1.50** / 0.0 |
| Carry型 | PPO | low_vol | carry | 1.0 / 1.00 / 1.00 / 1.00 |
| 快适应型 (Fast-adapt) | SAC | range | switch | 1.0 / 0.90 / **1.10** / 0.0 |

设计要点：

- 防守型和波动型专家的 drawdown 权重最高（1.60 / 1.50），强化风险规避
- Carry 型使用均衡权重，关注稳定收益
- 快适应型使用 SAC 算法，适合在震荡区间快速调整仓位
- 特征掩码（risk / carry / switch）限制专家只能看到与其策略相关的观测维度，避免信息冗余

---

## B. 门控路由机制 (Gate Routing)

### 架构

```
obs (13-dim)
  │
  ▼
Gate PPO Network
  │
  ▼
logits (N-dim)          ← N = 专家数量
  │
  ▼
softmax(logits / τ)     ← τ = 温度参数
  │
  ▼
weights w = [w₁, w₂, ..., wₙ]
  │
  ├─→ Expert₁: masked_obs → action a₁ ∈ [-1, 1]
  ├─→ Expert₂: masked_obs → action a₂ ∈ [-1, 1]
  ├─→ ...
  └─→ Expertₙ: masked_obs → action aₙ ∈ [-1, 1]
         │
         ▼
  a_mix = Σ(wᵢ × aᵢ), clip to [-1, 1]
         │
         ▼
  TradingEnv 执行约束 → 最终仓位
```

### 门控奖励函数

```python
gate_reward = env_reward
            - load_balance_coef × balance_penalty   # 默认 coef=0.02
            + diversity_coef × diversity_bonus       # 默认 coef=0.01
```

其中：

- `balance_penalty = MSE(ema_weights, uniform_distribution)` — 防止单一专家主导
- `diversity_bonus = std(expert_actions)` — 鼓励专家产生差异化动作
- `ema_weights` 使用指数移动平均平滑权重分布，避免瞬时波动

### 温度参数 (Temperature)

温度 τ 控制门控路由的决策风格：

| 温度 | 效果 | 适用场景 |
|------|------|----------|
| 低 (0.5) | 果断，集中权重于主导专家 | 趋势明确时 |
| 中 (1.0) | 均衡 | 默认起点 |
| 高 (2.0) | 分散，权重更均匀 | 不确定性高时 |

关键实践：

- 最优温度随市场周期变化 → 必须在 Walk-Forward 中扫描
- 典型扫描范围：`[0.5, 0.6, 0.68, 0.8, 1.0, 1.5, 2.0]`
- 温度是 MoE 系统中最敏感的超参数之一，直接影响专家协作效果

---

## C. 三阶段训练范式 (Three-Stage Training)

### Stage 1 — 专家预训练

- 每个专家**独立**在自己的市场切片上训练
- 使用各自的算法（PPO/SAC/A2C）、特征掩码、奖励配置
- 保存 `model.zip` + `vec_normalize.pkl`（每个专家一份）
- 典型规模：4-8 个专家，总耗时约 12 分钟

### Stage 2 — 门控训练

- **冻结**所有专家权重（不更新）
- 在**完整**训练数据（非切片）上训练 Gate PPO 网络
- Gate 学习将观测路由到合适的专家
- 保存 `gate_model.zip` + `gate_vec_normalize.pkl`
- 典型耗时：约 5 分钟

### Stage 3 — 联合微调（可选）

- 交替迭代：根据 Gate 的 `usage_ema` 微调专家，然后重新训练 Gate
- 读取 Gate 的 `usage_ema` 来重新分配专家微调步数
- 可进行多轮迭代
- 当前为可选阶段；**两阶段是生产基线**

训练流程图：

```
Stage 1: Expert Pretraining
  E1 (PPO, bull)  ──→ model.zip + vec_normalize.pkl
  E2 (PPO, bear)  ──→ model.zip + vec_normalize.pkl
  E3 (PPO, range) ──→ model.zip + vec_normalize.pkl
  E4 (SAC, high_vol) ──→ model.zip + vec_normalize.pkl
  ...

Stage 2: Gate Training (experts FROZEN)
  Full data ──→ Gate PPO ──→ gate_model.zip + gate_vec_normalize.pkl

Stage 3: Joint Fine-tuning (OPTIONAL)
  Loop:
    Read gate.usage_ema → redistribute expert finetune steps
    Finetune experts → retrain gate
    Check convergence
```

---

## D. 正则化 (Regularization)

### 负载均衡惩罚 (Load Balance Penalty)

- 目的：防止单一专家主导决策
- 公式：`balance_penalty = MSE(ema_weights, [1/N, 1/N, ..., 1/N])`
- 系数：0.02（小但有效）
- 无此惩罚时，Gate 倾向于将所有权重分配给表现最好的单个专家

### 多样性奖励 (Diversity Bonus)

- 目的：鼓励专家产生不同的动作
- 公式：`diversity_bonus = std(expert_actions)`
- 系数：0.01
- 无此奖励时，专家可能收敛到相似策略，MoE 退化为单模型

### 正则化缺失的后果

| 缺失项 | 典型后果 |
|--------|----------|
| 无 Load Balance | Gate 坍缩至单专家，MoE 退化为单模型 |
| 无 Diversity Bonus | 专家动作趋同，融合无增益 |
| 两者皆无 | 训练不稳定，专家利用率极不均衡 |

---

## E. 专家配置 YAML 模板

```yaml
experts:
  - expert_id: E2_PPO_bear_drawdown
    algorithm: ppo
    seed: 42
    data_slice: bear
    feature_mask: risk
    reward_profile:
      return: 1.0
      sortino: 1.20
      drawdown: 1.60
      turnover: 0.0
    timesteps: 150000

  - expert_id: E3_PPO_range_carry
    algorithm: ppo
    seed: 42
    data_slice: low_vol
    feature_mask: carry
    reward_profile:
      return: 1.0
      sortino: 1.00
      drawdown: 1.00
      turnover: 1.00
    timesteps: 150000

  - expert_id: E5_PPO_highvol_defensive
    algorithm: ppo
    seed: 42
    data_slice: high_vol
    feature_mask: risk
    reward_profile:
      return: 1.0
      sortino: 1.10
      drawdown: 1.50
      turnover: 0.0
    timesteps: 150000

  - expert_id: E7_SAC_fast_adapt
    algorithm: sac
    seed: 42
    data_slice: range
    feature_mask: switch
    reward_profile:
      return: 1.0
      sortino: 0.90
      drawdown: 1.10
      turnover: 0.0
    timesteps: 180000
```

### Manifest 解析规则

- 使用 `ExpertSpec` dataclass 解析每条专家配置
- `resolve_feature_mask()`: 将命名掩码（risk / carry / switch）解析为具体特征索引列表
- `_validate_unique_ids()`: 检查 expert_id 去重，重复则报错
- 缺失字段使用合理默认值（如 seed=42, timesteps=150000）

---

## F. MoE 推理流程

1. 加载 N 个专家模型 + 各自的 VecNormalize 状态
2. 加载 Gate 模型 + Gate VecNormalize
3. 对每个时间步：
   - Gate 接收 obs → logits → softmax → weights
   - 每个专家接收 masked_obs → 独立推理 → action ∈ [-1, 1]
   - 加权融合：`a_mix = Σ(wᵢ × aᵢ)`
   - 应用执行约束 → 最终仓位
4. 输出：returns, drawdown, sharpe, gate usage, expert contribution

---

## 常见陷阱 (Common Pitfalls)

| 陷阱 | 后果 | 解决方案 |
|------|------|----------|
| 不使用特征掩码 | 专家看到相同信息，无法特化 | 为每个专家配置不同的 feature_mask |
| 所有专家在完整数据上训练 | 无市场状态特化，MoE 退化为集成 | 严格按 data_slice 切分训练数据 |
| 忘记负载均衡惩罚 | Gate 坍缩至单专家 | 始终添加 load_balance_coef ≥ 0.02 |
| 不扫描温度参数 | 路由次优 | 在 Walk-Forward 中扫描 [0.5, 2.0] |
| Stage 3 无收敛检查 | 训练不稳定 | 监控 gate reward 和 expert usage 变化 |
| 专家数量过多 | 过拟合 + 训练成本高 | 4-8 个专家通常足够 |
| 切片数据量不足 | 专家欠拟合 | 切片为空时回退完整数据集 |
| 忽略 VecNormalize 状态 | 推理时观测分布不匹配 | 保存并加载每个专家的 vec_normalize.pkl |

---

## 代码模板

### 1. 专家 Manifest YAML + 解析器

```python
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import yaml

FEATURE_MASKS = {
    "risk": [0, 1, 2, 5, 6, 7],
    "carry": [0, 1, 3, 4, 8, 9],
    "switch": [0, 1, 2, 3, 4, 10, 11, 12],
    "full": list(range(13)),
}

@dataclass
class ExpertSpec:
    expert_id: str
    algorithm: str = "ppo"
    seed: int = 42
    data_slice: str = "full"
    feature_mask: str = "full"
    reward_profile: Dict[str, float] = field(default_factory=lambda: {
        "return": 1.0, "sortino": 1.0, "drawdown": 1.0, "turnover": 0.0
    })
    timesteps: int = 150000

    def resolve_feature_mask(self) -> List[int]:
        if self.feature_mask in FEATURE_MASKS:
            return FEATURE_MASKS[self.feature_mask]
        raise ValueError(f"未知特征掩码: {self.feature_mask}")

def load_expert_manifest(path: str) -> List[ExpertSpec]:
    with open(path, "r") as f:
        raw = yaml.safe_load(f)
    specs = [ExpertSpec(**e) for e in raw["experts"]]
    _validate_unique_ids(specs)
    return specs

def _validate_unique_ids(specs: List[ExpertSpec]) -> None:
    ids = [s.expert_id for s in specs]
    if len(ids) != len(set(ids)):
        dupes = [x for x in ids if ids.count(x) > 1]
        raise ValueError(f"重复 expert_id: {set(dupes)}")
```

### 2. 市场状态切分函数

```python
import pandas as pd
import numpy as np

def slice_by_regime(df: pd.DataFrame, regime: str) -> pd.DataFrame:
    roc20 = df["ROC_20"]
    atr_pct = df["ATR_pct"]

    roc_q35 = roc20.quantile(0.35)
    roc_q40 = roc20.quantile(0.40)
    roc_q65 = roc20.quantile(0.65)
    atr_q30 = atr_pct.quantile(0.30)
    atr_q70 = atr_pct.quantile(0.70)

    masks = {
        "bull": roc20 > roc_q65,
        "bear": roc20 < roc_q35,
        "range": roc20.abs() < roc_q40,
        "high_vol": atr_pct > atr_q70,
        "low_vol": atr_pct < atr_q30,
    }

    if regime == "full":
        return df

    mask = masks.get(regime)
    if mask is None:
        raise ValueError(f"未知市场状态: {regime}")

    sliced = df[mask].copy()
    if len(sliced) == 0:
        return df

    return sliced
```

### 3. 门控推理（含温度）

```python
import numpy as np
from typing import List, Tuple

def gate_inference(
    obs: np.ndarray,
    gate_model,
    gate_vec_norm,
    expert_models: List,
    expert_vec_norms: List,
    feature_masks: List[List[int]],
    temperature: float = 1.0,
) -> Tuple[float, np.ndarray]:
    norm_obs = gate_vec_norm.normalize_obs(obs.reshape(1, -1)).flatten()
    logits = gate_model.predict(norm_obs.reshape(1, -1), deterministic=True)[0]

    weights = _softmax(logits / temperature)

    actions = []
    for expert, vec_norm, mask in zip(expert_models, expert_vec_norms, feature_masks):
        masked = obs[mask]
        normed = vec_norm.normalize_obs(masked.reshape(1, -1)).flatten()
        a = expert.predict(normed.reshape(1, -1), deterministic=True)[0]
        actions.append(float(a))

    actions_arr = np.array(actions)
    a_mix = np.dot(weights, actions_arr)
    a_mix = np.clip(a_mix, -1.0, 1.0)

    return float(a_mix), weights

def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - np.max(x))
    return e / e.sum()
```

### 4. 三阶段训练编排

```python
from stable_baselines3 import PPO, SAC
from typing import List

def stage1_train_experts(specs: List[ExpertSpec], env_factory) -> None:
    for spec in specs:
        df = load_data()
        df_slice = slice_by_regime(df, spec.data_slice)
        env = env_factory(df_slice, spec.reward_profile, spec.feature_mask)

        algo_cls = {"ppo": PPO, "sac": SAC, "a2c": A2C}[spec.algorithm]
        model = algo_cls("MlpPolicy", env, seed=spec.seed, verbose=1)
        model.learn(total_timesteps=spec.timesteps)

        model.save(f"models/{spec.expert_id}/model.zip")
        env.get_vec_normalize_env().save(f"models/{spec.expert_id}/vec_normalize.pkl")

def stage2_train_gate(specs: List[ExpertSpec], env_factory) -> None:
    expert_models, expert_vec_norms, feature_masks = [], [], []
    for spec in specs:
        model = ...  # 加载专家模型
        expert_models.append(model)
        expert_vec_norms.append(...)
        feature_masks.append(spec.resolve_feature_mask())

    df = load_data()
    gate_env = MoEGateEnv(
        df=df,
        expert_models=expert_models,
        expert_vec_norms=expert_vec_norms,
        feature_masks=feature_masks,
        load_balance_coef=0.02,
        diversity_coef=0.01,
    )

    gate_model = PPO("MlpPolicy", gate_env, seed=42, verbose=1)
    gate_model.learn(total_timesteps=200000)

    gate_model.save("models/gate/gate_model.zip")
    gate_env.get_vec_normalize_env().save("models/gate/gate_vec_normalize.pkl")

def stage3_joint_finetune(specs, env_factory, rounds: int = 2) -> None:
    for rnd in range(rounds):
        usage_ema = read_gate_usage_ema()
        for spec in specs:
            finetune_steps = int(spec.timesteps * 0.1 * usage_ema.get(spec.expert_id, 0.2))
            finetune_expert(spec, env_factory, finetune_steps)
        stage2_train_gate(specs, env_factory)
        if check_convergence():
            break
```

---

## 关键参数速查

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `load_balance_coef` | 0.02 | 负载均衡惩罚系数 |
| `diversity_coef` | 0.01 | 多样性奖励系数 |
| `temperature` | 1.0 | 门控路由温度 |
| `temperature_scan` | [0.5, 0.6, 0.68, 0.8, 1.0, 1.5, 2.0] | 温度扫描范围 |
| PPO timesteps | 150,000 | PPO 专家训练步数 |
| SAC timesteps | 180,000 | SAC 专家训练步数 |
| Gate timesteps | 200,000 | 门控网络训练步数 |
| 专家数量 | 4-8 | 推荐范围 |
| ROC 分位数 | 35/40/65 | 牛/熊/震荡切分阈值 |
| ATR% 分位数 | 30/70 | 低/高波动切分阈值 |
