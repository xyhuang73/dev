# -*- coding: utf-8 -*-
"""
Alpha101 各特征公式中的**可调数值缺省**（与当前仓库内 WorldQuant 101 实现一致）。

可调参数以 ``InnerStrategy/factors/alpha_101_parameters.json`` 为磁盘主表（空文件时由本模块一次性写入全量缺省）；
逻辑入口为同目录 ``alpha_101_parameters.py`` 的 ``alpha101_params()``。公式在 ``alpha_101.py`` 中用 f-string 引用合并后的键。
"""
from __future__ import annotations

from typing import Any


def build_alpha101_formula_defaults() -> dict[str, dict[str, Any]]:
    """
    返回 alpha_id → 参数字典。

    命名约定：窗口/滞后尽量用 ``n_*``，quesval 阈值用 ``q_*``，权重系数用 ``w_*``。
    """
    d: dict[str, dict[str, Any]] = {}

    # --- Alpha1–Alpha35 ---
    d["alpha1"] = {"q0": 0, "n_std": 20, "pow_n": 2.0, "n_argmax": 5, "half": 0.5}
    d["alpha2"] = {"n_delta_vol": 2, "n_corr": 6}
    d["alpha3"] = {"n_corr": 10}
    d["alpha4"] = {"n_rank": 9}
    d["alpha5"] = {"n_sum_vwap": 10}
    d["alpha6"] = {"n_corr": 10}
    d["alpha7"] = {"n_vol_mean": 20, "n_delay_close": 7, "n_rank": 60, "n_delta_close": 7, "else_v": -1}
    d["alpha8"] = {"n_sum": 5, "n_delay": 10}
    d["alpha9"] = {"n_bound": 5}
    d["alpha10"] = {"n_bound": 4}
    d["alpha11"] = {"n_extreme": 3, "n_delta_vol": 3}
    d["alpha12"] = {"n_delta_vol": 1, "n_delta_close": 1}
    d["alpha13"] = {"n_cov": 5}
    d["alpha14"] = {"n_delay_ret": 3, "n_corr": 10}
    d["alpha15"] = {"n_corr_inner": 3, "n_sum_outer": 3}
    d["alpha16"] = {"n_cov": 5}
    d["alpha17"] = {
        "n_rank_close": 10,
        "k_delay2": 2,
        "n_delay1": 1,
        "n_delay2": 2,
        "n_vol_mean": 20,
        "n_rank_vol": 5,
    }
    d["alpha18"] = {"n_std": 5, "n_corr": 10}
    d["alpha19"] = {"n_delta": 7, "n_delay": 7, "n_sum_ret": 250}
    d["alpha20"] = {"n_delay_h": 1, "n_delay_c": 1, "n_delay_l": 1}
    d["alpha21"] = {"n_mean_long": 8, "n_mean_short": 2, "n_vol_mean": 20, "q_in": 1}
    d["alpha22"] = {"n_corr": 5, "n_delta_corr": 5, "n_std_close": 20}
    d["alpha23"] = {"n_mean_high": 20, "n_delta_high": 2, "else_v": 0}
    d["alpha24"] = {"q_thresh": 0.05, "n_sum": 100, "n_delay_close": 100, "n_delta_close": 3, "n_min_close": 100}
    d["alpha25"] = {"n_vol_mean": 20}
    d["alpha26"] = {"n_rank": 5, "n_corr": 5, "n_ts_max": 3}
    d["alpha27"] = {"q_thresh": 0.5, "n_corr": 6, "n_mean": 2, "v_neg": -1, "v_pos": 1}
    d["alpha28"] = {"n_vol_mean": 20, "n_corr": 5}
    d["alpha29"] = {
        "lit_close_minus": 1,
        "n_delta_close": 5,
        "n_min_inner": 2,
        "n_sum_inner": 1,
        "n_min_mid": 1,
        "n_min_outer": 5,
        "n_delay_ret": 6,
        "n_rank": 5,
    }
    d["alpha30"] = {"n_sum_vol_short": 5, "n_sum_vol_long": 20}
    d["alpha31"] = {"n_delta_long": 10, "n_decay": 10, "n_delta_short": 3, "n_vol_mean": 20, "n_corr": 12}
    d["alpha32"] = {"n_sum_close": 7, "k_scale_corr": 20, "n_delay_close": 5, "n_corr": 230}
    d["alpha33"] = {}  # 无独立数值窗口，保持原式
    d["alpha34"] = {"n_std_short": 2, "n_std_long": 5, "n_delta_close": 1}
    d["alpha35"] = {"n_rank_vol": 32, "n_rank_hlc": 16, "n_rank_ret": 32}
    d["alpha36"] = {
        "w1": 2.21,
        "n_corr1": 15,
        "w2": 0.7,
        "w3": 0.73,
        "n_delay_ret": 6,
        "n_rank_ret": 5,
        "n_vol_mean": 20,
        "n_corr_vw": 6,
        "w4": 0.6,
        "n_sum_close": 200,
    }
    d["alpha37"] = {"n_delay_oc": 1, "n_corr": 200}
    d["alpha38"] = {"n_rank_close": 10}
    d["alpha39"] = {"n_delta": 7, "n_vol_mean": 20, "n_decay": 9, "n_sum_ret": 250}
    d["alpha40"] = {"n_std_high": 10, "n_corr": 10}
    d["alpha41"] = {"pow_exp": 0.5}
    d["alpha42"] = {}  # 纯秩比，无数值参数
    d["alpha43"] = {"n_vol_mean": 20, "n_rank_vol": 20, "n_delta_close": 7, "n_rank_delta": 8}
    d["alpha44"] = {"n_corr": 5}
    d["alpha45"] = {"n_delay_close": 5, "n_sum_delay": 20, "n_corr_cv": 2, "n_sum_a": 5, "n_sum_b": 20, "n_corr_ss": 2}
    d["alpha46"] = {
        "q_outer": 0.25,
        "n_delay_long": 20,
        "n_delay_mid": 10,
        "n_div": 10,
        "q_inner": 0,
        "n_delay_ret": 1,
        "v_else_outer": -1,
        "v_else_inner": 1,
    }
    d["alpha47"] = {"n_vol_mean": 20, "n_sum_high": 5, "n_delay_vwap": 5, "pow_close": -1}
    d["alpha49"] = {"q_thresh": -0.1, "n_delay_long": 20, "n_delay_mid": 10, "n_div": 10, "n_delay_ret": 1, "v_else": 1}
    d["alpha50"] = {"n_corr": 5, "n_ts_max": 5}
    d["alpha51"] = {"q_thresh": -0.05, "n_delay_long": 20, "n_delay_mid": 10, "n_div": 10, "n_delay_ret": 1, "v_else": 1}
    d["alpha52"] = {"n_min_low": 5, "n_delay_min": 5, "n_sum_ret_long": 240, "n_sum_ret_short": 20, "n_div_ret": 220, "n_rank_vol": 5}
    d["alpha53"] = {"n_delta": 9}
    d["alpha54"] = {"pow_open": 5, "pow_close": 5}
    d["alpha55"] = {"n_extreme": 12, "n_corr": 6}
    d["alpha57"] = {"n_argmax": 30, "n_decay": 2}
    d["alpha60"] = {"k_scale": 2, "n_argmax": 10}
    d["alpha61"] = {"n_min_vwap": 16, "n_vol_mean": 180, "n_corr": 18, "v1": 1, "v0": 0}
    d["alpha62"] = {"n_vol_mean": 20, "n_sum_mean_vol": 22, "n_corr": 10}
    d["alpha64"] = {
        "w_open": 0.178404,
        "n_sum_oh": 13,
        "n_vol_mean": 120,
        "n_sum_vm": 13,
        "n_corr": 17,
        "w_hl": 0.178404,
        "n_delta": 4,
    }
    d["alpha65"] = {"w_open": 0.00817205, "n_vol_mean": 60, "n_sum_vm": 9, "n_corr": 6, "n_min_open": 14}
    d["alpha66"] = {"n_delta_vwap": 4, "n_decay_a": 7, "w_low_a": 0.96633, "n_decay_b": 11, "n_rank_b": 7}
    d["alpha68"] = {"n_vol_mean": 15, "n_corr_inner": 9, "n_rank_outer": 14, "w_close": 0.518371, "n_delta": 1}
    # 两段 ts_decay_linear / ts_rank 窗口与原版一致（4/16 与 16/4 交叉）
    d["alpha71"] = {
        "n_rank_close": 3,
        "n_vol_mean": 180,
        "n_mean_sum": 12,
        "n_corr": 18,
        "n_decay_first": 4,
        "n_rank_first": 16,
        "pow_inner": 2,
        "n_decay_second": 16,
        "n_rank_second": 4,
    }
    d["alpha72"] = {"n_vol_mean": 40, "n_corr_a": 9, "n_decay_a": 10, "n_rank_vwap": 4, "n_rank_vol": 19, "n_corr_b": 7, "n_decay_b": 3}
    d["alpha73"] = {"n_delta_vwap": 5, "n_decay_a": 3, "w_open": 0.147155, "n_delta_combo": 2, "n_decay_b": 3, "n_rank_b": 17}
    d["alpha74"] = {"n_vol_mean": 30, "n_sum_vm": 37, "n_corr_a": 15, "w_high": 0.0261661, "n_corr_b": 11, "v1": 1, "v0": 0}
    d["alpha75"] = {"n_corr_a": 4, "n_vol_mean": 50, "n_corr_b": 12, "v1": 1, "v0": 0}
    d["alpha77"] = {"n_decay_a": 20, "n_vol_mean": 40, "n_corr": 3, "n_decay_b": 6}
    d["alpha78"] = {"w_low": 0.352233, "n_sum_a": 20, "n_vol_mean": 40, "n_sum_b": 20, "n_corr_a": 7, "n_corr_b": 6}
    d["alpha81"] = {
        "n_vol_mean": 10,
        "n_sum_vm": 50,
        "n_corr_a": 8,
        "pow_rank": 4,
        "n_product": 15,
        "n_corr_b": 5,
        "v1": 1,
        "v0": 0,
    }
    d["alpha83"] = {"n_sum_close": 5, "n_delay": 2}
    d["alpha84"] = {"n_max_vwap": 15, "n_rank": 21, "n_delta_close": 5}
    d["alpha85"] = {"w_high": 0.876703, "w_close": 0.123297, "n_vol_mean": 30, "n_corr_a": 10, "n_rank_hl": 4, "n_rank_vol": 10, "n_corr_b": 7}
    d["alpha86"] = {"n_vol_mean": 20, "n_sum_vm": 15, "n_corr": 6, "n_rank": 20, "v1": 1, "v0": 0}
    d["alpha88"] = {"n_decay_a": 8, "n_vol_mean": 60, "n_rank_close": 8, "n_mean_sum": 21, "n_corr": 8, "n_decay_b": 7, "n_rank_b": 3}
    d["alpha92"] = {"n_decay_a": 15, "n_rank_a": 19, "n_vol_mean": 30, "n_corr": 8, "n_decay_b": 7, "n_rank_b": 7, "v_a": 1, "v_b": 0}
    d["alpha94"] = {"n_min_vwap": 12, "n_rank_vwap": 20, "n_vol_mean": 60, "n_rank_vm": 4, "n_corr": 18, "n_rank_last": 3}
    d["alpha95"] = {"n_min_open": 12, "n_sum_hl": 19, "n_vol_mean": 40, "n_sum_vm": 19, "n_corr": 13, "pow_rank": 5, "n_rank": 12, "v1": 1, "v0": 0}
    # ts_decay_linear(ts_corr(vwap,volume,4),4) → rank 8；内层 corr 窗口均为 4
    d["alpha96"] = {
        "n_corr_vw": 4,
        "n_decay_a": 4,
        "n_rank_a": 8,
        "n_rank_close": 7,
        "n_vol_mean": 60,
        "n_rank_vm": 4,
        "n_corr_cc": 4,
        "n_argmax": 13,
        "n_decay_b": 14,
        "n_rank_b": 13,
    }
    # 第二段 ts_corr 第三参 21 与 ts_argmin 第二参 9 不同，分键 n_corr_open / n_argmin_n
    d["alpha98"] = {
        "n_vol_mean_a": 5,
        "n_sum_vm_a": 26,
        "n_corr_a": 5,
        "n_decay_a": 7,
        "n_vol_mean_b": 15,
        "n_corr_open": 21,
        "n_argmin_n": 9,
        "n_rank_inner": 7,
        "n_decay_b": 8,
    }
    d["alpha99"] = {"n_sum_hl": 20, "n_vol_mean": 60, "n_sum_vm": 20, "n_corr_a": 9, "n_corr_lv": 6, "v1": 1, "v0": 0}
    d["alpha101"] = {"eps_hl": 0.001}

    return d


# 模块级常量：供 ``factor_single_parameters_settings`` 深合并使用
ALPHA101_FORMULA_DEFAULTS: dict[str, dict[str, Any]] = build_alpha101_formula_defaults()
