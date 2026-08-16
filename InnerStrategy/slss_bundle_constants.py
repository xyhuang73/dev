# -*- coding: utf-8 -*-
"""
SLSS 对外常量（无 vnpy 依赖）：从 ``Config/slss_strategy.json`` 同步。

修改因子包、权重、阈值等请编辑 ``Config/slss_strategy.json`` 后重启进程。
"""
from __future__ import annotations

from InnerStrategy.slss_strategy_config import load_slss_strategy_config

_cfg = load_slss_strategy_config()
BUNDLE_FACTOR_IDS: tuple[str, ...] = _cfg.bundle_factor_ids
STRATIFIED_LONG_SHORT_SHARPE_OBJECTIVE_EN: str = _cfg.stratified_long_short_sharpe_objective_en
