#!/usr/bin/env python3
"""Portable quant strategy template.

Keep signal generation pure. Submit orders outside this class through a
portfolio/risk/execution layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass(frozen=True)
class StrategyParams:
    fast_window: int = 10
    slow_window: int = 30
    max_position: float = 1.0
    min_signal_strength: float = 0.0


@dataclass
class StrategyState:
    prices: Dict[str, list[float]] = field(default_factory=dict)
    target_position: Dict[str, float] = field(default_factory=dict)
    last_signal: Dict[str, float] = field(default_factory=dict)
    exit_reason: Dict[str, str] = field(default_factory=dict)


class StrategyTemplate:
    def __init__(self, params: StrategyParams | None = None) -> None:
        self.params = params or StrategyParams()
        self.state = StrategyState()

    def initialize(self, symbols: list[str]) -> None:
        for symbol in symbols:
            self.state.prices.setdefault(symbol, [])
            self.state.target_position.setdefault(symbol, 0.0)

    def on_data(self, symbol: str, close: float) -> dict:
        self.update_indicators(symbol, close)
        signal = self.generate_signal(symbol)
        target = self.build_target(symbol, signal)
        target = self.risk_check(symbol, target)
        self.state.target_position[symbol] = target
        self.state.last_signal[symbol] = signal
        return {"symbol": symbol, "signal": signal, "target_position": target}

    def update_indicators(self, symbol: str, close: float) -> None:
        self.state.prices.setdefault(symbol, []).append(close)

    def generate_signal(self, symbol: str) -> float:
        prices = self.state.prices[symbol]
        if len(prices) < self.params.slow_window:
            return 0.0
        fast = sum(prices[-self.params.fast_window:]) / self.params.fast_window
        slow = sum(prices[-self.params.slow_window:]) / self.params.slow_window
        return (fast - slow) / slow if slow else 0.0

    def build_target(self, symbol: str, signal: float) -> float:
        if abs(signal) <= self.params.min_signal_strength:
            self.state.exit_reason[symbol] = "weak_signal"
            return 0.0
        return self.params.max_position if signal > 0 else -self.params.max_position

    def risk_check(self, symbol: str, target: float) -> float:
        clipped = max(-self.params.max_position, min(self.params.max_position, target))
        if clipped != target:
            self.state.exit_reason[symbol] = "position_clipped"
        return clipped

    def on_order_update(self, symbol: str, status: str, filled_qty: float, avg_price: Optional[float]) -> None:
        # Keep execution state here only if the surrounding framework does not own it.
        _ = (symbol, status, filled_qty, avg_price)
