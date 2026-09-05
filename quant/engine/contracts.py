"""回测及后续模拟/实盘共用的稳定数据合同。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping


class RunMode(str, Enum):
    VECTOR = "vector"
    EVENT = "event"
    PAPER = "paper"
    LIVE = "live"


class SignalDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"
    EXIT = "EXIT"


def _parse_date(value: str) -> datetime:
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"日期必须是 YYYYMMDD 或 YYYY-MM-DD: {value!r}")


@dataclass(frozen=True)
class RunConfig:
    """一次可复现运行的不可变配置快照。"""

    run_id: str
    mode: RunMode
    strategy_id: str
    strategy_version: str
    strategy_params: Mapping[str, Any]
    start_date: str
    end_date: str
    initial_capital: float
    warmup_start: str | None = None
    dataset_id: str = "local-current"
    universe_id: str = "configured-current"
    benchmark: str | None = None
    cost_model: str = "legacy-current"
    slippage_model: str = "legacy-current"
    fill_model: str = "legacy-current"
    risk_profile: str = "backtest-default"
    random_seed: int = 0

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id 不能为空")
        if not (self.strategy_id.startswith("S") and self.strategy_id[1:].isdigit()):
            raise ValueError(f"非法 strategy_id: {self.strategy_id!r}")
        start = _parse_date(self.start_date)
        end = _parse_date(self.end_date)
        if start > end:
            raise ValueError("start_date 不能晚于 end_date")
        if self.warmup_start and _parse_date(self.warmup_start) > start:
            raise ValueError("warmup_start 不能晚于 start_date")
        if float(self.initial_capital) <= 0:
            raise ValueError("initial_capital 必须大于 0")
        object.__setattr__(self, "strategy_params", MappingProxyType(dict(self.strategy_params)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "mode": self.mode.value,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "strategy_params": dict(self.strategy_params),
            "start_date": self.start_date,
            "end_date": self.end_date,
            "warmup_start": self.warmup_start,
            "initial_capital": self.initial_capital,
            "dataset_id": self.dataset_id,
            "universe_id": self.universe_id,
            "benchmark": self.benchmark,
            "cost_model": self.cost_model,
            "slippage_model": self.slippage_model,
            "fill_model": self.fill_model,
            "risk_profile": self.risk_profile,
            "random_seed": self.random_seed,
        }


@dataclass(frozen=True)
class SignalRecord:
    datetime: datetime
    symbol: str
    score: float | None
    signal: SignalDirection
    reason: str = ""


@dataclass(frozen=True)
class SignalFrame:
    """策略判断集合；信号不是订单，也不保证成交。"""

    records: tuple[SignalRecord, ...] = ()

    @classmethod
    def from_records(cls, records: Iterable[SignalRecord]) -> "SignalFrame":
        rows = tuple(records)
        if any(not row.symbol.strip() for row in rows):
            raise ValueError("SignalFrame.symbol 不能为空")
        return cls(rows)


@dataclass(frozen=True)
class TargetPositionRecord:
    datetime: datetime
    symbol: str
    target_weight: float | None = None
    target_volume: int | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("TargetPosition.symbol 不能为空")
        if (self.target_weight is None) == (self.target_volume is None):
            raise ValueError("target_weight 与 target_volume 必须且只能提供一个")
        if self.target_weight is not None and not -1.0 <= self.target_weight <= 1.0:
            raise ValueError("target_weight 必须位于 [-1, 1]")


@dataclass(frozen=True)
class TargetPosition:
    records: tuple[TargetPositionRecord, ...] = ()

    @classmethod
    def from_records(cls, records: Iterable[TargetPositionRecord]) -> "TargetPosition":
        return cls(tuple(records))


@dataclass(frozen=True)
class RunResult:
    ok: bool
    message: str
    run_id: str
    metrics: Mapping[str, Any] = field(default_factory=dict)
    artifact_paths: Mapping[str, str] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))
        object.__setattr__(self, "artifact_paths", MappingProxyType(dict(self.artifact_paths)))

