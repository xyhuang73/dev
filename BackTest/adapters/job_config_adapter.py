"""保持 GUI 旧调用不变，同时生成完整的新运行配置。"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from quant.engine.contracts import RunConfig, RunMode
from quant.strategy.registry import get_strategy_spec

from ..models import BacktestJobConfig


def job_to_run_config(job: BacktestJobConfig) -> RunConfig:
    spec = get_strategy_spec(job.strategy_key)
    if spec is None:
        raise ValueError(f"未注册策略: {job.strategy_key}")
    if job.backtest_mode not in spec.supported_modes:
        raise ValueError(f"策略 {job.strategy_key} 暂不支持 {job.backtest_mode} 模式")
    params = spec.parameter_schema.validate(job.strategy_params)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = job.run_id or f"BT-{stamp}-{uuid4().hex[:6].upper()}"
    return RunConfig(
        run_id=run_id,
        mode=RunMode(job.backtest_mode),
        strategy_id=job.strategy_key,
        strategy_version=spec.strategy_version,
        strategy_params=params,
        start_date=job.start_date,
        end_date=job.end_date,
        initial_capital=job.initial_capital,
        dataset_id=job.dataset_id,
        universe_id=job.universe_id,
        random_seed=job.random_seed,
    )

