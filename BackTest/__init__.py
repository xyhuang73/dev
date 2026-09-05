# -*- coding: utf-8 -*-
"""
BackTest：回测子界面、Config/backtest.json、向量/事件引擎架构入口。

- ``config_store``：配置文件读写
- ``InnerStrategy.inner_registry``：因子/策略编号与下拉条目
- ``runner`` + ``engines``：按模式分发回测
"""

def attach_backtest_handlers(window):
    """延迟加载 Qt 界面绑定，使回测核心可在无 GUI 进程中导入和测试。"""
    from .handlers import attach_backtest_handlers as _attach  # noqa: PLC0415

    return _attach(window)

__all__ = ["attach_backtest_handlers"]
