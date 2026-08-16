# -*- coding: utf-8 -*-
"""
全因子批量评估：行情面板 → 按 pack 缓存 Alpha raw_df → **因子级并行**截面指标 → IC 门槛与多空夏普筛选。

- 阶段 1：各因子包（alpha_101 / alpha_158）顺序 prepare_data 一次；包内多特征并行度由 ``alpha_prepare_max_workers`` 控制。
- 阶段 2：本批「前 N 个」因子并行做 long_table + 截面 IC（线程数默认 = N，可用 ``factor_eval_parallel_cap`` 封顶）。
- 全部完成后按注册表顺序汇总，再写 Excel 报告。

供 UI 线程通过回调输出进度；核心逻辑可在工作线程执行。
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Callable

import pandas as pd

from InnerStrategy.inner_registry import load_registry

from .factor_alpha_runner import long_table_for_feature, prepare_alpha_pack_raw_df
from .factor_cross_section_metrics import (
    CrossSectionMetricsResult,
    compute_cross_section_metrics,
    metrics_to_serializable,
)
from .factor_evaluation_config import (
    dict_to_scheme_b,
    is_local_datadir_market_source,
    load_factor_evaluation_json,
    load_single_factor_parameters_json,
)
from .factor_market_panel import build_daily_market_panel, iso_period_triple
from .factor_evaluation_settings import SchemeBConfig
from .factor_evaluation_settings import read_max_symbols_from_eval_cfg
from .factor_selection_objective import evaluate_factor_feasibility_and_objective
from .stock_pool_builder import build_factor_evaluation_stock_pool


ProgressCallback = Callable[[str], None]


@dataclass
class FactorEvalRow:
    """单个因子的评估结果行（可序列化）。"""

    factor_id: str
    label: str
    pack: str
    feature: str
    error: str
    metrics: dict[str, Any]
    selection_feasible: bool
    selection_objective: float
    selection_reason: str


def _noop(s: str) -> None:
    del s


def _parallel_factor_workers(n_factors: int, cfg: dict[str, Any]) -> int:
    """
    因子级（截面 IC）并行线程数：默认等于本批因子个数 N；可用 ``factor_eval_parallel_cap`` 封顶。
    """
    if n_factors < 1:
        return 1
    cap_raw = cfg.get("factor_eval_parallel_cap")
    try:
        cap = int(cap_raw) if cap_raw is not None else 0
    except (TypeError, ValueError):
        cap = 0
    if cap <= 0:
        return n_factors
    return max(1, min(n_factors, cap))


def _evaluate_one_factor_entry(
    entry: dict[str, str],
    raw_df: pd.DataFrame,
    selection_cfg: SchemeBConfig,
) -> FactorEvalRow:
    """
    单因子：长表 → 截面指标 → 规则判定；供线程池调用（依赖已就绪的 ``raw_df``）。
    """
    fid = str(entry.get("id", ""))
    label = str(entry.get("label", ""))
    pack = str(entry.get("pack", ""))
    feature = str(entry.get("feature", ""))

    err = ""
    metrics_d: dict[str, Any] = {}
    feasible = False
    obj = float("-inf")
    reason = ""

    try:
        lf = long_table_for_feature(raw_df, feature)
        m: CrossSectionMetricsResult = compute_cross_section_metrics(
            lf,
            "_factor_value",
            "fwd_ret",
            selection_cfg,
        )
        metrics_d = metrics_to_serializable(m)
        out = evaluate_factor_feasibility_and_objective(
            m.rank_ic_mean,
            m.ic_ir,
            m.long_short_sharpe,
            selection_cfg,
        )
        feasible = out.feasible
        obj = out.objective_value
        reason = out.reason
        if not feasible and m.n_ic_days == 0 and m.n_trade_dates > 0:
            reason = (
                f"{reason} | 诊断: 交易日={m.n_trade_dates}, "
                f"未达min_names日={m.n_days_skip_min_names}, "
                f"单日有效样本数[min,中位]=[{m.min_daily_valid_names},{m.median_daily_valid_names:.1f}], "
                f"因子截面近似常数日={m.n_days_ic_nan_const_factor}, "
                f"fwd_ret截面近似常数日={m.n_days_ic_nan_const_fwd_ret}, "
                f"截面有效样本<3日={m.n_days_ic_nan_small_cross}"
            )
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
        reason = err

    return FactorEvalRow(
        factor_id=fid,
        label=label,
        pack=pack,
        feature=feature,
        error=err,
        metrics=metrics_d,
        selection_feasible=feasible,
        selection_objective=obj,
        selection_reason=reason,
    )


def run_full_factor_evaluation(
    start_yyyymmdd: str,
    end_yyyymmdd: str,
    selection_cfg: SchemeBConfig | None = None,
    progress: ProgressCallback = _noop,
    max_factors: int | None = None,
) -> tuple[list[FactorEvalRow], dict[str, Any]]:
    """
    执行全因子评估。

    Args:
        max_factors: 仅取注册表 factors 列表前 N 条；``None`` 或 ``<=0`` 表示全量。

    Returns:
        (各行结果, 元数据 dict 含测试参数与运行时刻)
    """
    cfg_json = load_factor_evaluation_json()
    single_json = load_single_factor_parameters_json()
    selection_cfg = selection_cfg or dict_to_scheme_b(cfg_json)
    # max_symbols 统一由 GUI 的 spinBox_max_symbols 写入配置后读取，不再使用代码常量兜底。
    max_symbols = read_max_symbols_from_eval_cfg(cfg_json)
    # 包内 prepare 并行度来自单因子配置，与批量评估 JSON 分离
    max_workers = int(single_json.get("alpha_prepare_max_workers") or 1)

    meta: dict[str, Any] = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "start_date": start_yyyymmdd,
        "end_date": end_yyyymmdd,
        "selection_rule": asdict(selection_cfg),
        "evaluation_config": cfg_json,
        "single_factor_parameters": single_json,
        "factor_eval_front_n": int(max_factors) if max_factors is not None else None,
    }

    # 第一步：构建/复用股票池（写入 Config/stock_pool.json），再按池子拉行情
    pool_syms, pool_meta = build_factor_evaluation_stock_pool(cfg_json, progress=progress)
    meta["stock_pool_meta"] = pool_meta

    # local_datadir：纯磁盘 *.DAT，不经过 xtquant；xtdata：原生库（需客户端就绪）
    use_local_datadir = is_local_datadir_market_source()
    if pool_syms is not None:
        progress(
            f"加载行情数据（股票池 {len(pool_syms)} 只；"
            + ("本地 datadir）…" if use_local_datadir else "xtdata）…"),
        )
    else:
        progress(
            "加载行情数据（未使用股票池；"
            + ("本地 datadir，无 xtquant）…" if use_local_datadir else "xtdata）…"),
        )
    base_panel = build_daily_market_panel(
        start_yyyymmdd,
        end_yyyymmdd,
        max_symbols,
        stock_list=pool_syms,
    )
    meta["n_bar_rows"] = len(base_panel)
    meta["n_symbols"] = int(base_panel["vt_symbol"].nunique())

    train_p, valid_p, test_p = iso_period_triple(start_yyyymmdd, end_yyyymmdd)
    reg = load_registry()
    factors: list[dict[str, str]] = list(reg.get("factors", []))
    if max_factors is not None and max_factors > 0:
        factors = factors[: int(max_factors)]

    n_batch = len(factors)
    factor_pw = _parallel_factor_workers(n_batch, cfg_json)
    meta["factor_level_parallel_workers"] = factor_pw
    meta["factor_eval_unique_packs"] = list(
        dict.fromkeys(str(e.get("pack", "")) for e in factors),
    )

    # —— 阶段 1：按因子包去重，顺序 prepare_data（包内特征仍可用 alpha_prepare_max_workers 并行）——
    pack_cache: dict[str, pd.DataFrame] = {}
    unique_packs = list(dict.fromkeys(str(e.get("pack", "")) for e in factors))
    progress(
        f"阶段1/2：准备因子包 raw_df（共 {len(unique_packs)} 个包：{unique_packs}）；"
        f"包内特征并行度 alpha_prepare_max_workers={max_workers}。",
    )
    for pack in unique_packs:
        if not pack:
            continue
        progress(f"  → 因子包 [{pack}] prepare_data（Alpha101/158 内多特征可并行）…")
        pack_cache[pack] = prepare_alpha_pack_raw_df(
            pack,
            base_panel,
            train_p,
            valid_p,
            test_p,
            max_workers=max_workers,
        )
    progress("阶段1/2 完成：各包 raw_df 已就绪。")

    # —— 阶段 2：因子截面 IC / 规则判定，线程数 = min(本批因子数 N, factor_eval_parallel_cap 或 N)——
    progress(
        f"阶段2/2：因子截面评估（并行 worker={factor_pw}，本批因子数 N={n_batch}；"
        f"与所选前 N 个一致时可令 factor_eval_parallel_cap=0）。",
    )
    rows_by_index: list[FactorEvalRow | None] = [None] * n_batch
    lock = threading.Lock()
    done_cnt = 0

    def _task(ordinal: int, entry: dict[str, str]) -> None:
        nonlocal done_cnt
        pack = str(entry.get("pack", ""))
        fid = str(entry.get("id", ""))
        feature = str(entry.get("feature", ""))
        raw_df = pack_cache.get(pack)
        if raw_df is None:
            row = FactorEvalRow(
                factor_id=fid,
                label=str(entry.get("label", "")),
                pack=pack,
                feature=feature,
                error="ValueError: 缺少因子包 raw_df（pack 为空或未在缓存中）",
                metrics={},
                selection_feasible=False,
                selection_objective=float("-inf"),
                selection_reason="pack missing",
            )
        else:
            row = _evaluate_one_factor_entry(entry, raw_df, selection_cfg)
        rows_by_index[ordinal] = row
        with lock:
            done_cnt += 1
            progress(
                f"[并行 {done_cnt}/{n_batch}] 完成 {fid} | {pack}.{feature} "
                f"（活跃 worker 上限 {factor_pw}）",
            )

    if n_batch == 0:
        rows = []
    elif n_batch == 1:
        _task(0, factors[0])
        rows = [rows_by_index[0]]  # type: ignore[list-item]
    else:
        with ThreadPoolExecutor(max_workers=factor_pw) as executor:
            futures = [executor.submit(_task, i, factors[i]) for i in range(n_batch)]
            for fut in as_completed(futures):
                fut.result()
        rows = [rows_by_index[i] for i in range(n_batch)]  # type: ignore[misc]

    progress("全部因子评估完成，正在汇总并写入 Excel 报告…")

    return rows, meta


def rank_rows_by_selection_rule(rows: list[FactorEvalRow]) -> list[FactorEvalRow]:
    """按「IC 门槛与多空夏普」规则排序（可行优先，其次分层多空夏普）。"""

    def key(r: FactorEvalRow) -> tuple[float, float, str]:
        raw_ls = r.metrics.get("long_short_sharpe")
        ls = float(raw_ls) if raw_ls is not None and raw_ls == raw_ls else float("-inf")
        if r.selection_feasible:
            return (1.0, float(r.selection_objective), r.factor_id)
        return (0.0, ls, r.factor_id)

    return sorted(rows, key=key, reverse=True)


def top_n_factors(rows: list[FactorEvalRow], n: int = 10) -> list[FactorEvalRow]:
    """取排序后的前 n 个（含不可行时仍返回前 n 条以便对比）。"""
    ranked = rank_rows_by_selection_rule(rows)
    return ranked[:n]
