# -*- coding: utf-8 -*-
"""
兼容旧导入路径。

- **批量因子评估**：``factor_evaluation_settings`` ↔ ``Config/factor_evaluation.json``；
- **单因子计算**：``alpha_prepare_max_workers`` ↔ ``Config/single_factor_parameters.json``；
  Alpha101/Alpha158 ↔ ``InnerStrategy/factors/alpha_101_parameters.json``、``alpha_158_parameters.json``（与 ``.py`` 同名）。

旧名 ``FACTOR_PARAMETERS_JSON_PATH`` / ``load_factor_parameters_json`` 仍指向评估配置，便于渐进迁移。
"""
from __future__ import annotations

from .factor_evaluation_settings import (
    FACTOR_EVAL_CONFIG_PATH,
    FACTOR_EVALUATION_CONFIG_PATH,
    FACTOR_PARAMETERS_JSON_PATH,
    SchemeBConfig,
    dict_to_scheme_b,
    is_local_datadir_market_source,
    load_factor_evaluation_json,
    load_factor_parameters_json,
    patch_factor_evaluation_json,
    patch_factor_parameters_json,
    save_factor_evaluation_json,
    save_factor_parameters_json,
)
from InnerStrategy.factors.alpha_101_parameters import ALPHA101_PARAMETERS_JSON_PATH

from .factor_single_parameters_settings import (
    ALPHA158_PARAMETERS_JSON_PATH,
    FACTOR_SINGLE_PARAMETERS_JSON_PATH,
    alpha101_params,
    alpha158_formula_params,
    alpha158_ts_windows,
    load_single_factor_parameters_json,
    patch_single_factor_parameters_json,
    save_single_factor_parameters_json,
)

__all__ = [
    "ALPHA101_PARAMETERS_JSON_PATH",
    "ALPHA158_PARAMETERS_JSON_PATH",
    "FACTOR_EVAL_CONFIG_PATH",
    "FACTOR_EVALUATION_CONFIG_PATH",
    "FACTOR_PARAMETERS_JSON_PATH",
    "FACTOR_SINGLE_PARAMETERS_JSON_PATH",
    "SchemeBConfig",
    "alpha101_params",
    "alpha158_formula_params",
    "alpha158_ts_windows",
    "dict_to_scheme_b",
    "is_local_datadir_market_source",
    "load_factor_evaluation_json",
    "load_factor_parameters_json",
    "load_single_factor_parameters_json",
    "patch_factor_evaluation_json",
    "patch_factor_parameters_json",
    "patch_single_factor_parameters_json",
    "save_factor_evaluation_json",
    "save_factor_parameters_json",
    "save_single_factor_parameters_json",
]
