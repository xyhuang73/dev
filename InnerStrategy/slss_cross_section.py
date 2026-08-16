# -*- coding: utf-8 -*-
"""
SLSS 截面分桶：按交易日对 ``slss_composite`` 排序，将标的划入多 / 空 / 中性带。

规则（与 ``Config/slss_strategy.json`` 中 ``cross_section_*`` 一致）::
    - 当日仅使用合成值有限的标的参与排序；
    - 合成值从高到低排序，名次 1..N（并列时用 ``vt_symbol`` 升序打破并列，保证确定性）；
    - 名次 <= ``long_top_n`` 且满足可选过滤 → 做多目标（+1）；
    - 空头：可选「名次 >= short_min_rank」或「当日名次最差的 short_bottom_n 只」二选一（``short_bottom_n>0`` 时优先后者）；
      可选再并上「合成值 < 0」的或条件；
    - 其余名次 → 空仓目标（0）。

若当日有效标的数少于 ``short_min_rank-1``，则按 ``short_min_rank`` 的空头桶可能为空。
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def compute_cross_section_target_side(
    df: pd.DataFrame,
    *,
    value_col: str,
    long_top_n: int,
    short_min_rank: int,
    price_col: str = "close",
    long_require_close_positive: bool = False,
    long_require_composite_positive: bool = False,
    short_bottom_n: int = 0,
    short_or_negative_composite: bool = False,
) -> pd.Series:
    """
    为宽表每一行标注截面目标方向。

    Args:
        df: 须含 ``datetime``、``vt_symbol``、``value_col``（如 ``slss_composite``）。
        value_col: 用于排序的合成列名。
        long_top_n: 做多人数上限（名次 1..long_top_n），可再叠加正价、正合成过滤。
        short_min_rank: 当 ``short_bottom_n<=0`` 时：名次 >= 该值 → 空头候选（须 > long_top_n）。
        price_col: 用于「收盘价 > 0」过滤的列名，缺列且要求正价时视为不满足多头。
        long_require_close_positive: 为 True 时多头还要求 ``price_col`` 有限且 >0。
        long_require_composite_positive: 为 True 时多头还要求 ``value_col`` >0。
        short_bottom_n: >0 时，空头名次桶为「当日最差的 N 只」（与 ``short_min_rank`` 二选一）。
        short_or_negative_composite: 为 True 时，凡合成值 <0 且未标多头的标的也标空头（与名次空头取并）。

    Returns:
        与 ``df`` 行索引对齐的 ``int8`` 序列，取值为 -1 / 0 / 1。
    """
    need = {"datetime", "vt_symbol", value_col}
    miss = need - set(df.columns)
    if miss:
        raise ValueError(f"compute_cross_section_target_side 缺少列: {miss}")
    if long_require_close_positive and price_col not in df.columns:
        raise ValueError(f"long_require_close_positive 为 True 但缺少行情列: {price_col!r}")

    lt = max(1, int(long_top_n))
    sm = int(short_min_rank)
    if sm <= lt + 0:
        sm = lt + 1

    sbn = max(0, int(short_bottom_n))

    out = np.zeros(len(df), dtype=np.int8)
    gdt = pd.to_datetime(df["datetime"], errors="coerce").dt.normalize()
    val = pd.to_numeric(df[value_col], errors="coerce").to_numpy(dtype=np.float64)
    sym_all = df["vt_symbol"].to_numpy(dtype=object)
    if long_require_close_positive:
        close_all = pd.to_numeric(df[price_col], errors="coerce").to_numpy(dtype=np.float64)
    else:
        close_all = None

    for dk in gdt.dropna().unique():
        rows = np.flatnonzero((gdt == dk).to_numpy())
        if rows.size == 0:
            continue
        v = val[rows]
        sym = sym_all[rows]
        finite = np.isfinite(v)
        if not finite.any():
            continue
        rows_f = rows[finite]
        v_f = v[finite]
        sym_f = sym[finite]
        m = int(rows_f.shape[0])
        # 名次 rank_day[i] = 该有限样本内第几名（1 为合成最高）
        order = np.lexsort((sym_f, -v_f))
        rank_day = np.empty(m, dtype=np.int32)
        for pos in range(m):
            rank_day[int(order[pos])] = int(pos + 1)

        if long_require_close_positive and close_all is not None:
            c_f = close_all[rows_f]
        else:
            c_f = None

        for j in range(m):
            k = int(rows_f[j])
            rank1 = int(rank_day[j])
            vj = float(v_f[j])
            # 多头：名次满足且可选 close>0、composite>0
            long_rank_ok = rank1 <= lt
            long_close_ok = (not long_require_close_positive) or (
                c_f is not None and math.isfinite(float(c_f[j])) and float(c_f[j]) > 0.0
            )
            long_comp_ok = (not long_require_composite_positive) or (vj > 0.0)
            long_assign = bool(long_rank_ok and long_close_ok and long_comp_ok)

            # 空头名次桶：底 N 只 或 名次 >= short_min_rank
            if sbn > 0:
                eff_n = min(sbn, m)
                first_bottom_rank = m - eff_n + 1
                short_rank_ok = rank1 >= first_bottom_rank
            else:
                short_rank_ok = rank1 >= sm

            short_neg_ok = bool(short_or_negative_composite and vj < 0.0)
            short_assign = bool((not long_assign) and (short_rank_ok or short_neg_ok))

            if long_assign:
                out[k] = 1
            elif short_assign:
                out[k] = -1
            else:
                out[k] = 0

    return pd.Series(out, index=df.index, dtype=np.int8)
