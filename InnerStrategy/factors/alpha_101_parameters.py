# -*- coding: utf-8 -*-
"""
Alpha101 可调参数：与同目录 ``alpha_101_parameters.json`` 读写。

- 若 JSON 不存在或为空 ``{}``，首次读取时用 ``BackTest.alpha_101_formula_defaults`` 写入**完整缺省**；
- ``alpha101_params()``：代码缺省为底，JSON 中的键做覆盖（便于只改部分因子）；
- ``merge_alpha101_patch``：供 ``patch_single_factor_parameters_json`` 深合并写入。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

# 与同目录 ``alpha_101.py`` 并列，路径固定便于工具与文档引用
ALPHA101_PARAMETERS_JSON_PATH: Path = Path(__file__).resolve().with_name("alpha_101_parameters.json")


def _deep_merge_dict(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    """递归合并字典（就地修改 ``dst``）。"""
    for k, v in src.items():
        if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
            _deep_merge_dict(dst[k], v)
        else:
            dst[k] = v
    return dst


def _defaults_from_code() -> dict[str, dict[str, Any]]:
    """与 ``alpha_101.py`` 公式一致的缺省表（单一真相在 BackTest 模块，避免与 JSON 双轨漂移）。"""
    from BackTest.alpha_101_formula_defaults import ALPHA101_FORMULA_DEFAULTS  # noqa: PLC0415

    return copy.deepcopy(ALPHA101_FORMULA_DEFAULTS)


def _bootstrap_json_if_empty() -> None:
    """JSON 缺失或为空时，用代码缺省生成完整文件。"""
    ALPHA101_PARAMETERS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    if ALPHA101_PARAMETERS_JSON_PATH.is_file():
        text = ALPHA101_PARAMETERS_JSON_PATH.read_text(encoding="utf-8").strip()
        if text and text != "{}":
            return
    base = _defaults_from_code()
    ALPHA101_PARAMETERS_JSON_PATH.write_text(
        json.dumps(base, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_alpha101_parameters_json() -> dict[str, Any]:
    """读取磁盘 JSON（必要时先 bootstrap）。"""
    _bootstrap_json_if_empty()
    raw = json.loads(ALPHA101_PARAMETERS_JSON_PATH.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def write_alpha101_parameters_json(data: dict[str, Any]) -> None:
    """整体写回 ``alpha_101_parameters.json``（调用方负责结构合法）。"""
    ALPHA101_PARAMETERS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALPHA101_PARAMETERS_JSON_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def alpha101_params() -> dict[str, dict[str, Any]]:
    """
    返回各 ``alphaN`` 的参数字典：以代码缺省为底，合并 ``alpha_101_parameters.json`` 中的项。

    JSON 中可省略若干 alpha；省略的条目完全沿用代码缺省。键名以 ``_`` 开头的条目忽略（预留元数据）。
    """
    code = _defaults_from_code()
    raw = read_alpha101_parameters_json()
    out = copy.deepcopy(code)
    for aid, uvals in raw.items():
        if str(aid).startswith("_"):
            continue
        if not isinstance(uvals, dict):
            continue
        if aid not in out:
            out[aid] = {}
        out[aid].update(uvals)
    return out


def merge_alpha101_patch(partial: dict[str, Any]) -> None:
    """
    将 ``partial``（alpha_id → 参数字典）深合并进 ``alpha_101_parameters.json``。

    供 ``BackTest.factor_single_parameters_settings`` 的 patch 路径调用。
    """
    cur = read_alpha101_parameters_json()
    for aid, uvals in partial.items():
        if str(aid).startswith("_"):
            continue
        if not isinstance(uvals, dict):
            continue
        if aid not in cur or not isinstance(cur.get(aid), dict):
            cur[aid] = {}
        _deep_merge_dict(cur[aid], dict(uvals))
    write_alpha101_parameters_json(cur)
