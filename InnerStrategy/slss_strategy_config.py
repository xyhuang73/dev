# -*- coding: utf-8 -*-
"""
SLSS 策略可调参数：统一从 ``Config/slss_strategy.json`` 读取。

- 因子包编号、等权或显式权重、买卖阈值、手数、Alpha prepare 并行度；
- 报告用逐笔模拟的滚动 z 备用参数。

若 JSON 缺失或字段缺省，使用代码内嵌的默认并（可选）写回磁盘。

本模块位于 ``InnerStrategy/`` 根下，**不参与** ``strategies/`` 目录的 S 编号扫描。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# 项目根：本文件在 InnerStrategy/ 下，向上一级即为仓库根
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
SLSS_STRATEGY_JSON_PATH = _PROJECT_ROOT / "Config" / "slss_strategy.json"


@dataclass(frozen=True)
class SlssTradeSimulationParams:
    """逐笔模拟备用（rolling z）参数。"""

    rolling_window: int
    rolling_min_periods: int
    fallback_buy_z: float
    fallback_sell_z: float
    enable_rolling_z_fallback: bool


@dataclass(frozen=True)
class SlssStrategyConfig:
    """SLSS 策略完整可调配置（内存只读视图）。"""

    version: int
    stratified_long_short_sharpe_objective_en: str
    bundle_factor_ids: tuple[str, ...]
    equal_weight: bool
    explicit_weights: tuple[float, ...] | None
    # 决策模式：threshold=绝对阈值开平；cross_section_rank=按截面排名分多/空/中性
    decision_mode: str
    cross_section_long_top_n: int
    # 做空起始名次（1-based）：名次 >= 该值 → 空头，即「前 (值-1) 名之外」；默认 21 表示前 20 名不做空
    cross_section_short_min_rank: int
    # 截面多头：除名次外要求收盘价、合成值均 >0（与 JSON 一致，缺省 false 保持旧行为）
    cross_section_long_require_close_positive: bool
    cross_section_long_require_composite_positive: bool
    # 截面空头：>0 时按「当日有效样本中名次最差的 N 只」为底仓桶；与 short_min_rank 二选一（N>0 时优先 N）
    cross_section_short_bottom_n: int
    # 为 true 时：除名次空头外，凡 slss_composite<0 且未满足多头条件的标的也做空（或条件）
    cross_section_short_or_negative_composite: bool
    # A 股现货规则：为 true 时禁止截面做空（不生成 -1）；多头卖出须晚于买入开仓日（T+1，日 K 用日历日比较）
    a_share_cash_stock_rules: bool
    buy_threshold: float
    sell_threshold: float
    fixed_lot: int
    alpha_prepare_workers: int
    trade_simulation: SlssTradeSimulationParams

    def normalized_weights(self, n_features: int) -> np.ndarray:
        """
        返回长度 ``n_features`` 且和为 1 的权重向量（与 bundle 列顺序对齐）。

        ``equal_weight`` 为 True 或 ``explicit_weights`` 无效时退化为等权。
        """
        if n_features < 1:
            return np.array([], dtype=np.float64)
        if self.equal_weight or not self.explicit_weights:
            return np.full(n_features, 1.0 / float(n_features), dtype=np.float64)
        w = np.asarray(self.explicit_weights, dtype=np.float64)
        if w.shape[0] != n_features:
            return np.full(n_features, 1.0 / float(n_features), dtype=np.float64)
        s = float(np.nansum(w))
        if not math.isfinite(s) or s <= 0:
            return np.full(n_features, 1.0 / float(n_features), dtype=np.float64)
        return w / s


def _default_trade_sim_dict() -> dict[str, Any]:
    return {
        "rolling_window": 20,
        "rolling_min_periods": 10,
        "fallback_buy_z": 1.0,
        "fallback_sell_z": -0.5,
        "enable_rolling_z_fallback": True,
    }


def _default_config_dict() -> dict[str, Any]:
    """与 ``Config/slss_strategy.json`` 首次落盘内容一致。"""
    return {
        "version": 1,
        "stratified_long_short_sharpe_objective_en": "StratifiedLongShortSharpe",
        "bundle_factor_ids": [
            "F000139",
            "F000096",
            "F000099",
            "F000142",
            "F000138",
            "F000004",
            "F000137",
            "F000161",
            "F000104",
            "F000098",
        ],
        "equal_weight": True,
        "explicit_weights": None,
        "decision_mode": "threshold",
        "cross_section_long_top_n": 3,
        "cross_section_short_min_rank": 21,
        "cross_section_long_require_close_positive": False,
        "cross_section_long_require_composite_positive": False,
        "cross_section_short_bottom_n": 0,
        "cross_section_short_or_negative_composite": False,
        "a_share_cash_stock_rules": True,
        "buy_threshold": 3.5,
        "sell_threshold": 2.0,
        "fixed_lot": 100,
        "alpha_prepare_workers": 1,
        "trade_simulation": _default_trade_sim_dict(),
    }


def _parse_trade_sim(raw: Any) -> SlssTradeSimulationParams:
    d = _default_trade_sim_dict()
    if isinstance(raw, dict):
        d.update({k: raw.get(k, d[k]) for k in d})
    return SlssTradeSimulationParams(
        rolling_window=max(2, int(d["rolling_window"])),
        rolling_min_periods=max(2, int(d["rolling_min_periods"])),
        fallback_buy_z=float(d["fallback_buy_z"]),
        fallback_sell_z=float(d["fallback_sell_z"]),
        enable_rolling_z_fallback=bool(d["enable_rolling_z_fallback"]),
    )


def _coerce_float(d: dict[str, Any], key: str, default: float) -> float:
    """
    从 dict 读取浮点配置。

    显式写入 ``0.0`` 必须保留；不能用 ``value or default``，否则会把合法的 0 误判成缺省。
    """
    if key not in d:
        return default
    raw = d[key]
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _dict_to_config(data: dict[str, Any]) -> SlssStrategyConfig:
    """dict → SlssStrategyConfig，带类型与边界修正。"""
    base = _default_config_dict()
    base.update({k: data.get(k, base[k]) for k in base if k != "trade_simulation"})
    ts = _parse_trade_sim(data.get("trade_simulation"))

    ids = base["bundle_factor_ids"]
    if not isinstance(ids, list) or not ids:
        ids = _default_config_dict()["bundle_factor_ids"]
    bundle = tuple(str(x).strip() for x in ids if str(x).strip())

    ew = base.get("explicit_weights")
    exp_w: tuple[float, ...] | None = None
    if isinstance(ew, list) and ew:
        exp_w = tuple(float(x) for x in ew)

    dm = str(base.get("decision_mode") or "threshold").strip().lower()
    if dm not in {"threshold", "cross_section_rank"}:
        dm = "threshold"
    cs_long = max(1, int(base.get("cross_section_long_top_n") or 3))
    cs_short = int(base.get("cross_section_short_min_rank") or 21)
    if cs_short <= cs_long + 0:
        cs_short = cs_long + 1
    cs_req_close = bool(base.get("cross_section_long_require_close_positive", False))
    cs_req_comp = bool(base.get("cross_section_long_require_composite_positive", False))
    cs_short_bottom = max(0, int(base.get("cross_section_short_bottom_n") or 0))
    cs_short_neg = bool(base.get("cross_section_short_or_negative_composite", False))
    a_share = bool(base["a_share_cash_stock_rules"])

    return SlssStrategyConfig(
        version=int(base.get("version") or 1),
        stratified_long_short_sharpe_objective_en=str(
            base.get("stratified_long_short_sharpe_objective_en") or "StratifiedLongShortSharpe",
        ),
        bundle_factor_ids=bundle,
        equal_weight=bool(base.get("equal_weight", True)),
        explicit_weights=exp_w,
        decision_mode=dm,
        cross_section_long_top_n=cs_long,
        cross_section_short_min_rank=cs_short,
        cross_section_long_require_close_positive=cs_req_close,
        cross_section_long_require_composite_positive=cs_req_comp,
        cross_section_short_bottom_n=cs_short_bottom,
        cross_section_short_or_negative_composite=cs_short_neg,
        a_share_cash_stock_rules=a_share,
        buy_threshold=_coerce_float(base, "buy_threshold", 3.5),
        sell_threshold=_coerce_float(base, "sell_threshold", 2.0),
        fixed_lot=max(1, int(base.get("fixed_lot") or 100)),
        alpha_prepare_workers=max(1, int(base.get("alpha_prepare_workers") or 1)),
        trade_simulation=ts,
    )


def load_slss_strategy_config(
    *,
    ensure_file: bool = True,
    overrides: dict[str, Any] | None = None,
) -> SlssStrategyConfig:
    """
    读取 ``Config/slss_strategy.json``。

    Args:
        ensure_file: 为 True 时，若文件不存在则写入默认 JSON 后再解析。
    """
    if ensure_file and not SLSS_STRATEGY_JSON_PATH.is_file():
        SLSS_STRATEGY_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        SLSS_STRATEGY_JSON_PATH.write_text(
            json.dumps(_default_config_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if not SLSS_STRATEGY_JSON_PATH.is_file():
        data = _default_config_dict()
        if overrides:
            data.update(overrides)
        return _dict_to_config(data)
    try:
        data = json.loads(SLSS_STRATEGY_JSON_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = _default_config_dict()
        if overrides:
            data.update(overrides)
        return _dict_to_config(data)
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        data = _default_config_dict()
        if overrides:
            data.update(overrides)
        return _dict_to_config(data)


def slss_strategy_config_to_dict(cfg: SlssStrategyConfig) -> dict[str, Any]:
    """将只读配置转换为可序列化、可作为 RunConfig 快照的参数字典。"""
    return {
        "version": cfg.version,
        "stratified_long_short_sharpe_objective_en": cfg.stratified_long_short_sharpe_objective_en,
        "bundle_factor_ids": list(cfg.bundle_factor_ids),
        "equal_weight": cfg.equal_weight,
        "explicit_weights": list(cfg.explicit_weights) if cfg.explicit_weights is not None else None,
        "decision_mode": cfg.decision_mode,
        "cross_section_long_top_n": cfg.cross_section_long_top_n,
        "cross_section_short_min_rank": cfg.cross_section_short_min_rank,
        "cross_section_long_require_close_positive": cfg.cross_section_long_require_close_positive,
        "cross_section_long_require_composite_positive": cfg.cross_section_long_require_composite_positive,
        "cross_section_short_bottom_n": cfg.cross_section_short_bottom_n,
        "cross_section_short_or_negative_composite": cfg.cross_section_short_or_negative_composite,
        "a_share_cash_stock_rules": cfg.a_share_cash_stock_rules,
        "buy_threshold": cfg.buy_threshold,
        "sell_threshold": cfg.sell_threshold,
        "fixed_lot": cfg.fixed_lot,
        "alpha_prepare_workers": cfg.alpha_prepare_workers,
        "trade_simulation": {
            "rolling_window": cfg.trade_simulation.rolling_window,
            "rolling_min_periods": cfg.trade_simulation.rolling_min_periods,
            "fallback_buy_z": cfg.trade_simulation.fallback_buy_z,
            "fallback_sell_z": cfg.trade_simulation.fallback_sell_z,
            "enable_rolling_z_fallback": cfg.trade_simulation.enable_rolling_z_fallback,
        },
    }


def compute_slss_composite_series(df: pd.DataFrame, feature_cols: list[str], cfg: SlssStrategyConfig) -> pd.Series:
    """
    按配置权重对 ``feature_cols`` 列做行内加权平均（非有限值不参与分子分母）。

    Returns:
        与 ``df`` 行索引对齐的 ``slss_composite`` 序列。
    """
    n = len(feature_cols)
    if n < 1:
        return pd.Series(np.nan, index=df.index, dtype=np.float64)
    mat = df[feature_cols].to_numpy(dtype=np.float64)
    w = cfg.normalized_weights(n)
    wrow = np.broadcast_to(w, mat.shape)
    with np.errstate(invalid="ignore"):
        num = np.nansum(mat * wrow, axis=1)
        mask = np.isfinite(mat)
        den = np.sum(np.where(mask, wrow, 0.0), axis=1)
        out = np.where(den > 1e-15, num / den, np.nan)
    return pd.Series(out, index=df.index, dtype=np.float64)
