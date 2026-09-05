# -*- coding: utf-8 -*-
"""
向量回测引擎。

- **StratifiedLongShortSharpeEqualWeightStrategy**：全截面计算等权 SLSS 合成因子，并输出
  StratifiedLongShortSharpe（分层多空年化夏普）及收益类截面指标。
- 其它策略：暂回退占位说明，避免误认已数值回测。
"""
from __future__ import annotations

from collections.abc import Callable

from quant.strategy.registry import get_strategy_spec

from .base import BacktestEngine
from .placeholder_result import build_placeholder_backtest_result
from ..models import BacktestJobConfig, BacktestResult


class VectorBacktestEngine(BacktestEngine):
    """向量回测：通过稳定 StrategySpec 分发到兼容 runner。"""

    mode_id = "vector"

    def run(self, job: BacktestJobConfig, *, progress: Callable[[str], None] | None = None) -> BacktestResult:
        spec = get_strategy_spec(job.strategy_key)
        if spec is not None and "vector" in spec.supported_modes:
            runner = spec.load_vector_runner()
            return runner(job, progress=progress)

        steps = (
            "  1) 当前策略未在 StrategyRegistry 注册向量 runner；\n"
            "  2) 请为 StrategySpec 声明 vector_runner；\n"
            "  3) VectorEngine 不再增加按类名判断的分支。\n"
        )
        if progress is not None:
            progress("[向量回测] 当前策略无对应向量实现，返回占位说明。")
        print("[向量回测] 当前策略无对应向量实现，返回占位说明。", flush=True)
        return build_placeholder_backtest_result(job, "[向量回测 · 未实现该策略]", steps)
