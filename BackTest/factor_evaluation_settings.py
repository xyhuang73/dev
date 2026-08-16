# -*- coding: utf-8 -*-
"""
**批量因子评估**相关参数：只读写 ``Config/factor_evaluation.json``。

设计约定::
    - IC 门槛、分层、行情规模、评估前 N 个、股票池、因子级并行封顶、QMT 进程检测等 **评估任务** 参数放此文件；
    - **单因子计算**参数：``alpha_prepare_max_workers`` 见 ``Config/single_factor_parameters.json``；
      Alpha101/Alpha158 与源码同名的 ``InnerStrategy/factors/alpha_101_parameters.json``、
      ``alpha_158_parameters.json`` 由 ``factor_single_parameters_settings`` 读写；
    - 若仍存在历史合并文件 ``Config/factor_parameters.json``，首次加载本模块时会 **拆分** 为上述两个文件并删除合并文件。

``factor_selection_objective.evaluate_factor_feasibility_and_objective`` 依赖本模块中的 ``SchemeBConfig``。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent

FACTOR_EVALUATION_CONFIG_PATH: Path = _ROOT / "Config" / "factor_evaluation.json"
FACTOR_EVAL_CONFIG_PATH = FACTOR_EVALUATION_CONFIG_PATH

# 历史误合并的「因子参数」单文件（仅用于一次性拆分迁移）
_LEGACY_COMBINED_PARAMETERS: Path = _ROOT / "Config" / "factor_parameters.json"
_SINGLE_FACTOR_PARAMETERS_PATH: Path = _ROOT / "Config" / "single_factor_parameters.json"


def _single_factor_keys() -> frozenset[str]:
    """属于单因子计算、不应出现在 factor_evaluation.json 的键。"""
    return frozenset({"alpha_prepare_max_workers", "alpha158_ts_windows", "alpha101", "alpha158"})


def _eval_defaults() -> dict[str, Any]:
    """批量因子评估缺省（不含单因子键）。"""
    return {
        "min_rank_ic_mean": 0.0,
        "min_ic_ir": 0.0,
        "annualization_days": 252,
        "n_quantiles": 10,
        "min_names_per_day": 30,
        "factor_eval_parallel_cap": 0,
        "market_data_source": "xtdata",
        "factor_eval_front_n": 20,
        "skip_qmt_process_check": False,
        "qmt_process_name_substrings": ["XtMiniQmt", "miniqmt", "XtItClient", "QMT"],
        "use_factor_stock_pool": True,
        "stock_pool_refresh_each_run": True,
        "exclude_b_shares": True,
        "exclude_st_by_name": True,
        "exclude_delisted_meta": True,
    }


def _single_factor_defaults() -> dict[str, Any]:
    """拆分 legacy 时写入 ``single_factor_parameters.json`` 的底稿（仅 Config 内键）。"""
    return {
        "alpha_prepare_max_workers": 1,
    }


def _maybe_split_legacy_combined_parameters() -> None:
    """
    若存在 ``factor_parameters.json``（曾把评估与单因子混写），拆成::

        - ``factor_evaluation.json``：评估键；
        - ``single_factor_parameters.json``：单因子键；

    然后删除合并文件。
    """
    if not _LEGACY_COMBINED_PARAMETERS.is_file():
        return
    try:
        raw = json.loads(_LEGACY_COMBINED_PARAMETERS.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return
    except (OSError, json.JSONDecodeError):
        return
    sk = _single_factor_keys()
    single_part: dict[str, Any] = {**_single_factor_defaults()}
    for k in sk:
        if k in raw:
            single_part[k] = raw[k]
    eval_part: dict[str, Any] = {k: v for k, v in raw.items() if k not in sk}
    for k, v in _eval_defaults().items():
        if k not in eval_part:
            eval_part[k] = v
    FACTOR_EVALUATION_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SINGLE_FACTOR_PARAMETERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    FACTOR_EVALUATION_CONFIG_PATH.write_text(
        json.dumps(eval_part, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _SINGLE_FACTOR_PARAMETERS_PATH.write_text(
        json.dumps(single_part, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        _LEGACY_COMBINED_PARAMETERS.unlink()
    except OSError:
        pass


@dataclass(frozen=True)
class SchemeBConfig:
    """IC 门槛与分层多空夏普：与 JSON 中数值键一一对应（仅含截面/方案相关子集）。"""

    min_rank_ic_mean: float = 0.0
    min_ic_ir: float = 0.0
    annualization_days: int = 252
    n_quantiles: int = 10
    min_names_per_day: int = 30


def load_factor_evaluation_json() -> dict[str, Any]:
    """
    读取 ``factor_evaluation.json`` 并合并缺省键；不存在则创建。

    Returns:
        可直接修改的 dict；持久化请用 ``save_factor_evaluation_json``。
    """
    FACTOR_EVALUATION_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _maybe_split_legacy_combined_parameters()

    if not FACTOR_EVALUATION_CONFIG_PATH.is_file():
        data = dict(_eval_defaults())
        FACTOR_EVALUATION_CONFIG_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return dict(data)
    raw = json.loads(FACTOR_EVALUATION_CONFIG_PATH.read_text(encoding="utf-8"))
    defaults = _eval_defaults()
    changed = False
    for k, v in defaults.items():
        if k not in raw:
            raw[k] = v
            changed = True
    # 若误写入单因子键，剥离到单因子文件（轻量自愈）
    sk = _single_factor_keys()
    stray = {k: raw.pop(k) for k in list(raw.keys()) if k in sk}
    if stray:
        changed = True
        try:
            from .factor_single_parameters_settings import (  # noqa: PLC0415
                absorb_stray_keys_from_factor_evaluation,
            )

            absorb_stray_keys_from_factor_evaluation(
                {k: v for k, v in stray.items() if v is not None},
            )
        except Exception:  # noqa: BLE001 — 自愈失败则仅丢弃误写入键
            pass
    if changed:
        FACTOR_EVALUATION_CONFIG_PATH.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return raw


def save_factor_evaluation_json(data: dict[str, Any]) -> None:
    """整体写回 ``factor_evaluation.json``（调用方勿写入单因子键）。"""
    clean = {k: v for k, v in data.items() if k not in _single_factor_keys()}
    FACTOR_EVALUATION_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    FACTOR_EVALUATION_CONFIG_PATH.write_text(
        json.dumps(clean, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def patch_factor_evaluation_json(updates: dict[str, Any]) -> dict[str, Any]:
    """合并 ``updates`` 后保存；单因子键改写到 Config 或 ``factors/alpha_*_parameters.json``。"""
    single_updates = {k: v for k, v in updates.items() if k in _single_factor_keys()}
    eval_updates = {k: v for k, v in updates.items() if k not in _single_factor_keys()}
    if single_updates:
        from .factor_single_parameters_settings import patch_single_factor_parameters_json  # noqa: PLC0415

        patch_single_factor_parameters_json(single_updates)
    cur = load_factor_evaluation_json()
    cur.update(eval_updates)
    save_factor_evaluation_json(cur)
    return load_factor_evaluation_json()


def dict_to_scheme_b(data: dict[str, Any]) -> SchemeBConfig:
    """JSON 扁平 dict → ``SchemeBConfig``（仅用 IC 方案相关键）。"""
    d = {**_eval_defaults(), **{k: v for k, v in data.items() if k not in _single_factor_keys()}}
    return SchemeBConfig(
        min_rank_ic_mean=float(d["min_rank_ic_mean"]),
        min_ic_ir=float(d["min_ic_ir"]),
        annualization_days=int(d["annualization_days"]),
        n_quantiles=int(d["n_quantiles"]),
        min_names_per_day=int(d["min_names_per_day"]),
    )


def read_max_symbols_from_eval_cfg(data: dict[str, Any]) -> int:
    """
    从 ``factor_evaluation.json`` 读取 ``max_symbols``。

    约定：该值由 GUI 的 ``spinBox_max_symbols`` 持久化写入；业务代码不再内置默认常量。
    """
    if "max_symbols" not in data:
        raise KeyError("factor_evaluation.json 缺少 max_symbols，请在 GUI 的 spinBox_max_symbols 里设置后重试。")
    raw = data.get("max_symbols")
    try:
        v = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"max_symbols 非法: {raw!r}") from exc
    # 0 表示不限制，与行情/股票池模块既有约定一致。
    if v < 0:
        raise ValueError(f"max_symbols 不能为负数: {v}")
    return v


def is_local_datadir_market_source() -> bool:
    """为 True 时因子回测行情仅从本地 DAT 组装，不加载 xtquant。"""
    m = str(load_factor_evaluation_json().get("market_data_source") or "xtdata").strip().lower()
    return m in ("local_datadir", "offline", "datadir", "local")


# ---------------------------------------------------------------------------
# 兼容旧名：历史上曾用「factor_parameters」指合并 JSON；现评估项在 factor_evaluation.json。
# 旧代码仍可调这些别名；单因子键请用 factor_single_parameters_settings。
# ---------------------------------------------------------------------------
FACTOR_PARAMETERS_JSON_PATH = FACTOR_EVALUATION_CONFIG_PATH


def load_factor_parameters_json() -> dict[str, Any]:
    """兼容：等价于 ``load_factor_evaluation_json``（仅批量评估键）。"""
    return load_factor_evaluation_json()


def save_factor_parameters_json(data: dict[str, Any]) -> None:
    """兼容：等价于 ``save_factor_evaluation_json``。"""
    save_factor_evaluation_json(data)


def patch_factor_parameters_json(updates: dict[str, Any]) -> dict[str, Any]:
    """兼容：等价于 ``patch_factor_evaluation_json``（单因子键改写到 Config 或 factors 下 alpha_*_parameters.json）。"""
    return patch_factor_evaluation_json(updates)
