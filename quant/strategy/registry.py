"""显式、稳定的正式策略注册表。"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from .parameters import ParameterDefinition, ParameterSchema, infer_definitions
from .spec import StrategySpec


def _replace(definitions: dict[str, ParameterDefinition], name: str, **changes: Any) -> None:
    current = definitions[name]
    values = current.__dict__.copy()
    values.update(changes)
    definitions[name] = ParameterDefinition(**values)


def _s000001_schema() -> ParameterSchema:
    from InnerStrategy.strategies.qixingaozhao_etf_rotation_strategy import DEFAULT_PARAMS

    defs = infer_definitions(DEFAULT_PARAMS)
    _replace(defs, "lookback_days", minimum=3, maximum=250, step=1, searchable=True, description="动量回看交易日")
    _replace(defs, "holdings_num", minimum=1, maximum=20, step=1, searchable=True, description="目标持仓数量")
    _replace(defs, "loss", minimum=0.5, maximum=1.0, step=0.01, searchable=True)
    _replace(defs, "volume_lookback", minimum=2, maximum=60, step=1, searchable=True)
    _replace(defs, "volume_threshold", minimum=1.0, maximum=20.0, step=0.1, searchable=True)
    _replace(defs, "short_lookback_days", minimum=2, maximum=120, step=1, searchable=True)
    _replace(defs, "sell_ma_window", minimum=1, maximum=250, step=1, searchable=True)
    _replace(defs, "sell_upper_ratio", minimum=1.0, maximum=3.0, step=0.01, searchable=True)
    _replace(defs, "sell_lower_ratio", minimum=0.1, maximum=1.0, step=0.01, searchable=True)
    _replace(defs, "sell_priority", choices=("lower_first", "upper_first", "by_open"))
    _replace(defs, "sell_trigger_mode", choices=("tp_sl", "tp_only", "sl_only"))

    def _score_bounds(params: dict[str, Any]) -> str | None:
        return "min_score_threshold 必须小于 max_score_threshold" if params["min_score_threshold"] >= params["max_score_threshold"] else None

    return ParameterSchema(tuple(defs.values()), (_score_bounds,))


def _s000002_defaults() -> dict[str, Any]:
    from InnerStrategy.slss_strategy_config import load_slss_strategy_config, slss_strategy_config_to_dict

    return slss_strategy_config_to_dict(load_slss_strategy_config())


def _s000002_schema() -> ParameterSchema:
    defs = infer_definitions(_s000002_defaults())
    _replace(defs, "decision_mode", choices=("threshold", "cross_section_rank"), searchable=True)
    _replace(defs, "cross_section_long_top_n", minimum=1, maximum=100, step=1, searchable=True)
    _replace(defs, "cross_section_short_min_rank", minimum=2, maximum=1000, step=1, searchable=True)
    _replace(defs, "cross_section_short_bottom_n", minimum=0, maximum=100, step=1, searchable=True)
    _replace(defs, "buy_threshold", minimum=-100.0, maximum=100.0, step=0.1, searchable=True)
    _replace(defs, "sell_threshold", minimum=-100.0, maximum=100.0, step=0.1, searchable=True)
    _replace(defs, "fixed_lot", minimum=1, maximum=1_000_000, step=100)
    _replace(defs, "alpha_prepare_workers", minimum=1, maximum=64, step=1)

    def _rank_bounds(params: dict[str, Any]) -> str | None:
        if params["decision_mode"] == "cross_section_rank" and params["cross_section_short_min_rank"] <= params["cross_section_long_top_n"]:
            return "cross_section_short_min_rank 必须大于 cross_section_long_top_n"
        return None

    return ParameterSchema(tuple(defs.values()), (_rank_bounds,))


@lru_cache(maxsize=1)
def _registry() -> dict[str, StrategySpec]:
    specs = (
        StrategySpec(
            strategy_id="S000001",
            strategy_version="1.0.0",
            display_name="七星高照 ETF 轮动",
            module="qixingaozhao_etf_rotation_strategy",
            class_name="QixingaozhaoEtfRotationStrategy",
            vector_runner="BackTest.qixingaozhao_backtest_runner.run_qixingaozhao_backtest",
            parameter_schema=_s000001_schema(),
            supported_modes=("vector", "event"),
            asset_types=("etf", "stock"),
            warmup_bars=250,
        ),
        StrategySpec(
            strategy_id="S000002",
            strategy_version="1.0.0",
            display_name="分层多空夏普等权策略",
            module="stratified_ls_sharpe_equal_weight_strategy",
            class_name="StratifiedLongShortSharpeEqualWeightStrategy",
            vector_runner="BackTest.vector_slss_runner.run_vector_slss_backtest",
            parameter_schema=_s000002_schema(),
            supported_modes=("vector", "event"),
            asset_types=("stock",),
            warmup_bars=60,
        ),
    )
    return {spec.strategy_id: spec for spec in specs}


def get_strategy_spec(strategy_id: str) -> StrategySpec | None:
    return _registry().get(strategy_id)


def list_strategy_specs() -> tuple[StrategySpec, ...]:
    return tuple(_registry().values())
