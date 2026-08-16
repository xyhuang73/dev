# -*- coding: utf-8 -*-
"""
主窗口 TigerTrade 右侧日志区读写，与 gui_tiger 中控件名约定一致。

同时写入本地日志文件，确保长时间任务的消息不因窗口状态丢失。
"""
from __future__ import annotations

import atexit
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Union

from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QWidget

# 与 gui_tiger 一致：优先多行，兼容单行
LogWidget = Union[QPlainTextEdit, QLineEdit]

# 本地日志文件路径（写入主项目目录）
_log_file_path = Path(__file__).resolve().parent.parent / "logs" / "download_progress.log"
_log_lock = threading.Lock()


def _ensure_log_dir():
    """确保日志目录存在。"""
    _log_file_path.parent.mkdir(parents=True, exist_ok=True)


def _write_log_file(line: str) -> None:
    """线程安全地追加一行到本地日志文件。"""
    _ensure_log_dir()
    with _log_lock:
        try:
            with open(_log_file_path, "a", encoding="utf-8") as f:
                ts = datetime.now().strftime("%H:%M:%S")
                f.write(f"[{ts}] {line}\n")
        except Exception:
            pass


def find_main_log_widget(window: QWidget) -> LogWidget | None:
    """按 objectName 查找 lineEdit_log_stocks。"""
    w = window.findChild(QPlainTextEdit, "lineEdit_log_stocks")
    if w is not None:
        return w
    return window.findChild(QLineEdit, "lineEdit_log_stocks")


def set_main_log_text(window: QWidget, text: str) -> None:
    """整段替换日志文本。"""
    edit = find_main_log_widget(window)
    _write_log_file(f"[SET] {text}")
    if edit is None:
        return
    if isinstance(edit, QPlainTextEdit):
        edit.setPlainText(text)
    else:
        edit.setText(text)


def append_main_log(window: QWidget, line: str) -> None:
    """追加一行（自动换行），用于长时间任务进度输出。"""
    # 始终写入本地文件（不怕窗口关闭）
    _write_log_file(line)

    edit = find_main_log_widget(window)
    if edit is None:
        return
    if isinstance(edit, QPlainTextEdit):
        # 追加到 QPlainTextEdit（Qt 事件循环处理）
        edit.appendPlainText(line)
    else:
        prev = edit.text()
        edit.setText(f"{prev}\n{line}" if prev else line)


def clear_local_log() -> None:
    """清空本地日志文件。"""
    _ensure_log_dir()
    with _log_lock:
        try:
            if _log_file_path.exists():
                _log_file_path.unlink()
        except Exception:
            pass
