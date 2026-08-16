# quant-trading-env

**名称**: quant-trading-env
**描述**: RL 交易环境 — 四重执行约束 + 成本建模 + Reward 设计 + 训练/推理一致性

---

## 何时使用

当用户需要以下任一场景时，激活此技能：

- 为 RL 交易策略创建 Gymnasium 交易环境
- 设计交易 Reward 函数（多组件加权、风格配置）
- 实现执行约束（迟滞、变速限制、冷却期、硬裁剪）
- 确保训练环境与实盘推理的行为一致性
- 构建观测空间与 Feature Mask 机制
- 成本建模（交易成本、资金费率、波动率目标杠杆）
- 排查训练/实盘行为不一致的问题

---

## A. 四重执行约束（Four-Piece Turnover Reduction Constraints）

四重约束是系统在实盘中保持稳定的核心创新。它们按严格顺序叠加，逐层过滤噪声交易、防止过快换仓、抑制震荡翻转、确保仓位边界安全。

### 约束详解

| 序号 | 名称 | 符号 | 作用 | 典型值 |
|------|------|------|------|--------|
| 1 | 迟滞（Hysteresis） | τ | \|target - current\| < τ → 不执行，过滤微噪声 | 0.25 |
| 2 | 变速限制（Slew-rate） | δ_max | 单步最大仓位变化量，防止全仓反转 | 0.15 |
| 3 | 冷却期（Cooldown） | N | 仓位符号翻转后强制归零 N 步，防止来回打脸 | 3 |
| 4 | 硬裁剪（Clip） | — | 仓位绝对边界 [-1, 1] | ±1.0 |

### 执行顺序

约束必须按 1→2→3→4 顺序施加，顺序不可调换：

1. **Clip** — 先裁剪目标仓位到合法范围
2. **Hysteresis** — 判断偏差是否超过迟滞阈值
3. **Slew-rate** — 限制单步变化幅度
4. **Cooldown** — 翻转冷却检查
5. **Final Clip** — 最终安全裁剪

### 核心实现（训练与实盘共享）

```python
import numpy as np

def apply_execution_constraints_core(
    target_pos: float,
    current_pos: float,
    last_flip_marker: int,
    current_marker: int,
    tau: float = 0.25,
    delta_max: float = 0.15,
    cooldown_window: int = 3,
) -> tuple[float, int, str]:
    """
    四重执行约束核心函数。

    训练环境与实盘交易必须调用同一函数，确保行为一致。

    Parameters
    ----------
    target_pos : float
        模型输出的目标仓位（未经约束处理）
    current_pos : float
        当前实际仓位
    last_flip_marker : int
        上次仓位符号翻转的标记（step 编号或 bar 编号）
    current_marker : int
        当前标记
    tau : float
        迟滞阈值
    delta_max : float
        单步最大仓位变化量
    cooldown_window : int
        冷却期步数

    Returns
    -------
    exec_pos : float
        经约束处理后的执行仓位
    new_flip_marker : int
        更新后的翻转标记
    reason : str
        约束触发原因（用于日志和调试）
    """
    reason = "normal"

    # 1. Clip 目标仓位
    target_pos = np.clip(target_pos, -1.0, 1.0)

    # 2. Hysteresis — 偏差不足则不执行
    if abs(target_pos - current_pos) < tau:
        target_pos = current_pos
        reason = "hysteresis"

    # 3. Slew-rate — 限制单步变化
    delta = np.clip(target_pos - current_pos, -delta_max, delta_max)
    cand_pos = current_pos + delta

    # 4. Cooldown — 翻转冷却
    new_flip_marker = last_flip_marker
    steps_since_flip = current_marker - last_flip_marker
    in_cooldown = steps_since_flip < cooldown_window

    current_sign = np.sign(current_pos)
    cand_sign = np.sign(cand_pos)
    wants_flip = (
        current_sign != 0
        and cand_sign != 0
        and cand_sign != current_sign
    )

    if in_cooldown and wants_flip:
        exec_pos = 0.0
        reason = "cooldown"
    else:
        exec_pos = cand_pos
        if wants_flip:
            new_flip_marker = current_marker
            reason = "flip"

    # 5. Final clip
    exec_pos = np.clip(exec_pos, -1.0, 1.0)

    return float(exec_pos), int(new_flip_marker), reason
```

### ⚠️ 关键原则

**训练环境与实盘交易必须调用同一个 `apply_execution_constraints_core()` 函数。** 任何不一致都会导致行为偏差（behavioral divergence），使训练结果在实盘中失效。

---

## B. 成本建模（Cost Modeling）

### 交易成本

```python
trade_cost = turnover * net_worth * k_single
```

- `turnover`: 仓位变化量 `|new_pos - old_pos|`
- `k_single`: 单边费率，OKX maker/taker 均值典型值 **0.08%**（0.0008）

### 资金费率（Funding Cost）

```python
funding_cost = abs(position) * net_worth * funding_daily
```

- `funding_daily`: 永续合约日资金费率典型值 **0.03%**（0.0003）
- **动态费率**: 若数据包含 `Funding_Rate` 列，使用实际费率替代固定值

```python
if "Funding_Rate" in df.columns:
    funding_rate = df.loc[current_idx, "Funding_Rate"]
else:
    funding_rate = funding_daily
```

### 波动率目标杠杆（Volatility Targeting Leverage）

根据当前波动率动态调整杠杆，使策略在不同波动率环境下保持一致的风险暴露：

```python
vol_scale = target_atr_pct / current_atr_pct
vol_scale = np.clip(vol_scale, vol_scale_min, vol_scale_max)
effective_position = base_position * vol_scale
```

- `target_atr_pct`: 目标 ATR 百分比（典型：3%）
- `current_atr_pct`: 当前 ATR 百分比
- **ATR 下限**: 防止极低波动率下过度加杠杆（典型：0.5%）
- **杠杆边界**: 典型 0.1x ~ 2.0x

```python
atr_floor_pct = 0.005
current_atr_pct = max(current_atr_pct, atr_floor_pct)
vol_scale = np.clip(target_atr_pct / current_atr_pct, 0.1, 2.0)
```

---

## C. Reward 函数设计（Reward Function Design）

### 多组件加权 Reward

```python
reward = (
    profile["return"]   * log_return
    + profile["sortino"]  * sortino_component
    - profile["drawdown"] * drawdown_penalty
    - profile["turnover"] * turnover_cost
)
```

### 组件定义

**log_return**: 带 floor 的安全对数收益

```python
log_return = np.log(max(net_worth / prev_net_worth, 1e-8))
```

**sortino_component**: 稳定上涨奖励（滚动 30 步窗口）

```python
rolling_returns = deque(maxlen=30)
downside = [r for r in rolling_returns if r < 0]
downside_std = np.std(downside) if downside else 1e-8
sortino = np.mean(rolling_returns) / downside_std
sortino_component = 0.05 * sortino if sortino > 0.5 else 0.0
```

**drawdown_penalty**: 回撤惩罚（DD > 5% 时触发）

```python
drawdown = (peak_net_worth - net_worth) / peak_net_worth
drawdown_penalty = drawdown * 0.5 if drawdown > 0.05 else 0.0
```

**turnover_cost**: 换仓成本直接惩罚

```python
turnover_cost = abs(new_pos - old_pos)
```

### Reward Profile 配置

不同 Profile 创造不同交易风格：

```python
REWARD_PROFILES = {
    "defensive": {
        "return": 1.00,
        "sortino": 1.20,
        "drawdown": 1.60,
        "turnover": 1.00,
    },
    "aggressive": {
        "return": 1.20,
        "sortino": 1.00,
        "drawdown": 0.80,
        "turnover": 0.80,
    },
    "balanced": {
        "return": 1.00,
        "sortino": 1.00,
        "drawdown": 1.00,
        "turnover": 1.00,
    },
    "hedge": {
        "return": 0.80,
        "sortino": 1.00,
        "drawdown": 1.80,
        "turnover": 1.20,
    },
}
```

| Profile | 适用场景 | 特点 |
|---------|----------|------|
| defensive | 熊市专家 | 高回撤惩罚(1.60)、高Sortino奖励(1.20) |
| aggressive | 趋势跟踪 | 高收益权重(1.20)、低回撤惩罚(0.80) |
| balanced | 通用 | 所有权重均衡(1.00) |
| hedge | 极端风控 | 极高回撤惩罚(1.80)、高换仓惩罚(1.20) |

### 附加 Reward Shaping 选项

**Regime 加权 Reward**: 在目标 regime 中强调 reward，在非目标 regime 中弱化

```python
if current_regime == target_regime:
    reward *= regime_weight
else:
    reward *= (1.0 / regime_weight)
```

**饱和惩罚（Saturation Penalty）**: 抑制持续满仓行为

```python
saturation_penalty = 0.0
if abs(position) > 0.9:
    saturation_steps += 1
    if saturation_steps > saturation_threshold:
        saturation_penalty = 0.01 * (saturation_steps - saturation_threshold)
```

**方向偏差惩罚（Directional Bias Penalty）**: 抑制长期单边持仓

```python
bias_penalty = 0.0
if consecutive_same_direction_steps > bias_threshold:
    bias_penalty = 0.005 * (consecutive_same_direction_steps - bias_threshold)
```

---

## D. 观测空间设计（Observation Space）

### 13 维连续向量

| 索引 | 名称 | 范围 | 说明 |
|------|------|------|------|
| 0 | pos | [-1, 1] | 当前仓位 |
| 1 | cooldown_remaining | [0, 1] | 冷却期剩余比例 |
| 2 | unrealized_pnl_pct | float | 未实现盈亏百分比 |
| 3 | nw_change_pct | float | 上一步净值变化 |
| 4 | Signal_Proba | [0, 1] | ML 信号概率 |
| 5 | RSI/100 | [0, 1] | 归一化 RSI |
| 6 | Rolling_Vol | float | 20 日滚动波动率 |
| 7 | MACD/100 | float | 归一化 MACD |
| 8 | BB_Width/1000 | float | 归一化布林带宽度 |
| 9 | Dist_SMA_200 | float | 距 200 日 SMA 距离 |
| 10 | ATR/Close | float | ATR 百分比 |
| 11 | Vol_Ratio | float | 成交量比率 |
| 12 | direction | {-1, 0, 1} | 当前仓位方向 |

### 归一化注意事项

- RSI 除以 100 归一化到 [0, 1]
- MACD 可除以 100 或除以 Close 价格
- BB_Width 可除以 1000 或除以 Close 价格
- ATR 除以 Close 得到百分比
- 所有特征应在训练前用 VecNormalize 统一归一化

---

## E. Feature Mask 机制

不同专家（Expert）看到观测空间的不同子集，实现专业化分工：

### Mask 定义

| 专家名 | Mask 索引 | 关注维度 |
|--------|-----------|----------|
| all | [0,1,2,3,4,5,6,7,8,9,10,11,12] | 全部 13 维 |
| trend | [0,3,4,5,7,9,10,12] | Signal/RSI/MACD/Dist_SMA200 |
| risk | [0,1,3,6,8,10,11,12] | Cooldown/Vol/BB_Width/ATR |
| carry | [0,3,4,6,10,11,12] | Signal/Vol/ATR/Vol_Ratio |
| switch | [0,1,3,4,6,7,11,12] | Cooldown/Signal/MACD/Vol_Ratio |

### 实现

```python
FEATURE_MASKS = {
    "all":    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    "trend":  [0, 3, 4, 5, 7, 9, 10, 12],
    "risk":   [0, 1, 3, 6, 8, 10, 11, 12],
    "carry":  [0, 3, 4, 6, 10, 11, 12],
    "switch": [0, 1, 3, 4, 6, 7, 11, 12],
}

def apply_feature_mask(obs: np.ndarray, mask_name: str) -> np.ndarray:
    """
    对观测向量施加 Feature Mask。
    被 mask 掉的维度填零，保留维度保持原值。
    """
    mask_indices = FEATURE_MASKS[mask_name]
    masked_obs = np.zeros_like(obs)
    masked_obs[mask_indices] = obs[mask_indices]
    return masked_obs
```

### 设计原则

- Mask 通过填零实现，保持观测向量维度不变（13 维），便于统一训练和推理
- 每个专家只关注与其策略相关的市场特征，减少噪声干扰
- Gate 网络通常使用 "all" mask，需要全局视角来做路由决策

---

## F. 训练/推理一致性保证

### 必须保持一致的组件

| 组件 | 训练端 | 推理端 | 一致性要求 |
|------|--------|--------|------------|
| 执行约束 | TradingEnv.step() | live_trading | 调用同一 apply_execution_constraints_core() |
| 观测归一化 | VecNormalize (训练时) | VecNormalize (加载) | 保存/加载同一 .pkl 文件 |
| 成本参数 | env 构造参数 | 实盘配置 | k_single、funding_daily 完全一致 |
| 观测空间 | env.observation_space | 推理时构建 | 维度、顺序、归一化方式一致 |
| Feature Mask | env 内部 | 推理时 | mask 索引集合一致 |

### VecNormalize 保存与加载

```python
from stable_baselines3.common.vec_env import VecNormalize

vec_env = VecNormalize(training_env)

vec_env.save("vec_normalize.pkl")

loaded_vec_env = VecNormalize.load("vec_normalize.pkl", eval_env)
loaded_vec_env.training = False
loaded_vec_env.norm_reward = False
```

### 一致性检查清单

1. ✅ `apply_execution_constraints_core()` 参数（tau, delta_max, cooldown_window）训练与实盘一致
2. ✅ VecNormalize 的 `.pkl` 文件在推理时正确加载，且 `training=False, norm_reward=False`
3. ✅ 成本参数 `k_single`、`funding_daily` 与交易所实际费率一致
4. ✅ 观测空间的特征顺序与训练时完全一致
5. ✅ Feature Mask 索引与训练时一致
6. ✅ ATR floor 和杠杆边界参数一致

---

## G. 常见陷阱（Common Pitfalls）

| 陷阱 | 后果 | 解决方案 |
|------|------|----------|
| 训练与实盘使用不同的约束逻辑 | 行为偏差，实盘表现与回测不符 | 共享 `apply_execution_constraints_core()` |
| 忘记保存 VecNormalize 状态 | 推理时观测分布不匹配 | 训练结束后立即保存 `.pkl` |
| 训练与实盘成本参数不同 | 训练结果不现实 | 统一参数来源（配置文件） |
| 未在约束前裁剪 action | 意外行为、越界仓位 | action 先 clip 到 [-1, 1] 再进约束 |
| Reward 中出现 NaN/Inf | 训练静默失败，loss 不下降 | log_return 加 floor，所有除法加 eps |
| 冷却期标记未正确传递 | 冷却逻辑失效 | 用 step/bar 编号作为 marker，确保单调递增 |
| VecNormalize 加载后仍 training=True | 推理时持续更新归一化统计 | 显式设置 `training=False, norm_reward=False` |
| 波动率极低时未设 ATR floor | 过度加杠杆 | `current_atr_pct = max(current_atr_pct, 0.005)` |

---

## H. 代码模板

### 模板 1: apply_execution_constraints_core()

见上方 A 节完整实现。

### 模板 2: TradingEnv 类骨架

```python
import gymnasium as gym
import numpy as np
from gymnasium import spaces
from collections import deque


class TradingEnv(gym.Env):
    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        df,
        reward_profile: str = "balanced",
        feature_mask: str = "all",
        tau: float = 0.25,
        delta_max: float = 0.15,
        cooldown_window: int = 3,
        k_single: float = 0.0008,
        funding_daily: float = 0.0003,
        target_atr_pct: float = 0.03,
        atr_floor_pct: float = 0.005,
        vol_scale_min: float = 0.1,
        vol_scale_max: float = 2.0,
        **kwargs,
    ):
        super().__init__()
        self.df = df
        self.profile = REWARD_PROFILES[reward_profile]
        self.feature_mask = FEATURE_MASKS[feature_mask]
        self.tau = tau
        self.delta_max = delta_max
        self.cooldown_window = cooldown_window
        self.k_single = k_single
        self.funding_daily = funding_daily
        self.target_atr_pct = target_atr_pct
        self.atr_floor_pct = atr_floor_pct
        self.vol_scale_min = vol_scale_min
        self.vol_scale_max = vol_scale_max

        self.action_space = spaces.Box(
            low=-1.0, high=1.0, shape=(1,), dtype=np.float32
        )
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(13,), dtype=np.float32
        )

        self._reset_state()

    def _reset_state(self):
        self.current_step = 0
        self.position = 0.0
        self.net_worth = 1.0
        self.peak_net_worth = 1.0
        self.last_flip_marker = -self.cooldown_window
        self.rolling_returns = deque(maxlen=30)

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self._reset_state()
        obs = self._get_obs()
        info = {}
        return obs, info

    def step(self, action):
        target_pos = float(np.clip(action[0], -1.0, 1.0))

        exec_pos, self.last_flip_marker, reason = apply_execution_constraints_core(
            target_pos=target_pos,
            current_pos=self.position,
            last_flip_marker=self.last_flip_marker,
            current_marker=self.current_step,
            tau=self.tau,
            delta_max=self.delta_max,
            cooldown_window=self.cooldown_window,
        )

        turnover = abs(exec_pos - self.position)
        self.position = exec_pos

        trade_cost = turnover * self.net_worth * self.k_single

        funding_rate = self.funding_daily
        if "Funding_Rate" in self.df.columns:
            funding_rate = self.df.iloc[self.current_step].get(
                "Funding_Rate", self.funding_daily
            )
        funding_cost = abs(self.position) * self.net_worth * funding_rate

        price_change = self._get_price_change()
        pnl = self.position * price_change * self.net_worth

        prev_net_worth = self.net_worth
        self.net_worth = self.net_worth + pnl - trade_cost - funding_cost
        self.peak_net_worth = max(self.peak_net_worth, self.net_worth)

        reward = self._compute_reward(prev_net_worth, turnover)

        self.current_step += 1
        terminated = self.net_worth <= 0.0
        truncated = self.current_step >= len(self.df) - 1

        obs = self._get_obs()
        info = {
            "net_worth": self.net_worth,
            "position": self.position,
            "turnover": turnover,
            "reason": reason,
            "trade_cost": trade_cost,
            "funding_cost": funding_cost,
        }

        return obs, reward, terminated, truncated, info

    def _compute_reward(self, prev_nw, turnover):
        log_return = np.log(max(self.net_worth / prev_nw, 1e-8))
        self.rolling_returns.append(log_return)

        mean_ret = np.mean(self.rolling_returns)
        downside = [r for r in self.rolling_returns if r < 0]
        downside_std = np.std(downside) if downside else 1e-8
        sortino = mean_ret / downside_std
        sortino_component = 0.05 * sortino if sortino > 0.5 else 0.0

        drawdown = (self.peak_net_worth - self.net_worth) / self.peak_net_worth
        drawdown_penalty = drawdown * 0.5 if drawdown > 0.05 else 0.0

        turnover_cost = turnover

        reward = (
            self.profile["return"] * log_return
            + self.profile["sortino"] * sortino_component
            - self.profile["drawdown"] * drawdown_penalty
            - self.profile["turnover"] * turnover_cost
        )

        if np.isnan(reward) or np.isinf(reward):
            reward = 0.0

        return float(reward)

    def _get_obs(self):
        row = self.df.iloc[self.current_step]
        obs = np.array(
            [
                self.position,
                self._cooldown_remaining(),
                self._unrealized_pnl_pct(),
                self._nw_change_pct(),
                row.get("Signal_Proba", 0.5),
                row.get("RSI", 50) / 100.0,
                row.get("Rolling_Vol", 0.0),
                row.get("MACD", 0) / 100.0,
                row.get("BB_Width", 0) / 1000.0,
                row.get("Dist_SMA_200", 0.0),
                row.get("ATR", 0) / row.get("Close", 1),
                row.get("Vol_Ratio", 1.0),
                np.sign(self.position),
            ],
            dtype=np.float32,
        )
        masked = np.zeros_like(obs)
        masked[self.feature_mask] = obs[self.feature_mask]
        return masked

    def _cooldown_remaining(self):
        steps_since = self.current_step - self.last_flip_marker
        remaining = max(0, self.cooldown_window - steps_since)
        return remaining / max(self.cooldown_window, 1)

    def _unrealized_pnl_pct(self):
        return 0.0

    def _nw_change_pct(self):
        return 0.0

    def _get_price_change(self):
        if self.current_step + 1 < len(self.df):
            curr = self.df.iloc[self.current_step]["Close"]
            next_ = self.df.iloc[self.current_step + 1]["Close"]
            return (next_ - curr) / curr
        return 0.0
```

### 模板 3: Reward Profile 配置

```python
REWARD_PROFILES = {
    "defensive": {
        "return": 1.00,
        "sortino": 1.20,
        "drawdown": 1.60,
        "turnover": 1.00,
    },
    "aggressive": {
        "return": 1.20,
        "sortino": 1.00,
        "drawdown": 0.80,
        "turnover": 0.80,
    },
    "balanced": {
        "return": 1.00,
        "sortino": 1.00,
        "drawdown": 1.00,
        "turnover": 1.00,
    },
    "hedge": {
        "return": 0.80,
        "sortino": 1.00,
        "drawdown": 1.80,
        "turnover": 1.20,
    },
}
```

### 模板 4: Feature Mask 实现

```python
FEATURE_MASKS = {
    "all":    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    "trend":  [0, 3, 4, 5, 7, 9, 10, 12],
    "risk":   [0, 1, 3, 6, 8, 10, 11, 12],
    "carry":  [0, 3, 4, 6, 10, 11, 12],
    "switch": [0, 1, 3, 4, 6, 7, 11, 12],
}


def apply_feature_mask(obs: np.ndarray, mask_name: str) -> np.ndarray:
    mask_indices = FEATURE_MASKS[mask_name]
    masked_obs = np.zeros_like(obs)
    masked_obs[mask_indices] = obs[mask_indices]
    return masked_obs
```

---

## I. 实盘集成检查清单

在将训练好的模型部署到实盘前，逐项确认：

- [ ] `apply_execution_constraints_core()` 的参数与训练时完全一致
- [ ] VecNormalize `.pkl` 文件已加载，且 `training=False, norm_reward=False`
- [ ] `k_single` 与交易所实际费率一致
- [ ] `funding_daily` 与永续合约实际费率一致（或使用动态 Funding_Rate）
- [ ] 观测空间 13 维特征顺序与训练时一致
- [ ] Feature Mask 索引与训练时一致
- [ ] ATR floor 已设置（防止极低波动率下过度杠杆）
- [ ] 杠杆边界 `vol_scale_min/max` 与风控要求一致
- [ ] Reward 中无 NaN/Inf（log_return 有 floor，除法有 eps）
- [ ] 冷却期 marker 使用单调递增的 bar 编号
