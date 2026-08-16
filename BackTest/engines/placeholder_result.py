# -*- coding: utf-8 -*-
"""向量/事件占位引擎共用：注册表解析摘要 + 统一拼装 BacktestResult。"""
from __future__ import annotations

from InnerStrategy.inner_registry import get_factor_entry, get_strategy_entry

from ..models import BacktestJobConfig, BacktestResult


def build_placeholder_backtest_result(
    job: BacktestJobConfig,
    header: str,
    steps_block: str,
) -> BacktestResult:
    """
    占位回测：仅回显任务参数与注册表解析结果。

    :param header: 首行标题，如 ``[事件回测 · 架构占位]``。
    :param steps_block: 「后续步骤建议」下的多行正文（可含行首空格与换行）。
    """
    fe = get_factor_entry(job.factor_key)
    se = get_strategy_entry(job.strategy_key)
    resolve_lines = ""
    if fe:
        resolve_lines += f"注册表解析因子: pack={fe['pack']}, feature={fe['feature']}\n"
    if se:
        resolve_lines += f"注册表解析策略: module={se['module']}, class={se['class']}\n"
    msg = (
        f"{header}\n{job.describe()}\n\n"
        f"{resolve_lines}\n"
        "后续步骤建议：\n"
        f"{steps_block}"
    )
    return BacktestResult(True, msg)
