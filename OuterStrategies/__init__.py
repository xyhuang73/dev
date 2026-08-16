# -*- coding: utf-8 -*-
"""
OuterStrategies：备用归档（与 InnerStrategy 并行保留，不参与本工程 import）。

子目录说明::
    - strategies/：VeighNa CTA 策略源码与示例，依赖 vnpy_ctastrategy。
    - strategies/from_vnpy_ctastrategy/：自官方 ``vnpy/vnpy_ctastrategy`` 复制的内置示例策略（MIT，见包内 LICENSE）。
    - _vendor/vnpy_ctastrategy/：上述官方仓库的浅克隆（``git pull`` 可更新后再按需覆盖 from_vnpy 副本）。
    - factors/：VeighNa Alpha 因子数据集类（Alpha101、Alpha158），依赖 vnpy.alpha 与 polars。

主工程运行与回测请使用 ``InnerStrategy``；若需同步到 VeighNa vntrader，可从本目录拷贝至对方策略/因子目录，
或参考 F2 仓库中的 scripts/sync_strategies_to_vntrader.py 思路自行同步。
"""
