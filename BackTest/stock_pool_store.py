# -*- coding: utf-8 -*-
"""
因子评估用「股票池」磁盘管理：读写 ``Config/stock_pool.json``。

约定::
    - 与 ``Config/backtest.json``、``Config/factor_evaluation.json`` 并列，专用于缓存筛选后的标的列表；
    - 结构保持扁平、可人工编辑；版本字段便于日后迁移。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 项目根（BackTest 的上一级）
_ROOT = Path(__file__).resolve().parent.parent

# 股票池 JSON 固定路径（因子评估第一步产出）
STOCK_POOL_JSON_PATH: Path = _ROOT / "Config" / "stock_pool.json"


def _defaults() -> dict[str, Any]:
    """首次创建文件时的空壳结构。"""
    return {
        "version": 1,
        "updated_at": "",
        "source": "",
        "symbols": [],
        "stats": {},
    }


def load_stock_pool_json() -> dict[str, Any]:
    """
    读取股票池；不存在则创建默认文件。

    Returns:
        含 ``symbols``（字符串列表）等字段的 dict。
    """
    STOCK_POOL_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STOCK_POOL_JSON_PATH.is_file():
        data = _defaults()
        STOCK_POOL_JSON_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return dict(data)
    raw = json.loads(STOCK_POOL_JSON_PATH.read_text(encoding="utf-8"))
    base = _defaults()
    changed = False
    for k, v in base.items():
        if k not in raw:
            raw[k] = v
            changed = True
    if changed:
        STOCK_POOL_JSON_PATH.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return raw


def save_stock_pool_json(data: dict[str, Any]) -> None:
    """整体写回 ``stock_pool.json``。"""
    STOCK_POOL_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    STOCK_POOL_JSON_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_stock_pool_snapshot(
    symbols: list[str],
    *,
    source: str,
    stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    写入一次构建结果并返回落盘内容（便于调用方放入 meta）。

    Args:
        symbols: 筛选后的 vt 列表（如 ``600000.SH``）。
        source: 人类可读来源说明（如板块名或 ``local_datadir``）。
        stats: 构建统计（剔除计数等）。
    """
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    payload: dict[str, Any] = {
        "version": 1,
        "updated_at": now,
        "source": source,
        "symbols": list(symbols),
        "stats": dict(stats or {}),
    }
    save_stock_pool_json(payload)
    return payload
