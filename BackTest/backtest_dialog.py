# -*- coding: utf-8 -*-
"""
BackTest 子窗口：配置与 UI 同步、因子/策略下拉、向量/事件引擎分发入口。
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Union

import pandas as pd
from PySide6.QtCore import QObject, QThread, QDate, QTimer, Slot, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

# 新版 UI 用 QPlainTextEdit（plainTextEdit_result）；兼容旧版单行 lineEdit
ResultWidget = Union[QPlainTextEdit, QLineEdit]


class _FactorEvalUiBridge(QObject):
    """
    将 FactorEvaluationWorker 的信号投递到主线程再更新控件。

    背景：工作线程里 ``emit`` 的 Signal 若连接到普通 Python 函数/lambda，
    在 PySide6 下槽函数可能仍运行在工作线程，直接改 QPlainTextEdit 会触发未定义行为甚至进程静默崩溃。
    本桥接对象挂到主线程窗口 ``sub`` 上，槽函数运行于 GUI 线程。
    """

    def __init__(
        self,
        parent: QWidget,
        result_widget: ResultWidget | None,
        btn_factor: QPushButton | None,
        thread: QThread,
        worker: "FactorEvaluationWorker",
    ) -> None:
        super().__init__(parent)
        self._result_widget = result_widget
        self._btn_factor = btn_factor
        self._thread = thread
        self._worker = worker
        self._host = parent

    @Slot(str)
    def on_progress(self, line: str) -> None:
        # 与向量 SLSS 一致：终端留痕 + 对话框追加（无进度条）
        print(line, flush=True)
        _append_result_text(self._result_widget, line)

    @Slot(bool, str)
    def on_finished(self, _ok: bool, msg: str) -> None:
        # _ok：成功与否均已写入 msg，此处仅用于信号签名兼容
        _append_result_text(self._result_widget, "—— 结束 ——")
        _append_result_text(self._result_widget, msg)
        if self._btn_factor is not None:
            self._btn_factor.setEnabled(True)
        self._thread.quit()
        if not self._thread.wait(120_000):
            _append_result_text(self._result_widget, "（警告：后台线程未能及时结束。）")
        self._worker.deleteLater()
        self._thread.deleteLater()
        setattr(self._host, "_factor_eval_thread", None)
        setattr(self._host, "_factor_eval_worker", None)
        self.deleteLater()


# 因子/策略下拉数据直接来自 InnerStrategy 注册表（避免经 catalog 再转发一层）
from InnerStrategy.inner_registry import (
    default_factor_id,
    default_strategy_id,
    list_factor_entries,
    list_strategy_entries,
    resolve_strategy_key,
)
from .config_store import dict_to_job, job_to_dict, load_backtest_json, save_backtest_json
from .factor_evaluation_settings import (
    is_local_datadir_market_source,
    load_factor_evaluation_json,
    patch_factor_evaluation_json,
)
from .factor_evaluation_worker import FactorEvaluationWorker
from .qmt_client_guard import require_qmt_client_for_xtdata_datafeed
from .backtest_strategy_report_excel import ensure_backtest_excel_report
from .factor_local_datadir_panel import build_daily_market_panel_from_local_datadir
from .runner import run_backtest
from quant.report.performance import (
    PerformanceSummary,
    build_nav_comparison,
    calculate_symbol_performance,
    load_performance_summary,
)


BENCHMARK_SYMBOL = "000300.SH"
BENCHMARK_NAME = "沪深300"


def _ui_search_root(sub: QWidget) -> QWidget:
    """
    在 QMainWindow 上优先从 centralwidget 查找子控件。

    部分加载场景下对顶层窗口 ``findChild`` 与对 centralwidget 查找结果不一致，
    从内容区根节点搜索可避免找不到「策略回测」按钮或结果框。
    """
    if isinstance(sub, QMainWindow):
        cw = sub.centralWidget()
        if cw is not None:
            return cw
    return sub


def _find_result_widget(sub: QWidget) -> ResultWidget | None:
    """查找回测输出区：优先多行 plainTextEdit_result，兼容旧版 objectName=lineEdit。"""
    root = _ui_search_root(sub)
    w = root.findChild(QPlainTextEdit, "plainTextEdit_result")
    if w is not None:
        return w
    return root.findChild(QLineEdit, "lineEdit")


def _apply_result_panel_style(edit: ResultWidget | None) -> None:
    """多行结果区：自动换行、只读样式，与主窗股票信息报告区风格协调。"""
    if edit is None or not isinstance(edit, QPlainTextEdit):
        return
    edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
    edit.setStyleSheet(
        """
        QPlainTextEdit {
            background-color: #f8fafc;
            color: #1e293b;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 12px 14px;
            font-family: "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
            font-size: 12px;
        }
        """
    )


def _set_result_text(edit: ResultWidget | None, text: str) -> None:
    """写入回测说明；PlainTextEdit 用 setPlainText，单行 LineEdit 用 setText。"""
    if edit is None:
        return
    if isinstance(edit, QPlainTextEdit):
        edit.setPlainText(text)
    else:
        edit.setText(text)


def _append_result_text(edit: ResultWidget | None, text: str) -> None:
    """追加一行说明；仅多行控件支持追加。"""
    if edit is None:
        return
    if isinstance(edit, QPlainTextEdit):
        edit.appendPlainText(text)
    else:
        cur = edit.text()
        edit.setText((cur + "\n" + text).strip())


def _project_root() -> Path:
    """以 BackTest 目录为锚点推导项目根目录。"""
    return Path(__file__).resolve().parent.parent


def _report_sheet_names(path: Path) -> set[str]:
    """轻量读取 Excel sheet 名；损坏或非 Excel 文件返回空集合。"""
    try:
        with pd.ExcelFile(path) as book:
            return set(book.sheet_names)
    except Exception:  # noqa: BLE001 - 扫描历史产物时跳过损坏文件
        return set()


def _report_has_stock_detail(path: Path) -> bool:
    """报告是否能作为股票列表、K 线标记的有效数据源。"""
    sheets = _report_sheet_names(path)
    return bool(sheets & {"按股票汇总统计", "按ETF汇总统计", "逐笔买卖明细"})


def _report_identity(path: Path) -> tuple[str | None, str | None]:
    """从回测任务 sheet 读取 ``(strategy_key, backtest_mode)``。"""
    try:
        task = pd.read_excel(path, sheet_name="回测任务")
    except Exception:  # noqa: BLE001 - 兼容没有任务 sheet 的旧报告
        return None, None
    if task.empty or not {"key", "value"}.issubset(task.columns):
        return None, None
    values = {
        str(key).strip(): str(value).strip()
        for key, value in zip(task["key"], task["value"])
        if pd.notna(key) and pd.notna(value)
    }
    return values.get("strategy_key"), values.get("backtest_mode")


def _latest_strategy_report_path(
    *,
    strategy_key: str | None = None,
    backtest_mode: str | None = None,
    require_stock_detail: bool = True,
) -> Path | None:
    """返回匹配策略/模式的最新有效报告，自动跳过事件占位报告。"""
    # 约定目录与 backtest_strategy_report_excel 中保持一致。
    # 注意：向量 SLSS 把汇总 xlsx 写到「同名子目录」里（例如
    # ``reports/strategy/strategy_backtest_SLSS_S000002_20260830_114858/…xlsx``），
    # ``Path.glob`` 不递归，会漏掉这些报告，所以这里必须用 ``rglob``。
    # 文件名匹配 ``strategy_backtest_*.xlsx`` 已自动排除 ``trades_<symbol>.xlsx`` 这类单票文件。
    report_dir = _project_root() / "reports" / "strategy"
    if not report_dir.is_dir():
        return None
    paths = sorted(
        report_dir.rglob("strategy_backtest_*.xlsx"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in paths:
        if require_stock_detail and not _report_has_stock_detail(path):
            continue
        report_strategy, report_mode = _report_identity(path)
        if strategy_key:
            if report_strategy and report_strategy != strategy_key:
                continue
            if not report_strategy and strategy_key not in path.name:
                continue
        if backtest_mode and report_mode and report_mode != backtest_mode:
            continue
        return path
    return None


def _extract_success_symbols_from_report(path: Path) -> tuple[list[str], str]:
    """
    从策略报告提取股票列表。

    优先级：
      1. ``按股票汇总统计`` 或 ``按ETF汇总统计`` sheet 的第一列；
      2. 否则退回到 ``逐笔买卖明细`` sheet 的 ``vt_symbol`` 列
         （新版向量 SLSS 报告——``按股票汇总统计`` 已被拆到单票 xlsx，
         主汇总 xlsx 只保留 ``逐笔买卖明细``，里面仍带 ``vt_symbol`` 列）。
      3. 都没有时返回空列表 + 说明。

    口径：不做盈亏筛选，去重保序。
    """
    def _clean(series: pd.Series) -> list[str]:
        return (
            series.astype(str)
            .str.strip()
            .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
            .dropna()
            .drop_duplicates()
            .tolist()
        )

    # 1) 优先读汇总 sheet（兼容股票和 ETF 两种报告命名）。
    for sheet_name in ("按股票汇总统计", "按ETF汇总统计"):
        try:
            df = pd.read_excel(path, sheet_name=sheet_name)
        except Exception:  # noqa: BLE001 — sheet 不存在 / 文件格式异常
            df = None
        if df is not None and not df.empty and len(df.columns) >= 1:
            first_col = df.columns[0]
            syms = _clean(df[first_col])
            if syms:
                return syms, f"加载口径：{sheet_name}第一列「{first_col}」，不做盈亏筛选。"

    # 2) 回退到「逐笔买卖明细」sheet 的 vt_symbol 列（新版 SLSS 主汇总文件）。
    try:
        td = pd.read_excel(path, sheet_name="逐笔买卖明细")
    except Exception:  # noqa: BLE001
        td = None
    if td is not None and not td.empty and "vt_symbol" in td.columns:
        syms = _clean(td["vt_symbol"])
        if syms:
            return syms, "加载口径：逐笔买卖明细 vt_symbol 列（SLSS 新版主汇总不含「按股票汇总统计」时的回退）。"

    # 3) 都没有：返回空列表与说明。
    return [], "有效交易报告当前没有可展示的股票。"


def _current_report_selection(sub: QWidget) -> tuple[str, str]:
    """读取当前策略与回测模式，作为窗体内报告记忆键。"""
    root = _ui_search_root(sub)
    strategy_combo = root.findChild(QComboBox, "comboBox_strategy")
    mode_combo = root.findChild(QComboBox, "comboBox_backtest_mode")
    strategy_key = str(strategy_combo.currentData() or default_strategy_id()) if strategy_combo else default_strategy_id()
    backtest_mode = str(mode_combo.currentData() or "vector") if mode_combo else "vector"
    return strategy_key, backtest_mode


def _remember_bound_report(sub: QWidget, path: Path) -> None:
    """按策略/模式记忆有效报告，并设为当前图表数据源。"""
    resolved = str(path.resolve())
    paths = dict(getattr(sub, "_report_paths_by_selection", {}) or {})
    report_strategy, report_mode = _report_identity(path)
    key = (report_strategy, report_mode) if report_strategy and report_mode else _current_report_selection(sub)
    paths[key] = resolved
    setattr(sub, "_report_paths_by_selection", paths)
    setattr(sub, "_latest_strategy_excel_path", resolved)


def _restore_report_for_current_selection(
    sub: QWidget,
    result_widget: ResultWidget | None,
) -> bool:
    """恢复当前策略/模式的有效报告；没有时保留现有展示，不清空股票。"""
    strategy_key, backtest_mode = _current_report_selection(sub)
    paths = dict(getattr(sub, "_report_paths_by_selection", {}) or {})
    remembered = paths.get((strategy_key, backtest_mode))
    candidate = Path(remembered) if remembered else None
    if candidate is None or not candidate.is_file() or not _report_has_stock_detail(candidate):
        candidate = _latest_strategy_report_path(
            strategy_key=strategy_key,
            backtest_mode=backtest_mode,
        )
    # 事件引擎尚未完成时，允许继续展示该策略最近一次有效向量结果。
    if candidate is None and backtest_mode == "event":
        candidate = _latest_strategy_report_path(strategy_key=strategy_key, backtest_mode="vector")
    if candidate is None:
        return False
    loaded = _load_stock_list_to_combo_from_latest_report(sub, result_widget, candidate)
    if loaded:
        setattr(sub, "_performance_report_path", None)
        _render_finance_plot(sub, result_widget)
        _render_k_plot(sub, result_widget)
    return loaded


def _load_stock_list_to_combo_from_latest_report(
    sub: QWidget,
    result_widget: ResultWidget | None,
    report_path: str | Path | None = None,
) -> bool:
    """把同一份绑定报告的股票列表加载到下拉框。

    ``report_path`` 由本次回测结果显式传入；首次打开窗口时才回退到全局最新
    报告。选定后会保存到窗体，K 线和成交标记只使用这一路径。
    """
    root = _ui_search_root(sub)
    combo = root.findChild(QComboBox, "comboBox_stock_list")
    if combo is None:
        _append_result_text(result_widget, "未找到 comboBox_stock_list，跳过股票列表加载。")
        return False
    bound = Path(report_path) if report_path else None
    if bound is None:
        remembered = getattr(sub, "_latest_strategy_excel_path", None)
        bound = Path(remembered) if remembered else _latest_strategy_report_path()
    if bound is None or not bound.is_file():
        _append_result_text(result_widget, "未找到有效策略回测报告，保留当前股票列表。")
        return False
    if not _report_has_stock_detail(bound):
        _append_result_text(
            result_widget,
            f"报告不含股票汇总或交易明细，未替换当前股票列表：{bound}",
        )
        return False
    try:
        symbols, rule_note = _extract_success_symbols_from_report(bound)
    except Exception as exc:  # noqa: BLE001
        _append_result_text(result_widget, f"加载股票列表失败：{type(exc).__name__}: {exc}")
        return False
    # 校验成功后才切换绑定，避免占位/损坏报告污染当前图表状态。
    _remember_bound_report(sub, bound)
    combo.clear()
    combo.addItems(symbols)
    _append_result_text(result_widget, f"已从绑定报告加载股票 {len(symbols)} 只：{bound}")
    _append_result_text(result_widget, rule_note)
    if symbols:
        _append_result_text(result_widget, f"股票列表：{', '.join(symbols)}")
    else:
        _append_result_text(result_widget, "本次筛选无成功股票。")
    # 记录当前使用的报告路径，供 K 线标注读取逐笔买卖明细。
    return True


def _ensure_k_plot_canvas(plot_host: QWidget, result_widget: ResultWidget | None):
    """在 widget_K_plot 中懒加载 matplotlib 画布；若库缺失则给出明确提示。"""
    canvas = getattr(plot_host, "_k_plot_canvas", None)
    ax = getattr(plot_host, "_k_plot_ax", None)
    if canvas is not None and ax is not None:
        return canvas, ax
    try:
        # 懒加载：避免未安装 matplotlib 时在模块导入阶段直接失败。
        import matplotlib as mpl  # noqa: PLC0415
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: PLC0415
        from matplotlib.backends.backend_qtagg import NavigationToolbar2QT  # noqa: PLC0415
        from matplotlib.figure import Figure  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        _append_result_text(result_widget, f"K线绘图不可用：{type(exc).__name__}: {exc}（请安装 matplotlib）")
        return None, None
    # 中文字体与负号修复：避免标题、图例出现方块/乱码。
    mpl.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    mpl.rcParams["axes.unicode_minus"] = False
    # 使用宿主 QWidget 的布局承载画布，保持和 Designer 窗体尺寸联动。
    layout = plot_host.layout()
    if layout is None:
        layout = QVBoxLayout(plot_host)
        layout.setContentsMargins(0, 0, 0, 0)
        plot_host.setLayout(layout)
    fig = Figure(figsize=(8, 4), dpi=100)
    # 价格与成交量共用日期轴；3:1 的高度兼顾 K 线可读性和量能观察。
    grid = fig.add_gridspec(4, 1, hspace=0.04)
    ax = fig.add_subplot(grid[:3, 0])
    volume_ax = fig.add_subplot(grid[3, 0], sharex=ax)
    ax.tick_params(axis="x", which="both", labelbottom=False)
    canvas = FigureCanvasQTAgg(fig)
    # 导航工具栏：支持框选缩放、平移、重置等标准交互。
    toolbar = NavigationToolbar2QT(canvas, plot_host)
    # 使用更明确的中文提示，避免仅凭图标猜测功能。
    toolbar_tips = {
        "home": "恢复当前股票的默认完整视图",
        "back": "返回上一个缩放/平移视图",
        "forward": "前进到下一个缩放/平移视图",
        "pan": "平移模式：左键拖动，右键缩放",
        "zoom": "框选缩放模式",
        "configure_subplots": "调整价格图和成交量图的布局",
        "edit_parameters": "编辑坐标轴和图形参数",
        "save_figure": "将当前图保存为图片",
    }
    for action_name, tip in toolbar_tips.items():
        action = getattr(toolbar, "_actions", {}).get(action_name)
        if action is not None:
            action.setToolTip(tip)
    layout.addWidget(toolbar)
    layout.addWidget(canvas)
    setattr(plot_host, "_k_plot_canvas", canvas)
    setattr(plot_host, "_k_plot_ax", ax)
    setattr(plot_host, "_k_plot_volume_ax", volume_ax)
    setattr(plot_host, "_k_plot_fig", fig)
    setattr(plot_host, "_k_plot_toolbar", toolbar)
    # 交互重绘限频：高 DPI 画布一次完整 draw 的成本不低。鼠标移动事件可能
    # 每秒触发数百次，逐事件 draw_idle 会让 Qt 事件队列堆积，表现为拖动粘滞。
    # 用单次 16 ms 定时器合并同一帧内的请求，最多约 60 FPS。
    redraw_state = {"pending": False}
    redraw_timer = QTimer(canvas)
    redraw_timer.setSingleShot(True)
    redraw_timer.setInterval(16)

    def _flush_interaction_draw() -> None:
        if not bool(redraw_state.get("pending")):
            return
        redraw_state["pending"] = False
        canvas.draw_idle()

    def _schedule_interaction_draw() -> None:
        redraw_state["pending"] = True
        if not redraw_timer.isActive():
            redraw_timer.start()

    redraw_timer.timeout.connect(_flush_interaction_draw)

    # 滚轮可能连续触发很多次，只在停止滚动后写入一次历史，保证后退/前进
    # 有效，同时避免历史栈被高分辨率滚轮塞满。
    history_timer = QTimer(canvas)
    history_timer.setSingleShot(True)
    history_timer.setInterval(180)
    history_timer.timeout.connect(toolbar.push_current)

    # NavigationToolbar2QT 的 pan 模式默认也会在每个 motion 事件中直接
    # draw_idle。替换为相同的合帧策略，使“点击四向箭头后拖动”与直接左键
    # 拖动都得到一致的性能。这里只改变 GUI 事件调度，不改变坐标计算。
    def _on_toolbar_drag_pan(event) -> None:
        pan_info = getattr(toolbar, "_pan_info", None)
        if pan_info is None:
            return
        for pan_ax in pan_info.axes:
            pan_ax.drag_pan(pan_info.button, event.key, event.x, event.y)
        _schedule_interaction_draw()

    setattr(toolbar, "drag_pan", _on_toolbar_drag_pan)

    # 鼠标滚轮缩放：围绕光标位置缩放 x/y 轴。
    def _on_scroll(event) -> None:
        if event.inaxes not in (ax, volume_ax):
            return
        cur_xlim = ax.get_xlim()
        if event.xdata is None or event.ydata is None:
            return
        scale = 0.85 if event.button == "up" else 1.18
        x_left = event.xdata - cur_xlim[0]
        x_right = cur_xlim[1] - event.xdata
        target_ax = event.inaxes
        cur_ylim = target_ax.get_ylim()
        y_down = event.ydata - cur_ylim[0]
        y_up = cur_ylim[1] - event.ydata
        ax.set_xlim(event.xdata - x_left * scale, event.xdata + x_right * scale)
        target_ax.set_ylim(event.ydata - y_down * scale, event.ydata + y_up * scale)
        _schedule_interaction_draw()
        history_timer.start()

    # 左键按住拖拽平移：保存按下时的像素坐标和轴范围，后续始终相对这个
    # 固定起点计算。不能使用每次 motion 的 xdata/ydata 做增量，因为 set_xlim
    # 会立即改变数据坐标映射，下一事件的 xdata 已处在新坐标系中，容易抖动。
    drag_state: dict[str, object] = {
        "dragging": False,
        "press_x": None,
        "press_y": None,
        "start_xlim": None,
        "start_ylim": None,
        "active_ax": None,
        "moved": False,
    }

    def _on_button_press(event) -> None:
        # 工具栏处于 pan/zoom 时交给 matplotlib 原生交互，避免双重处理导致抖动。
        tb = getattr(plot_host, "_k_plot_toolbar", None)
        if tb is not None and getattr(tb, "mode", ""):
            return
        if event.inaxes not in (ax, volume_ax) or event.button != 1:
            return
        if event.x is None or event.y is None:
            return
        drag_state["dragging"] = True
        drag_state["press_x"] = float(event.x)
        drag_state["press_y"] = float(event.y)
        drag_state["start_xlim"] = tuple(ax.get_xlim())
        drag_state["start_ylim"] = tuple(event.inaxes.get_ylim())
        drag_state["active_ax"] = event.inaxes
        drag_state["moved"] = False

    def _on_motion(event) -> None:
        if not bool(drag_state.get("dragging")):
            return
        if event.x is None or event.y is None:
            return
        press_x = drag_state.get("press_x")
        press_y = drag_state.get("press_y")
        start_xlim = drag_state.get("start_xlim")
        start_ylim = drag_state.get("start_ylim")
        active_ax = drag_state.get("active_ax")
        if press_x is None or press_y is None or start_xlim is None or start_ylim is None or active_ax is None:
            return
        bbox = active_ax.bbox
        if bbox.width <= 0 or bbox.height <= 0:
            return
        x0, x1 = start_xlim
        y0, y1 = start_ylim
        dx = (float(event.x) - float(press_x)) / float(bbox.width) * (x1 - x0)
        dy = (float(event.y) - float(press_y)) / float(bbox.height) * (y1 - y0)
        ax.set_xlim(x0 - dx, x1 - dx)
        active_ax.set_ylim(y0 - dy, y1 - dy)
        drag_state["moved"] = True
        _schedule_interaction_draw()

    def _on_button_release(event) -> None:
        if event.button == 1:
            was_dragging = bool(drag_state.get("dragging"))
            moved = bool(drag_state.get("moved"))
            drag_state["dragging"] = False
            drag_state["press_x"] = None
            drag_state["press_y"] = None
            drag_state["start_xlim"] = None
            drag_state["start_ylim"] = None
            drag_state["active_ax"] = None
            drag_state["moved"] = False
            # 松开时保证最后一个目标范围被绘制，不留下未刷新的半帧状态。
            if was_dragging:
                if redraw_timer.isActive():
                    redraw_timer.stop()
                _flush_interaction_draw()
                if moved:
                    toolbar.push_current()

    cid = canvas.mpl_connect("scroll_event", _on_scroll)
    cid_press = canvas.mpl_connect("button_press_event", _on_button_press)
    cid_motion = canvas.mpl_connect("motion_notify_event", _on_motion)
    cid_release = canvas.mpl_connect("button_release_event", _on_button_release)
    setattr(plot_host, "_k_plot_scroll_cid", cid)
    setattr(plot_host, "_k_plot_press_cid", cid_press)
    setattr(plot_host, "_k_plot_motion_cid", cid_motion)
    setattr(plot_host, "_k_plot_release_cid", cid_release)
    setattr(plot_host, "_k_plot_redraw_timer", redraw_timer)
    setattr(plot_host, "_k_plot_history_timer", history_timer)
    return canvas, ax


def _ensure_finance_plot_canvas(plot_host: QWidget, result_widget: ResultWidget | None):
    """在红框 ``widget_finance`` 中创建组合净值对比图。"""
    canvas = getattr(plot_host, "_finance_plot_canvas", None)
    ax = getattr(plot_host, "_finance_plot_ax", None)
    if canvas is not None and ax is not None:
        return canvas, ax
    try:
        import matplotlib as mpl  # noqa: PLC0415
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: PLC0415
        from matplotlib.figure import Figure  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        _append_result_text(result_widget, f"净值绘图不可用：{type(exc).__name__}: {exc}（请安装 matplotlib）")
        return None, None
    mpl.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    mpl.rcParams["axes.unicode_minus"] = False
    layout = plot_host.layout()
    if layout is None:
        layout = QVBoxLayout(plot_host)
        layout.setContentsMargins(0, 0, 0, 0)
        plot_host.setLayout(layout)
    fig = Figure(figsize=(8, 1.7), dpi=100)
    # 双行标题同时展示组合名称和六项指标，预留顶部空间避免第一行被容器裁切。
    fig.subplots_adjust(left=0.075, right=0.985, top=0.70, bottom=0.22)
    ax = fig.add_subplot(111)
    canvas = FigureCanvasQTAgg(fig)
    layout.addWidget(canvas)
    setattr(plot_host, "_finance_plot_canvas", canvas)
    setattr(plot_host, "_finance_plot_ax", ax)
    setattr(plot_host, "_finance_plot_fig", fig)
    return canvas, ax


def _load_local_symbol_bars(symbol: str, start_yyyymmdd: str, end_yyyymmdd: str) -> pd.DataFrame:
    """从本地 datadir 读取单只股票日线（含 open/high/low/close/volume）。"""
    bars = build_daily_market_panel_from_local_datadir(
        start_yyyymmdd,
        end_yyyymmdd,
        max_symbols=1,
        stock_list=[symbol],
    )
    out = bars.loc[bars["vt_symbol"].astype(str) == str(symbol)].copy()
    out["datetime"] = pd.to_datetime(out["datetime"], errors="coerce")
    out = out.dropna(subset=["datetime"]).sort_values("datetime", kind="mergesort")
    return out


def _performance_for_bound_report(sub: QWidget) -> PerformanceSummary | None:
    report_path = str(getattr(sub, "_latest_strategy_excel_path", "") or "")
    if getattr(sub, "_performance_report_path", None) == report_path:
        return getattr(sub, "_performance_summary", None)
    try:
        summary = load_performance_summary(report_path)
    except Exception:  # noqa: BLE001 - 旧报告异常时 K 线仍应正常显示
        summary = None
    setattr(sub, "_performance_report_path", report_path)
    setattr(sub, "_performance_summary", summary)
    return summary


def _render_finance_plot(sub: QWidget, result_widget: ResultWidget | None) -> None:
    """绘制策略净值、沪深300基准净值和相对超额净值。"""
    root = _ui_search_root(sub)
    host = root.findChild(QWidget, "widget_finance")
    if host is None:
        return
    canvas, ax = _ensure_finance_plot_canvas(host, result_widget)
    if canvas is None or ax is None:
        return
    summary = _performance_for_bound_report(sub)
    ax.clear()
    if summary is None or summary.equity.empty:
        ax.text(0.5, 0.5, "当前报告暂无统一净值曲线", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        canvas.draw_idle()
        return
    equity = summary.equity
    start_s = pd.Timestamp(equity["datetime"].min()).strftime("%Y%m%d")
    end_s = pd.Timestamp(equity["datetime"].max()).strftime("%Y%m%d")
    has_embedded_benchmark = (
        "benchmark_nav" in equity.columns
        and pd.to_numeric(equity["benchmark_nav"], errors="coerce").notna().any()
    )
    benchmark_label = summary.benchmark_name or f"{BENCHMARK_NAME}（{BENCHMARK_SYMBOL}）"
    if has_embedded_benchmark:
        benchmark = pd.DataFrame(columns=["datetime", "close"])
    else:
        try:
            benchmark = _load_local_symbol_bars(BENCHMARK_SYMBOL, start_s, end_s)
        except Exception as exc:  # noqa: BLE001
            benchmark = pd.DataFrame(columns=["datetime", "close"])
            _append_result_text(result_widget, f"基准行情加载失败（{BENCHMARK_SYMBOL}）：{type(exc).__name__}: {exc}")
    comparison = build_nav_comparison(equity, benchmark)
    if comparison.empty:
        ax.text(0.5, 0.5, "净值数据为空", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        canvas.draw_idle()
        return
    ax.set_axis_on()
    ax.plot(comparison["datetime"], comparison["strategy_nav"], color="#dc2626", linewidth=1.8, label="策略净值")
    if comparison["benchmark_nav"].notna().any():
        ax.plot(
            comparison["datetime"], comparison["benchmark_nav"],
            color="#6b7280", linewidth=1.3, linestyle="--", label=f"基准净值（{benchmark_label}）",
        )
        ax.plot(
            comparison["datetime"], comparison["excess_nav"],
            color="#2563eb", linewidth=1.0, label="超额净值（策略/基准）",
        )
    ax.axhline(1.0, color="#94a3b8", linewidth=0.7, alpha=0.7)
    sharpe = "--" if summary.sharpe_ratio is None else f"{summary.sharpe_ratio:.2f}"
    metrics = (
        f"总收益 {_format_percent(summary.total_return)}  |  "
        f"年化 {_format_percent(summary.annualized_return)}  |  "
        f"最大回撤 {_format_percent(summary.max_drawdown)}  |  "
        f"夏普 {sharpe}  |  胜率 {_format_percent(summary.win_rate)}  |  "
        f"交易成功率(回合/交易日) {_format_percent(summary.trade_success_rate)}"
    )
    ax.set_title(f"组合净值对比｜基准：{benchmark_label}\n{metrics}", fontsize=9.5)
    ax.set_ylabel("净值", fontsize=9)
    ax.grid(alpha=0.22, linestyle="--")
    ax.legend(loc="best", ncol=3, fontsize=8)
    ax.tick_params(axis="both", labelsize=8)
    canvas.draw_idle()


def _format_percent(value: float | None) -> str:
    return "--" if value is None else f"{value * 100:.2f}%"


def _k_plot_title(symbol: str, bars: pd.DataFrame, marks: pd.DataFrame) -> str:
    summary = calculate_symbol_performance(bars, marks)
    if summary.trade_days == 0:
        return f"{symbol} 日K线（本地数据）"
    sharpe = "--" if summary.sharpe_ratio is None else f"{summary.sharpe_ratio:.2f}"
    metrics = (
        f"单股收益 {_format_percent(summary.total_return)}  |  "
        f"年化 {_format_percent(summary.annualized_return)}  |  "
        f"最大回撤 {_format_percent(summary.max_drawdown)}  |  "
        f"夏普 {sharpe}  |  胜率 {_format_percent(summary.win_rate)}  |  "
        f"交易成功率(回合/交易日) {_format_percent(summary.trade_success_rate)}"
    )
    return f"{symbol} 日K线（本地数据）\n{metrics}"


def _load_trade_markers_from_report(report_path: str | None, symbol: str) -> pd.DataFrame:
    """从绑定报告读取指定股票买卖标记，动作统一为 BUY/SELL。"""
    from .report_trade_adapter import load_trade_markers  # noqa: PLC0415

    return load_trade_markers(report_path, symbol)


def _volume_display_scale(volume: pd.Series) -> tuple[float, str]:
    """按本地日线成交量（手）的量级返回显示除数和纵轴单位。"""
    clean = pd.to_numeric(volume, errors="coerce").dropna()
    peak = float(clean.max()) if not clean.empty else 0.0
    if peak >= 100_000_000:
        return 100_000_000.0, "亿手"
    if peak >= 10_000:
        return 10_000.0, "万手"
    return 1.0, "手"


def _render_k_plot(sub: QWidget, result_widget: ResultWidget | None) -> None:
    """按当前下拉股票与日期区间绘制本地 K 线，并叠加报告中的买卖标记。"""
    root = _ui_search_root(sub)
    host = root.findChild(QWidget, "widget_K_plot")
    combo = root.findChild(QComboBox, "comboBox_stock_list")
    ds = root.findChild(QDateEdit, "dateEdit_start_date")
    de = root.findChild(QDateEdit, "dateEdit_end_date")
    if host is None or combo is None or ds is None or de is None:
        return
    sym = str(combo.currentText() or "").strip()
    if not sym:
        return
    start_s = ds.date().toString("yyyyMMdd")
    end_s = de.date().toString("yyyyMMdd")
    canvas, ax = _ensure_k_plot_canvas(host, result_widget)
    if canvas is None or ax is None:
        return
    volume_ax = getattr(host, "_k_plot_volume_ax", None)
    if volume_ax is None:
        return
    # 切换股票/日期时取消上一幅图尚未落栈的延迟事件，避免旧视图污染新图历史。
    for timer_name in ("_k_plot_redraw_timer", "_k_plot_history_timer"):
        timer = getattr(host, timer_name, None)
        if timer is not None and timer.isActive():
            timer.stop()
    try:
        bars = _load_local_symbol_bars(sym, start_s, end_s)
    except Exception as exc:  # noqa: BLE001
        ax.clear()
        volume_ax.clear()
        ax.set_title(f"{sym} K线加载失败")
        canvas.draw_idle()
        _append_result_text(result_widget, f"K线数据读取失败（{sym}）：{type(exc).__name__}: {exc}")
        return
    if bars.empty:
        ax.clear()
        volume_ax.clear()
        ax.set_title(f"{sym} 在区间 {start_s}-{end_s} 无本地K线数据")
        canvas.draw_idle()
        _append_result_text(result_widget, f"K线无数据：{sym} {start_s}~{end_s}")
        return
    # 股票列表、K 线和成交标记必须绑定同一份报告，不在绘图阶段重新猜“最新文件”。
    rp = getattr(sub, "_latest_strategy_excel_path", None)
    marks = _load_trade_markers_from_report(rp, sym)
    if not marks.empty:
        start_dt = bars["datetime"].min().normalize()
        end_dt = bars["datetime"].max().normalize()
        marks = marks.loc[marks["datetime"].between(start_dt, end_dt)].copy()
    x = bars["datetime"]
    o = pd.to_numeric(bars["open"], errors="coerce")
    h = pd.to_numeric(bars["high"], errors="coerce")
    l = pd.to_numeric(bars["low"], errors="coerce")
    c = pd.to_numeric(bars["close"], errors="coerce")
    volume = pd.to_numeric(bars["volume"], errors="coerce").fillna(0.0).clip(lower=0.0)
    # 简版蜡烛：高低线 + 实体（红涨绿跌）。实体使用单个 PolyCollection
    # 批量绘制，避免 ax.bar 为每根 K 线创建一个 Rectangle；拖动时需要重绘
    # 的 artist 数量由数百个降为两个 collection。
    import matplotlib.dates as mdates  # noqa: PLC0415
    from matplotlib.collections import PolyCollection  # noqa: PLC0415

    ax.clear()
    volume_ax.clear()
    ax.vlines(x, l, h, color="#64748b", linewidth=0.8, alpha=0.9)
    width = 0.6  # 按日线稀疏程度取固定宽度（matplotlib 日期轴单位=天）
    x_num = mdates.date2num(pd.to_datetime(x).to_numpy(dtype="datetime64[ns]"))
    bodies: list[list[tuple[float, float]]] = []
    body_colors: list[str] = []
    for xi, oi, ci in zip(x_num, o, c):
        if pd.isna(oi) or pd.isna(ci):
            continue
        left = float(xi) - width / 2.0
        right = float(xi) + width / 2.0
        bottom = min(float(oi), float(ci))
        top = max(float(oi), float(ci))
        # 开收相等时保留一条可见的极薄实体。
        if top == bottom:
            pad = max(abs(top) * 0.0002, 0.0005)
            bottom -= pad
            top += pad
        bodies.append([(left, bottom), (left, top), (right, top), (right, bottom)])
        body_colors.append("#ef4444" if float(ci) >= float(oi) else "#22c55e")
    if bodies:
        ax.add_collection(
            PolyCollection(
                bodies,
                facecolors=body_colors,
                edgecolors=body_colors,
                linewidths=0.4,
                antialiaseds=False,
            )
        )
    volume_scale, volume_unit = _volume_display_scale(volume)
    scaled_volume = volume / volume_scale
    volume_bodies: list[list[tuple[float, float]]] = []
    volume_colors: list[str] = []
    for xi, oi, ci, vi in zip(x_num, o, c, scaled_volume):
        if pd.isna(vi):
            continue
        left = float(xi) - width / 2.0
        right = float(xi) + width / 2.0
        top = max(0.0, float(vi))
        volume_bodies.append([(left, 0.0), (left, top), (right, top), (right, 0.0)])
        volume_colors.append("#ef4444" if float(ci) >= float(oi) else "#22c55e")
    if volume_bodies:
        volume_ax.add_collection(
            PolyCollection(
                volume_bodies,
                facecolors=volume_colors,
                edgecolors=volume_colors,
                linewidths=0.2,
                antialiaseds=False,
            )
        )
    volume_peak = float(scaled_volume.max()) if not scaled_volume.empty else 0.0
    volume_ax.set_ylim(0.0, volume_peak * 1.12 if volume_peak > 0 else 1.0)
    if not marks.empty:
        buy_mask = marks["action"].eq("BUY")
        sell_mask = marks["action"].eq("SELL")
        mb = marks.loc[buy_mask]
        ms = marks.loc[sell_mask]
        if not mb.empty:
            ax.scatter(mb["datetime"], mb["price"], marker="^", s=40, color="#2563eb", label="买入", zorder=5)
        if not ms.empty:
            ax.scatter(ms["datetime"], ms["price"], marker="v", s=40, color="#f97316", label="卖出", zorder=5)
        if (not mb.empty) or (not ms.empty):
            ax.legend(loc="best")
    ax.set_title(_k_plot_title(sym, bars, marks), fontsize=10)
    ax.set_ylabel("Price")
    ax.grid(alpha=0.2, linestyle="--")
    ax.tick_params(axis="x", which="both", labelbottom=False)
    volume_ax.set_xlabel("Date")
    volume_ax.set_ylabel(f"成交量\n（{volume_unit}）", fontsize=9)
    volume_ax.grid(axis="y", alpha=0.2, linestyle="--")
    volume_ax.margins(x=0.01)
    getattr(host, "_k_plot_fig").autofmt_xdate()
    # 每次完整重绘都把当前价格、成交量和日期范围登记为唯一 Home 基线。
    # 没有这两步时，工具栏是在空坐标轴上创建的，Home 可能无状态可恢复，
    # 或在切换股票后恢复到上一只股票的旧范围。
    toolbar = getattr(host, "_k_plot_toolbar", None)
    if toolbar is not None:
        toolbar.update()
        toolbar.push_current()
    canvas.draw_idle()
    _append_result_text(
        result_widget,
        f"K线已更新：{sym} | 区间 {start_s}~{end_s} | K线 {len(bars)} 条 | 买卖标记 {len(marks)} 条",
    )


def _set_combo_current_by_data(cb: QComboBox, key: str) -> None:
    """按 itemData（因子/策略/模式 key）选中下拉项；找不到则保持首项。"""
    for i in range(cb.count()):
        if cb.itemData(i) == key:
            cb.setCurrentIndex(i)
            return


def _populate_combos(sub: QWidget) -> None:
    """扫描 InnerStrategy 填充因子、策略；回测方式固定为向量/事件两种。"""
    root = _ui_search_root(sub)
    cf = root.findChild(QComboBox, "comboBox_factor")
    cs = root.findChild(QComboBox, "comboBox_strategy")
    cm = root.findChild(QComboBox, "comboBox_backtest_mode")
    if cf is not None:
        cf.clear()
        for key, label in list_factor_entries():
            cf.addItem(label, key)
    if cs is not None:
        cs.clear()
        for key, label in list_strategy_entries():
            cs.addItem(label, key)
    if cm is not None:
        cm.clear()
        cm.addItem("向量回测", "vector")
        cm.addItem("事件回测", "event")


def apply_backtest_config_to_ui(sub: QWidget) -> None:
    """从 Config/backtest.json 载入并反映到控件（调用前应先 _populate_combos）。"""
    data = load_backtest_json()
    job = dict_to_job(data)
    root = _ui_search_root(sub)

    le_cash = root.findChild(QLineEdit, "lineEdit_crash")
    if le_cash is not None:
        v = job.initial_capital
        le_cash.setText(str(int(v)) if float(v).is_integer() else str(v))

    ds = root.findChild(QDateEdit, "dateEdit_start_date")
    de = root.findChild(QDateEdit, "dateEdit_end_date")
    if ds is not None:
        qd = QDate.fromString(job.start_date, "yyyyMMdd")
        if qd.isValid():
            ds.setDate(qd)
    if de is not None:
        qd = QDate.fromString(job.end_date, "yyyyMMdd")
        if qd.isValid():
            de.setDate(qd)

    cf = root.findChild(QComboBox, "comboBox_factor")
    cs = root.findChild(QComboBox, "comboBox_strategy")
    cm = root.findChild(QComboBox, "comboBox_backtest_mode")
    if cf is not None and cf.count():
        _set_combo_current_by_data(cf, job.factor_key)
    if cs is not None and cs.count():
        _set_combo_current_by_data(cs, job.strategy_key)
    if cm is not None and cm.count():
        _set_combo_current_by_data(cm, job.backtest_mode)

    sp = root.findChild(QSpinBox, "spinBox_factor_front_n")
    if sp is not None:
        sp.setValue(int(load_factor_evaluation_json().get("factor_eval_front_n", 20)))
    sp_max = root.findChild(QSpinBox, "spinBox_max_symbols")
    if sp_max is not None:
        cfg = load_factor_evaluation_json()
        # max_symbols 由 GUI 控件维护；若配置缺失则先用控件当前值并回写。
        if "max_symbols" in cfg:
            try:
                sp_max.setValue(int(cfg.get("max_symbols")))
            except (TypeError, ValueError):
                pass


def read_ui_to_job(sub: QWidget):
    """从当前控件读取任务配置。"""
    from .models import BacktestJobConfig

    root = _ui_search_root(sub)
    le_cash = root.findChild(QLineEdit, "lineEdit_crash")
    raw = (le_cash.text() if le_cash is not None else "").strip() or "0"
    try:
        capital = float(raw)
    except ValueError:
        capital = 0.0

    ds = root.findChild(QDateEdit, "dateEdit_start_date")
    de = root.findChild(QDateEdit, "dateEdit_end_date")
    start_s = ds.date().toString("yyyyMMdd") if ds is not None else "20230101"
    end_s = de.date().toString("yyyyMMdd") if de is not None else "20231231"

    cf = root.findChild(QComboBox, "comboBox_factor")
    cs = root.findChild(QComboBox, "comboBox_strategy")
    cm = root.findChild(QComboBox, "comboBox_backtest_mode")
    fk = cf.currentData() if cf is not None and cf.currentIndex() >= 0 else default_factor_id()
    sk = cs.currentData() if cs is not None and cs.currentIndex() >= 0 else default_strategy_id()
    mode = cm.currentData() if cm is not None and cm.currentIndex() >= 0 else "vector"
    if mode not in ("vector", "event"):
        mode = "vector"

    # M10 动态参数控件完成前，保留 Config/backtest.json 中与当前策略匹配的
    # 手工参数覆盖，避免用户点击回测或修改日期时被空字典覆盖。
    saved = load_backtest_json()
    saved_strategy = resolve_strategy_key(str(saved.get("strategy_key") or ""))
    strategy_params = dict(saved.get("strategy_params") or {}) if saved_strategy == str(sk) else {}

    return BacktestJobConfig(
        initial_capital=capital,
        start_date=start_s,
        end_date=end_s,
        factor_key=str(fk),
        strategy_key=str(sk),
        backtest_mode=mode,  # type: ignore[arg-type]
        strategy_params=strategy_params,
    )


def persist_ui_to_config(sub: QWidget) -> None:
    """策略回测参数写入 backtest.json；因子评估专用项写入 factor_evaluation.json。"""
    job = read_ui_to_job(sub)
    bt = {**load_backtest_json(), **job_to_dict(job)}
    bt.pop("factor_eval_front_n", None)
    save_backtest_json(bt)
    root = _ui_search_root(sub)
    sp = root.findChild(QSpinBox, "spinBox_factor_front_n")
    sp_max = root.findChild(QSpinBox, "spinBox_max_symbols")
    updates: dict[str, int] = {}
    if sp is not None:
        updates["factor_eval_front_n"] = int(sp.value())
    if sp_max is not None:
        updates["max_symbols"] = int(sp_max.value())
    if updates:
        patch_factor_evaluation_json(updates)


def refresh_backtest_panel(sub: QWidget) -> None:
    """每次显示子窗体时刷新下拉与配置显示（便于 InnerStrategy 增删文件后生效）。"""
    # 根据当前 factors/*.py、strategies/*.py 重写编号注册表
    from InnerStrategy.inner_registry import force_rebuild_inner_registry_file  # noqa: PLC0415

    force_rebuild_inner_registry_file()
    root = _ui_search_root(sub)
    # 填充下拉时会触发 currentIndexChanged，先屏蔽避免反复写回配置文件
    guarded: list = []
    for w in (
        root.findChild(QComboBox, "comboBox_factor"),
        root.findChild(QComboBox, "comboBox_strategy"),
        root.findChild(QComboBox, "comboBox_backtest_mode"),
        root.findChild(QDateEdit, "dateEdit_start_date"),
        root.findChild(QDateEdit, "dateEdit_end_date"),
        root.findChild(QSpinBox, "spinBox_factor_front_n"),
        root.findChild(QSpinBox, "spinBox_max_symbols"),
    ):
        if w is not None:
            w.blockSignals(True)
            guarded.append(w)
    try:
        _populate_combos(sub)
        apply_backtest_config_to_ui(sub)
    finally:
        for w in guarded:
            w.blockSignals(False)


def wire_backtest_dialog(sub: QWidget, _main_window: QWidget) -> None:
    """
    绑定 BackTest.ui；同一子窗体只连接信号一次。

    _main_window: 预留写主窗口日志；当前回测说明输出在子窗体 plainTextEdit_result（或旧版 lineEdit）。
    """
    if getattr(sub, "_backtest_dialog_wired", False):
        return

    root = _ui_search_root(sub)
    _apply_result_panel_style(_find_result_widget(sub))

    _populate_combos(sub)
    apply_backtest_config_to_ui(sub)
    # 首次进入时按当前策略/模式恢复最近有效报告；跳过事件占位报告。
    if not _restore_report_for_current_selection(sub, _find_result_widget(sub)):
        _render_finance_plot(sub, _find_result_widget(sub))
        _render_k_plot(sub, _find_result_widget(sub))

    ds = root.findChild(QDateEdit, "dateEdit_start_date")
    de = root.findChild(QDateEdit, "dateEdit_end_date")
    le_cash = root.findChild(QLineEdit, "lineEdit_crash")
    cf = root.findChild(QComboBox, "comboBox_factor")
    cs = root.findChild(QComboBox, "comboBox_strategy")
    cm = root.findChild(QComboBox, "comboBox_backtest_mode")

    def _on_field_changed() -> None:
        # 任意参数变更即落盘，便于下次启动恢复
        persist_ui_to_config(sub)

    def _on_strategy_or_mode_changed() -> None:
        """切换策略/模式时恢复对应有效报告；找不到时保留当前展示。"""
        persist_ui_to_config(sub)
        _restore_report_for_current_selection(sub, result_widget)

    if ds is not None:
        ds.dateChanged.connect(lambda *_: _on_field_changed())
        ds.dateChanged.connect(lambda *_: _render_k_plot(sub, result_widget))
    if de is not None:
        de.dateChanged.connect(lambda *_: _on_field_changed())
        de.dateChanged.connect(lambda *_: _render_k_plot(sub, result_widget))
    if le_cash is not None:
        le_cash.editingFinished.connect(_on_field_changed)
    if cf is not None:
        cf.currentIndexChanged.connect(lambda *_: _on_field_changed())
    if cs is not None:
        cs.currentIndexChanged.connect(lambda *_: _on_strategy_or_mode_changed())
    if cm is not None:
        cm.currentIndexChanged.connect(lambda *_: _on_strategy_or_mode_changed())
    combo_stock = root.findChild(QComboBox, "comboBox_stock_list")
    if combo_stock is not None:
        combo_stock.currentIndexChanged.connect(lambda *_: _render_k_plot(sub, result_widget))
    sp_nf = root.findChild(QSpinBox, "spinBox_factor_front_n")
    sp_max = root.findChild(QSpinBox, "spinBox_max_symbols")
    if sp_nf is not None:
        sp_nf.valueChanged.connect(lambda *_: _on_field_changed())
    if sp_max is not None:
        sp_max.valueChanged.connect(lambda *_: _on_field_changed())

    btn = root.findChild(QPushButton, "pushButton")
    btn_factor = root.findChild(QPushButton, "pushButton_2")
    result_widget = _find_result_widget(sub)

    def on_start_backtest() -> None:
        """先读回测方式；向量模式再读策略下拉并执行对应向量引擎。"""
        try:
            persist_ui_to_config(sub)
            # 1) 回测方式：向量 / 事件
            mode = "vector"
            if cm is not None and cm.currentIndex() >= 0:
                raw_mode = cm.currentData()
                if raw_mode in ("vector", "event"):
                    mode = str(raw_mode)
            # 2) 向量回测：记录 comboBox_strategy 当前选项（与 read_ui_to_job 中 strategy_key 一致）
            strat_header = ""
            if mode == "vector" and cs is not None and cs.currentIndex() >= 0:
                sk = str(cs.currentData() or default_strategy_id())
                strat_label = cs.currentText()
                strat_header = (
                    "—— 策略回测（向量）——\n"
                    f"comboBox_backtest_mode = vector\n"
                    f"comboBox_strategy = {sk} | {strat_label}\n\n"
                )
            job = read_ui_to_job(sub)
            if job.start_date > job.end_date:
                _set_result_text(result_widget, "起始日期不能晚于结束日期。")
                return
            # 先写入策略头信息；后续进度由引擎 print + 本回调追加到文本框（无进度条）
            _set_result_text(result_widget, strat_header if strat_header else "")

            def ui_log(msg: str) -> None:
                # 与引擎内 print 配套：把同一行文本同步到结果区，并刷新事件循环避免界面假死
                _append_result_text(result_widget, msg)
                QApplication.processEvents()

            result = run_backtest(job, progress=ui_log)
            # 引擎若已生成详细报告（如 SLSS 向量）则沿用；否则补写通用 Excel
            excel_path = result.excel_path or ensure_backtest_excel_report(job, result)
            # 保留上文进度行，仅在末尾追加汇总（避免 _set_result_text 清空日志）
            tail = "\n—— 回测汇总 ——\n" + result.message
            report_loaded = False
            if excel_path:
                tail += f"\n\nExcel 报告已生成:\n{excel_path}"
            _append_result_text(result_widget, tail)
            # 只有包含股票汇总/交易明细的报告才能替换当前展示。事件占位、失败或
            # 损坏报告仍可留档，但不得清空上一次有效股票列表和净值/K线。
            if excel_path:
                report_loaded = _load_stock_list_to_combo_from_latest_report(
                    sub, result_widget, excel_path,
                )
            if report_loaded:
                setattr(sub, "_performance_report_path", None)
                _render_finance_plot(sub, result_widget)
                _render_k_plot(sub, result_widget)
            else:
                _append_result_text(
                    result_widget,
                    "本次结果没有可展示的股票交易数据，继续保留上一次有效回测的股票列表和图表。",
                )
        except Exception as exc:  # noqa: BLE001 — 必须反馈到界面与 stderr，避免静默失败
            tb = traceback.format_exc()
            err = f"策略回测执行失败: {type(exc).__name__}: {exc}\n\n{tb}"
            print(err, file=sys.stderr)
            if result_widget is not None:
                _set_result_text(result_widget, err)
            else:
                QMessageBox.critical(sub, "策略回测错误", err[:4000])

    if btn is not None:
        btn.clicked.connect(on_start_backtest)
    else:
        print(
            "BackTest: 未在 centralwidget 下找到 pushButton（策略回测），请检查 GUI/BackTest.ui。",
            file=sys.stderr,
        )
        QMessageBox.warning(
            sub,
            "回测界面异常",
            "未找到「策略回测」按钮（objectName=pushButton）。\n请确认 GUI/BackTest.ui 未改名且已保存。",
        )

    def on_factor_batch_backtest() -> None:
        """全因子「IC 门槛与多空夏普」评估：后台线程 + Excel 报告。"""
        try:
            persist_ui_to_config(sub)
            job = read_ui_to_job(sub)
            if job.start_date > job.end_date:
                _set_result_text(result_widget, "起始日期不能晚于结束日期。")
                return
            thr: QThread | None = getattr(sub, "_factor_eval_thread", None)
            if thr is not None and thr.isRunning():
                _append_result_text(result_widget, "（已有全因子任务在运行，请稍候。）")
                return

            # 仅在使用 xtdata 行情路径时要求本机进程就绪；local_datadir 不加载 xtquant
            if not is_local_datadir_market_source():
                try:
                    require_qmt_client_for_xtdata_datafeed()
                except RuntimeError as exc:
                    QMessageBox.warning(
                        sub,
                        "需要先启动 QMT / miniQMT",
                        str(exc),
                    )
                    return

            sp_limit = root.findChild(QSpinBox, "spinBox_factor_front_n")
            front_n = int(sp_limit.value()) if sp_limit is not None else 20

            _set_result_text(
                result_widget,
                "—— 因子批量评估（IC 门槛与多空夏普：先 RankIC/IC_IR 门槛，再以分层多空夏普排序）——\n"
                f"区间 {job.start_date} ~ {job.end_date}；仅评估注册表排序后的前 {front_n} 个因子\n"
                "参数见 Config/factor_evaluation.json（评估）、Config/single_factor_parameters.json（prepare 并行度）、"
                "InnerStrategy/factors/alpha_101_parameters.json / alpha_158_parameters.json（因子公式）；运行日志如下：\n",
            )
            if btn_factor is not None:
                btn_factor.setEnabled(False)

            worker = FactorEvaluationWorker(job.start_date, job.end_date, front_n)
            thread = QThread()
            worker.moveToThread(thread)
            sub._factor_eval_thread = thread
            sub._factor_eval_worker = worker

            bridge = _FactorEvalUiBridge(sub, result_widget, btn_factor, thread, worker)
            thread.started.connect(worker.run)
            worker.progress.connect(
                bridge.on_progress,
                Qt.ConnectionType.QueuedConnection,
            )
            worker.finished.connect(
                bridge.on_finished,
                Qt.ConnectionType.QueuedConnection,
            )
            thread.start()
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc()
            err = f"因子批量评估启动失败: {type(exc).__name__}: {exc}\n\n{tb}"
            print(err, file=sys.stderr)
            if result_widget is not None:
                _append_result_text(result_widget, err)
            QMessageBox.critical(sub, "因子回测错误", err[:4000])

    if btn_factor is not None:
        btn_factor.clicked.connect(on_factor_batch_backtest)

    sub._backtest_dialog_wired = True
