# -*- coding: utf-8 -*-
"""策略回测报告的成交标记适配器。

输入是报告路径和证券代码，输出统一为 ``BUY``/``SELL`` 动作，供 GUI
绘图复用。这里兼容历史报告中的中英文动作值，但不依赖任何 Qt 组件。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd


MARKER_COLUMNS = ["datetime", "action", "price", "action_raw"]


def _empty_markers() -> pd.DataFrame:
    return pd.DataFrame(columns=MARKER_COLUMNS)


def normalize_trade_action(value: object) -> str | None:
    """把历史报告中的动作别名归一为 ``BUY`` 或 ``SELL``。"""
    raw = str(value or "").strip()
    lowered = raw.lower()
    if lowered in {"buy", "b", "long", "open_long"} or "买" in raw:
        return "BUY"
    if lowered in {"sell", "s", "short", "close_long"} or "卖" in raw:
        return "SELL"
    return None


def load_trade_markers(report_path: str | Path | None, symbol: str) -> pd.DataFrame:
    """读取指定报告和证券的有效成交标记，并归一化日期、价格和动作。"""
    if not report_path:
        return _empty_markers()
    path = Path(report_path)
    if not path.is_file():
        return _empty_markers()
    try:
        trades = pd.read_excel(path, sheet_name="逐笔买卖明细")
    except Exception:  # noqa: BLE001 - 兼容旧报告、损坏报告和缺失工作表
        return _empty_markers()

    required = {"vt_symbol", "datetime", "action", "price"}
    if trades.empty or not required.issubset(trades.columns):
        return _empty_markers()

    selected = trades.loc[
        trades["vt_symbol"].astype(str).str.strip() == str(symbol).strip(),
        ["datetime", "action", "price"],
    ].copy()
    selected["action_raw"] = selected["action"]
    selected["action"] = selected["action"].map(normalize_trade_action)
    try:
        parsed_datetime = pd.to_datetime(selected["datetime"], errors="coerce", format="mixed")
    except TypeError:  # pandas < 2.0 不支持 format="mixed"
        parsed_datetime = pd.to_datetime(selected["datetime"], errors="coerce")
    selected["datetime"] = parsed_datetime.dt.normalize()
    selected["price"] = pd.to_numeric(selected["price"], errors="coerce")
    selected = selected.dropna(subset=["datetime", "action", "price"])
    return selected[MARKER_COLUMNS].sort_values("datetime", kind="mergesort").reset_index(drop=True)
