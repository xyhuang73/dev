"""
「股票信息」：统计仅读本地 datadir 下 .DAT，不依赖 xtquant / QMT 客户端（见 qmt_service.build_stock_quarter_report）。
"""
from __future__ import annotations

import sys
from typing import Union

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QPushButton, QWidget

from qmt_service import build_stock_quarter_report

# 日志控件在 .ui 中应为 QPlainTextEdit（多行）；兼容旧版单行 QLineEdit
LogWidget = Union[QPlainTextEdit, QLineEdit]


def _find_log_widget(window: QWidget) -> LogWidget | None:
    """按 objectName 查找日志区：优先多行文本框，兼容单行 QLineEdit。"""
    w = window.findChild(QPlainTextEdit, "lineEdit_log_stocks")
    if w is not None:
        return w
    return window.findChild(QLineEdit, "lineEdit_log_stocks")


def _set_log_text(edit: LogWidget, text: str) -> None:
    if isinstance(edit, QPlainTextEdit):
        edit.setPlainText(text)
    else:
        edit.setText(text)


def _apply_report_panel_style(edit: LogWidget) -> None:
    """为多行报告区设置只读、自动换行与浅色卡片样式，避免长路径挤成一行。"""
    if not isinstance(edit, QPlainTextEdit):
        return
    edit.setReadOnly(True)
    edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
    edit.setStyleSheet(
        """
        QPlainTextEdit {
            background-color: #f5f7fa;
            color: #1e293b;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 14px 16px;
            font-family: "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
            font-size: 12px;
        }
        """
    )


def attach_tiger_trade_handlers(window: QWidget) -> None:
    btn = window.findChild(QPushButton, "pushButton")
    edit = _find_log_widget(window)
    if btn is None or edit is None:
        print(
            "TigerTrade: 未找到 pushButton 或 lineEdit_log_stocks，请检查 GUI/TigerTrade.ui 控件名。",
            file=sys.stderr,
        )
        return

    _apply_report_panel_style(edit)

    def on_click() -> None:
        # 禁用按钮，避免重复点击；统计在主线程执行（见模块说明）
        btn.setEnabled(False)
        _set_log_text(
            edit,
            "正在读取本机 datadir 日 K 并统计各季度股票数量，请稍候…",
        )

        def run_report_on_main_thread() -> None:
            # 纯本地文件解析；放在主线程避免长时间占用时 UI 无响应（可再改为后台线程）
            try:
                _set_log_text(edit, build_stock_quarter_report())
            except Exception as exc:  # noqa: BLE001
                _set_log_text(edit, f"处理失败:\n{exc}")
            finally:
                btn.setEnabled(True)

        # 先让界面刷新「请稍候」再进入可能较久的统计（仍在主线程事件循环内）
        QTimer.singleShot(0, run_report_on_main_thread)

    btn.clicked.connect(on_click)
