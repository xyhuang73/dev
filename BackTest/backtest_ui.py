# -*- coding: utf-8 -*-
"""
从 Designer 生成的 BackTest.ui 加载回测子窗口，供主界面「回测」按钮调用。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFile, QIODevice
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QWidget

# 后续若在子窗体内绑定「开始回测」等控件，可在 backtest_dialog 中扩展 wire_backtest_dialog
from .backtest_dialog import refresh_backtest_panel, wire_backtest_dialog


# 项目根目录（BackTest 的上一级）
_APP_DIR = Path(__file__).resolve().parent.parent


def load_backtest_window(parent: QWidget | None = None):
    """
    加载 GUI/BackTest.ui，返回顶层窗口（一般为 QMainWindow）。

    parent: 传入主窗口便于随主窗口管理生命周期。
    """
    ui_path = _APP_DIR / "GUI" / "BackTest.ui"
    ui_file = QFile(str(ui_path))
    if not ui_file.open(QIODevice.ReadOnly):
        raise RuntimeError(f"无法打开 UI 文件: {ui_path}")

    loader = QUiLoader()
    window = loader.load(ui_file, parent)
    ui_file.close()

    if window is None:
        raise RuntimeError("加载 BackTest.ui 失败，请确认文件格式正确。")

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
