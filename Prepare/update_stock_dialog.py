# -*- coding: utf-8 -*-
"""
UpdateStock 子窗口：日期与 Config 同步、触发 QMT 数据下载（支持多周期）。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot, QTimer
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QCheckBox, QComboBox, QDateEdit, QLineEdit, QPushButton, QWidget

from qmt_service import get_local_datadir, get_update_stock_date_range, save_update_stock_date_range

from .main_window_log import append_main_log, set_main_log_text
from .qmt_history_download import QmtHistoryDownloadWorker
from quant.data.localdata_config import load_localdata_ui_config, save_localdata_ui_config


class _LocalDataImportWorker(QObject):
    progress = Signal(str)
    stock_progress = Signal(int, int)
    finished = Signal(bool, str)

    def __init__(self, source: str, period: str, start: str, end: str, max_symbols: int,
                 expected_symbols: int) -> None:
        super().__init__()
        self.source, self.period, self.start, self.end = source, period, start, end
        self.max_symbols = max_symbols
        self.expected_symbols = expected_symbols

    @Slot()
    def run(self) -> None:
        try:
            from quant.data.localdata_import import import_q_daily, import_t_daily, import_t_minute
            final_stock_total = self.expected_symbols

            if self.source == "T" and self.period == "1d":
                result = import_t_daily(self.start, self.end, progress=self.progress.emit,
                                        max_symbols=self.max_symbols, stock_progress=self.stock_progress.emit)
            elif self.source == "T" and self.period == "1m":
                parts = []
                selected_symbols: set[str] = set()
                years = list(range(int(self.start[:4]), int(self.end[:4]) + 1))
                total_jobs = max(1, self.expected_symbols * len(years))
                final_stock_total = total_jobs
                for year_index, year in enumerate(years):
                    parts.append(import_t_minute(year, self.start, self.end, progress=self.progress.emit,
                                                 max_symbols=self.max_symbols,
                                                 selected_symbols=selected_symbols,
                                                 stock_progress=lambda done, _total, base=year_index * self.expected_symbols:
                                                 self.stock_progress.emit(base + done, total_jobs)))
                result = {
                    "files": sum(p.get("files", 0) for p in parts),
                    "rows_written": sum(p.get("rows_written", 0) for p in parts),
                    "database": parts[-1]["database"] if parts else "",
                    "status": "completed" if all(p.get("status") == "completed" for p in parts) else "completed_with_rejects",
                }
            elif self.source == "Q" and self.period == "1d":
                result = import_q_daily(get_local_datadir(), self.start, self.end,
                                        progress=self.progress.emit, max_symbols=self.max_symbols,
                                        stock_progress=self.stock_progress.emit)
            else:
                raise ValueError(f"不支持的数据源: {self.source}")

            written = result.get("rows_written", 0)
            files = result.get("files", 0)
            status = result.get("status", "completed")
            ok = status == "completed" and written > 0
            if ok:
                self.stock_progress.emit(final_stock_total, final_stock_total)
            summary = (
                f"LocalData 导入{'完成' if ok else '结束，但未写入数据或存在文件错误'}："
                f"{written:,} 行，扫描 {files:,} 个文件。\n"
                f"数据库：{result.get('database', 'E:/03_back_test_data/LocalData/market.duckdb')}\n"
                f"状态：{status}"
            )
            self.finished.emit(ok, summary)
        except Exception as exc:
            self.finished.emit(False, f"{type(exc).__name__}: {exc}")


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


class _LocalImportLogRelay(_DownloadLogRelay):
    def __init__(self, main_window: QWidget, update_btn: QPushButton, progress_label: QWidget,
                 parent: QObject | None = None) -> None:
        super().__init__(main_window, update_btn, parent)
        self._progress_label = progress_label

    @Slot(int, int)
    def on_stock_progress(self, done: int, total: int) -> None:
        remaining = max(0, total - done)
        self._progress_label.setText(
            f"转换进度：已完成 {done:,}/{total:,} 个股票数据文件，剩余 {remaining:,} 个"
        )

    @Slot(bool, str)
    def on_finished(self, ok: bool, summary: str) -> None:
        self._update_timer.stop()
        self._flush_log()
        append_main_log(self._main_window, summary if ok else f"LocalData 导入失败:\n{summary}")
        self._progress_label.setText("转换进度：已完成，剩余 0 个" if ok else "转换进度：导入失败")
        self._update_btn.setEnabled(True)


class _AvailabilityWorker(QObject):
    finished = Signal(int, int, str)

    def __init__(self, request_id: int, source: str, period: str, start: str, end: str) -> None:
        super().__init__()
        self.request_id, self.source, self.period = request_id, source, period
        self.start, self.end = start, end

    @Slot()
    def run(self) -> None:
        try:
            from quant.data.localdata_import import count_available_symbols
            datadir = get_local_datadir() if self.source == "Q" else None
            count = count_available_symbols(self.source, self.period, self.start, self.end,
                                            datadir=datadir)
            self.finished.emit(self.request_id, count, "")
        except Exception as exc:
            self.finished.emit(self.request_id, 0, f"{type(exc).__name__}: {exc}")


class _LocalDataReportWorker(QObject):
    finished = Signal(str)

    @Slot()
    def run(self) -> None:
        try:
            from quant.data.localdata_import import build_localdata_stock_quarter_report
            report = build_localdata_stock_quarter_report()
        except Exception as exc:
            report = f"LocalData 股票信息统计失败：{type(exc).__name__}: {exc}"
        self.finished.emit(report)


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
    """恢复 QMT 日期与 LocalData 转换选项。"""
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
    c0 = sub.findChild(QDateEdit, "dateEdit_convert_start")
    c1 = sub.findChild(QDateEdit, "dateEdit_convert_end")
    source_combo = sub.findChild(QComboBox, "comboBox_local_source")
    period_combo = sub.findChild(QComboBox, "comboBox_local_period")
    max_symbols_edit = sub.findChild(QLineEdit, "lineEdit_max_symbols")
    cfg = load_localdata_ui_config()

    if source_combo is not None and period_combo is not None and c0 is not None and c1 is not None:
        source_combo.blockSignals(True)
        source_index = source_combo.findData(cfg.get("source", "T"))
        source_combo.setCurrentIndex(source_index if source_index >= 0 else 0)
        source_combo.blockSignals(False)
        rebuild_periods = getattr(sub, "_localdata_rebuild_periods", None)
        if rebuild_periods:
            rebuild_periods()
        period_combo.blockSignals(True)
        period_index = period_combo.findData(cfg.get("period", "1d"))
        period_combo.setCurrentIndex(period_index if period_index >= 0 else 0)
        period_combo.blockSignals(False)

        start_convert = QDate.fromString(str(cfg.get("convert_start", "")), "yyyyMMdd")
        end_convert = QDate.fromString(str(cfg.get("convert_end", "")), "yyyyMMdd")
        c0.blockSignals(True)
        c1.blockSignals(True)
        c0.setDate(start_convert if start_convert.isValid() else qs)
        c1.setDate(end_convert if end_convert.isValid() else qe)
        c0.blockSignals(False)
        c1.blockSignals(False)

    saved_max = cfg.get("max_symbols")
    if max_symbols_edit is not None:
        max_symbols_edit.setText(str(saved_max) if isinstance(saved_max, int) and saved_max >= 0 else "")
    setattr(sub, "_localdata_manual_count", isinstance(saved_max, int) and saved_max >= 0)
    schedule_count = getattr(sub, "_localdata_schedule_count", None)
    if schedule_count:
        schedule_count(preserve_manual=isinstance(saved_max, int) and saved_max >= 0)


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

    local_info_btn = sub.findChild(QPushButton, "pushButton_local_stock_info")
    if local_info_btn is not None:
        def on_local_stock_info_clicked() -> None:
            local_info_btn.setEnabled(False)
            set_main_log_text(main_window, "正在统计 LocalData 各季度股票数量，请稍候…")
            worker = _LocalDataReportWorker()
            thread = QThread(sub)
            worker.moveToThread(thread)

            def show_report(report: str) -> None:
                set_main_log_text(main_window, report)
                local_info_btn.setEnabled(True)

            worker.finished.connect(show_report, Qt.ConnectionType.QueuedConnection)
            thread.started.connect(worker.run)
            worker.finished.connect(thread.quit)
            thread.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            setattr(sub, "_localdata_info_thread", thread)
            setattr(sub, "_localdata_info_worker", worker)
            thread.start()

        local_info_btn.clicked.connect(on_local_stock_info_clicked)

    import_btn = sub.findChild(QPushButton, "pushButton_local_import")
    source_combo = sub.findChild(QComboBox, "comboBox_local_source")
    if import_btn is not None and source_combo is not None:
        period_combo = sub.findChild(QComboBox, "comboBox_local_period")
        convert_start = sub.findChild(QDateEdit, "dateEdit_convert_start")
        convert_end = sub.findChild(QDateEdit, "dateEdit_convert_end")
        max_symbols_edit = sub.findChild(QLineEdit, "lineEdit_max_symbols")
        if period_combo is None or convert_start is None or convert_end is None or max_symbols_edit is None:
            sub._prepare_dialog_wired = True
            return

        # QUiLoader 对 Designer item 的 userData 支持不一致，代码中明确设定稳定的源 ID。
        for index, source_id in enumerate(("T", "Q")):
            if index < source_combo.count():
                source_combo.setItemData(index, source_id)
        max_symbols_edit.setValidator(QIntValidator(0, 100_000, max_symbols_edit))
        max_symbols_edit.setText("")

        def rebuild_periods() -> None:
            source = str(source_combo.currentData() or "T")
            previous = str(period_combo.currentData() or "1d")
            period_combo.blockSignals(True)
            period_combo.clear()
            period_combo.addItem("日线", "1d")
            if source == "T":
                period_combo.addItem("1分钟线", "1m")
            selected = period_combo.findData(previous)
            period_combo.setCurrentIndex(selected if selected >= 0 else 0)
            period_combo.blockSignals(False)

        rebuild_periods()
        setattr(sub, "_localdata_rebuild_periods", rebuild_periods)
        source_combo.currentIndexChanged.connect(rebuild_periods)

        def persist_localdata_preferences() -> None:
            count_text = max_symbols_edit.text().strip()
            save_localdata_ui_config({
                "source": str(source_combo.currentData() or "T"),
                "period": str(period_combo.currentData() or "1d"),
                "convert_start": convert_start.date().toString("yyyyMMdd"),
                "convert_end": convert_end.date().toString("yyyyMMdd"),
                "max_symbols": int(count_text) if count_text.isdigit() else None,
            })

        def schedule_availability_count(*, preserve_manual: bool = False) -> None:
            if not preserve_manual:
                setattr(sub, "_localdata_manual_count", False)
                max_symbols_edit.setText("统计中…")
            setattr(sub, "_localdata_available_count", None)
            timer = getattr(sub, "_localdata_count_timer", None)
            if timer is None:
                timer = QTimer(sub)
                timer.setSingleShot(True)
                timer.setInterval(350)
                timer.timeout.connect(start_availability_count)
                setattr(sub, "_localdata_count_timer", timer)
            timer.start()

        def queue_availability_count(*_args) -> None:
            schedule_availability_count()

        def on_count_finished(request_id: int, count: int, error: str) -> None:
            if request_id != getattr(sub, "_localdata_count_request_id", 0):
                return
            setattr(sub, "_localdata_available_count", count)
            if not getattr(sub, "_localdata_manual_count", False):
                max_symbols_edit.setText(str(count))
            persist_localdata_preferences()
            if not getattr(sub, "_localdata_import_active", False):
                import_btn.setEnabled(True)
            if error:
                append_main_log(main_window, f"统计当前日期范围内可用股票数失败：{error}")

        def on_max_symbols_edited(_text: str) -> None:
            setattr(sub, "_localdata_manual_count", True)
            persist_localdata_preferences()

        def start_availability_count() -> None:
            pair = (convert_start.date().toString("yyyyMMdd"), convert_end.date().toString("yyyyMMdd"))
            if pair[0] > pair[1]:
                max_symbols_edit.setText("0")
                append_main_log(main_window, "转换起始日期不能晚于转换终止日期。")
                return
            request_id = getattr(sub, "_localdata_count_request_id", 0) + 1
            setattr(sub, "_localdata_count_request_id", request_id)
            worker = _AvailabilityWorker(request_id, str(source_combo.currentData()),
                                         str(period_combo.currentData()), *pair)
            thread = QThread(sub)
            worker.moveToThread(thread)
            worker.finished.connect(on_count_finished, Qt.ConnectionType.QueuedConnection)
            thread.started.connect(worker.run)
            worker.finished.connect(thread.quit)
            thread.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            setattr(sub, "_localdata_count_thread", thread)
            setattr(sub, "_localdata_count_worker", worker)
            thread.start()

        source_combo.currentIndexChanged.connect(queue_availability_count)
        source_combo.currentIndexChanged.connect(lambda *_: persist_localdata_preferences())
        period_combo.currentIndexChanged.connect(queue_availability_count)
        period_combo.currentIndexChanged.connect(lambda *_: persist_localdata_preferences())
        convert_start.dateChanged.connect(queue_availability_count)
        convert_start.dateChanged.connect(lambda *_: persist_localdata_preferences())
        convert_end.dateChanged.connect(queue_availability_count)
        convert_end.dateChanged.connect(lambda *_: persist_localdata_preferences())
        setattr(sub, "_localdata_queue_count", queue_availability_count)
        setattr(sub, "_localdata_schedule_count", schedule_availability_count)
        max_symbols_edit.textEdited.connect(on_max_symbols_edited)
        max_symbols_edit.editingFinished.connect(persist_localdata_preferences)

        def on_local_import_clicked() -> None:
            start_s = convert_start.date().toString("yyyyMMdd")
            end_s = convert_end.date().toString("yyyyMMdd")
            if start_s > end_s:
                append_main_log(main_window, "转换起始日期不能晚于转换终止日期，请修改。")
                return

            source = str(source_combo.currentData() or "")
            period = str(period_combo.currentData() or "")
            labels = {"T": "T CSV", "Q": "QMT 本地 DAT"}
            period_label = {"1d": "日线", "1m": "1分钟线"}.get(period, period)
            count_text = max_symbols_edit.text().strip()
            if not count_text.isdigit():
                append_main_log(main_window, "请等待可用股票数统计完成，或输入有效的最大股票数。")
                return
            max_symbols = int(count_text)
            if max_symbols <= 0:
                append_main_log(main_window, "当前日期范围内没有可转换股票，或最大股票数为 0。")
                return
            available_symbols = getattr(sub, "_localdata_available_count", None)
            if available_symbols == 0:
                append_main_log(main_window, "当前日期范围内没有可用股票，请确认来源目录和转换日期。")
                return
            effective_limit = min(max_symbols, available_symbols) if available_symbols is not None else max_symbols
            expected_symbols = effective_limit
            setattr(sub, "_localdata_import_active", True)
            import_btn.setEnabled(False)
            progress_label = sub.findChild(QWidget, "label_import_progress")
            if progress_label is not None:
                progress_label.setText(f"转换进度：准备导入，最多 {expected_symbols:,} 个股票数据文件")
            append_main_log(main_window, f"—— 导入 {labels.get(source, source)} / {period_label} 到 LocalData ——\n"
                                        f"转换区间：{convert_start.date().toString('yyyyMMdd')} ~ {convert_end.date().toString('yyyyMMdd')}\n"
                                        f"最大股票数：{max_symbols}")

            worker = _LocalDataImportWorker(source, period, start_s, end_s, effective_limit, expected_symbols)
            thread = QThread(sub)
            worker.moveToThread(thread)
            relay = _LocalImportLogRelay(main_window, import_btn, progress_label, main_window)
            thread.started.connect(worker.run)
            worker.progress.connect(relay.on_progress, Qt.ConnectionType.QueuedConnection)
            worker.finished.connect(relay.on_finished, Qt.ConnectionType.QueuedConnection)
            worker.stock_progress.connect(relay.on_stock_progress, Qt.ConnectionType.QueuedConnection)
            worker.finished.connect(lambda *_: setattr(sub, "_localdata_import_active", False),
                                    Qt.ConnectionType.QueuedConnection)
            worker.finished.connect(thread.quit)
            thread.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            setattr(sub, "_localdata_import_thread", thread)
            setattr(sub, "_localdata_import_worker", worker)
            setattr(sub, "_localdata_import_relay", relay)
            thread.start()

        import_btn.clicked.connect(on_local_import_clicked)
    sub._prepare_dialog_wired = True
