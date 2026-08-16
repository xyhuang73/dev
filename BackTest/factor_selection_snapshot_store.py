# -*- coding: utf-8 -*-
"""
因子选择结果快照（selection_feasible）读写。

用途：
- 批量评估完成后落盘最新可行性结果；
- 交易策略启动时读取，用于买入/强平门控。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .factor_batch_job import FactorEvalRow

_ROOT = Path(__file__).resolve().parent.parent
FACTOR_SELECTION_SNAPSHOT_PATH: Path = _ROOT / "Config" / "factor_selection_snapshot.json"


def save_factor_selection_snapshot(rows: list[FactorEvalRow]) -> Path:
    """将本次评估结果写入快照，供策略运行时读取。"""
    payload: dict[str, Any] = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "factors": {},
    }
    factors: dict[str, Any] = payload["factors"]
    for r in rows:
        # 以 factor_id 为主键覆盖写入；重复 id 时以最后一条为准。
        factors[str(r.factor_id)] = {
            "selection_feasible": bool(r.selection_feasible),
            "selection_objective": float(r.selection_objective),
            "selection_reason": str(r.selection_reason),
            "error": str(r.error),
        }
    FACTOR_SELECTION_SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    FACTOR_SELECTION_SNAPSHOT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return FACTOR_SELECTION_SNAPSHOT_PATH


def load_factor_selection_snapshot() -> dict[str, Any]:
    """读取快照；缺失或损坏时返回空结构，调用方可按“未知=不通过”处理。"""
    if not FACTOR_SELECTION_SNAPSHOT_PATH.is_file():
        return {"updated_at": "", "factors": {}}
    try:
        raw = json.loads(FACTOR_SELECTION_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"updated_at": "", "factors": {}}
    if not isinstance(raw, dict):
        return {"updated_at": "", "factors": {}}
    factors = raw.get("factors")
    if not isinstance(factors, dict):
        factors = {}
    return {
        "updated_at": str(raw.get("updated_at") or ""),
        "factors": factors,
    }
