# quant-feature-engineering

## Description

量化特征工程 — 防未来函数技术指标管线 + 数据校验 + 信号预测器集成

## When to Use

当用户需要为任意金融时间序列数据（加密货币、股票、期货）构建特征工程管线、将 ML 信号预测器集成到 RL 观察空间、或实现防 look-ahead bias 的数据处理时，使用此 skill。

典型触发场景：
- 构建 OHLCV → 技术指标 → 特征矩阵的管线
- 在强化学习环境中集成 XGBoost 信号作为观察维度
- 对金融数据做异常检测与清洗
- 需要严格时间对齐的回测特征生成
- 多资产参数化配置管理

---

## A. 防 Look-Ahead Bias 的 shift(1) 策略

### 核心原则

**所有滚动指标计算完成后必须 shift(1)**，确保 t 时刻的决策仅使用 t-1 及更早的数据。这会造成 1 天滞后，但完全杜绝未来函数。

### 为什么必须 shift(1)

| 场景 | 不 shift | shift(1) |
|------|---------|----------|
| t 日 RSI | 使用了 t 日 close，决策时 t 日收盘价尚未产生 | 使用 t-1 日 close 计算，t 日开盘即可获得 |
| t 日 MACD | 同上，含未来信息 | 安全 |
| t 日 ATR | 使用了 t 日 high/low/close | 使用 t-1 日数据，安全 |

### 实现范式

```python
import numpy as np
import pandas as pd

# 第一步：对原始价格序列做 shift(1)
close_prev = df['Close'].shift(1)
high_prev = df['High'].shift(1)
low_prev = df['Low'].shift(1)
close_prev2 = df['Close'].shift(2)  # ATR 的 TR 计算需要

# 第二步：在 shifted 序列上计算所有指标
rsi = compute_rsi(close_prev, window=14)
macd_line, signal_line, hist = compute_macd(close_prev, 12, 26, 9)
atr = compute_atr(high_prev, low_prev, close_prev2, window=14)

# 第三步：Log Return 天然带 shift
log_ret = np.log(df['Close'] / df['Close'].shift(1))  # 等价于 log(close_t / close_{t-1})
```

### 滞后特征的额外 shift

```python
# RSI 的 lag 特征需要在已 shift 的 RSI 上再做 shift
df['RSI'] = compute_rsi(close_prev, window=14)  # 本身已 shift(1)
df['RSI_Lag1'] = df['RSI'].shift(1)  # 实际使用 t-2 数据
df['RSI_Lag2'] = df['RSI'].shift(2)  # 实际使用 t-3 数据
df['RSI_Lag3'] = df['RSI'].shift(3)  # 实际使用 t-4 数据
```

### ATR 的 shift 细节

ATR 的 True Range 需要用到前一日收盘价，因此需要额外注意：

```python
# TR = max(H - L, |H - C_prev|, |L - C_prev|)
# 如果 H/L/C 都已经 shift(1)，则 C_prev 应该 shift(2)
high_prev = df['High'].shift(1)
low_prev = df['Low'].shift(1)
close_prev2 = df['Close'].shift(2)  # 注意是 shift(2)

tr = pd.concat([
    high_prev - low_prev,
    (high_prev - close_prev2).abs(),
    (low_prev - close_prev2).abs()
], axis=1).max(axis=1)

atr = tr.rolling(window=14).mean()
```

---

## B. 技术指标四维体系

### 趋势维度 (Trend)

| 指标 | 参数 | 计算方式 | 归一化 |
|------|------|---------|--------|
| RSI | window=14 | Wilder's RSI on shifted close | 原始 [0, 100] |
| MACD | fast=12, slow=26, signal=9 | EMA 差值 | 原始值，不归一化 |
| SMA_50 | window=50 | 简单移动平均 | 原始值 |
| SMA_200 | window=200 | 简单移动平均 | 原始值 |
| Dist_SMA_200 | — | (Close - SMA_200) / SMA_200 | 百分比，天然归一化 |
| ROC_3 | period=3 | (Close - Close_{t-3}) / Close_{t-3} | 百分比 |
| ROC_5 | period=5 | 同上 | 百分比 |
| ROC_10 | period=10 | 同上 | 百分比 |

### 波动率维度 (Volatility)

| 指标 | 参数 | 计算方式 | 归一化 |
|------|------|---------|--------|
| ATR | window=14 | TR rolling mean on shifted H/L/C | 原始值 |
| BB_Upper | window=20, std=2 | SMA + 2σ | 原始值 |
| BB_Lower | window=20, std=2 | SMA - 2σ | 原始值 |
| BB_Width | — | (Upper - Lower) / SMA | 百分比，天然归一化 |
| Rolling_Vol | window=20 | log returns rolling std * sqrt(365) | 年化波动率 |
| Volatility_Regime | — | Rolling_Vol 的百分位排名 (rolling 252) | [0, 1] |

### 成交量维度 (Volume)

| 指标 | 参数 | 计算方式 | 归一化 |
|------|------|---------|--------|
| Vol_Ratio | window=20 | Volume / Volume_SMA | 比率 |
| Volume_SMA | window=20 | Volume 滚动均值 | 原始值 |

### 动量维度 (Momentum)

| 指标 | 参数 | 计算方式 | 归一化 |
|------|------|---------|--------|
| Log_Returns | — | log(Close_t / Close_{t-1}) | 天然归一化 |
| Ret_Lag_1 | lag=1 | Log_Returns.shift(1) | 天然归一化 |
| Ret_Lag_2 | lag=2 | Log_Returns.shift(2) | 天然归一化 |
| Ret_Lag_3 | lag=3 | Log_Returns.shift(3) | 天然归一化 |
| RSI_Lag_1 | lag=1 | RSI.shift(1) | [0, 100] |
| RSI_Lag_2 | lag=2 | RSI.shift(2) | [0, 100] |
| RSI_Lag_3 | lag=3 | RSI.shift(3) | [0, 100] |
| Range_Pct | — | (High - Low) / Close | 百分比 |

---

## C. 资产参数 Profile 模式

### 设计思想

不同资产（BTC vs ETH vs 山寨币）的波动率、流动性、参数敏感度差异巨大。使用 frozen dataclass 将特征参数与环境参数封装为不可变配置，通过 PROFILE_MAP 实现资产级别的参数查找。

### FeatureProfile

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class FeatureProfile:
    rsi_window: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bb_window: int = 20
    bb_std: float = 2.0
    atr_window: int = 14
    sma_fast: int = 50
    sma_slow: int = 200
    volume_window: int = 20
    rolling_vol_window: int = 20
```

### EnvProfile

```python
@dataclass(frozen=True)
class EnvProfile:
    atr_floor: float = 1.0
    vol_scale_min: float = 0.3
    vol_scale_max: float = 3.0
    target_atr_pct: float = 0.02
    tau: float = 0.005
    delta_max: float = 0.05
    cooldown_n: int = 3
    k_single: float = 1.0
    funding_daily: float = 0.0001
```

### AssetProfile 与 PROFILE_MAP

```python
@dataclass(frozen=True)
class AssetProfile:
    key: str
    feature: FeatureProfile
    env: EnvProfile

BTC_PROFILE = AssetProfile(
    key="BTC",
    feature=FeatureProfile(rsi_window=14, atr_window=14, bb_window=20),
    env=EnvProfile(atr_floor=500.0, target_atr_pct=0.015, delta_max=0.03),
)

ETH_PROFILE = AssetProfile(
    key="ETH",
    feature=FeatureProfile(rsi_window=14, atr_window=14, bb_window=20),
    env=EnvProfile(atr_floor=20.0, target_atr_pct=0.02, delta_max=0.05),
)

ALT_PROFILE = AssetProfile(
    key="ALT",
    feature=FeatureProfile(rsi_window=14, atr_window=14, bb_window=20),
    env=EnvProfile(atr_floor=0.5, target_atr_pct=0.04, delta_max=0.10, cooldown_n=5),
)

PROFILE_MAP: dict[str, AssetProfile] = {
    "BTC": BTC_PROFILE,
    "ETH": ETH_PROFILE,
    "SOL": ALT_PROFILE,
    "DOGE": ALT_PROFILE,
}

def infer_asset_key(symbol: str) -> str:
    """灵活匹配资产 key：支持 'BTCUSDT', 'BTC-USD', 'btc' 等格式"""
    upper = symbol.upper()
    for key in PROFILE_MAP:
        if key in upper:
            return key
    return "ALT"

def get_profile(symbol: str) -> AssetProfile:
    return PROFILE_MAP[infer_asset_key(symbol)]
```

---

## D. 数据校验分级处理模式

### Level 1 — WARN（20%–50% 单 bar 变化）

- **判断**：可能是真实极端行情（闪崩、暴涨），保留数据但记录警告
- **处理**：不修改数据，输出 WARN 日志，标记 bar 索引

### Level 2 — ERROR（>50% 单 bar 变化）

- **判断**：极大概率是脏数据（交易所异常、API 错误），需要修复
- **处理**：标记为 NaN，然后 ffill 向前填充修复

### 零值/负值处理

```python
# 价格为零或负数 → ffill 修复
for col in ['Open', 'High', 'Low', 'Close']:
    mask = df[col] <= 0
    if mask.any():
        df.loc[mask, col] = np.nan
        df[col] = df[col].ffill()
        if df[col].iloc[0] <= 0 or pd.isna(df[col].iloc[0]):
            raise ValueError(f"首行 {col} 无效且无法 ffill 修复")
```

### 时间连续性检查

- 加密货币市场 7×24 运行，时间间隔不均匀是正常的
- 仅做信息性检查，不强制修复
- 记录 gap 统计信息供用户参考

### 重复时间戳去重

```python
df = df[~df.index.duplicated(keep='first')]
```

### 合并行数断言

```python
def assert_no_row_expansion(left: pd.DataFrame, right: pd.DataFrame, context: str = ""):
    """防止 merge 操作导致行数静默膨胀"""
    if len(left) != len(right):
        raise AssertionError(
            f"行数膨胀检测 [{context}]: "
            f"left={len(left)}, right={len(right)}, diff={len(right) - len(left)}"
        )
```

### DataValidator 代码模板

```python
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class DataValidator:
    def __init__(self, warn_threshold: float = 0.20, error_threshold: float = 0.50):
        self.warn_threshold = warn_threshold
        self.error_threshold = error_threshold
        self.report: dict = {"warn": [], "error": [], "repaired": []}

    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df = self._check_price_validity(df)
        df = self._check_single_bar_change(df)
        df = self._dedup_timestamps(df)
        df = self._check_time_continuity(df)
        return df

    def _check_price_validity(self, df: pd.DataFrame) -> pd.DataFrame:
        for col in ['Open', 'High', 'Low', 'Close']:
            mask = df[col] <= 0
            if mask.any():
                n_invalid = mask.sum()
                df.loc[mask, col] = np.nan
                df[col] = df[col].ffill()
                if df[col].iloc[0] <= 0 or pd.isna(df[col].iloc[0]):
                    raise ValueError(f"首行 {col} 无效且无法 ffill 修复")
                self.report["repaired"].append(f"{col}: {n_invalid} 行零/负值已 ffill")
        return df

    def _check_single_bar_change(self, df: pd.DataFrame) -> pd.DataFrame:
        pct_change = df['Close'].pct_change()
        for idx in pct_change.index:
            val = pct_change.loc[idx]
            if pd.isna(val):
                continue
            abs_val = abs(val)
            if abs_val > self.error_threshold:
                self.report["error"].append(f"{idx}: {val:.2%} (>50%)")
                df.loc[idx, ['Open', 'High', 'Low', 'Close']] = np.nan
            elif abs_val > self.warn_threshold:
                self.report["warn"].append(f"{idx}: {val:.2%} (20%-50%)")

        for col in ['Open', 'High', 'Low', 'Close']:
            df[col] = df[col].ffill()
        return df

    def _dedup_timestamps(self, df: pd.DataFrame) -> pd.DataFrame:
        n_before = len(df)
        df = df[~df.index.duplicated(keep='first')]
        n_dup = n_before - len(df)
        if n_dup > 0:
            self.report["repaired"].append(f"去除 {n_dup} 个重复时间戳")
        return df

    def _check_time_continuity(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < 2:
            return df
        diffs = pd.Series(df.index).diff().dropna()
        median_diff = diffs.median()
        gaps = diffs[diffs > 3 * median_diff]
        if len(gaps) > 0:
            self.report["warn"].append(
                f"检测到 {len(gaps)} 个时间间隔 >3x 中位数，可能为正常市场间隔"
            )
        return df
```

---

## E. XGBoost "情报员+司令官"分工模式

### 架构思想

- **情报员（XGBoost）**：只输出概率 Signal_Proba ∈ [0, 1]，不做任何交易决策
- **司令官（RL Agent）**：综合 Signal_Proba 与其他观察维度，做出最终交易决策
- Signal_Proba 仅作为 RL 观察空间的一个维度，不直接产生信号

### 严格时间分割

```python
# 禁止 shuffle！时间序列必须按时间顺序分割
split_idx = int(len(df) * 0.8)
train_df = df.iloc[:split_idx]
test_df = df.iloc[split_idx:]

# 训练集内部再做 80/20 分割用于 early stopping
inner_split = int(len(train_df) * 0.8)
fit_df = train_df.iloc[:inner_split]
val_df = train_df.iloc[inner_split:]
```

### 特征选择原则

```python
# ✅ 正确：只用衍生技术指标作为特征
FEATURE_COLS = [
    'RSI', 'MACD', 'MACD_Signal', 'MACD_Hist',
    'SMA_50', 'SMA_200', 'Dist_SMA_200',
    'ATR', 'BB_Width', 'Rolling_Vol', 'Volatility_Regime',
    'Vol_Ratio', 'Log_Returns', 'Ret_Lag_1', 'Ret_Lag_2', 'Ret_Lag_3',
    'RSI_Lag_1', 'RSI_Lag_2', 'RSI_Lag_3', 'Range_Pct',
]

# ❌ 禁止：原始 OHLCV 不能作为 ML 特征
# 原始价格包含绝对价格水平信息，会导致模型过拟合到特定价格区间
```

### SignalPredictor 代码模板

```python
import hashlib
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from xgboost import XGBClassifier

class SignalPredictor:
    def __init__(self, feature_cols: list[str], model_params: dict | None = None):
        self.feature_cols = feature_cols
        self.model_params = model_params or {
            "n_estimators": 200,
            "max_depth": 5,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "eval_metric": "logloss",
            "use_label_encoder": False,
            "verbosity": 0,
        }
        self.model: XGBClassifier | None = None

    def fit(self, df: pd.DataFrame, target_col: str = "Target"):
        split_idx = int(len(df) * 0.8)
        train_df = df.iloc[:split_idx]
        oos_df = df.iloc[split_idx:]

        inner_split = int(len(train_df) * 0.8)
        fit_df = train_df.iloc[:inner_split]
        val_df = train_df.iloc[inner_split:]

        X_fit = fit_df[self.feature_cols]
        y_fit = fit_df[target_col]
        X_val = val_df[self.feature_cols]
        y_val = val_df[target_col]

        self.model = XGBClassifier(**self.model_params)
        self.model.fit(
            X_fit, y_fit,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )

        # OOS 概率生成：仅用训练集训练的模型
        X_oos = oos_df[self.feature_cols]
        oos_proba = self.model.predict_proba(X_oos)[:, 1]

        return oos_proba, oos_df.index

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("模型未训练，请先调用 fit()")
        X = df[self.feature_cols]
        return self.model.predict_proba(X)[:, 1]

    def save(self, path: str):
        joblib.dump(self.model, path)

    def load(self, path: str):
        self.model = joblib.load(path)
```

### 集成到 RL 观察空间

```python
# Signal_Proba 作为观察空间的一个维度
import gymnasium as gym

obs_space = gym.spaces.Box(
    low=-np.inf, high=np.inf,
    shape=(n_technical_features + 1,),  # +1 for Signal_Proba
    dtype=np.float32,
)

# 在 step() 中构建观察
def _build_obs(self):
    tech_features = self._get_technical_features()  # 技术指标向量
    signal_proba = self._get_signal_proba()          # XGBoost 输出 [0, 1]
    return np.concatenate([tech_features, [signal_proba]]).astype(np.float32)
```

---

## F. 数据版本管理模式

### SHA256 哈希追踪

```python
import hashlib
from pathlib import Path
import pandas as pd

def compute_file_hash(filepath: str | Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def record_data_version(
    filepath: str | Path,
    version_csv: str = "data_versions.csv",
    description: str = "",
):
    file_hash = compute_file_hash(filepath)
    filename = Path(filepath).name
    record = {
        "filename": filename,
        "sha256": file_hash,
        "description": description,
        "timestamp": pd.Timestamp.now().isoformat(),
    }

    version_path = Path(version_csv)
    if version_path.exists():
        df = pd.read_csv(version_path)
        df = pd.concat([df, pd.DataFrame([record])], ignore_index=True)
    else:
        df = pd.DataFrame([record])

    df.to_csv(version_path, index=False)
    return file_hash
```

### 使用方式

```python
# 每次加载数据后记录版本
data_hash = record_data_version(
    "data/BTCUSDT_1d.csv",
    description="2024-01 至 2025-05 日线数据"
)

# 实验开始时验证数据版本
current_hash = compute_file_hash("data/BTCUSDT_1d.csv")
expected_hash = "abc123..."
assert current_hash == expected_hash, "数据文件已变更，实验不可复现"
```

---

## Common Pitfalls

| 陷阱 | 后果 | 正确做法 |
|------|------|---------|
| 滚动指标忘记 shift(1) | Look-ahead bias，回测虚高 | 所有 rolling 指标计算后 shift(1) |
| 时间序列使用 random shuffle | 时间泄漏，模型看到未来数据 | 严格按时间顺序分割 |
| ML 特征包含原始 OHLCV | 过拟合到价格水平，泛化差 | 只用衍生技术指标 |
| rolling 计算后不检查 NaN | 静默失败，模型训练异常 | 检查 NaN 数量，合理 dropna |
| OOS 集用全量数据生成信号 | 信号包含未来信息，回测无效 | OOS 信号必须由 train-only 模型生成 |
| merge 操作导致行数膨胀 | 静默数据错误 | 使用 assert_no_row_expansion() |
| 首行数据无效且 ffill 无法修复 | 后续所有数据被污染 | raise ValueError 终止 |
| 不同资产使用相同参数 | 低波动资产信号噪声大，高波动资产信号滞后 | 使用 AssetProfile 区分参数 |

---

## FeatureEngineer 代码模板

```python
import numpy as np
import pandas as pd
from dataclasses import dataclass

@dataclass(frozen=True)
class FeatureProfile:
    rsi_window: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bb_window: int = 20
    bb_std: float = 2.0
    atr_window: int = 14
    sma_fast: int = 50
    sma_slow: int = 200
    volume_window: int = 20
    rolling_vol_window: int = 20

class FeatureEngineer:
    def __init__(self, profile: FeatureProfile | None = None):
        self.profile = profile or FeatureProfile()

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        # === shift(1) 核心策略 ===
        close_prev = df['Close'].shift(1)
        high_prev = df['High'].shift(1)
        low_prev = df['Low'].shift(1)
        close_prev2 = df['Close'].shift(2)

        # === 趋势维度 ===
        df['RSI'] = self._rsi(close_prev, self.profile.rsi_window)
        macd_line, signal_line, hist = self._macd(
            close_prev, self.profile.macd_fast,
            self.profile.macd_slow, self.profile.macd_signal
        )
        df['MACD'] = macd_line
        df['MACD_Signal'] = signal_line
        df['MACD_Hist'] = hist

        df['SMA_50'] = close_prev.rolling(self.profile.sma_fast).mean()
        df['SMA_200'] = close_prev.rolling(self.profile.sma_slow).mean()
        df['Dist_SMA_200'] = (close_prev - df['SMA_200']) / df['SMA_200']

        for period in [3, 5, 10]:
            df[f'ROC_{period}'] = close_prev.pct_change(period)

        # === 波动率维度 ===
        tr = pd.concat([
            high_prev - low_prev,
            (high_prev - close_prev2).abs(),
            (low_prev - close_prev2).abs(),
        ], axis=1).max(axis=1)
        df['ATR'] = tr.rolling(self.profile.atr_window).mean()

        bb_sma = close_prev.rolling(self.profile.bb_window).mean()
        bb_std = close_prev.rolling(self.profile.bb_window).std()
        df['BB_Upper'] = bb_sma + self.profile.bb_std * bb_std
        df['BB_Lower'] = bb_sma - self.profile.bb_std * bb_std
        df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / bb_sma

        log_ret = np.log(df['Close'] / df['Close'].shift(1))
        df['Rolling_Vol'] = log_ret.rolling(self.profile.rolling_vol_window).std() * np.sqrt(365)
        df['Volatility_Regime'] = df['Rolling_Vol'].rolling(252, min_periods=20).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False
        )

        # === 成交量维度 ===
        vol_sma = df['Volume'].shift(1).rolling(self.profile.volume_window).mean()
        df['Vol_Ratio'] = df['Volume'].shift(1) / vol_sma

        # === 动量维度 ===
        df['Log_Returns'] = log_ret
        for lag in [1, 2, 3]:
            df[f'Ret_Lag_{lag}'] = log_ret.shift(lag)
            df[f'RSI_Lag_{lag}'] = df['RSI'].shift(lag)
        df['Range_Pct'] = (high_prev - low_prev) / close_prev

        return df

    @staticmethod
    def _rsi(series: pd.Series, window: int) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(alpha=1/window, min_periods=window).mean()
        avg_loss = loss.ewm(alpha=1/window, min_periods=window).mean()
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _macd(series: pd.Series, fast: int, slow: int, signal: int):
        ema_fast = series.ewm(span=fast, min_periods=fast).mean()
        ema_slow = series.ewm(span=slow, min_periods=slow).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, min_periods=signal).mean()
        hist = macd_line - signal_line
        return macd_line, signal_line, hist
```

---

## 完整管线集成示例

```python
# 1. 加载 & 校验
validator = DataValidator(warn_threshold=0.20, error_threshold=0.50)
df = pd.read_csv("BTCUSDT_1d.csv", parse_dates=True, index_col=0)
df = validator.validate(df)

# 2. 特征工程
profile = get_profile("BTCUSDT")
fe = FeatureEngineer(profile.feature)
df = fe.transform(df)

# 3. 生成目标变量（示例：次日收益 > 0 为正类）
df['Target'] = (df['Close'].pct_change().shift(-1) > 0).astype(int)

# 4. 训练 XGBoost 信号预测器
FEATURE_COLS = [
    'RSI', 'MACD', 'MACD_Signal', 'MACD_Hist',
    'Dist_SMA_200', 'ATR', 'BB_Width', 'Rolling_Vol',
    'Volatility_Regime', 'Vol_Ratio', 'Log_Returns',
    'Ret_Lag_1', 'Ret_Lag_2', 'Ret_Lag_3',
    'RSI_Lag_1', 'RSI_Lag_2', 'RSI_Lag_3', 'Range_Pct',
]

predictor = SignalPredictor(feature_cols=FEATURE_COLS)
oos_proba, oos_index = predictor.fit(df, target_col="Target")

# 5. 将 Signal_Proba 写回 DataFrame
df.loc[oos_index, 'Signal_Proba'] = oos_proba

# 6. 记录数据版本
record_data_version("BTCUSDT_1d.csv", description="特征工程后完整数据")
```
