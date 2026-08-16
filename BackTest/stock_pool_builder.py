# -*- coding: utf-8 -*-
"""
因子评估「第一步」：构建初步股票池并写入 ``Config/stock_pool.json``。

流程::
    - 读取 ``Config/factor_evaluation.json`` 中的开关与剔除选项；
    - **xtdata** 源：从 ``qmt.json`` 板块拉全列表，按规则逐项筛选直至凑满 ``max_symbols``；
    - **local_datadir** 源：枚举本地 ``*.DAT`` 推导 vt，仅能做不依赖接口的规则（如 B 股），
      ST/退市需简称时 **无法** 在纯离线下完成，将给出进度提示；
    - 若关闭 ``use_factor_stock_pool``，返回 ``None`` 表示回退为旧逻辑（直接板块截断）。

本模块依赖 ``stock_pool_universe_filter``（规则）与 ``stock_pool_store``（落盘），与 Alpha 计算解耦。
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Callable

from qmt_service import ensure_xtquant_path, get_local_datadir, load_config

from .factor_evaluation_settings import is_local_datadir_market_source, read_max_symbols_from_eval_cfg
from .qmt_client_guard import require_qmt_client_for_xtdata_datafeed
from .stock_pool_store import STOCK_POOL_JSON_PATH, load_stock_pool_json, write_stock_pool_snapshot
from .stock_pool_universe_filter import (
    fetch_xt_instrument_detail,
    is_b_share,
    should_keep_for_factor_pool,
)

ProgressCallback = Callable[[str], None]


def _noop(s: str) -> None:
    del s


def _iter_local_dat_vt_symbols(datadir: Path, period_name: str) -> list[str]:
    """
    枚举 ``datadir/**/{period}/*.DAT``，按路径排序得到 vt 列表并去重保序。
    """
    seen: set[str] = set()
    out: list[str] = []
    for fp in sorted(datadir.glob(f"**/{period_name}/*.DAT")):
        market = fp.parent.parent.name
        code = fp.stem
        vt = f"{code}.{market}"
        if vt in seen:
            continue
        seen.add(vt)
        out.append(vt)
    return out


def _build_pool_xtdata(
    _eval_cfg: dict[str, Any],
    *,
    max_symbols: int,
    exclude_b: bool,
    exclude_st: bool,
    exclude_del: bool,
    progress: ProgressCallback,
) -> tuple[list[str], dict[str, Any]]:
    """板块全量顺序遍历 + 规则 + 详情，凑满 ``max_symbols``。"""
    require_qmt_client_for_xtdata_datafeed()
    ensure_xtquant_path()
    from xtquant import xtdata  # type: ignore

    if hasattr(xtdata, "enable_hello"):
        xtdata.enable_hello = False  # type: ignore[union-attr]

    cfg = ensure_xtquant_path()
    sector = str(cfg.get("update_stock_sector") or "沪深A股").strip()
    progress(f"股票池：从板块「{sector}」拉取证券列表并筛选…")
    raw = list(xtdata.get_stock_list_in_sector(sector) or [])
    if not raw:
        raise RuntimeError(f"板块「{sector}」证券列表为空，请检查 qmt.json / 客户端连接。")

    stats: Counter[str] = Counter()
    out: list[str] = []
    for vt in raw:
        if max_symbols > 0 and len(out) >= max_symbols:
            break
        if exclude_b and is_b_share(vt):
            stats["drop_b_share"] += 1
            continue
        detail = None
        if exclude_st or exclude_del:
            detail = fetch_xt_instrument_detail(vt)
        keep, tag = should_keep_for_factor_pool(
            vt,
            detail,
            exclude_b_shares=False,
            exclude_st_by_name=exclude_st,
            exclude_delisted_meta=exclude_del,
        )
        if not keep:
            stats[tag] += 1
            continue
        if tag == "keep_no_detail":
            stats["keep_no_detail"] += 1
        out.append(vt)

    if not out:
        raise RuntimeError(
            "股票池筛选后为空：请放宽剔除条件、更换板块或检查 get_instrument_detail 是否可用。",
        )
    stats["max_symbols_applied"] = max_symbols
    snap = write_stock_pool_snapshot(
        out,
        source=f"xtdata:{sector}",
        stats=dict(stats),
    )
    progress(f"股票池已写入 Config/stock_pool.json（共 {len(out)} 只）。")
    return out, {"stock_pool_snapshot": snap, "stats": dict(stats)}


def _build_pool_local_datadir(
    _eval_cfg: dict[str, Any],
    *,
    max_symbols: int,
    exclude_b: bool,
    exclude_st: bool,
    exclude_del: bool,
    progress: ProgressCallback,
) -> tuple[list[str], dict[str, Any]]:
    """仅从本地 dat 文件名构造 vt；ST/退市在无 xtdata 时不剔除。"""
    datadir = get_local_datadir()
    cfg_q = load_config()
    period_name = str(cfg_q.get("kline_period_dir_name") or "86400")
    if not datadir.is_dir():
        raise FileNotFoundError(
            f"未找到本地行情目录: {datadir}\n"
            "请确认 Config/qmt.json 路径，或改用 market_data_source=xtdata。",
        )
    progress("股票池：扫描本地 datadir 日线文件并筛选（纯离线，ST/退市需简称时无法剔除）…")
    if exclude_st or exclude_del:
        progress(
            "提示：当前为 local_datadir，未调用 xtdata.get_instrument_detail；"
            "已跳过简称类 ST/退市剔除，仅保留代码规则（如 B 股）。",
        )

    all_vt = _iter_local_dat_vt_symbols(datadir, period_name)
    if not all_vt:
        raise RuntimeError(
            f"在 {datadir} 下未找到 **/{period_name}/*.DAT，无法构建股票池。",
        )

    stats: Counter[str] = Counter()
    out: list[str] = []
    for vt in all_vt:
        if max_symbols > 0 and len(out) >= max_symbols:
            break
        if exclude_b and is_b_share(vt):
            stats["drop_b_share"] += 1
            continue
        # 离线无法安全拉取简称：不调用 xtquant
        out.append(vt)

    if not out:
        raise RuntimeError("本地 dat 筛选后股票池为空，请检查数据或放宽条件。")

    stats["n_kept"] = len(out)
    stats["max_symbols_applied"] = max_symbols
    snap = write_stock_pool_snapshot(
        out,
        source="local_datadir",
        stats=dict(stats),
    )
    progress(f"股票池已写入 Config/stock_pool.json（共 {len(out)} 只）。")
    return out, {"stock_pool_snapshot": snap, "stats": dict(stats)}


def build_factor_evaluation_stock_pool(
    eval_cfg: dict[str, Any],
    *,
    progress: ProgressCallback = _noop,
) -> tuple[list[str] | None, dict[str, Any]]:
    """
    构建（或复用）因子评估用股票池。

    Returns:
        - ``(None, meta)``：配置关闭股票池功能，调用方应回退为 ``load_sector_stock_list(max_symbols)``；
        - ``(symbols, meta)``：非空列表，调用方应传入 ``build_daily_market_panel(..., stock_list=symbols)``。
    """
    use_pool = bool(eval_cfg.get("use_factor_stock_pool", True))
    if not use_pool:
        return None, {"use_factor_stock_pool": False}

    # max_symbols 统一由 GUI 的 spinBox_max_symbols 写入配置后读取，不再使用代码常量兜底。
    max_symbols = read_max_symbols_from_eval_cfg(eval_cfg)
    progress(f"股票池：读取 factor_evaluation.json 的 max_symbols={max_symbols}。")
    refresh = bool(eval_cfg.get("stock_pool_refresh_each_run", True))
    if not refresh:
        prev = load_stock_pool_json()
        syms = prev.get("symbols")
        if isinstance(syms, list) and len(syms) > 0:
            prev_list = [str(x) for x in syms]
            out_syms = prev_list[:max_symbols] if max_symbols > 0 else prev_list
            progress(
                f"股票池：复用 stock_pool.json（磁盘 {len(prev_list)} 只）→ 按 max_symbols 实际使用 {len(out_syms)} 只。",
            )
            # 若磁盘上仍为「旧的大池子」而本次只取前 N 只，回写 JSON，避免文件仍显示 4000 等误导
            if len(prev_list) != len(out_syms):
                base_stats = prev.get("stats") if isinstance(prev.get("stats"), dict) else {}
                write_stock_pool_snapshot(
                    out_syms,
                    source=f"{prev.get('source') or 'file'};trimmed_to_max_symbols",
                    stats={
                        **base_stats,
                        "max_symbols_applied": max_symbols,
                        "trimmed_from_count": len(prev_list),
                    },
                )
                progress(
                    f"已同步写回 stock_pool.json（现为 {len(out_syms)} 只，与 max_symbols 一致）。",
                )
            return out_syms, {
                "reused_stock_pool_file": True,
                "path": str(STOCK_POOL_JSON_PATH),
                "max_symbols_applied": max_symbols,
                "symbols_on_disk_before_trim": len(prev_list),
            }

    exclude_b = bool(eval_cfg.get("exclude_b_shares", True))
    exclude_st = bool(eval_cfg.get("exclude_st_by_name", True))
    exclude_del = bool(eval_cfg.get("exclude_delisted_meta", True))

    if is_local_datadir_market_source():
        return _build_pool_local_datadir(
            eval_cfg,
            max_symbols=max_symbols,
            exclude_b=exclude_b,
            exclude_st=exclude_st,
            exclude_del=exclude_del,
            progress=progress,
        )

    return _build_pool_xtdata(
        eval_cfg,
        max_symbols=max_symbols,
        exclude_b=exclude_b,
        exclude_st=exclude_st,
        exclude_del=exclude_del,
        progress=progress,
    )
