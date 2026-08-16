# -*- coding: utf-8 -*-
"""
事件驱动回测引擎（架构占位）。

设计意图::
    - 按时间轴（日线 bar / 更高频 tick）依次推送行情事件，驱动策略状态机下单。
    - 与 VeighNa CtaTemplate、自研事件循环模型对齐，适合逐 K 仿真与精细成交假设。

后续可接入：事件队列 → 策略 on_bar → 撮合 → 更新资金与持仓。
"""
from __future__ import annotations

from collections.abc import Callable

from .base import BacktestEngine
from .placeholder_result import build_placeholder_backtest_result
from ..models import BacktestJobConfig, BacktestResult


class EventDrivenBacktestEngine(BacktestEngine):
    """按事件循环的回测，占位实现仅回显任务参数。"""

    mode_id = "event"

    def run(self, job: BacktestJobConfig, *, progress: Callable[[str], None] | None = None) -> BacktestResult:
        msg = "[事件回测] 占位引擎：未执行真实撮合，仅输出步骤说明。"
        print(msg, flush=True)
        if progress is not None:
            progress(msg)
        steps = (
            "  1) 按 strategy_key（S 编号）取 module+class，动态 import InnerStrategy/strategies 下模块；\n"
            "  2) 在区间内逐根 K 线推送 BarData；\n"
            "  3) 调用策略回调并模拟委托/成交/费用/滑点；\n"
            "  4) 汇总权益与日志。\n"
        )
        return build_placeholder_backtest_result(job, "[事件回测 · 架构占位]", steps)
