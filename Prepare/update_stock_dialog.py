# -*- coding: utf-8 -*-
"""
UpdateStock 子窗口：日期与 Config 同步、触发 QMT 数据下载（支持多周期）。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot, QTimer
from PySide6.QtWidgets import QCheckBox, QDateEdit, QLineEdit, QPushButton, QWidget

from qmt_service import get_update_stock_date_range, save_update_stock_date_range

from .main_window_log import append_main_log
from .qmt_history_download import QmtHistoryDownloadWorker


class _DownloadLogRelay(QObject):
    """在工作线程与主线程之间传递日志行；任务结束后恢复「更新」按钮。"""

    progress = Signal(str)  # 转发 worker 的 progress

    def __init__(self, main_window: QWidget, update_btn: QPushButton, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._main_window = main_window
        self._update_btn = update_btn
        self._pending_lines: list[str] = []
        self._update_timer = QTimer()
        self._update_timer.setInterval(500)  # 每 500ms 批量更新一次 UI
        self._update_timer.timeout.connect(self._flush_log)
        self._update_timer.start()

    @Slot()
    def _flush_log(self) -> None:
        """从待处理队列批量写入日志，防止高频 emit 淹没事件循环。"""
        if not self._pending_lines:
            return
        lines = self._pending_lines
        self._pending_lines = []
        for line in lines:
            append_main_log(self._main_window, line)

    @Slot(str)
    def on_progress(self, line: str) -> None:
        # 追加到队列，由定时器批量写入（避免 Qt 事件循环被高频信号阻塞）
        self._pending_lines.append(line)

    @Slot(bool, str)
    def on_finished(self, ok: bool, summary: str) -> None:
        self._update_timer.stop()
        # 先刷新剩余的 pending 日志
        self._flush_log()
        text = summary if ok else f"下载失败:\n{summary}"
        append_main_log(self._main_window, text)
        self._update_btn.setEnabled(True)


def _read_dates_from_ui(sub: QWidget) -> tuple[str, str] | None:
    """从子窗体读取起止日 YYYYMMDD；控件缺失时返回 None。"""
    d0 = sub.findChild(QDateEdit, "dateEdit_start_day")
    d1 = sub.findChild(QDateEdit, "dateEdit_end_day")
    if d0 is None or d1 is None:
        return None
    return d0.date().toString("yyyyMMdd"), d1.date().toString("yyyyMMdd")


def _read_periods_from_ui(sub: QWidget) -> list[str]:
    """
    从子窗体读取用户选择的下载周期。

    Returns:
        周期列表，如 ["1d", "5m"]。空列表表示未选择任何周期。
    """
    periods: list[str] = []

    # 日线
    cb_daily = sub.findChild(QCheckBox, "checkBox")
    if cb_daily is not None and cb_daily.isChecked():
        periods.append("1d")

    # 分钟线
    cb_min = sub.findChild(QCheckBox, "checkBox_2")
    le_min = sub.findChild(QLineEdit, "lineEdit_min")
    if cb_min is not None and cb_min.isChecked() and le_min is not None:
        min_text = le_min.text().strip()
        if min_text.isdigit() and int(min_text) > 0:
            minutes = int(min_text)
            periods.append(f"{minutes}m")

    return periods


def refresh_update_stock_dates(sub: QWidget) -> None:
    """从 Config 读取日期并写入两个 QDateEdit（加载时屏蔽信号避免误保存）。"""
    from PySide6.QtCore import QDate

    start_s, end_s = get_update_stock_date_range()
    d0 = sub.findChild(QDateEdit, "dateEdit_start_day")
    d1 = sub.findChild(QDateEdit, "dateEdit_end_day")
    if d0 is None or d1 is None:
        return

    qs = QDate.fromString(start_s, "yyyyMMdd")
    qe = QDate.fromString(end_s, "yyyyMMdd")
    if not qs.isValid():
        qs = QDate(2023, 1, 1)
    if not qe.isValid():
        qe = QDate(2023, 12, 31)

    d0.blockSignals(True)
    d1.blockSignals(True)
    d0.setDate(qs)
    d1.setDate(qe)
    d0.blockSignals(False)
    d1.blockSignals(False)


def _persist_dates_from_ui(sub: QWidget) -> None:
    """将当前界面日期写回 Config。"""
    pair = _read_dates_from_ui(sub)
    if pair is None:
        return
    save_update_stock_date_range(pair[0], pair[1])


def wire_update_stock_dialog(sub: QWidget, main_window: QWidget) -> None:
    """
    绑定 UpdateStock 子窗体控件（仅执行一次）；主窗口用于追加日志。

    约定控件名：
    - dateEdit_start_day, dateEdit_end_day：日期选择
    - checkBox：日线复选框
    - checkBox_2：分钟线复选框
    - lineEdit_min：分钟数输入框
    - pushButton：更新按钮
    """
    if getattr(sub, "_prepare_dialog_wired", False):
        return

    btn = sub.findChild(QPushButton, "pushButton")
    d0 = sub.findChild(QDateEdit, "dateEdit_start_day")
    d1 = sub.findChild(QDateEdit, "dateEdit_end_day")
    cb_daily = sub.findChild(QCheckBox, "checkBox")
    cb_min = sub.findChild(QCheckBox, "checkBox_2")
    le_min = sub.findChild(QLineEdit, "lineEdit_min")

    if btn is None or d0 is None or d1 is None:
        sub._prepare_dialog_wired = True
        return

    def on_date_changed() -> None:
        _persist_dates_from_ui(sub)

    d0.dateChanged.connect(on_date_changed)
    d1.dateChanged.connect(on_date_changed)

    def _periods_summary(periods: list[str]) -> str:
        labels = []
        for p in periods:
            if p == "1d":
                labels.append("日线")
            elif p.endswith("m"):
                labels.append(f"{p[:-1]}分钟")
        return " + ".join(labels) if labels else "无"

    def on_download_clicked() -> None:
        pair = _read_dates_from_ui(sub)
        if pair is None:
            return
        start_s, end_s = pair
        if start_s > end_s:
            append_main_log(main_window, "起始日期不能晚于结束日期，请修改。")
            return

        periods = _read_periods_from_ui(sub)
        if not periods:
            append_main_log(main_window, "未选择下载周期，请勾选「日线」或填写「分钟数」并勾选「分钟线」。")
            return

        save_update_stock_date_range(start_s, end_s)
        btn.setEnabled(False)

        periods_str = _periods_summary(periods)
        append_main_log(
            main_window,
            f"—— 准备从 QMT 拉取数据 —— {periods_str}\n"
            f"  日期区间: {start_s} ~ {end_s}",
        )

        worker = QmtHistoryDownloadWorker(start_s, end_s, periods)
        thread = QThread(sub)
        worker.moveToThread(thread)
        relay = _DownloadLogRelay(main_window, btn, main_window)

        thread.started.connect(worker.run)
        worker.progress.connect(relay.on_progress, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(relay.on_finished, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        setattr(sub, "_prepare_download_thread", thread)
        setattr(sub, "_prepare_download_worker", worker)
        setattr(sub, "_prepare_download_relay", relay)

        thread.start()

    btn.clicked.connect(on_download_clicked)
    sub._prepare_dialog_wired = True
