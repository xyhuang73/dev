# -*- coding: utf-8 -*-
"""
引擎抽象：后续向量实现可走全截面矩阵运算；事件实现可走 bar/tick 循环。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import ClassVar

from ..models import BacktestJobConfig, BacktestResult


class BacktestEngine(ABC):
    """所有回测引擎的基类，便于单元测试与插件式扩展。"""

    mode_id: ClassVar[str]  # "vector" | "event"

    @abstractmethod
    def run(self, job: BacktestJobConfig, *, progress: Callable[[str], None] | None = None) -> BacktestResult:
        """
        执行回测；真实实现中应加载因子/策略并产出净值与指标。

        progress: 可选文本进度回调（如写入对话框）；引擎内应同时 ``print`` 便于终端留痕。
        """
        ...
