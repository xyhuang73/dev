# -*- coding: utf-8 -*-
"""
Prepare 模块：主窗体上与「数据准备 / 更新」相关的信号槽集中在此注册。
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QPushButton, QWidget

from .update_stock_ui import show_update_stock_window


def attach_prepare_handlers(window: QWidget) -> None:
    """
    绑定 TigerTrade 主界面中与 Prepare 相关的控件。

    约定：「更新」按钮 objectName 为 pushButton_5（见 GUI/TigerTrade.ui）。
    """
    btn = window.findChild(QPushButton, "pushButton_5")
    if btn is None:
        print(
            "Prepare: 未找到 pushButton_5（更新），请检查 GUI/TigerTrade.ui。",
            file=sys.stderr,
        )
        return

    def on_update_clicked() -> None:
        # 打开 UpdateStock.ui 对应窗口；引用保存在 window._prepare_update_stock_win
        show_update_stock_window(owner=window)

    btn.clicked.connect(on_update_clicked)
