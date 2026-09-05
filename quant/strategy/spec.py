"""策略稳定注册信息。"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Callable

from .parameters import ParameterSchema


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    strategy_version: str
    display_name: str
    module: str
    class_name: str
    vector_runner: str
    parameter_schema: ParameterSchema
    supported_modes: tuple[str, ...] = ("vector",)
    asset_types: tuple[str, ...] = ("stock",)
    warmup_bars: int = 0

    def load_vector_runner(self) -> Callable:
        module_name, function_name = self.vector_runner.rsplit(".", 1)
        return getattr(import_module(module_name), function_name)

    def legacy_entry(self) -> dict[str, str]:
        return {
            "id": self.strategy_id,
            "label": f"{self.strategy_id} | {self.module} | {self.class_name}",
            "module": self.module,
            "class": self.class_name,
            "version": self.strategy_version,
        }

