# -*- coding: utf-8 -*-
"""
向量回测：StratifiedLongShortSharpeEqualWeightStrategy（等权 SLSS 合成因子）全截面指标。

流程::
    1) 按 factor_evaluation.json 建股票池并拉日线面板；
    2) prepare Alpha101/Alpha158，按注册表合并 10 个特征列，逐行 ``nanmean`` 得 ``slss_composite``；
    3) 长表 + ``compute_cross_section_metrics`` → RankIC、分层多空收益序列及 **StratifiedLongShortSharpe**（即 long_short_sharpe）。
"""
from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import pandas as pd

from InnerStrategy.inner_registry import get_factor_entry
from InnerStrategy.slss_strategy_config import (
    compute_slss_composite_series,
    load_slss_strategy_config,
)

from .factor_alpha_runner import long_table_for_feature, prepare_alpha_pack_raw_df
from .factor_cross_section_metrics import compute_cross_section_metrics, metrics_to_serializable
from .factor_evaluation_config import dict_to_scheme_b, load_factor_evaluation_json
from .factor_market_panel import build_daily_market_panel, iso_period_triple
from .factor_single_parameters_settings import load_single_factor_parameters_json
from .factor_evaluation_settings import read_max_symbols_from_eval_cfg
from .backtest_strategy_report_excel import format_decimal_for_display, write_slss_vector_backtest_excel
from .models import BacktestJobConfig, BacktestResult
from .slss_trade_simulation import simulate_slss_trades
from .qmt_client_guard import require_qmt_client_for_xtdata_datafeed
from .stock_pool_builder import build_factor_evaluation_stock_pool


def _log_line(progress: Callable[[str], None] | None, msg: str) -> None:
    """
    文本进度：始终打印到 stdout（无进度条）；若提供 progress 则同步到 GUI（如对话框追加）。

    说明：避免在 UI 回调里再 print，防止同一行重复两次。
    """
    print(msg, flush=True)
    if progress is not None:
        progress(msg)


def _merge_calendar_day_key(series: pd.Series) -> pd.Series:
    """
    将 datetime 列规范为「日历日」的 naive Timestamp（当日 00:00:00）。

    Alpha（polars→pandas）与本地 .DAT 常出现同日不同时分；若仍用精确 ``datetime`` 左连接行情，
    会导致 OHLCV 匹配失败或错行，进而在成交模拟里出现近 0 / 异常大价格。统一按交易日键对齐。
    """
    t = pd.to_datetime(series, errors="coerce")
    # 带时区的序列先落到上海再剥时区，避免 UTC 子夜与 A 股交易日错位
    if getattr(t.dt, "tz", None) is not None:
        t = t.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    return t.dt.normalize()


def _merge_alpha_packs_for_bundle(
    base_df: pd.DataFrame,
    train_p: tuple[str, str],
    valid_p: tuple[str, str],
    test_p: tuple[str, str],
    *,
    max_workers: int,
) -> pd.DataFrame:
    """
    按 ``Config/slss_strategy.json`` 中 ``bundle_factor_ids`` 解析 pack，分别 prepare alpha_158 / alpha_101 并合并列。

    Returns:
        含 datetime, vt_symbol, OHLCV 及全部 bundle 特征列的宽表。
    """
    cfg_ids = load_slss_strategy_config().bundle_factor_ids
    specs: list[tuple[str, str]] = []
    for fid in cfg_ids:
        ent = get_factor_entry(fid)
        if not ent:
            raise KeyError(f"inner_registry 缺少因子: {fid}")
        specs.append((str(ent["pack"]), str(ent["feature"])))

    need_158 = any(p == "alpha_158" for p, _ in specs)
    need_101 = any(p == "alpha_101" for p, _ in specs)
    # 仅计算 bundle 中真实被引用的列，避免整包 Alpha 全量计算。
    feats158 = sorted({f for p, f in specs if p == "alpha_158"})
    feats101 = sorted({f for p, f in specs if p == "alpha_101"})
    merged: pd.DataFrame | None = None
    mw = max(1, int(max_workers))

    if need_158:
        merged = prepare_alpha_pack_raw_df(
            "alpha_158",
            base_df,
            train_p,
            valid_p,
            test_p,
            max_workers=mw,
            selected_features=feats158,
        )
    if need_101:
        raw101 = prepare_alpha_pack_raw_df(
            "alpha_101",
            base_df,
            train_p,
            valid_p,
            test_p,
            max_workers=mw,
            selected_features=feats101,
        )
        cols101 = ["datetime", "vt_symbol"] + feats101
        miss = [c for c in cols101 if c not in raw101.columns]
        if miss:
            raise KeyError(f"alpha_101 结果缺少列: {miss}")
        sub101 = raw101[cols101]
        if merged is None:
            merged = sub101.copy()
        else:
            merged = merged.merge(sub101, on=["datetime", "vt_symbol"], how="left")
    if merged is None:
        raise RuntimeError("未请求任何 Alpha 包")
    return merged


def attach_base_ohlcv_to_merged(merged: pd.DataFrame, base_panel: pd.DataFrame) -> pd.DataFrame:
    """
    用 ``base_panel``（原始日线行情）覆盖 ``merged`` 中的 OHLCV 等行情列。

    说明：逐笔模拟、``fwd_ret`` 与真实成交价必须以行情为准。个别环境下 Alpha 的 polars→pandas
    或列对齐问题可能导致 ``merged['close']`` 出现近 0 的数值噪声（Excel 中表现为极长小数），
    本函数在因子合并后强制恢复行情列，避免盈亏与资金统计失真。

    对齐键使用 ``(vt_symbol, 日历日)`` 而非精确到时分秒的 ``datetime``，避免 Alpha 与本地行情
    同一交易日时间戳不一致时 merge 失败，从而仍沿用因子管道里被污染的 OHLCV。
    """
    keys = ["datetime", "vt_symbol"]
    if not all(k in merged.columns and k in base_panel.columns for k in keys):
        return merged
    # 与行情面板可对齐的列（vwap 在部分数据源由面板侧已算好）
    ohlcv = [c for c in ("open", "high", "low", "close", "volume", "vwap") if c in base_panel.columns]
    if "close" not in ohlcv:
        return merged
    use_cols = keys + [c for c in ohlcv if c not in keys]
    base_sub = base_panel[use_cols].copy()
    # 同一标的同一日历日只保留最后一条（防源数据重复）
    base_sub["__bar_day"] = _merge_calendar_day_key(base_sub["datetime"])
    base_sub = base_sub.drop(columns=["datetime"]).drop_duplicates(subset=["__bar_day", "vt_symbol"], keep="last")

    out = merged.copy()
    out["__bar_day"] = _merge_calendar_day_key(out["datetime"])
    for c in ohlcv:
        if c in out.columns:
            out = out.drop(columns=[c])
    out = out.merge(base_sub, on=["__bar_day", "vt_symbol"], how="left")
    return out.drop(columns=["__bar_day"])


def run_vector_slss_backtest(
    job: BacktestJobConfig,
    *,
    progress: Callable[[str], None] | None = None,
) -> BacktestResult:
    """
    对当前任务区间执行 SLSS 向量截面评估，返回可读报告字符串。

    Args:
        job: 须含合法 start_date/end_date；资金字段此处不参与 PnL 演算（截面指标为主）。
        progress: 可选文本进度（如回测对话框追加）；关键步骤会同时 ``print`` 到终端。
    """
    from .factor_evaluation_settings import is_local_datadir_market_source  # noqa: PLC0415

    _log_line(progress, f"[向量SLSS] 开始 {job.describe()}")

    if not is_local_datadir_market_source():
        try:
            require_qmt_client_for_xtdata_datafeed()
        except RuntimeError as exc:
            err = f"向量 SLSS 回测需要行情源：{exc}"
            _log_line(progress, f"[向量SLSS] 失败: {err}")
            return BacktestResult(False, err)

    eval_cfg = load_factor_evaluation_json()
    # max_symbols 统一由 GUI 的 spinBox_max_symbols 写入配置后读取，不再使用代码常量兜底。
    max_symbols = read_max_symbols_from_eval_cfg(eval_cfg)
    slss_cfg = load_slss_strategy_config()
    single_json = load_single_factor_parameters_json()
    mw = max(1, int(slss_cfg.alpha_prepare_workers or single_json.get("alpha_prepare_max_workers") or 1))
    _log_line(
        progress,
        f"[向量SLSS] 配置: max_symbols={max_symbols}, alpha_prepare_workers={mw}, "
        f"decision_mode={slss_cfg.decision_mode}",
    )

    try:

        def _pool_cb(line: str) -> None:
            _log_line(progress, f"[股票池] {line}")

        pool_syms, pool_meta = build_factor_evaluation_stock_pool(
            eval_cfg,
            progress=_pool_cb,
        )
        _log_line(progress, "[向量SLSS] 正在加载日线面板…")
        base_panel = build_daily_market_panel(
            job.start_date,
            job.end_date,
            max_symbols,
            stock_list=pool_syms,
        )
    except Exception as exc:  # noqa: BLE001
        err = f"行情/股票池加载失败: {type(exc).__name__}: {exc}"
        _log_line(progress, f"[向量SLSS] 失败: {err}")
        return BacktestResult(False, err)

    if base_panel.empty:
        err = "行情长表为空：请检查日期区间、max_symbols 或本地 datadir。"
        _log_line(progress, f"[向量SLSS] 失败: {err}")
        return BacktestResult(False, err)

    n_sym = int(base_panel["vt_symbol"].nunique()) if "vt_symbol" in base_panel.columns else -1
    _log_line(
        progress,
        f"[向量SLSS] 日线面板就绪: 行数={len(base_panel)}, 标的数≈{n_sym}",
    )

    t0 = pd.to_datetime(base_panel["datetime"].min())
    t1 = pd.to_datetime(base_panel["datetime"].max())
    train_p, valid_p, test_p = iso_period_triple(
        t0.strftime("%Y%m%d"),
        t1.strftime("%Y%m%d"),
    )

    try:
        _log_line(progress, "[向量SLSS] 正在计算 Alpha 并合并特征（可能较久）…")
        merged = _merge_alpha_packs_for_bundle(
            base_panel,
            train_p,
            valid_p,
            test_p,
            max_workers=mw,
        )
    except Exception as exc:  # noqa: BLE001
        err = f"Alpha 计算失败: {type(exc).__name__}: {exc}"
        _log_line(progress, f"[向量SLSS] 失败: {err}")
        return BacktestResult(False, err)

    _log_line(progress, f"[向量SLSS] Alpha 宽表行数={len(merged)}, 列数={merged.shape[1]}")

    # 成交价与次日收益必须基于原始行情 close，不可使用因子管道中可能被污染的 OHLCV
    merged = attach_base_ohlcv_to_merged(merged, base_panel)
    _log_line(progress, "[向量SLSS] 已用原始行情对齐 OHLCV（attach_base_ohlcv，按日历日+标的键）")
    if "close" in merged.columns:
        _nan_c = int(merged["close"].isna().sum())
        _c = pd.to_numeric(merged["close"], errors="coerce")
        _impl = int(((~_c.isna()) & ((_c < 0.01) | (_c > 200_000.0))).sum())
        if _nan_c or _impl:
            _log_line(
                progress,
                f"[向量SLSS] 行情对齐自检: close 为 NaN 行={_nan_c}, "
                f"超出常规现价区间[0.01,200000]行={_impl}（若>0 请检查日期或数据源）",
            )

    feat_cols: list[str] = []
    for fid in slss_cfg.bundle_factor_ids:
        ent = get_factor_entry(fid)
        if not ent:
            err = f"注册表缺少因子 {fid}"
            _log_line(progress, f"[向量SLSS] 失败: {err}")
            return BacktestResult(False, err)
        feat_cols.append(str(ent["feature"]))
    miss_feat = [c for c in feat_cols if c not in merged.columns]
    if miss_feat:
        err = f"合并表缺少特征列: {miss_feat}"
        _log_line(progress, f"[向量SLSS] 失败: {err}")
        return BacktestResult(False, err)

    # 按 Config/slss_strategy.json 的权重（等权或 explicit_weights）合成 slss_composite
    merged = merged.copy()
    _log_line(progress, "[向量SLSS] 正在计算 slss_composite…")
    merged["slss_composite"] = compute_slss_composite_series(merged, feat_cols, slss_cfg)

    # 与 CTA 策略同阈值的逐标的买卖模拟，用于报告中的成交笔数与收益率统计
    _log_line(progress, "[向量SLSS] 正在逐标的模拟成交…")
    trades_df, rounds_df, per_sym_df, portfolio_stats = simulate_slss_trades(merged, job)
    _log_line(
        progress,
        f"[向量SLSS] 逐笔模拟完成: 开平回合数={portfolio_stats.get('total_round_trips', '')}, "
        f"threshold_mode={portfolio_stats.get('threshold_mode', '')}",
    )

    try:
        _log_line(progress, "[向量SLSS] 正在构建因子长表（fwd_ret）…")
        lf = long_table_for_feature(merged, "slss_composite")
    except Exception as exc:  # noqa: BLE001
        err = f"构建长表失败: {type(exc).__name__}: {exc}"
        _log_line(progress, f"[向量SLSS] 失败: {err}")
        return BacktestResult(False, err)

    _log_line(progress, f"[向量SLSS] 长表行数={len(lf)}")

    scheme_cfg = dict_to_scheme_b(eval_cfg)
    try:
        _log_line(progress, "[向量SLSS] 正在计算截面 RankIC / 分层多空指标…")
        m = compute_cross_section_metrics(lf, "_factor_value", "fwd_ret", scheme_cfg)
    except Exception as exc:  # noqa: BLE001
        err = f"截面指标计算失败: {type(exc).__name__}: {exc}"
        _log_line(progress, f"[向量SLSS] 失败: {err}")
        return BacktestResult(False, err)

    _log_line(progress, "[向量SLSS] 截面指标计算完成，正在组装报告并写 Excel…")

    ser = metrics_to_serializable(m)
    # 人类可读报告（首行对齐 BacktestJobConfig 摘要）
    lines: list[str] = [
        job.describe(),
        "",
        f"区间: {job.start_date} ~ {job.end_date}",
        f"标的数(配置上限): max_symbols={max_symbols}，面板行数={len(base_panel)}",
        f"股票池元信息键: {sorted(pool_meta.keys())}",
        "",
        f"【{slss_cfg.stratified_long_short_sharpe_objective_en}】（截面分层多空年化夏普，与因子评估 long_short_sharpe 同口径）",
        f"  StratifiedLongShortSharpe = { _fmt_num(m.long_short_sharpe) }",
        "",
        "【收益率与风险（分层多空组合，非单票 CTA 现金曲线）】",
        f"  分层多空日均收益 = { _fmt_num(m.long_short_mean_daily) }",
        f"  分层多空日收益波动 = { _fmt_num(m.long_short_vol_daily) }",
        f"  分层多空区间累计收益 = { _fmt_num(m.long_short_cumulative_return) }",
        f"  分层多空年化收益(近似) = { _fmt_num(m.long_short_annualized_return_approx) }",
        f"  分层多空日胜率 = { _fmt_num(m.long_short_win_rate) }",
        "",
        "【Rank IC】",
        f"  RankIC 均值 = { _fmt_num(m.rank_ic_mean) }",
        f"  IC_IR = { _fmt_num(m.ic_ir) }",
        f"  RankIC 胜率 = { _fmt_num(m.rank_ic_win_rate) }",
        "",
        "【样本规模】",
        f"  交易日数={m.n_trade_dates}, 有效IC日={m.n_ic_days}, 有效分层日={m.n_ls_days}",
        f"  截面覆盖度均值={ _fmt_num(m.coverage_mean) }",
        "",
        "【机器可读 metrics 字典】",
        str(ser),
        "",
        "【逐标的模拟交易（收盘价；未扣费）】",
        f"  阈值模式 threshold_mode = {portfolio_stats.get('threshold_mode', '')}",
        (
            f"  截面：long_top_n={portfolio_stats.get('cross_section_long_top_n', '')}, "
            f"short_min_rank={portfolio_stats.get('cross_section_short_min_rank', '')}, "
            f"short_bottom_n={portfolio_stats.get('cross_section_short_bottom_n', '')}, "
            f"long_req_close+={portfolio_stats.get('cross_section_long_require_close_positive', '')}, "
            f"long_req_comp+={portfolio_stats.get('cross_section_long_require_composite_positive', '')}, "
            f"short_or_neg={portfolio_stats.get('cross_section_short_or_negative_composite', '')}；"
            f"a_share_cash_stock_rules={portfolio_stats.get('a_share_cash_stock_rules', '')}；"
            f"signal={portfolio_stats.get('signal_column_used', '')}；"
            f"买开={portfolio_stats['total_buy_orders']}, 卖平={portfolio_stats['total_sell_orders']}, "
            f"卖空开={portfolio_stats.get('total_short_open_orders', 0)}, 平空={portfolio_stats.get('total_cover_orders', 0)}"
        )
        if str(slss_cfg.decision_mode) == "cross_section_rank"
        else (
            f"  使用信号列 signal_column_used = {portfolio_stats.get('signal_column_used', '')} "
            f"(买>{portfolio_stats.get('buy_threshold_applied', '')}, 卖<{portfolio_stats.get('sell_threshold_applied', '')})；"
            f"买委托={portfolio_stats['total_buy_orders']}, 卖委托={portfolio_stats['total_sell_orders']}"
        ),
        f"  完整开平回合数={portfolio_stats['total_round_trips']}",
        f"  有成交回合的标的数={portfolio_stats['n_symbols_with_any_round_trip']} / 面板标的数={portfolio_stats['n_symbols_in_panel']}",
        f"  slss 全样本有限值行数={portfolio_stats.get('slss_finite_rows', '')}, "
        f"min/median/p90/max={portfolio_stats.get('slss_global_min', '')}/"
        f"{portfolio_stats.get('slss_global_p50', '')}/"
        f"{portfolio_stats.get('slss_global_p90', '')}/"
        f"{portfolio_stats.get('slss_global_max', '')}",
        f"  已实现盈亏(现金加总)={ _fmt_num(portfolio_stats['total_realized_pnl_cash']) }",
        f"  相对界面初始资金的简化收益率={ _fmt_num(portfolio_stats['simple_return_vs_initial_capital']) }",
        f"  开仓名义本金加总(元)={ _fmt_num(portfolio_stats.get('sum_round_open_notional_cny', float('nan'))) }",
        f"  按名义本金加权的组合平均回合收益率={ _fmt_num(portfolio_stats.get('nominal_weighted_avg_round_return_on_notional', float('nan'))) }",
        f"  全部回合胜率={ _fmt_num(portfolio_stats['all_round_trips_win_rate']) }, "
        f"回合平均涨跌幅={ _fmt_num(portfolio_stats['all_round_trips_mean_pnl_pct']) }",
        f"  （说明）{portfolio_stats.get('note', '')}",
        f"  （名义加权）{portfolio_stats.get('notional_weighting_note', '')}",
    ]
    fn = portfolio_stats.get("fallback_rolling_z_note")
    if fn:
        lines.extend(["", f"  （阈值补充）{fn}"])
    hint = ser.get("ic_unavailable_hint") or ""
    if hint:
        lines.insert(8, f"提示: {hint}")

    msg = "\n".join(lines)
    # 能走到此处表示管线已跑通；n_ls_days=0 时指标多为 nan，但仍输出便于排障
    xlsx = write_slss_vector_backtest_excel(
        job,
        metrics_flat=ser,
        pool_meta=pool_meta,
        eval_cfg=eval_cfg,
        text_summary=msg,
        max_symbols=max_symbols,
        n_bar_rows=int(len(base_panel)),
        trade_detail_df=trades_df,
        round_trip_df=rounds_df,
        per_symbol_stats_df=per_sym_df,
        portfolio_stats=portfolio_stats,
    )
    _log_line(progress, f"[向量SLSS] 完成。Excel: {xlsx}")
    return BacktestResult(True, msg, excel_path=str(xlsx))


def _fmt_num(x: Any) -> str:
    """有限浮点转为十进制可读字符串（与 Excel 报告一致，避免科学计数法）。"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return str(x)
    if not math.isfinite(v):
        return str(x)
    return format_decimal_for_display(v)
