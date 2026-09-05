from __future__ import annotations

import unittest
from datetime import datetime

from quant.engine.contracts import SignalDirection
from quant.strategy.adapters.s000001 import S000001OutputCollector


class S000001SignalTargetContractTests(unittest.TestCase):
    def test_ranked_selection_and_exit_become_explicit_contract_records(self) -> None:
        collector = S000001OutputCollector(lot_size=100)
        collector.capture(
            signal_datetime=datetime(2022, 1, 4),
            ranked=[
                {"etf": "510300.SH", "score": 2.5},
                {"etf": "510500.SH", "score": 1.2},
            ],
            target_symbols=["510300.SH"],
            current_symbols=["510500.SH"],
            regime_weak=False,
        )

        signals = {row.symbol: row for row in collector.signal_frame.records}
        targets = {row.symbol: row for row in collector.target_positions.records}
        self.assertEqual(signals["510300.SH"].signal, SignalDirection.LONG)
        self.assertEqual(signals["510500.SH"].signal, SignalDirection.EXIT)
        self.assertEqual(targets["510300.SH"].target_volume, 100)
        self.assertEqual(targets["510500.SH"].target_volume, 0)
        self.assertIn("regime=normal", signals["510300.SH"].reason)


if __name__ == "__main__":
    unittest.main()

