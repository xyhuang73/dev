# -*- coding: utf-8 -*-
"""
在 QThread 中运行全因子评估，避免阻塞 UI；进度通过 Signal 回传主线程。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from .factor_batch_job import run_full_factor_evaluation
from .factor_evaluation_report import write_factor_evaluation_excel
from .factor_selection_snapshot_store import save_factor_selection_snapshot


class FactorEvaluationWorker(QObject):
    """后台线程内对象：执行批量因子计算与 Excel 导出。"""

    progress = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, start_yyyymmdd: str, end_yyyymmdd: str, max_factors: int) -> None:
        super().__init__()
        self._start = start_yyyymmdd.strip()
        self._end = end_yyyymmdd.strip()
        # 仅评估注册表排序后的前 N 个因子，0 或负数表示不截断（兼容旧调用）
        self._max_factors = int(max_factors)

    @Slot()
    def run(self) -> None:
        try:

            def _cb(line: str) -> None:
                self.progress.emit(line)

            mf = self._max_factors if self._max_factors > 0 else None
            rows, meta = run_full_factor_evaluation(
                self._start,
                self._end,
                progress=_cb,
                max_factors=mf,
            )
            # 评估完成后落盘快照，供交易策略读取 selection_feasible 门控。
            snap = save_factor_selection_snapshot(rows)
            self.progress.emit(f"已更新因子评估快照: {snap}")
            self.progress.emit("写入 Excel 报告（汇总阶段，单线程）…")
            path = write_factor_evaluation_excel(rows, meta, top_n=10)
            n = len(rows)
            ok_msg = (
                f"全因子评估完成，共 {n} 条。\n"
                f"Excel 报告:\n{path}\n"
                "（含「测试参数」「指标与列说明」「全部因子」「Top10_IC门槛与多空夏普」工作表）"
            )
            self.finished.emit(True, ok_msg)
        except Exception as exc:  # noqa: BLE001
            self.finished.emit(False, f"{type(exc).__name__}: {exc}")
