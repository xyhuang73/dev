# -*- coding: utf-8 -*-
"""
InnerStrategy 统一注册表：每个因子、策略一条编号记录，供回测下拉与引擎解析。

- 因子编号：F000001 起，对应「因子包 alpha_xxx」内的单条 feature 名。
- 策略编号：S000001 起，对应 strategies 下模块内的策略类。

首次缺失 ``inner_registry.json`` 时自动根据源码生成。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# 项目根目录
_PROJECT = Path(__file__).resolve().parent.parent
_INNER = _PROJECT / "InnerStrategy"
_FACTORS_DIR = _INNER / "factors"
_STRATEGIES_DIR = _INNER / "strategies"
_REGISTRY_PATH = _INNER / "inner_registry.json"


def _parse_alpha101_feature_names(py_text: str) -> list[str]:
    """从 alpha_101.py 文本提取已启用的 ``add_feature("name", ...)`` 名称（跳过整行注释）。"""
    out: list[str] = []
    for line in py_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        m = re.search(r'self\.add_feature\(\s*"([^"]+)"', line)
        if m:
            out.append(m.group(1))
    return out


def _alpha158_feature_names() -> list[str]:
    """按 Alpha158 类中的循环展开，与 alpha_158.py 逻辑一致（共 158 条）；窗口与 ``alpha_158_parameters.json`` 同步。"""
    try:
        from BackTest.factor_single_parameters_settings import alpha158_ts_windows  # noqa: PLC0415

        windows = alpha158_ts_windows()
    except Exception:  # noqa: BLE001 — 启动早期或循环依赖时回退缺省
        windows = [5, 10, 20, 30, 60]
    static = [
        "kmid",
        "klen",
        "kmid_2",
        "kup",
        "kup_2",
        "klow",
        "klow_2",
        "ksft",
        "ksft_2",
    ]
    out: list[str] = list(static)
    for field in ["open", "high", "low", "vwap"]:
        out.append(f"{field}_0")
    prefixes = [
        "roc_",
        "ma_",
        "std_",
        "beta_",
        "rsqr_",
        "resi_",
        "max_",
        "min_",
        "qtlu_",
        "qtld_",
        "rank_",
        "rsv_",
        "imax_",
        "imin_",
        "imxd_",
        "corr_",
        "cord_",
        "cntp_",
        "cntn_",
        "cntd_",
        "sump_",
        "sumn_",
        "sumd_",
        "vma_",
        "vstd_",
        "wvma_",
        "vsump_",
        "vsumn_",
        "vsumd_",
    ]
    for pref in prefixes:
        for w in windows:
            out.append(f"{pref}{w}")
    return out


def _parse_strategy_classes(file_path: Path) -> list[str]:
    """从单个 .py 文件中解析顶层 class 名称。"""
    text = file_path.read_text(encoding="utf-8")
    return re.findall(r"^class\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(|:)", text, re.MULTILINE)


def build_registry_dict() -> dict[str, Any]:
    """扫描 InnerStrategy/factors 与 strategies，生成注册表字典（不写盘）。"""
    factors: list[dict[str, str]] = []
    n = 0

    alpha101_path = _FACTORS_DIR / "alpha_101.py"
    if alpha101_path.is_file():
        names = _parse_alpha101_feature_names(alpha101_path.read_text(encoding="utf-8"))
        for feat in names:
            n += 1
            fid = f"F{n:06d}"
            factors.append(
                {
                    "id": fid,
                    "label": f"{fid} | Alpha101 | {feat}",
                    "pack": "alpha_101",
                    "feature": feat,
                }
            )

    alpha158_path = _FACTORS_DIR / "alpha_158.py"
    if alpha158_path.is_file():
        for feat in _alpha158_feature_names():
            n += 1
            fid = f"F{n:06d}"
            factors.append(
                {
                    "id": fid,
                    "label": f"{fid} | Alpha158 | {feat}",
                    "pack": "alpha_158",
                    "feature": feat,
                }
            )

    strategies: list[dict[str, str]] = []
    sn = 0
    if _STRATEGIES_DIR.is_dir():
        for py in sorted(_STRATEGIES_DIR.glob("*.py")):
            if py.name.startswith("_") or py.name == "__init__.py":
                continue
            module_stem = py.stem
            for class_name in _parse_strategy_classes(py):
                sn += 1
                sid = f"S{sn:06d}"
                strategies.append(
                    {
                        "id": sid,
                        "label": f"{sid} | {module_stem} | {class_name}",
                        "module": module_stem,
                        "class": class_name,
                    }
                )

    return {
        "version": 2,
        "factors": factors,
        "strategies": strategies,
    }


# 注册表结构升级时递增，旧文件会自动重写
_MIN_REGISTRY_VERSION = 2


def ensure_inner_registry_file() -> Path:
    """若 ``inner_registry.json`` 缺失、版本过旧或损坏则重新生成并返回路径。"""
    need_write = True
    if _REGISTRY_PATH.is_file():
        try:
            old = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
            if (
                int(old.get("version", 0)) >= _MIN_REGISTRY_VERSION
                and old.get("factors")
                and old.get("strategies")
            ):
                need_write = False
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            need_write = True
    # 仅在需要写盘时扫描源码构建字典，避免每次 load 都全量解析因子/策略文件
    if need_write:
        data = build_registry_dict()
        _REGISTRY_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return _REGISTRY_PATH


def force_rebuild_inner_registry_file() -> Path:
    """强制根据当前源码重写注册表（因子/策略变更后调用）。"""
    data = build_registry_dict()
    _REGISTRY_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return _REGISTRY_PATH


def load_registry() -> dict[str, Any]:
    """读取注册表；不存在则先构建。"""
    ensure_inner_registry_file()
    return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))


def list_factor_entries() -> list[tuple[str, str]]:
    """[(因子 id, 展示名), ...]，供 QComboBox 使用。"""
    reg = load_registry()
    return [(f["id"], f["label"]) for f in reg.get("factors", [])]


def list_strategy_entries() -> list[tuple[str, str]]:
    """[(策略 id, 展示名), ...]。"""
    reg = load_registry()
    return [(s["id"], s["label"]) for s in reg.get("strategies", [])]


def get_factor_entry(factor_id: str) -> dict[str, str] | None:
    """按因子 id 取一条记录（含 pack、feature），供向量/事件引擎解析。"""
    for f in load_registry().get("factors", []):
        if f.get("id") == factor_id:
            return f
    return None


def get_strategy_entry(strategy_id: str) -> dict[str, str] | None:
    """按策略 id 取 module / class。"""
    for s in load_registry().get("strategies", []):
        if s.get("id") == strategy_id:
            return s
    return None


def default_factor_id() -> str:
    """配置缺省因子 id（首条）。"""
    fac = list_factor_entries()
    return fac[0][0] if fac else "F000001"


def default_strategy_id() -> str:
    """配置缺省策略 id。"""
    st = list_strategy_entries()
    return st[0][0] if st else "S000001"


def resolve_factor_key(raw: str) -> str:
    """
    将配置中的因子键解析为注册表 id。

    兼容：空串、``F000001``、旧版整包名 ``alpha_101`` / ``alpha_158``（取该包内第一条）。
    """
    raw = (raw or "").strip()
    if not raw:
        return default_factor_id()
    if raw.startswith("F") and len(raw) == 7 and raw[1:].isdigit():
        return raw if get_factor_entry(raw) else default_factor_id()
    reg = load_registry()
    for f in reg.get("factors", []):
        if f.get("pack") == raw:
            return str(f["id"])
    return default_factor_id()


def resolve_strategy_key(raw: str) -> str:
    """
    将配置中的策略键解析为注册表 id。

    兼容：空串、``S000001``、旧版模块 stem（如 stratified_ls_sharpe_equal_weight_strategy）。
    """
    raw = (raw or "").strip()
    if not raw:
        return default_strategy_id()
    if raw.startswith("S") and len(raw) == 7 and raw[1:].isdigit():
        return raw if get_strategy_entry(raw) else default_strategy_id()
    reg = load_registry()
    for s in reg.get("strategies", []):
        if s.get("module") == raw:
            return str(s["id"])
    return default_strategy_id()


if __name__ == "__main__":
    # 手动重建：python -m InnerStrategy.inner_registry
    p = force_rebuild_inner_registry_file()
    reg = json.loads(p.read_text(encoding="utf-8"))
    print(f"已写入: {p}")
    print(f"因子条数: {len(reg.get('factors', []))}, 策略条数: {len(reg.get('strategies', []))}")
