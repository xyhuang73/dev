# -*- coding: utf-8 -*-
"""
回测任务与结果的轻量数据模型（与 Config/backtest.json 字段对齐）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from quant.engine.contracts import SignalFrame, TargetPosition

# 与引擎注册表一致：向量 = 全截面/矩阵一次性算收益；事件 = 按 K 线或逐笔驱动
BacktestMode = Literal["vector", "event"]


@dataclass
class BacktestJobConfig:
    """旧 GUI 的回测任务模型；由适配器转换为新 ``RunConfig``。"""

    initial_capital: float
    start_date: str
    end_date: str
    factor_key: str  # InnerStrategy inner_registry 因子编号，如 F000001
    strategy_key: str  # 策略编号，如 S000001
    backtest_mode: BacktestMode
    strategy_params: dict[str, Any] = field(default_factory=dict)
    resolved_strategy_params: dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    run_id: str | None = None
    dataset_id: str = "local-current"
    universe_id: str = "configured-current"
    random_seed: int = 0

    def describe(self) -> str:
        """生成简短说明，供占位引擎与日志使用。"""
        return (
            f"资金={self.initial_capital}, 区间={self.start_date}~{self.end_date}, "
            f"因子 id={self.factor_key}, 策略 id={self.strategy_key}, 模式={self.backtest_mode}, "
            f"显式参数={len(self.strategy_params)}项"
        )

    def effective_strategy_params(self) -> dict[str, Any]:
        """返回经 Schema 校验后的运行参数；入口外调用时兼容原始覆盖项。"""
        return dict(self.resolved_strategy_params or self.strategy_params)


@dataclass
class BacktestResult:
    """引擎运行结果；后续可扩展收益指标、净值序列等字段。"""

    ok: bool
    message: str
    # 策略回测生成的 Excel 报告绝对路径（未生成时为 None）
    excel_path: str | None = None
    signal_frame: SignalFrame | None = None
    target_positions: TargetPosition | None = None
