#!/usr/bin/env python3
"""Minimal event-driven backtest skeleton.

This is a starting point, not a production engine. Replace the broker simulator
with venue-specific fill, fee, margin, and liquidity rules before using it for
research conclusions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class MarketEvent:
    time: str
    symbol: str
    close: float


@dataclass(frozen=True)
class SignalEvent:
    time: str
    symbol: str
    target_position: int
    reason: str


@dataclass(frozen=True)
class OrderEvent:
    time: str
    symbol: str
    quantity: int
    reason: str


@dataclass(frozen=True)
class FillEvent:
    time: str
    symbol: str
    quantity: int
    price: float
    fee: float


@dataclass
class Portfolio:
    cash: float = 100000.0
    position: int = 0
    last_price: float = 0.0

    def mark_to_market(self) -> float:
        return self.cash + self.position * self.last_price

    def apply_fill(self, fill: FillEvent) -> None:
        self.cash -= fill.quantity * fill.price + fill.fee
        self.position += fill.quantity
        self.last_price = fill.price


class MovingAverageStrategy:
    def __init__(self, window: int = 3) -> None:
        self.window = window
        self.prices: List[float] = []

    def on_market(self, event: MarketEvent, current_position: int) -> Optional[SignalEvent]:
        self.prices.append(event.close)
        if len(self.prices) < self.window:
            return None
        avg = sum(self.prices[-self.window:]) / self.window
        target = 1 if event.close > avg else 0
        if target == current_position:
            return None
        return SignalEvent(event.time, event.symbol, target, f"close_vs_ma_{self.window}")


class BrokerSimulator:
    def __init__(self, fee_bps: float = 1.0) -> None:
        self.fee_bps = fee_bps

    def execute_next_bar(self, order: OrderEvent, next_event: MarketEvent) -> FillEvent:
        notional = abs(order.quantity) * next_event.close
        fee = notional * self.fee_bps / 10000.0
        return FillEvent(next_event.time, order.symbol, order.quantity, next_event.close, fee)


def run(events: Iterable[MarketEvent]) -> list[dict]:
    events = list(events)
    strategy = MovingAverageStrategy()
    broker = BrokerSimulator()
    portfolio = Portfolio()
    audit_log: list[dict] = []

    for idx, event in enumerate(events[:-1]):
        portfolio.last_price = event.close
        signal = strategy.on_market(event, portfolio.position)
        if signal is None:
            audit_log.append({"time": event.time, "event": "hold", "equity": portfolio.mark_to_market()})
            continue

        quantity = signal.target_position - portfolio.position
        order = OrderEvent(event.time, event.symbol, quantity, signal.reason)
        fill = broker.execute_next_bar(order, events[idx + 1])
        portfolio.apply_fill(fill)
        audit_log.append({
            "time": event.time,
            "event": "fill_next_bar",
            "signal": signal.reason,
            "quantity": quantity,
            "fill_time": fill.time,
            "fill_price": fill.price,
            "equity": portfolio.mark_to_market(),
        })

    return audit_log


if __name__ == "__main__":
    sample = [
        MarketEvent("2026-01-01", "SPY", 100.0),
        MarketEvent("2026-01-02", "SPY", 101.0),
        MarketEvent("2026-01-03", "SPY", 102.0),
        MarketEvent("2026-01-04", "SPY", 99.0),
        MarketEvent("2026-01-05", "SPY", 103.0),
    ]
    for row in run(sample):
        print(row)
