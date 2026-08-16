# -*- coding: utf-8 -*-
"""
MiniQMT 本地 Alpha 表达式引擎（衍生自 vnpy，MIT License）。

与 pip 包 ``vnpy`` 解耦：回测与全因子评估仅依赖本包 + polars/scipy 等，不 ``import vnpy``。
"""
from __future__ import annotations

from .dataset import AlphaDataset, Segment, to_datetime

__all__ = ["AlphaDataset", "Segment", "to_datetime"]
