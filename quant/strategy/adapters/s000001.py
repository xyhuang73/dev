"""S000001 七星高照策略的统一输出适配器。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from quant.engine.contracts import (
    SignalDirection,
    SignalFrame,
    SignalRecord,
    TargetPosition,
    TargetPositionRecord,
)


@dataclass
class S000001OutputCollector:
    """在旧日线循环内旁路采集信号与目标，不改变成交状态机。"""

    lot_size: int = 100
    _signals: list[SignalRecord] = field(default_factory=list)
    _targets: list[TargetPositionRecord] = field(default_factory=list)

    def capture(
        self,
        *,
        signal_datetime: datetime,
        ranked: Iterable[dict[str, Any]],
        target_symbols: Iterable[str],
        current_symbols: Iterable[str],
        regime_weak: bool,
    ) -> None:
        ranked_rows = list(ranked)
        ranked_by_symbol = {str(row.get("etf", "")): row for row in ranked_rows if row.get("etf")}
        target_set = {str(symbol) for symbol in target_symbols}
        current_set = {str(symbol) for symbol in current_symbols}
        symbols = sorted(set(ranked_by_symbol) | target_set | current_set)
        regime = "weak" if regime_weak else "normal"

        for symbol in symbols:
            rank_row = ranked_by_symbol.get(symbol, {})
            score_value = rank_row.get("score")
            score = float(score_value) if score_value is not None else None
            if symbol in target_set:
                direction = SignalDirection.LONG
                reason = f"selected_by_momentum_rank;regime={regime}"
            elif symbol in current_set:
                direction = SignalDirection.EXIT
                reason = f"removed_from_target;regime={regime}"
            else:
                direction = SignalDirection.FLAT
                reason = f"not_selected;regime={regime}"
            self._signals.append(SignalRecord(signal_datetime, symbol, score, direction, reason))

        for symbol in sorted(target_set):
            self._targets.append(
                TargetPositionRecord(
                    signal_datetime,
                    symbol,
                    target_volume=self.lot_size,
                    reason=f"selected_target;regime={regime}",
                ),
            )
        for symbol in sorted(current_set - target_set):
            self._targets.append(
                TargetPositionRecord(
                    signal_datetime,
                    symbol,
                    target_volume=0,
                    reason=f"exit_target;regime={regime}",
                ),
            )

    @property
    def signal_frame(self) -> SignalFrame:
        return SignalFrame.from_records(self._signals)

    @property
    def target_positions(self) -> TargetPosition:
        return TargetPosition.from_records(self._targets)

