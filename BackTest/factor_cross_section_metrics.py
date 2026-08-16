# -*- coding: utf-8 -*-
"""
由长表（datetime × vt_symbol）计算 Rank IC 序列、IC_IR 与分层多空日收益及夏普。

使用 pandas + numpy，不依赖 polars，便于最小环境运行。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .factor_evaluation_settings import SchemeBConfig


@dataclass
class CrossSectionMetricsResult:
    """单因子全样本截面指标汇总。"""

    rank_ic_mean: float
    rank_ic_std: float
    ic_ir: float
    long_short_mean_daily: float
    long_short_vol_daily: float
    long_short_sharpe: float
    n_ic_days: int
    n_ls_days: int
    coverage_mean: float
    # 以下为 n_ic_days==0 时的排障计数（见 metrics_to_serializable 写入 Excel）
    n_trade_dates: int = 0
    n_days_skip_min_names: int = 0
    n_days_ic_nan_const_factor: int = 0
    n_days_ic_nan_const_fwd_ret: int = 0
    n_days_ic_nan_small_cross: int = 0
    # 各交易日截面上「因子与 fwd_ret 同时有效」的个数 vn；用于对照 min_names_per_day
    min_daily_valid_names: int = 0
    median_daily_valid_names: float = 0.0
    # 直观指标：胜率与区间收益（由日序列直接统计）
    rank_ic_win_rate: float = float("nan")  # 有效 IC 日中 Rank IC>0 的占比
    long_short_win_rate: float = float("nan")  # 有效分层日中多空日收益>0 的占比
    long_short_cumulative_return: float = float("nan")  # 分层多空日收益链式复利：∏(1+r_t)-1
    long_short_annualized_return_approx: float = float("nan")  # (1+日均多空收益)^annualization_days - 1，粗略年化


def _rank_ic_numpy(f: np.ndarray, r: np.ndarray) -> float:
    """单日截面 Rank IC：对秩做 Pearson 相关（与常见 Rank IC 一致）。"""
    m = np.isfinite(f) & np.isfinite(r)
    n = int(m.sum())
    if n < 3:
        return float("nan")
    ff = f[m].astype(np.float64)
    rr = r[m].astype(np.float64)
    rk_f = ff.argsort().argsort().astype(np.float64)
    rk_r = rr.argsort().argsort().astype(np.float64)
    rk_f -= rk_f.mean()
    rk_r -= rk_r.mean()
    sf = rk_f.std()
    sr = rk_r.std()
    if sf < 1e-15 or sr < 1e-15:
        return float("nan")
    rk_f /= sf
    rk_r /= sr
    return float(np.dot(rk_f, rk_r) / len(rk_f))


def _decile_long_short_daily(f: np.ndarray, r: np.ndarray, n_q: int) -> float:
    """单日分层：按因子分 n_q 组，最高组均收益 − 最低组均收益（等权）。"""
    m = np.isfinite(f) & np.isfinite(r)
    n = int(m.sum())
    if n < max(n_q * 3, 15):
        return float("nan")
    ff = f[m]
    rr = r[m]
    order = np.argsort(ff)
    k = max(n // n_q, 1)
    low = order[:k]
    high = order[-k:]
    return float(rr[high].mean() - rr[low].mean())


def compute_cross_section_metrics(
    lf: pd.DataFrame,
    factor_col: str,
    fwd_ret_col: str,
    cfg: SchemeBConfig,
) -> CrossSectionMetricsResult:
    """
    lf 须含列：datetime, vt_symbol, {factor_col}, {fwd_ret_col}。

    按交易日循环计算 Rank IC 与分层多空日收益，再汇总 IC_IR 与多空夏普。
    """
    need = {"datetime", "vt_symbol", factor_col, fwd_ret_col}
    miss = need - set(lf.columns)
    if miss:
        raise ValueError(f"缺少列: {miss}")

    # 按「日历交易日」聚合同一天内所有标的：若用 datetime 精确相等，时间戳微差会拆成大量「伪日」，
    # 每段仅几只股票 < min_names_per_day，导致 IC/分层全日为空、Excel 中 n_ic_days=0 且指标列全空。
    lf = lf.copy()
    lf["_trade_date"] = pd.to_datetime(lf["datetime"]).dt.normalize()
    dates = sorted(lf["_trade_date"].dropna().unique())
    ics: list[float] = []
    lss: list[float] = []
    covs: list[float] = []

    n_days_skip_min_names = 0
    n_days_ic_nan_const_factor = 0
    n_days_ic_nan_const_fwd_ret = 0
    n_days_ic_nan_small_cross = 0

    daily_valid_names: list[int] = []

    for d in dates:
        sub = lf[lf["_trade_date"] == d]
        f = sub[factor_col].to_numpy()
        r = sub[fwd_ret_col].to_numpy()
        m = np.isfinite(f) & np.isfinite(r)
        covs.append(float(m.mean()) if m.size else 0.0)
        vn = int(m.sum())
        daily_valid_names.append(vn)
        if vn < cfg.min_names_per_day:
            n_days_skip_min_names += 1
            continue
        ff = f[m].astype(np.float64)
        rr = r[m].astype(np.float64)
        # Rank IC 在因子或收益截面「无离散度」时为 nan；与 _rank_ic_numpy 内部秩方差为 0 等价
        if vn < 3:
            n_days_ic_nan_small_cross += 1
        elif float(np.std(ff)) < 1e-12:
            n_days_ic_nan_const_factor += 1
        elif float(np.std(rr)) < 1e-12:
            n_days_ic_nan_const_fwd_ret += 1
        ic = _rank_ic_numpy(f, r)
        ls = _decile_long_short_daily(f, r, cfg.n_quantiles)
        if np.isfinite(ic):
            ics.append(ic)
        if np.isfinite(ls):
            lss.append(ls)

    ic_arr = np.array(ics, dtype=np.float64)
    ls_arr = np.array(lss, dtype=np.float64)

    # 胜率：有效样本日内「方向猜对」的比例（IC 与 0 比，多空收益与 0 比）
    if ic_arr.size:
        rank_ic_win_rate = float(np.mean(ic_arr > 0.0))
    else:
        rank_ic_win_rate = float("nan")
    if ls_arr.size:
        long_short_win_rate = float(np.mean(ls_arr > 0.0))
        # 区间累计：日度多空收益复利滚存（与样本外持有假设一致时需自行理解含义）
        long_short_cumulative_return = float(np.prod(1.0 + ls_arr) - 1.0)
    else:
        long_short_win_rate = float("nan")
        long_short_cumulative_return = float("nan")

    rank_ic_mean = float(np.nanmean(ic_arr)) if ic_arr.size else float("nan")
    rank_ic_std = float(np.nanstd(ic_arr, ddof=1)) if ic_arr.size > 1 else float("nan")
    if np.isfinite(rank_ic_std) and rank_ic_std > 1e-15:
        ic_ir = float(rank_ic_mean / rank_ic_std)
    else:
        ic_ir = float("nan")

    ls_mean = float(np.nanmean(ls_arr)) if ls_arr.size else float("nan")
    ls_vol = float(np.nanstd(ls_arr, ddof=1)) if ls_arr.size > 1 else float("nan")
    ann = float(np.sqrt(cfg.annualization_days))
    ann_days = float(cfg.annualization_days)
    if np.isfinite(ls_vol) and ls_vol > 1e-15:
        ls_sharpe = float(ls_mean / ls_vol * ann)
    else:
        ls_sharpe = float("nan")
    # 由「日均分层多空收益」外推的年化收益（近似，非连续复利持有结果）
    if np.isfinite(ls_mean) and ann_days > 0:
        long_short_annualized_return_approx = float((1.0 + ls_mean) ** ann_days - 1.0)
    else:
        long_short_annualized_return_approx = float("nan")

    cov_mean = float(np.mean(covs)) if covs else float("nan")

    min_vn = int(min(daily_valid_names)) if daily_valid_names else 0
    med_vn = float(np.median(daily_valid_names)) if daily_valid_names else 0.0

    return CrossSectionMetricsResult(
        rank_ic_mean=rank_ic_mean,
        rank_ic_std=rank_ic_std,
        ic_ir=ic_ir,
        long_short_mean_daily=ls_mean,
        long_short_vol_daily=ls_vol,
        long_short_sharpe=ls_sharpe,
        n_ic_days=len(ics),
        n_ls_days=len(lss),
        coverage_mean=cov_mean,
        n_trade_dates=len(dates),
        n_days_skip_min_names=n_days_skip_min_names,
        n_days_ic_nan_const_factor=n_days_ic_nan_const_factor,
        n_days_ic_nan_const_fwd_ret=n_days_ic_nan_const_fwd_ret,
        n_days_ic_nan_small_cross=n_days_ic_nan_small_cross,
        min_daily_valid_names=min_vn,
        median_daily_valid_names=med_vn,
        rank_ic_win_rate=rank_ic_win_rate,
        long_short_win_rate=long_short_win_rate,
        long_short_cumulative_return=long_short_cumulative_return,
        long_short_annualized_return_approx=long_short_annualized_return_approx,
    )


def metrics_to_serializable(m: CrossSectionMetricsResult) -> dict[str, Any]:
    """转为可写入 Excel/json 的纯字典。"""
    out: dict[str, Any] = {
        "rank_ic_mean": m.rank_ic_mean,
        "rank_ic_std": m.rank_ic_std,
        "ic_ir": m.ic_ir,
        "long_short_mean_daily": m.long_short_mean_daily,
        "long_short_vol_daily": m.long_short_vol_daily,
        "long_short_sharpe": m.long_short_sharpe,
        "n_ic_days": m.n_ic_days,
        "n_ls_days": m.n_ls_days,
        "coverage_mean": m.coverage_mean,
        "n_trade_dates": m.n_trade_dates,
        "n_days_skip_min_names": m.n_days_skip_min_names,
        "n_days_ic_nan_const_factor": m.n_days_ic_nan_const_factor,
        "n_days_ic_nan_const_fwd_ret": m.n_days_ic_nan_const_fwd_ret,
        "n_days_ic_nan_small_cross": m.n_days_ic_nan_small_cross,
        "min_daily_valid_names": m.min_daily_valid_names,
        "median_daily_valid_names": m.median_daily_valid_names,
        "rank_ic_win_rate": m.rank_ic_win_rate,
        "long_short_win_rate": m.long_short_win_rate,
        "long_short_cumulative_return": m.long_short_cumulative_return,
        "long_short_annualized_return_approx": m.long_short_annualized_return_approx,
    }
    # 人类可读一句：便于报告里直接看「为什么没算出 IC」
    if m.n_ic_days == 0 and m.n_trade_dates > 0:
        if m.n_days_skip_min_names >= m.n_trade_dates and m.n_trade_dates > 0:
            out["ic_unavailable_hint"] = (
                "全部交易日均未达 min_names_per_day："
                f"全样本里「单日因子与fwd_ret同时有效」最少仅约 {m.min_daily_valid_names} 只、中位数约 {m.median_daily_valid_names:.1f} 只，"
                "低于 Config/factor_evaluation.json 中的 min_names_per_day 时整日跳过，故 n_ic_days=0。"
                "请把 min_names_per_day 调到不高于 min_daily_valid_names（或扩大 max_symbols/拉长区间/减少因子前导缺失）。"
            )
        else:
            out["ic_unavailable_hint"] = (
                "无有效RankIC日：请对照右侧计数——"
                "「因子截面常数」多为表达式在该日全市场同值；"
                "「fwd_ret截面常数」多为收盘价/对齐错误导致次日收益全相同；"
                "「未达min_names」为当日有效样本少于配置门槛。"
            )
    else:
        out["ic_unavailable_hint"] = ""
    return out
