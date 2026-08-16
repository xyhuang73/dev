# -*- coding: utf-8 -*-
"""
主窗 TigerTrade 上与「回测」入口相关的信号槽。
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QMessageBox, QPushButton, QWidget

from .backtest_ui import show_backtest_window


def attach_backtest_handlers(window: QWidget) -> None:
    """
    绑定「回测」按钮：打开 GUI/BackTest.ui。

    约定：objectName 为 pushButton_3（见 GUI/TigerTrade.ui）。
    """
    btn = window.findChild(QPushButton, "pushButton_3")
    if btn is None:
        print(
            "BackTest: 未找到 pushButton_3（回测），请检查 GUI/TigerTrade.ui。",
            file=sys.stderr,
        )
        return

    def on_backtest_clicked() -> None:
        try:
            show_backtest_window(owner=window)
        except Exception as exc:  # noqa: BLE001 — 避免加载 BackTest.ui 失败时完全无反馈
            import traceback

            tb = traceback.format_exc()
            print(tb, file=sys.stderr)
            QMessageBox.critical(
                window,
                "无法打开回测窗口",
                f"{type(exc).__name__}: {exc}\n\n详见终端标准错误输出。",
            )

    btn.clicked.connect(on_backtest_clicked)
