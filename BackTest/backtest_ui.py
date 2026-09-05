# -*- coding: utf-8 -*-
"""
从 Designer 生成的 BackTest.ui 加载回测子窗口，供主界面「回测」按钮调用。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFile, QIODevice, Qt
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QWidget

# 后续若在子窗体内绑定「开始回测」等控件，可在 backtest_dialog 中扩展 wire_backtest_dialog
from .backtest_dialog import refresh_backtest_panel, wire_backtest_dialog


# 项目根目录（BackTest 的上一级）
_APP_DIR = Path(__file__).resolve().parent.parent


def load_backtest_window(parent: QWidget | None = None):
    """
    加载 GUI/BackTest.ui，返回顶层窗口（QMainWindow）。

    重要：``QUiLoader.load`` 的 ``parent`` 参数会把加载出来的窗口「认作」主窗的
    Qt 子对象，Windows 任务栏会把两个窗口合并成一个条目，主窗点最小化时子窗
    也会跟着消失。生命周期引用已在 ``show_backtest_window`` 里通过
    ``setattr(owner, "_backtest_win", w)`` 单独保留，因此这里把 ``parent`` 一律传
    ``None``，让回测窗成为真正的独立顶层窗口（独立任务栏条目、独立最小化）。
    加载完成后再用 ``Qt.Window`` 显式声明窗口类型并强制显示最小化/最大化/关闭按钮。
    """
    ui_path = _APP_DIR / "GUI" / "BackTest.ui"
    ui_file = QFile(str(ui_path))
    if not ui_file.open(QIODevice.ReadOnly):
        raise RuntimeError(f"无法打开 UI 文件: {ui_path}")

    loader = QUiLoader()
    # 关键：parent=None，让回测窗是独立顶层窗口，不再跟随主窗最小化。
    window = loader.load(ui_file, None)
    ui_file.close()

    if window is None:
        raise RuntimeError("加载 BackTest.ui 失败，请确认文件格式正确。")

    # 显式声明：独立顶级窗口，强制显示 Min/Max/Close 按钮。
    window.setWindowFlags(
        Qt.Window
        | Qt.WindowMinimizeButtonHint
        | Qt.WindowMaximizeButtonHint
        | Qt.WindowCloseButtonHint
        | Qt.WindowSystemMenuHint
    )
    # 某些主题下还要把 window 属性置位，否则 QMainWindow 会被当 MDI 子窗。
    window.setAttribute(Qt.WA_DeleteOnClose, False)

    window.setWindowTitle("回测")
    return window


def show_backtest_window(owner: QWidget | None = None):
    """
    显示回测界面：非模态；已创建过则复用实例（含用户曾关闭子窗体的情况）。

    owner: 主窗口，引用保存在 _backtest_win 属性上。
    """
    if owner is not None:
        existing = getattr(owner, "_backtest_win", None)
        if existing is not None:
            wire_backtest_dialog(existing, owner)
            refresh_backtest_panel(existing)
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return existing

    w = load_backtest_window(parent=owner)
    if owner is not None:
        setattr(owner, "_backtest_win", w)
        wire_backtest_dialog(w, owner)
        refresh_backtest_panel(w)
    w.show()
    w.raise_()
    w.activateWindow()
    return w
