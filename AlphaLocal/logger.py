# -*- coding: utf-8 -*-
"""
轻量日志（替代 vnpy.alpha 对 loguru 的依赖，便于本地回测环境解耦）。

衍生说明：vnpy 原版使用 loguru；此处用标准库 logging，行为对因子计算无影响。
"""
from __future__ import annotations

import logging

logger = logging.getLogger("AlphaLocal")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)
