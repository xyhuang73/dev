#!/usr/bin/env python3
"""Order lifecycle state machine for adapter design checks."""

from __future__ import annotations

from dataclasses import dataclass


ALLOWED = {
    "created": {"accepted", "rejected"},
    "accepted": {"partially_filled", "filled", "cancel_requested", "rejected"},
    "partially_filled": {"partially_filled", "filled", "cancel_requested"},
    "cancel_requested": {"cancelled", "partially_filled", "filled", "unknown"},
    "unknown": {"accepted", "partially_filled", "filled", "cancelled", "rejected"},
    "filled": set(),
    "cancelled": set(),
    "rejected": set(),
}


@dataclass
class Order:
    client_order_id: str
    quantity: float
    state: str = "created"
    filled_quantity: float = 0.0

    def transition(self, new_state: str, fill_qty: float = 0.0) -> None:
        if new_state not in ALLOWED[self.state]:
            raise ValueError(f"invalid transition {self.state} -> {new_state}")
        if fill_qty < 0:
            raise ValueError("fill_qty cannot be negative")
        if self.filled_quantity + fill_qty > self.quantity:
            raise ValueError("filled quantity exceeds order quantity")
        self.filled_quantity += fill_qty
        self.state = new_state


def demo() -> list[dict]:
    order = Order("demo-001", 10)
    events = []
    for state, qty in [("accepted", 0), ("partially_filled", 4), ("cancel_requested", 0), ("cancelled", 0)]:
        order.transition(state, qty)
        events.append({"state": order.state, "filled_quantity": order.filled_quantity})
    return events


if __name__ == "__main__":
    for event in demo():
        print(event)
