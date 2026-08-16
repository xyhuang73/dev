# -*- coding: utf-8 -*-
"""
回测引擎子包：向量回测与事件驱动回测共用抽象接口，由 runner 按配置分发。
"""

from ..models import BacktestResult
from .base import BacktestEngine
from .event_engine import EventDrivenBacktestEngine
from .vector_engine import VectorBacktestEngine

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "VectorBacktestEngine",
    "EventDrivenBacktestEngine",
]
