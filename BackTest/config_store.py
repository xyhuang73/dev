# -*- coding: utf-8 -*-
"""
回测专用配置文件 Config/backtest.json 的读写与缺省合并。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import BacktestJobConfig, BacktestMode

_ROOT = Path(__file__).resolve().parent.parent
BACKTEST_CONFIG_PATH = _ROOT / "Config" / "backtest.json"


def _defaults() -> dict[str, Any]:
    """与界面控件默认值一致；因子/策略使用编号 Fxxxxxx / Sxxxxxx。"""
    return {
        "initial_capital": 10000.0,
        "start_date": "20230101",
        "end_date": "20231231",
        "factor_key": "F000001",
        "strategy_key": "S000001",
        "backtest_mode": "vector",
    }


def load_backtest_json() -> dict[str, Any]:
    """读取 backtest.json；不存在则创建，缺键则补默认并写回。"""
    BACKTEST_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not BACKTEST_CONFIG_PATH.exists():
        data = _defaults()
        BACKTEST_CONFIG_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    else:
        data = json.loads(BACKTEST_CONFIG_PATH.read_text(encoding="utf-8"))
        defaults = _defaults()
        # 迁移：因子评估参数在 Config/factor_evaluation.json；旧版曾误将 factor_eval_front_n 写入 backtest.json
        migrated = data.pop("factor_eval_front_n", None) is not None
        missing = {k: defaults[k] for k in defaults if k not in data}
        if missing or migrated:
            data.update(missing)
            BACKTEST_CONFIG_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    return data


def save_backtest_json(data: dict[str, Any]) -> None:
    """整体写回配置文件。"""
    BACKTEST_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    BACKTEST_CONFIG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def dict_to_job(data: dict[str, Any]) -> BacktestJobConfig:
    """字典 → BacktestJobConfig，带类型与模式校验；兼容旧配置中的 pack 名 / 模块名。"""
    from InnerStrategy.inner_registry import (  # noqa: PLC0415
        default_factor_id,
        default_strategy_id,
        resolve_factor_key,
        resolve_strategy_key,
    )

    mode_raw = str(data.get("backtest_mode") or "vector").strip().lower()
    mode: BacktestMode = "vector" if mode_raw != "event" else "event"
    fk = resolve_factor_key(str(data.get("factor_key") or ""))
    sk = resolve_strategy_key(str(data.get("strategy_key") or ""))
    if not fk:
        fk = default_factor_id()
    if not sk:
        sk = default_strategy_id()
    return BacktestJobConfig(
        initial_capital=float(data.get("initial_capital") or 0.0),
        start_date=str(data.get("start_date") or "20230101"),
        end_date=str(data.get("end_date") or "20231231"),
        factor_key=fk,
        strategy_key=sk,
        backtest_mode=mode,
    )


def job_to_dict(job: BacktestJobConfig) -> dict[str, Any]:
    """BacktestJobConfig → 可 JSON 序列化的 dict。"""
    return {
        "initial_capital": job.initial_capital,
        "start_date": job.start_date,
        "end_date": job.end_date,
        "factor_key": job.factor_key,
        "strategy_key": job.strategy_key,
        "backtest_mode": job.backtest_mode,
    }
