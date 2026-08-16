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
from PySide6.QtCore import QObject, QThread, QDate, Slot, Qt
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


def _latest_strategy_report_path() -> Path | None:
    """返回 reports/strategy 下最近修改的一份策略回测 Excel。"""
    # 约定目录与 backtest_strategy_report_excel 中保持一致。
    report_dir = _project_root() / "reports" / "strategy"
    if not report_dir.is_dir():
        return None
    paths = sorted(report_dir.glob("strategy_backtest_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    return paths[0] if paths else None


def _extract_success_symbols_from_report(path: Path) -> tuple[list[str], str]:
    """
    从策略报告提取股票列表（按“按股票汇总统计”第一列）。

    口径：不做盈亏筛选，直接读取第一列并去重去空。
    """
    df = pd.read_excel(path, sheet_name="按股票汇总统计")
    if df.empty or len(df.columns) < 1:
        return [], "按股票汇总统计为空或缺少列。"
    first_col = df.columns[0]
    # 按你的要求：直接看第一列，不再根据盈亏或回合数过滤。
    syms = (
        df[first_col]
        .astype(str)
        .str.strip()
        .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
        .dropna()
        .drop_duplicates()
        .tolist()
    )
    return syms, f"加载口径：按股票汇总统计第一列「{first_col}」，不做盈亏筛选。"


def _load_stock_list_to_combo_from_latest_report(sub: QWidget, result_widget: ResultWidget | None) -> None:
    """回测结束后：自动把最新策略报告中的成功股票加载到 comboBox_stock_list。"""
    root = _ui_search_root(sub)
    combo = root.findChild(QComboBox, "comboBox_stock_list")
    if combo is None:
        _append_result_text(result_widget, "未找到 comboBox_stock_list，跳过股票列表加载。")
        return
    latest = _latest_strategy_report_path()
    if latest is None:
        combo.clear()
        _append_result_text(result_widget, "未找到策略回测报告（reports/strategy），股票列表已清空。")
        return
    try:
        symbols, rule_note = _extract_success_symbols_from_report(latest)
    except Exception as exc:  # noqa: BLE001
        combo.clear()
        _append_result_text(result_widget, f"加载股票列表失败：{type(exc).__name__}: {exc}")
        return
    combo.clear()
    combo.addItems(symbols)
    _append_result_text(result_widget, f"已从最新报告加载成功股票 {len(symbols)} 只：{latest}")
    _append_result_text(result_widget, rule_note)
    if symbols:
        _append_result_text(result_widget, f"股票列表：{', '.join(symbols)}")
    else:
        _append_result_text(result_widget, "本次筛选无成功股票。")
    # 记录当前使用的报告路径，供 K 线标注读取逐笔买卖明细。
    setattr(sub, "_latest_strategy_excel_path", str(latest))


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
    ax = fig.add_subplot(111)
    canvas = FigureCanvasQTAgg(fig)
    # 导航工具栏：支持框选缩放、平移、重置等标准交互。
    toolbar = NavigationToolbar2QT(canvas, plot_host)
    layout.addWidget(toolbar)
    layout.addWidget(canvas)
    setattr(plot_host, "_k_plot_canvas", canvas)
    setattr(plot_host, "_k_plot_ax", ax)
    setattr(plot_host, "_k_plot_fig", fig)
    setattr(plot_host, "_k_plot_toolbar", toolbar)
    # 鼠标滚轮缩放：围绕光标位置缩放 x/y 轴。
    def _on_scroll(event) -> None:
        if event.inaxes != ax:
            return
        cur_xlim = ax.get_xlim()
        cur_ylim = ax.get_ylim()
        if event.xdata is None or event.ydata is None:
            return
        scale = 0.85 if event.button == "up" else 1.18
        x_left = event.xdata - cur_xlim[0]
        x_right = cur_xlim[1] - event.xdata
        y_down = event.ydata - cur_ylim[0]
        y_up = cur_ylim[1] - event.ydata
        ax.set_xlim(event.xdata - x_left * scale, event.xdata + x_right * scale)
        ax.set_ylim(event.ydata - y_down * scale, event.ydata + y_up * scale)
        canvas.draw_idle()
    # 左键按住拖拽平移：不依赖工具栏按钮，直接左键拖动即可查看前后区间。
    drag_state: dict[str, object] = {"dragging": False, "last_x": None, "last_y": None}

    def _on_button_press(event) -> None:
        # 工具栏处于 pan/zoom 时交给 matplotlib 原生交互，避免双重处理导致抖动。
        tb = getattr(plot_host, "_k_plot_toolbar", None)
        if tb is not None and getattr(tb, "mode", ""):
            return
        if event.inaxes != ax or event.button != 1:
            return
        if event.xdata is None or event.ydata is None:
            return
        drag_state["dragging"] = True
        drag_state["last_x"] = float(event.xdata)
        drag_state["last_y"] = float(event.ydata)

    def _on_motion(event) -> None:
        if not bool(drag_state.get("dragging")) or event.inaxes != ax:
            return
        if event.xdata is None or event.ydata is None:
            return
        last_x = drag_state.get("last_x")
        last_y = drag_state.get("last_y")
        if last_x is None or last_y is None:
            return
        # 增量平移：使用“上一帧到当前帧”的位移，减少事件抖动放大效应。
        dx = float(event.xdata) - float(last_x)
        dy = float(event.ydata) - float(last_y)
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        ax.set_xlim(xlim[0] - dx, xlim[1] - dx)
        ax.set_ylim(ylim[0] - dy, ylim[1] - dy)
        drag_state["last_x"] = float(event.xdata)
        drag_state["last_y"] = float(event.ydata)
        canvas.draw_idle()

    def _on_button_release(event) -> None:
        if event.button == 1:
            drag_state["dragging"] = False
            drag_state["last_x"] = None
            drag_state["last_y"] = None

    cid = canvas.mpl_connect("scroll_event", _on_scroll)
    cid_press = canvas.mpl_connect("button_press_event", _on_button_press)
    cid_motion = canvas.mpl_connect("motion_notify_event", _on_motion)
    cid_release = canvas.mpl_connect("button_release_event", _on_button_release)
    setattr(plot_host, "_k_plot_scroll_cid", cid)
    setattr(plot_host, "_k_plot_press_cid", cid_press)
    setattr(plot_host, "_k_plot_motion_cid", cid_motion)
    setattr(plot_host, "_k_plot_release_cid", cid_release)
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


def _load_trade_markers_from_report(report_path: str | None, symbol: str) -> pd.DataFrame:
    """从策略报告的“逐笔买卖明细”读取指定股票买卖标记点。"""
    if not report_path:
        return pd.DataFrame(columns=["datetime", "action", "price"])
    p = Path(report_path)
    if not p.is_file():
        return pd.DataFrame(columns=["datetime", "action", "price"])
    try:
        td = pd.read_excel(p, sheet_name="逐笔买卖明细")
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=["datetime", "action", "price"])
    need = {"vt_symbol", "datetime", "action", "price"}
    if td.empty or not need.issubset(set(td.columns)):
        return pd.DataFrame(columns=["datetime", "action", "price"])
    sub = td.loc[td["vt_symbol"].astype(str) == str(symbol), ["datetime", "action", "price"]].copy()
    sub["datetime"] = pd.to_datetime(sub["datetime"], errors="coerce")
    sub["price"] = pd.to_numeric(sub["price"], errors="coerce")
    sub = sub.dropna(subset=["datetime", "price"]).sort_values("datetime", kind="mergesort")
    return sub


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
    try:
        bars = _load_local_symbol_bars(sym, start_s, end_s)
    except Exception as exc:  # noqa: BLE001
        ax.clear()
        ax.set_title(f"{sym} K线加载失败")
        canvas.draw_idle()
        _append_result_text(result_widget, f"K线数据读取失败（{sym}）：{type(exc).__name__}: {exc}")
        return
    if bars.empty:
        ax.clear()
        ax.set_title(f"{sym} 在区间 {start_s}-{end_s} 无本地K线数据")
        canvas.draw_idle()
        _append_result_text(result_widget, f"K线无数据：{sym} {start_s}~{end_s}")
        return
    # 报告路径优先使用本次回测产物；不存在时退回最新报告。
    rp = getattr(sub, "_latest_strategy_excel_path", None)
    if not rp:
        latest = _latest_strategy_report_path()
        rp = str(latest) if latest is not None else None
    marks = _load_trade_markers_from_report(rp, sym)
    x = bars["datetime"]
    o = pd.to_numeric(bars["open"], errors="coerce")
    h = pd.to_numeric(bars["high"], errors="coerce")
    l = pd.to_numeric(bars["low"], errors="coerce")
    c = pd.to_numeric(bars["close"], errors="coerce")
    # 简版蜡烛：高低线 + 实体（红涨绿跌），依赖 matplotlib 通用组件，避免额外绘图库耦合。
    ax.clear()
    up = c >= o
    down = ~up
    ax.vlines(x, l, h, color="#64748b", linewidth=0.8, alpha=0.9)
    width = 0.6  # 按日线稀疏程度取固定宽度（matplotlib 日期轴单位=天）
    ax.bar(x[up], (c[up] - o[up]), bottom=o[up], width=width, color="#ef4444", edgecolor="#ef4444", align="center")
    ax.bar(
        x[down],
        (c[down] - o[down]),
        bottom=o[down],
        width=width,
        color="#22c55e",
        edgecolor="#22c55e",
        align="center",
    )
    if not marks.empty:
        buy_mask = marks["action"].astype(str).str.contains("买", na=False)
        sell_mask = marks["action"].astype(str).str.contains("卖", na=False)
        mb = marks.loc[buy_mask]
        ms = marks.loc[sell_mask]
        if not mb.empty:
            ax.scatter(mb["datetime"], mb["price"], marker="^", s=40, color="#2563eb", label="买入", zorder=5)
        if not ms.empty:
            ax.scatter(ms["datetime"], ms["price"], marker="v", s=40, color="#f97316", label="卖出", zorder=5)
        if (not mb.empty) or (not ms.empty):
            ax.legend(loc="best")
    ax.set_title(f"{sym} 日K线（本地数据）")
    ax.set_xlabel("Date")
    ax.set_ylabel("Price")
    ax.grid(alpha=0.2, linestyle="--")
    getattr(host, "_k_plot_fig").autofmt_xdate()
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

    return BacktestJobConfig(
        initial_capital=capital,
        start_date=start_s,
        end_date=end_s,
        factor_key=str(fk),
        strategy_key=str(sk),
        backtest_mode=mode,  # type: ignore[arg-type]
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
    # 首次进入回测窗口时，优先从最新策略报告恢复股票下拉，便于直接查看历史结果。
    _load_stock_list_to_combo_from_latest_report(sub, _find_result_widget(sub))
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
        cs.currentIndexChanged.connect(lambda *_: _on_field_changed())
    if cm is not None:
        cm.currentIndexChanged.connect(lambda *_: _on_field_changed())
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
            if excel_path:
                tail += f"\n\nExcel 报告已生成:\n{excel_path}"
                # 优先记录本次回测报告，供 K 线买卖标记读取，避免误读更旧的“最新文件”。
                setattr(sub, "_latest_strategy_excel_path", str(excel_path))
            _append_result_text(result_widget, tail)
            # 回测完成后自动刷新“股票列表”下拉，便于直接查看成功股票。
            _load_stock_list_to_combo_from_latest_report(sub, result_widget)
            _render_k_plot(sub, result_widget)
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
