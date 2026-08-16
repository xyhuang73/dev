# -*- coding: utf-8 -*-
"""
通过 miniQMT 附带的 xtquant.xtdata 按区间下载日线/分钟线到本地缓存。

支持多周期并行下载：勾选日线下载日线，勾选分钟线下载指定分钟周期数据。
"""
from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from qmt_service import ensure_xtquant_path

# 每只股票下载超时（秒），防止卡住导致整个任务停摆
_DOWNLOAD_TIMEOUT_SEC = 30


def _is_qmt_client_accessible() -> bool:
    """检测 QMT 客户端的行情服务端口是否可连接（58610）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        result = s.connect_ex(("127.0.0.1", 58610))
        return result == 0
    except Exception:
        return False
    finally:
        s.close()


def _check_qmt_readiness() -> tuple[bool, str]:
    """
    检查 QMT 客户端是否就绪。

    Returns:
        (is_ready, message): is_ready=True 表示可继续；False 时 message 含原因说明。
    """
    if not _is_qmt_client_accessible():
        return False, (
            "无法连接 miniQMT 行情服务（端口 58610 无响应）。\n"
            "请确认：\n"
            "  1. miniQMT / 国金 QMT 客户端已启动\n"
            "  2. 客户端已登录（账号状态正常）\n"
            "  3. 客户端已开启「行情服务」或「本地数据」权限\n"
            "  4. 客户端与本脚本在同一台电脑上运行\n"
            "\n"
            "提示：可在任务管理器中搜索 XtMiniQmt、miniqmt、QMT 等进程确认客户端状态。"
        )

    kw: dict = {}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        cp = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20, **kw,
        )
        blob = (cp.stdout or "").lower()
        process_hints = ["xtminiqmt", "miniqmt", "xtitclient", "qmt"]
        found = [h for h in process_hints if h in blob]
        if not found:
            return True, "warn_no_process_but_port_open"
    except Exception:
        pass
    return True, ""


def _period_label(period: str) -> str:
    """将周期字符串转为友好显示名。"""
    if period == "1d":
        return "日线"
    if period.endswith("m"):
        mins = period[:-1]
        return f"{mins}分钟"
    return period


def _download_with_timeout(xtdata: Any, symbol: str, period: str, start: str, end: str) -> tuple[bool, str]:
    """
    带超时的下载封装，防止某只股票卡住导致整个任务停摆。

    Returns:
        (success, error_message): success=True 表示下载成功，error_message 为错误描述（成功时为空）
    """
    result = {"success": False, "error": ""}

    def _download():
        try:
            try:
                xtdata.download_history_data(
                    symbol,
                    period,
                    start,
                    end,
                    incrementally=True,
                )
            except TypeError:
                xtdata.download_history_data(symbol, period, start, end)
            result["success"] = True
        except Exception as exc:  # noqa: BLE001
            result["error"] = str(exc)

    t = threading.Thread(target=_download, daemon=True)
    t.start()
    t.join(timeout=_DOWNLOAD_TIMEOUT_SEC)

    if t.is_alive():
        return False, f"下载超时（>{_DOWNLOAD_TIMEOUT_SEC}秒未响应）"
    if result["error"]:
        return False, result["error"]
    return True, ""


class QmtHistoryDownloadWorker(QObject):
    """
    在 QThread 中运行：枚举板块标的并逐只调用 ``download_history_data``。

    支持多周期下载（日线 + 任意分钟周期）。
    """

    progress = Signal(str)
    finished = Signal(bool, str)

    def __init__(
        self,
        start_yyyymmdd: str,
        end_yyyymmdd: str,
        periods: list[str],
    ) -> None:
        """
        Args:
            start_yyyymmdd: 起始日期
            end_yyyymmdd: 结束日期
            periods: 下载周期列表，如 ["1d", "5m", "15m"]
        """
        super().__init__()
        self._start = start_yyyymmdd.strip()
        self._end = end_yyyymmdd.strip()
        self._periods = periods

    @Slot()
    def run(self) -> None:
        ready, readiness_msg = _check_qmt_readiness()
        if not ready:
            self.finished.emit(False, readiness_msg)
            return

        try:
            cfg: dict[str, Any] = ensure_xtquant_path()
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(False, f"无法初始化 QMT 路径: {exc}")
            return

        try:
            from xtquant import xtdata  # type: ignore
        except ImportError as exc:
            self.finished.emit(
                False,
                f"无法 import xtquant（请确认 miniQMT 已安装且 userdata 路径正确）: {exc}",
            )
            return

        if hasattr(xtdata, "enable_hello"):
            xtdata.enable_hello = False  # type: ignore[union-attr]

        sector = str(cfg.get("update_stock_sector") or "沪深A股").strip()
        max_n = int(cfg.get("update_stock_max_symbols") or 0)

        try:
            stock_list = list(xtdata.get_stock_list_in_sector(sector) or [])
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(
                False,
                f"获取板块「{sector}」标的失败: {exc}\n"
                "提示：如果 QMT 客户端刚启动，请等待 5~10 秒后再试（行情服务需要初始化时间）。",
            )
            return

        if max_n > 0:
            stock_list = stock_list[:max_n]

        total = len(stock_list)
        if total == 0:
            self.finished.emit(False, f"板块「{sector}」标的列表为空，请检查名称或登录状态。")
            return

        if not self._periods:
            self.finished.emit(False, "未选择任何下载周期（日线/分钟线），请至少勾选一个。")
            return

        period_names = "、".join(_period_label(p) for p in self._periods)
        self.progress.emit(
            f"开始下载 {period_names}: {self._start} ~ {self._end}，板块={sector}，共 {total} 只（请保持 miniQMT 已登录）。",
        )

        grand_ok = 0
        grand_fail = 0
        grand_total = total * len(self._periods)

        for period in self._periods:
            period_name = _period_label(period)
            self.progress.emit(f"\n========== 正在下载 {period_name} ==========")
            print(f"[DEBUG] 开始周期 {period_name}，共 {total} 只股票")

            ok_count = 0
            fail_count = 0
            for i, xt_symbol in enumerate(stock_list):
                step_start = time.time()
                self.progress.emit(f"[{period_name}] 第 {i+1}/{total} 只: {xt_symbol}")
                print(f"[DEBUG] 下载中 {xt_symbol}...")
                success, err = _download_with_timeout(
                    xtdata, xt_symbol, period, self._start, self._end
                )
                elapsed = time.time() - step_start
                print(f"[DEBUG] {xt_symbol} 完成，耗时 {elapsed:.1f}秒，成功={success}")
                if success:
                    ok_count += 1
                    self.progress.emit(f"[{period_name}] {i+1}/{total}: {xt_symbol} OK")
                else:
                    fail_count += 1
                    self.progress.emit(f"[{period_name}] {i+1}/{total}: {xt_symbol} 失败 - {err}")

                step = i + 1
                if step == 1 or step % 50 == 0 or step == total:
                    self.progress.emit(
                        f"[{period_name} {step}/{total}] 成功{ok_count}，失败{fail_count}，当前 {xt_symbol}",
                    )

            print(f"[DEBUG] 周期 {period_name} 完成，ok={ok_count}, fail={fail_count}")
            grand_ok += ok_count
            grand_fail += fail_count
            self.progress.emit(
                f"【{period_name}完成】成功 {ok_count}/{total}，失败 {fail_count}",
            )

        summary = (
            f"全部下载任务结束：\n"
            f"  成功 {grand_ok} / {grand_total}\n"
            f"  失败 {grand_fail}\n"
            f"  周期 {period_names}，区间 {self._start}~{self._end}"
        )
        self.finished.emit(True, summary)
