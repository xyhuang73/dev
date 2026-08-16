# -*- coding: utf-8 -*-
"""
根据 BacktestJobConfig.backtest_mode 分发到向量引擎或事件引擎。
"""
from __future__ import annotations

from collections.abc import Callable

from .engines.event_engine import EventDrivenBacktestEngine
from .engines.vector_engine import VectorBacktestEngine
from .models import BacktestJobConfig, BacktestResult

# 无状态占位引擎可单例复用
_VECTOR = VectorBacktestEngine()
_EVENT = EventDrivenBacktestEngine()


def run_backtest(
    job: BacktestJobConfig,
    *,
    progress: Callable[[str], None] | None = None,
) -> BacktestResult:
    """
    统一入口；后续可在此增加参数校验、计时与指标汇总。

    progress: 可选进度文本回调（对话框追加等）；各引擎内部对关键步骤应 ``print``。
    """
    if job.backtest_mode == "vector":
        return _VECTOR.run(job, progress=progress)
    if job.backtest_mode == "event":
        return _EVENT.run(job, progress=progress)
    return BacktestResult(False, f"不支持的回测模式: {job.backtest_mode!r}")
