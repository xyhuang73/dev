# -*- coding: utf-8 -*-
"""
IC 门槛与多空夏普（约束 + 主目标）：
先满足 RankIC 均值与 IC_IR 等 IC 类门槛，再以「分层多空年化夏普」作为排序主目标。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .factor_evaluation_settings import SchemeBConfig


@dataclass
class FactorSelectionOutcome:
    """单因子在「IC 门槛与多空夏普」规则下的可行性与目标值。"""

    feasible: bool
    # 可行时为 long_short_sharpe；不可行时通常为 -inf 或 nan（由调用方约定）
    objective_value: float
    reason: str


def evaluate_factor_feasibility_and_objective(
    rank_ic_mean: float,
    ic_ir: float,
    long_short_sharpe: float,
    cfg: SchemeBConfig,
) -> FactorSelectionOutcome:
    """
    判定是否满足 IC 门槛；满足则主目标取分层多空年化夏普，否则不可行。

    参数中的 rank_ic_mean / ic_ir / long_short_sharpe 须与全样本同一口径。
    """
    reasons: list[str] = []
    # 防止 nan 与阈值比较直接返回 False 导致误判可行。
    if not math.isfinite(rank_ic_mean):
        reasons.append("RankIC均值非有限值（无有效 IC 日或截面因子退化为常数）")
    elif rank_ic_mean < cfg.min_rank_ic_mean:
        reasons.append(
            f"RankIC均值 {rank_ic_mean:.6f} < 下限 {cfg.min_rank_ic_mean:.6f}",
        )
    if not math.isfinite(ic_ir):
        reasons.append("IC_IR 非有限值（IC 序列有效日不足或方差为 0）")
    elif ic_ir < cfg.min_ic_ir:
        reasons.append(f"IC_IR {ic_ir:.6f} < 下限 {cfg.min_ic_ir:.6f}")
    feasible = len(reasons) == 0
    if feasible and not math.isfinite(long_short_sharpe):
        feasible = False
        reasons.append("分层多空夏普非有限值（有效分层日不足或收益方差为 0）")
    if feasible:
        return FactorSelectionOutcome(
            feasible=True,
            objective_value=float(long_short_sharpe),
            reason="已满足 IC 门槛（RankIC 与 IC_IR），主目标=分层多空年化夏普",
        )
    return FactorSelectionOutcome(
        feasible=False,
        objective_value=float("-inf"),
        reason="；".join(reasons),
    )


def build_factor_sort_key(outcome: FactorSelectionOutcome, long_short_sharpe: float) -> tuple[float, float]:
    """
    排序键：可行因子按 objective 降序；不可行排在最后，用夏普占位避免乱序。

    返回 (primary, secondary) 供 sorted(..., reverse=True) 使用。
    """
    if outcome.feasible:
        return (1.0, outcome.objective_value)
    return (0.0, long_short_sharpe)
