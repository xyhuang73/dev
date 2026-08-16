# -*- coding: utf-8 -*-
"""
InnerStrategy：本工程主用的策略与因子目录（与 VeighNa / F2 侧同步时以本目录为准，可独立增删改）。
仓库内 ``OuterStrategies`` 为同源备用归档，不参与 import；需要双份对照或对外拷贝时可参考该目录。

子目录说明::
    - strategies/：CTA 策略源码；注册表按文件内每个顶层 class 分配 S 编号（配置类请放包根目录，勿放此目录）。
    - factors/：因子包（如 alpha_101.py）；单条因子在 inner_registry.json 中为 F 编号 + pack + feature。

``inner_registry.json`` 由 ``inner_registry.py`` 根据源码扫描生成；打开回测窗口时会强制重建以同步文件变更。
"""
