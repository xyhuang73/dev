# -*- coding: utf-8 -*-
"""
策略回测结果导出为 Excel（.xlsx）：任务参数、注册表解析的因子/策略、指标与文本摘要。

输出目录：项目根下 ``reports/strategy/``。依赖：pandas + openpyxl（requirements 已声明）。
"""
from __future__ import annotations

import math
import numbers
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from InnerStrategy.inner_registry import get_factor_entry, get_strategy_entry
from InnerStrategy.slss_strategy_config import (
    SLSS_STRATEGY_JSON_PATH,
    load_slss_strategy_config,
)

from .models import BacktestJobConfig, BacktestResult
from .slss_trade_simulation import portfolio_summary_rows


def format_decimal_for_display(v: float) -> str:
    """
    将有限浮点转为非科学计数法的十进制字符串，便于 Excel/日志直接阅读。

    极小量（如数值噪声级收益）仍用定点小数展开，避免 ``1.5E-41`` 一类显示。
    """
    if not math.isfinite(v):
        return "inf" if v > 0 else ("-inf" if v < 0 else "nan")
    av = abs(float(v))
    if av == 0.0:
        return "0"
    # 常见量级：有限小数位后去尾零即可
    if 1e-4 <= av < 1e15:
        s = f"{float(v):.10f}".rstrip("0").rstrip(".")
        return s if s else "0"
    # 极小或很大：按数量级补足小数位，避免科学计数法
    exp = math.floor(math.log10(av))
    frac = min(42, max(8, 8 - int(exp)))
    s = f"{float(v):.{frac}f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _excel_stringify_float_columns(df: pd.DataFrame) -> pd.DataFrame:
    """将 DataFrame 中浮点列转为十进制字符串，避免明细表在 Excel 里显示成科学计数法。"""
    if df.empty:
        return df
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_float_dtype(out[col]):
            out[col] = out[col].map(
                lambda x, fd=format_decimal_for_display: fd(float(x)) if pd.notna(x) else "",
            )
    return out


def _strategy_reports_dir() -> Path:
    """策略回测 Excel 输出目录：项目根下 ``reports/strategy/``。"""
    root = Path(__file__).resolve().parent.parent
    out = root / "reports" / "strategy"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _timestamp_slug() -> str:
    """文件名用时间戳，避免覆盖。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _job_rows(job: BacktestJobConfig) -> pd.DataFrame:
    """回测任务配置 → 两列键值表。"""
    return pd.DataFrame(
        [
            ("initial_capital", job.initial_capital),
            ("start_date", job.start_date),
            ("end_date", job.end_date),
            ("factor_key_ui", job.factor_key),
            ("strategy_key", job.strategy_key),
            ("backtest_mode", job.backtest_mode),
            ("describe", job.describe()),
        ],
        columns=["key", "value"],
    )


def _ui_factor_row(job: BacktestJobConfig) -> pd.DataFrame:
    """界面所选「单因子」下拉对应的注册表解析（向量 SLSS 实际用组合因子，此处仍记录 UI 选择）。"""
    fe = get_factor_entry(job.factor_key)
    if not fe:
        return pd.DataFrame([{"factor_key": job.factor_key, "note": "注册表中未找到该因子"}])
    return pd.DataFrame(
        [
            {
                "factor_key": job.factor_key,
                "pack": fe.get("pack", ""),
                "feature": fe.get("feature", ""),
                "label": fe.get("label", ""),
            },
        ],
    )


def _strategy_row(job: BacktestJobConfig) -> pd.DataFrame:
    """策略注册表解析。"""
    se = get_strategy_entry(job.strategy_key)
    if not se:
        return pd.DataFrame([{"strategy_key": job.strategy_key, "note": "注册表中未找到该策略"}])
    return pd.DataFrame(
        [
            {
                "strategy_key": job.strategy_key,
                "module": se.get("module", ""),
                "class": se.get("class", ""),
                "label": se.get("label", ""),
            },
        ],
    )


def _slss_factor_weight_table() -> pd.DataFrame:
    """
    SLSS 组合：引用因子及权值（来自 ``Config/slss_strategy.json``，默认等权）。
    """
    cfg = load_slss_strategy_config()
    ids = list(cfg.bundle_factor_ids)
    n = len(ids)
    warr = cfg.normalized_weights(n)
    rows: list[dict[str, Any]] = []
    for i, fid in enumerate(ids, start=1):
        ent = get_factor_entry(fid) or {}
        wi = float(warr[i - 1]) if i <= len(warr) else (1.0 / float(n) if n else 0.0)
        note = "等权 1/N" if cfg.equal_weight or not cfg.explicit_weights else "显式权重（已归一）"
        rows.append(
            {
                "序号": i,
                "factor_id": fid,
                # 权重写入为十进制字符串，避免 Excel 将很小/很大的权重显示成科学计数法
                "weight": format_decimal_for_display(float(wi)),
                "weight_note": note,
                "pack": ent.get("pack", ""),
                "feature": ent.get("feature", ""),
                "registry_label": ent.get("label", ""),
            },
        )
    return pd.DataFrame(rows)


def write_slss_vector_backtest_excel(
    job: BacktestJobConfig,
    *,
    metrics_flat: dict[str, Any],
    pool_meta: dict[str, Any],
    eval_cfg: dict[str, Any],
    text_summary: str,
    max_symbols: int,
    n_bar_rows: int,
    trade_detail_df: pd.DataFrame | None = None,
    round_trip_df: pd.DataFrame | None = None,
    per_symbol_stats_df: pd.DataFrame | None = None,
    portfolio_stats: dict[str, Any] | None = None,
) -> Path:
    """
    向量 SLSS 策略回测专用 Excel：因子权值、截面指标、逐笔买卖、按票汇总、组合统计等。

    Returns:
        写入后的 ``.xlsx`` 绝对路径。
    """
    ts = _timestamp_slug()
    file_name = f"strategy_backtest_SLSS_{job.strategy_key}_{ts}.xlsx"
    # 输出结构：reports/strategy/<同名同名>.xlsx；同名文件夹用于放按股票拆出的逐笔 xlsx
    report_dir = _strategy_reports_dir() / file_name.replace(".xlsx", "")
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / file_name

    # 指标：单行宽表便于复制；再附一张纵表便于阅读
    # 宽表单元格若保留 float，Excel 常把极小/极大数显示为科学计数法，故统一经 _excel_scalar 文本化
    met_wide = pd.DataFrame([{k: _excel_scalar(v) for k, v in metrics_flat.items()}])
    met_long = pd.DataFrame(
        [{"metric": k, "value": _excel_scalar(v)} for k, v in sorted(metrics_flat.items())],
    )

    cfg_flat: dict[str, Any] = {}
    for k, v in sorted(eval_cfg.items()):
        if isinstance(v, (str, int, float, bool)) or v is None:
            cfg_flat[k] = v
        else:
            cfg_flat[k] = str(v)
    cfg_df = pd.DataFrame([{"key": k, "value": _excel_scalar(v)} for k, v in sorted(cfg_flat.items())])

    pool_df = pd.DataFrame([{"key": k, "value": _excel_scalar(v)} for k, v in sorted(pool_meta.items())])

    _cfg = load_slss_strategy_config()
    _tsim = _cfg.trade_simulation
    summary_extra = pd.DataFrame(
        [
            ("objective_metric_en", _cfg.stratified_long_short_sharpe_objective_en),
            ("slss_strategy_config_path", str(SLSS_STRATEGY_JSON_PATH)),
            ("max_symbols_applied", max_symbols),
            ("n_bar_rows_panel", n_bar_rows),
            (
                "composite_rule",
                "slss_composite 由 Config/slss_strategy.json 的 bundle_factor_ids 与 equal_weight/explicit_weights 决定（见「引用因子与权值」表）。",
            ),
            (
                "buy_sell_rule_summary",
                (
                    f"decision_mode={_cfg.decision_mode}：截面排名时按日对股票池 slss_composite 排序，"
                    f"名次≤{_cfg.cross_section_long_top_n} 目标多、名次≥{_cfg.cross_section_short_min_rank} 目标空，"
                    "其余平仓；与 simulate_slss_trades 截面模式一致。"
                    + (
                        " a_share_cash_stock_rules=true：现货近似下截面目标 -1 已钳为 0，不产生卖空开与空头回合；"
                        "多头平仓仍为「卖出平仓」，见逐笔表明细。"
                    )
                    if bool(_cfg.a_share_cash_stock_rules)
                    else ""
                )
                if str(_cfg.decision_mode) == "cross_section_rank"
                else (
                    "原始信号列 slss_composite：空仓且合成值>buy_threshold 买入；持仓且合成值<sell_threshold 卖出（阈值见 JSON）。"
                    f"若 raw 下无任何完整开平回合且 enable_rolling_z_fallback=true，则改用列 _sig_roll_z（逐标的 rolling z），"
                    f"买入 z>{_tsim.fallback_buy_z}，卖出 z<{_tsim.fallback_sell_z}；"
                    f"rolling_window={_tsim.rolling_window}, min_periods={_tsim.rolling_min_periods}。"
                ),
            ),
        ],
        columns=["key", "value"],
    )
    summary_extra["value"] = summary_extra["value"].map(_excel_scalar)

    # 文本摘要按行拆开，避免单格过长（仍保留 raw 表）
    text_lines = text_summary.splitlines()
    text_df = pd.DataFrame({"line_no": range(1, len(text_lines) + 1), "content": text_lines})

    # 与 factor_cross_section_metrics / long_table_for_feature 一致的文字口径，便于审阅
    methodology = pd.DataFrame(
        [
            (
                "StratifiedLongShortSharpe",
                f"英文目标名见 slss_strategy.json 的 stratified_long_short_sharpe_objective_en；"
                "数值=截面分层多空日收益序列的年化夏普（同 long_short_sharpe）。",
            ),
            ("因子权值", "组合为等权：各因子权重=1/N，N 为引用因子个数；合成值 slss_composite 为各 feature 在同一行上的 nanmean。"),
            ("fwd_ret", "次日收盘/当日收盘-1，按 vt_symbol 对齐下一交易日（与因子批量评估一致）。"),
            ("分层多空", f"按 factor_evaluation.json 的 n_quantiles（默认十分位）分组，取最高组与最低组等权收益之差为当日多空收益。"),
            (
                "逐标的模拟成交",
                (
                    f"截面模式 decision_mode=cross_section_rank：与 CTA 一致按日排名，"
                    f"long_top_n={_cfg.cross_section_long_top_n}、short_min_rank={_cfg.cross_section_short_min_rank}；"
                    + (
                        "a_share_cash_stock_rules=true 时：无卖空开/买平；回合表 round_side 仅「多」表示先买后卖一整笔，"
                        "平仓在「逐笔买卖明细」中 action=卖出平仓；未扣手续费/滑点。"
                        if bool(_cfg.a_share_cash_stock_rules)
                        else "逐笔表可含卖空开/买平与 round_side；未扣手续费/滑点，融券可得性未建模。"
                    )
                )
                if str(_cfg.decision_mode) == "cross_section_rank"
                else (
                    f"优先：信号列 slss_composite，与 CTA 一致使用 JSON 中 buy_threshold={_cfg.buy_threshold}、sell_threshold={_cfg.sell_threshold}；"
                    "空仓且合成值>买入阈值→按收盘价买入 fixed_lot；持仓且合成值<卖出阈值→按收盘价卖出。"
                    "若全样本 raw 下无完整开平回合，且 trade_simulation.enable_rolling_z_fallback=true，"
                    f"则改用逐标的滚动 z（window={_tsim.rolling_window}, min_periods={_tsim.rolling_min_periods}），"
                    f"买入 z>{_tsim.fallback_buy_z}，卖出 z<{_tsim.fallback_sell_z}；"
                    "逐笔表列 signal_for_rule、signal_column、threshold_mode 标明实际口径；未扣手续费/滑点。"
                ),
            ),
        ],
        columns=["item", "description"],
    )

    td = trade_detail_df if trade_detail_df is not None else pd.DataFrame()
    rt = round_trip_df if round_trip_df is not None else pd.DataFrame()
    ps = per_symbol_stats_df if per_symbol_stats_df is not None else pd.DataFrame()
    # 便于阅读：时间升序、再按代码
    if not td.empty and "datetime" in td.columns:
        td = td.sort_values(["datetime", "vt_symbol"], kind="mergesort").reset_index(drop=True)
    if not rt.empty and "open_datetime" in rt.columns:
        rt = rt.sort_values(["open_datetime", "vt_symbol"], kind="mergesort").reset_index(drop=True)
    if not td.empty:
        td = _excel_stringify_float_columns(td)
    if not rt.empty:
        rt = _excel_stringify_float_columns(rt)
    if not ps.empty:
        ps = _excel_stringify_float_columns(ps)
    port_df = portfolio_summary_rows(portfolio_stats) if portfolio_stats else pd.DataFrame(columns=["key", "value"])
    if not port_df.empty:
        port_df = port_df.copy()
        port_df["value"] = port_df["value"].map(_excel_scalar)

    # 本次输出约定：
    #   1) reports/strategy/<同名文件夹>/<同名 xlsx> 是「汇总文件」，必须保留其 14 个 sheet 主体；
    #   2) 但「开平回合盈亏」「按股票汇总统计」这两个 sheet **不放进主汇总文件**，
    #      而是写到同名文件夹下的单票 xlsx（trades_<symbol>.xlsx）里；
    #   3) 单票 xlsx 含三个 sheet：按股票汇总统计 / 开平回合盈亏 / 逐笔买卖明细。
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        _job_rows(job).to_excel(writer, sheet_name="回测任务", index=False)
        _ui_factor_row(job).to_excel(writer, sheet_name="界面因子引用", index=False)
        _strategy_row(job).to_excel(writer, sheet_name="策略注册", index=False)
        _slss_factor_weight_table().to_excel(writer, sheet_name="引用因子与权值", index=False)
        summary_extra.to_excel(writer, sheet_name="策略规则摘要", index=False)
        met_wide.to_excel(writer, sheet_name="截面指标_宽表", index=False)
        met_long.to_excel(writer, sheet_name="截面指标_纵表", index=False)
        cfg_df.to_excel(writer, sheet_name="factor_evaluation概要", index=False)
        pool_df.to_excel(writer, sheet_name="股票池元信息", index=False)
        methodology.to_excel(writer, sheet_name="合成信号摘要", index=False)
        # 注：跳过「开平回合盈亏」「按股票汇总统计」——这两个 sheet 已在单票文件里：
        port_df.to_excel(writer, sheet_name="组合收益统计", index=False)
        if not td.empty:
            _excel_stringify_float_columns(td).to_excel(writer, sheet_name="逐笔买卖明细", index=False)
        text_df.to_excel(writer, sheet_name="文本报告", index=False)

    _write_per_symbol_workbook(report_dir, td, rt, ps)

    return path.resolve()


def _safe_symbol_slug(symbol: str) -> str:
    """把 vt_symbol 改成可作为文件名的形式（屏蔽路径分隔符与控制字符）。"""
    raw = str(symbol or "").strip()
    if not raw:
        return "UNKNOWN"
    bad = '<>:"/\\|?*' + "".join(chr(c) for c in range(32))
    out = "".join("_" if ch in bad else ch for ch in raw)
    return out or "UNKNOWN"


def _write_per_symbol_workbook(
    report_dir: Path,
    trade_detail_df: pd.DataFrame,
    round_trip_df: pd.DataFrame,
    per_symbol_stats_df: pd.DataFrame,
) -> list[Path]:
    """
    按 ``vt_symbol`` 拆出单票 xlsx：每只票三个 sheet。

    Sheet 1「按股票汇总统计」：仅当该票在 ``per_symbol_stats_df`` 中有行时写入；
    Sheet 2「开平回合盈亏」：仅当该票在 ``round_trip_df`` 中有行时写入；
    Sheet 3「逐笔买卖明细」：完整逐笔记录（含未平仓的半笔）。

    行为约定：
    - 以 ``vt_symbol`` 为统一分组键；任一表中缺失该列的，跳过对应 sheet（仍输出其它可用 sheet）。
    - 任一股票若在三个表里都没有数据，则跳过整个文件（不创建空 xlsx）。
    - 仅当文件至少写入了一个 sheet 时才创建。
    """
    if trade_detail_df is None and round_trip_df is None and per_symbol_stats_df is None:
        return []

    symbols: set[str] = set()
    for df in (trade_detail_df, round_trip_df, per_symbol_stats_df):
        if df is not None and not df.empty and "vt_symbol" in df.columns:
            symbols.update(df["vt_symbol"].dropna().astype(str).tolist())

    written: list[Path] = []
    for symbol in sorted(symbols):
        slug = _safe_symbol_slug(symbol)
        target = report_dir / f"trades_{slug}.xlsx"

        sub_td = _safe_sub(trade_detail_df, symbol, sort_keys=["datetime", "vt_symbol"])
        sub_rt = _safe_sub(round_trip_df, symbol, sort_keys=["open_datetime", "vt_symbol"])
        sub_ps = _safe_sub(per_symbol_stats_df, symbol, sort_keys=["vt_symbol"])

        sheet_count = 0
        with pd.ExcelWriter(target, engine="openpyxl") as writer:
            if sub_ps is not None and not sub_ps.empty:
                sub_ps.to_excel(writer, sheet_name="按股票汇总统计", index=False)
                sheet_count += 1
            if sub_rt is not None and not sub_rt.empty:
                sub_rt.to_excel(writer, sheet_name="开平回合盈亏", index=False)
                sheet_count += 1
            if sub_td is not None and not sub_td.empty:
                sub_td.to_excel(writer, sheet_name="逐笔买卖明细", index=False)
                sheet_count += 1
        if sheet_count > 0:
            written.append(target.resolve())
    return written


def _safe_sub(df: pd.DataFrame | None, symbol: str, *, sort_keys: list[str]) -> pd.DataFrame | None:
    """按 ``symbol`` 过滤 + 排序，缺失列时原样返回（保持时序）。"""
    if df is None or df.empty:
        return df
    if "vt_symbol" not in df.columns:
        return df
    sub = df.loc[df["vt_symbol"].astype(str) == str(symbol)].copy()
    if sub.empty:
        return sub
    keys = [k for k in sort_keys if k in sub.columns]
    if keys:
        sub = sub.sort_values(keys, kind="mergesort").reset_index(drop=True)
    return sub


def write_generic_strategy_backtest_excel(job: BacktestJobConfig, result: BacktestResult) -> Path:
    """
    通用策略回测报告（占位引擎、非 SLSS 向量、或失败时的最小信息）。

    仍输出界面因子、策略注册与完整 message，便于留档。
    """
    ts = _timestamp_slug()
    file_name = f"strategy_backtest_{job.strategy_key}_{ts}.xlsx"
    report_dir = _strategy_reports_dir() / file_name.replace(".xlsx", "")
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / file_name
    text_lines = result.message.splitlines()
    text_df = pd.DataFrame({"line_no": range(1, len(text_lines) + 1), "content": text_lines})
    status = pd.DataFrame([{"ok": result.ok}])

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        _job_rows(job).to_excel(writer, sheet_name="回测任务", index=False)
        _ui_factor_row(job).to_excel(writer, sheet_name="界面因子引用", index=False)
        _strategy_row(job).to_excel(writer, sheet_name="策略注册", index=False)
        status.to_excel(writer, sheet_name="运行状态", index=False)
        text_df.to_excel(writer, sheet_name="文本报告", index=False)

    return path.resolve()


def ensure_backtest_excel_report(job: BacktestJobConfig, result: BacktestResult) -> str | None:
    """
    若引擎未写 excel_path，则补写通用报告；已写则原样返回路径。

    Returns:
        报告文件路径字符串，或 ``None``（不应发生）。
    """
    if result.excel_path:
        return result.excel_path
    p = write_generic_strategy_backtest_excel(job, result)
    return str(p)


def _excel_scalar(v: Any) -> Any:
    """
    写入 Excel 前的标量规范化：避免 openpyxl 报错，且浮点用十进制字符串避免科学计数法。
    """
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, numbers.Real):
        return format_decimal_for_display(float(v))
    if isinstance(v, str):
        return v
    return str(v)
