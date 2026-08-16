# -*- coding: utf-8 -*-
"""
**单因子计算**参数读写。

- ``Config/single_factor_parameters.json``：仅 **Alpha prepare 并行度** 等全局项（``alpha_prepare_max_workers``）；
- ``InnerStrategy/factors/alpha_101_parameters.json``：与 ``alpha_101.py`` 同名，存 Alpha101 全量参数（空文件时由代码缺省自动生成）；逻辑见 ``InnerStrategy/factors/alpha_101_parameters.py``；
- ``InnerStrategy/factors/alpha_158_parameters.json``：与 ``alpha_158.py`` 同名，Alpha158 **时序窗口** 与公式常数。

历史 ``Config/single_factor_parameters.json`` 中若仍含 ``alpha101`` / ``alpha158`` / ``alpha158_ts_windows``，
首次 ``load_single_factor_parameters_json`` 会 **迁移** 到上述 factors 下 JSON 并从配置中删除。

合并文件 ``factor_parameters.json`` 的拆分迁移在 ``factor_evaluation_settings`` 中完成。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent

FACTOR_SINGLE_PARAMETERS_JSON_PATH: Path = _ROOT / "Config" / "single_factor_parameters.json"

from InnerStrategy.factors.alpha_101_parameters import (  # noqa: E402
    ALPHA101_PARAMETERS_JSON_PATH,
)

ALPHA158_PARAMETERS_JSON_PATH: Path = _ROOT / "InnerStrategy" / "factors" / "alpha_158_parameters.json"


def _alpha158_scalar_defaults() -> dict[str, Any]:
    """Alpha158 公式常数缺省（与 alpha_158_parameters.json 可合并的键）。"""
    return {
        "eps": 1e-12,
        "quantile_high": 0.8,
        "quantile_low": 0.2,
        "log_volume_offset": 1.0,
    }


def _default_alpha158_file_dict() -> dict[str, Any]:
    """``alpha_158_parameters.json`` 首次落盘内容。"""
    return {
        "alpha158_ts_windows": [5, 10, 20, 30, 60],
        **dict(_alpha158_scalar_defaults()),
    }


def _defaults_config_only() -> dict[str, Any]:
    """仅写入 ``Config/single_factor_parameters.json`` 的键。"""
    return {
        "alpha_prepare_max_workers": 1,
    }


def _deep_merge_dict(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    """递归合并字典。"""
    for k, v in src.items():
        if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
            _deep_merge_dict(dst[k], v)
        else:
            dst[k] = v
    return dst


def _ensure_alpha158_parameters_file() -> dict[str, Any]:
    """若 ``alpha_158_parameters.json`` 不存在则写入缺省。"""
    ALPHA158_PARAMETERS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not ALPHA158_PARAMETERS_JSON_PATH.is_file():
        data = _default_alpha158_file_dict()
        ALPHA158_PARAMETERS_JSON_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return dict(data)
    return json.loads(ALPHA158_PARAMETERS_JSON_PATH.read_text(encoding="utf-8"))


def _write_alpha158_parameters_file(data: dict[str, Any]) -> None:
    ALPHA158_PARAMETERS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALPHA158_PARAMETERS_JSON_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _patch_sidecar_factor_parameters(updates: dict[str, Any]) -> None:
    """
    将 ``alpha101`` / ``alpha158`` / ``alpha158_ts_windows`` 写入 factors 下同名 JSON。

    ``alpha158`` 若为嵌套 dict（旧格式），会摊平合并进 ``alpha_158_parameters.json`` 顶层。
    """
    if "alpha158_ts_windows" in updates:
        cur158 = _ensure_alpha158_parameters_file()
        cur158["alpha158_ts_windows"] = updates["alpha158_ts_windows"]
        _write_alpha158_parameters_file(cur158)
    if "alpha158" in updates and isinstance(updates["alpha158"], dict):
        cur158 = _ensure_alpha158_parameters_file()
        _deep_merge_dict(cur158, dict(updates["alpha158"]))
        _write_alpha158_parameters_file(cur158)
    if "alpha101" in updates and isinstance(updates["alpha101"], dict):
        from InnerStrategy.factors.alpha_101_parameters import merge_alpha101_patch  # noqa: PLC0415

        merge_alpha101_patch(dict(updates["alpha101"]))


def absorb_keys_into_factor_parameter_files(sidecar: dict[str, Any]) -> dict[str, Any]:
    """
    从「本应只在 Config 单因子文件」的 dict 中拆出 alpha101/158 相关键，写入 factors 下 JSON。

    Returns:
        仅含应保留在 ``single_factor_parameters.json`` 的键（如 ``alpha_prepare_max_workers``）。
    """
    out: dict[str, Any] = {}
    patch: dict[str, Any] = {}
    for k, v in sidecar.items():
        if k in ("alpha101", "alpha158", "alpha158_ts_windows"):
            patch[k] = v
        else:
            out[k] = v
    if patch:
        _patch_sidecar_factor_parameters(patch)
    return out


def _migrate_legacy_keys_from_config_raw(raw: dict[str, Any]) -> bool:
    """若 ``raw`` 仍含已迁到 factors 的键，则迁移并返回是否改写磁盘。"""
    legacy = ("alpha101", "alpha158", "alpha158_ts_windows")
    if not any(k in raw for k in legacy):
        return False
    absorbed = {k: raw.pop(k) for k in legacy if k in raw}
    _patch_sidecar_factor_parameters(absorbed)
    return True


def load_single_factor_parameters_json() -> dict[str, Any]:
    """读取 ``Config/single_factor_parameters.json`` 并合并缺省；同时迁移旧键到 factors JSON。"""
    FACTOR_SINGLE_PARAMETERS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not FACTOR_SINGLE_PARAMETERS_JSON_PATH.is_file():
        data = dict(_defaults_config_only())
        FACTOR_SINGLE_PARAMETERS_JSON_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return dict(data)
    raw = json.loads(FACTOR_SINGLE_PARAMETERS_JSON_PATH.read_text(encoding="utf-8"))
    changed = False
    if _migrate_legacy_keys_from_config_raw(raw):
        changed = True
    defaults = _defaults_config_only()
    for k, v in defaults.items():
        if k not in raw:
            raw[k] = v
            changed = True
    if changed:
        FACTOR_SINGLE_PARAMETERS_JSON_PATH.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return raw


def save_single_factor_parameters_json(data: dict[str, Any]) -> None:
    """整体写回 ``single_factor_parameters.json``（勿写入 alpha101/158 侧车键）。"""
    clean = {k: v for k, v in data.items() if k not in ("alpha101", "alpha158", "alpha158_ts_windows")}
    FACTOR_SINGLE_PARAMETERS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    FACTOR_SINGLE_PARAMETERS_JSON_PATH.write_text(
        json.dumps(clean, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def patch_single_factor_parameters_json(updates: dict[str, Any]) -> dict[str, Any]:
    """合并 ``updates``：侧车键写 factors JSON，其余写 Config。"""
    side = {k: v for k, v in updates.items() if k in ("alpha101", "alpha158", "alpha158_ts_windows")}
    rest = {k: v for k, v in updates.items() if k not in side}
    if side:
        _patch_sidecar_factor_parameters(side)
    if rest:
        cur = load_single_factor_parameters_json()
        cur.update(rest)
        save_single_factor_parameters_json(cur)
    return load_single_factor_parameters_json()


def absorb_stray_keys_from_factor_evaluation(stray: dict[str, Any]) -> None:
    """
    从 ``factor_evaluation.json`` 误写入的单因子键迁回正确位置（供 ``load_factor_evaluation_json`` 调用）。

    ``alpha_prepare_max_workers`` → Config；``alpha101``/``alpha158``/``alpha158_ts_windows`` → factors JSON。
    """
    if not stray:
        return
    prep = {k: v for k, v in stray.items() if k == "alpha_prepare_max_workers"}
    side = {k: v for k, v in stray.items() if k in ("alpha101", "alpha158", "alpha158_ts_windows")}
    if side:
        _patch_sidecar_factor_parameters(side)
    if prep:
        cur = load_single_factor_parameters_json()
        cur.update(prep)
        save_single_factor_parameters_json(cur)


def alpha158_ts_windows() -> list[int]:
    """供 Alpha158 / 注册表展开使用的窗口列表。"""
    raw = _ensure_alpha158_parameters_file().get("alpha158_ts_windows")
    if not isinstance(raw, list) or not raw:
        return list(_default_alpha158_file_dict()["alpha158_ts_windows"])
    out: list[int] = []
    for x in raw:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out if out else list(_default_alpha158_file_dict()["alpha158_ts_windows"])


def alpha158_formula_params() -> dict[str, Any]:
    """Alpha158 公式常数（不含 ``alpha158_ts_windows`` 键）。"""
    full = _ensure_alpha158_parameters_file()
    out = dict(_alpha158_scalar_defaults())
    for k, v in full.items():
        if k == "alpha158_ts_windows":
            continue
        out[k] = v
    return out


def alpha101_params() -> dict[str, dict[str, Any]]:
    """委托 ``InnerStrategy/factors/alpha_101_parameters.py``（与 JSON 同目录）。"""
    from InnerStrategy.factors.alpha_101_parameters import alpha101_params as _params  # noqa: PLC0415

    return _params()
