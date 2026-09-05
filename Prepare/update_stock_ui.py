# -*- coding: utf-8 -*-
"""
从 Designer 生成的 UpdateStock.ui 加载子窗口，供主界面「更新」按钮调用。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFile, QIODevice, Qt
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QWidget

from .update_stock_dialog import refresh_update_stock_dates, wire_update_stock_dialog


# 项目根目录（Prepare 的上一级），用于解析 GUI 相对路径
_APP_DIR = Path(__file__).resolve().parent.parent


def load_update_stock_window(parent: QWidget | None = None):
    """
    加载 GUI/UpdateStock.ui，返回顶层窗口控件（QMainWindow）。

    重要：``QUiLoader.load`` 的 ``parent`` 参数会把加载出来的窗口「认作」主窗的
    Qt 子对象，Windows 任务栏会把两个窗口合并成一个条目，主窗点最小化时子窗
    也会跟着消失。生命周期引用已在 ``show_update_stock_window`` 里通过
    ``setattr(owner, "_prepare_update_stock_win", w)`` 单独保留，因此这里把
    ``parent`` 一律传 ``None``，让更新窗成为真正的独立顶层窗口。
    加载完成后再用 ``Qt.Window`` 显式声明窗口类型并强制显示最小化/最大化/关闭按钮。
    """
    ui_path = _APP_DIR / "GUI" / "UpdateStock.ui"
    ui_file = QFile(str(ui_path))
    if not ui_file.open(QIODevice.ReadOnly):
        raise RuntimeError(f"无法打开 UI 文件: {ui_path}")

    loader = QUiLoader()
    # 关键：parent=None，让更新窗是独立顶层窗口，不再跟随主窗最小化。
    window = loader.load(ui_file, None)
    ui_file.close()

    if window is None:
        raise RuntimeError("加载 UpdateStock.ui 失败，请确认文件格式正确。")

    window.setWindowFlags(
        Qt.Window
        | Qt.WindowMinimizeButtonHint
        | Qt.WindowMaximizeButtonHint
        | Qt.WindowCloseButtonHint
        | Qt.WindowSystemMenuHint
    )
    window.setAttribute(Qt.WA_DeleteOnClose, False)

    window.setWindowTitle("更新股票数据")
    return window


def show_update_stock_window(owner: QWidget | None = None):
    """
    显示「更新」子界面：非模态，便于与主窗口并存。

    owner: 主窗口，用于设置父对象及保存引用属性 _prepare_update_stock_win；
           若该窗口已存在且仍可见，则直接置顶而非重复创建。
    """
    # 已创建过则复用（含用户曾关闭子窗体的情况），避免重复实例化
    if owner is not None:
        existing = getattr(owner, "_prepare_update_stock_win", None)
        if existing is not None:
            wire_update_stock_dialog(existing, owner)
            refresh_update_stock_dates(existing)
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return existing

    w = load_update_stock_window(parent=owner)
    if owner is not None:
        setattr(owner, "_prepare_update_stock_win", w)
        wire_update_stock_dialog(w, owner)
        refresh_update_stock_dates(w)
    w.show()
    w.raise_()
    w.activateWindow()
    return w
