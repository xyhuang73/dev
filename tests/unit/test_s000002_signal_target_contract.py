from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from InnerStrategy.slss_strategy_config import load_slss_strategy_config
from quant.engine.contracts import SignalDirection
from quant.strategy.adapters.s000002 import build_s000002_outputs


_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "market_data" / "s000002_cross_section_selection_case.csv"


class S000002SignalTargetContractTests(unittest.TestCase):
    def test_research_short_signal_is_clamped_for_a_share_cash_target(self) -> None:
        panel = pd.read_csv(_FIXTURE)
        cfg = load_slss_strategy_config(
            overrides={
                "decision_mode": "cross_section_rank",
                "cross_section_long_top_n": 1,
                "cross_section_short_min_rank": 3,
                "cross_section_short_bottom_n": 0,
                "a_share_cash_stock_rules": True,
                "fixed_lot": 100,
            },
        )
        signals, targets = build_s000002_outputs(
            panel,
            cfg,
            {"selection_allow_buy": True, "selection_force_sell": False},
        )

        signal_by_symbol = {row.symbol: row for row in signals.records}
        target_by_symbol = {row.symbol: row for row in targets.records}
        self.assertEqual(signal_by_symbol["600001.SH"].signal, SignalDirection.LONG)
        self.assertEqual(signal_by_symbol["600003.SH"].signal, SignalDirection.SHORT)
        self.assertEqual(target_by_symbol["600001.SH"].target_volume, 100)
        self.assertEqual(target_by_symbol["600003.SH"].target_volume, 0)
        self.assertIn("a_share_long_only_short_clamped", target_by_symbol["600003.SH"].reason)

    def test_research_mode_can_retain_short_target_when_cash_rules_are_disabled(self) -> None:
        panel = pd.read_csv(_FIXTURE)
        cfg = load_slss_strategy_config(
            overrides={
                "decision_mode": "cross_section_rank",
                "cross_section_long_top_n": 1,
                "cross_section_short_min_rank": 3,
                "cross_section_short_bottom_n": 0,
                "a_share_cash_stock_rules": False,
                "fixed_lot": 100,
            },
        )
        _, targets = build_s000002_outputs(panel, cfg, {})

        target_by_symbol = {row.symbol: row for row in targets.records}
        self.assertEqual(target_by_symbol["600003.SH"].target_volume, -100)


if __name__ == "__main__":
    unittest.main()

