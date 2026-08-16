# -*- coding: utf-8 -*-
"""
向量回测引擎。

- **StratifiedLongShortSharpeEqualWeightStrategy**：全截面计算等权 SLSS 合成因子，并输出
  StratifiedLongShortSharpe（分层多空年化夏普）及收益类截面指标。
- 其它策略：暂回退占位说明，避免误认已数值回测。
"""
from __future__ import annotations

from collections.abc import Callable

from InnerStrategy.inner_registry import get_strategy_entry

from .base import BacktestEngine
from .placeholder_result import build_placeholder_backtest_result
from ..models import BacktestJobConfig, BacktestResult


class VectorBacktestEngine(BacktestEngine):
    """向量回测：按策略编号分发到具体实现。"""

    mode_id = "vector"

    def run(self, job: BacktestJobConfig, *, progress: Callable[[str], None] | None = None) -> BacktestResult:
        se = get_strategy_entry(job.strategy_key)
        class_name = str(se.get("class", "")) if se else ""
        if class_name == "StratifiedLongShortSharpeEqualWeightStrategy":
            from ..vector_slss_runner import run_vector_slss_backtest  # noqa: PLC0415

            return run_vector_slss_backtest(job, progress=progress)

        if class_name == "QixingaozhaoEtfRotationStrategy":
            from ..qixingaozhao_backtest_runner import run_qixingaozhao_backtest  # noqa: PLC0415

            return run_qixingaozhao_backtest(job, progress=progress)

        steps = (
            "  1) 当前已实现的向量策略：StratifiedLongShortSharpeEqualWeightStrategy、QixingaozhaoEtfRotationStrategy；\n"
            "  2) 其它策略请使用事件回测占位或接入 VeighNa CtaBacktester；\n"
            "  3) 或在 vector_engine 中为对应 class 增加分支实现。\n"
        )
        if progress is not None:
            progress("[向量回测] 当前策略无对应向量实现，返回占位说明。")
        print("[向量回测] 当前策略无对应向量实现，返回占位说明。", flush=True)
        return build_placeholder_backtest_result(job, "[向量回测 · 未实现该策略]", steps)
