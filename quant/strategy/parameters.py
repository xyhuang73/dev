"""策略参数的可发现、可校验 schema。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


_TYPE_NAMES = {bool: "bool", int: "int", float: "float", str: "str", list: "list", tuple: "list", dict: "object"}


@dataclass(frozen=True)
class ParameterDefinition:
    name: str
    value_type: str
    default: Any
    description: str = ""
    minimum: float | int | None = None
    maximum: float | int | None = None
    step: float | int | None = None
    choices: tuple[Any, ...] = ()
    searchable: bool = False
    search_scale: str = "linear"
    nullable: bool = False

    def validate(self, value: Any) -> Any:
        if value is None and self.nullable:
            return None
        valid = {
            "bool": isinstance(value, bool),
            "int": isinstance(value, int) and not isinstance(value, bool),
            "float": isinstance(value, (int, float)) and not isinstance(value, bool),
            "str": isinstance(value, str),
            "list": isinstance(value, (list, tuple)),
            "object": isinstance(value, Mapping),
        }.get(self.value_type, False)
        if not valid:
            raise ValueError(f"参数 {self.name} 应为 {self.value_type}，实际为 {type(value).__name__}")
        normalized = float(value) if self.value_type == "float" else value
        if self.minimum is not None and normalized < self.minimum:
            raise ValueError(f"参数 {self.name} 不能小于 {self.minimum}")
        if self.maximum is not None and normalized > self.maximum:
            raise ValueError(f"参数 {self.name} 不能大于 {self.maximum}")
        if self.choices and normalized not in self.choices:
            raise ValueError(f"参数 {self.name} 必须是 {self.choices} 之一")
        return list(normalized) if self.value_type == "list" else normalized


@dataclass(frozen=True)
class ParameterSchema:
    definitions: tuple[ParameterDefinition, ...]
    constraints: tuple[Callable[[Mapping[str, Any]], str | None], ...] = field(default_factory=tuple)

    def validate(self, values: Mapping[str, Any] | None = None) -> dict[str, Any]:
        supplied = dict(values or {})
        known = {item.name for item in self.definitions}
        unknown = sorted(set(supplied) - known)
        if unknown:
            raise ValueError(f"未知策略参数: {', '.join(unknown)}")
        result = {item.name: item.validate(supplied.get(item.name, item.default)) for item in self.definitions}
        for constraint in self.constraints:
            error = constraint(result)
            if error:
                raise ValueError(error)
        return result

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return {
            item.name: {
                "type": item.value_type,
                "default": item.default,
                "description": item.description,
                "minimum": item.minimum,
                "maximum": item.maximum,
                "step": item.step,
                "choices": list(item.choices),
                "searchable": item.searchable,
                "search_scale": item.search_scale,
                "nullable": item.nullable,
            }
            for item in self.definitions
        }


def infer_definitions(defaults: Mapping[str, Any]) -> dict[str, ParameterDefinition]:
    definitions: dict[str, ParameterDefinition] = {}
    for name, value in defaults.items():
        value_type = _TYPE_NAMES.get(type(value), "object") if value is not None else "list"
        definitions[name] = ParameterDefinition(name, value_type, value, nullable=value is None)
    return definitions

