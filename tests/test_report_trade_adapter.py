from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys
import types

import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]
if "BackTest" not in sys.modules:
    package = types.ModuleType("BackTest")
    package.__path__ = [str(_ROOT / "BackTest")]
    sys.modules["BackTest"] = package

from BackTest.report_trade_adapter import load_trade_markers, normalize_trade_action


class ReportTradeAdapterTests(unittest.TestCase):
    def test_normalize_trade_action_accepts_english_and_chinese(self) -> None:
        self.assertEqual(normalize_trade_action("buy"), "BUY")
        self.assertEqual(normalize_trade_action("买入开仓"), "BUY")
        self.assertEqual(normalize_trade_action("SELL"), "SELL")
        self.assertEqual(normalize_trade_action("卖出平仓"), "SELL")
        self.assertIsNone(normalize_trade_action("hold"))

    def test_load_trade_markers_filters_symbol_and_invalid_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "report.xlsx"
            trades = pd.DataFrame([
                {"vt_symbol": "600053.SH", "datetime": "2022-02-15 13:10", "action": "buy", "price": 21.42},
                {"vt_symbol": "600053.SH", "datetime": "2022-02-16", "action": "卖出", "price": 20.23},
                {"vt_symbol": "600053.SH", "datetime": "2022-02-17", "action": "hold", "price": 20.50},
                {"vt_symbol": "600012.SH", "datetime": "2022-02-15", "action": "buy", "price": 8.05},
            ])
            trades.to_excel(report, sheet_name="逐笔买卖明细", index=False)

            markers = load_trade_markers(report, "600053.SH")

        self.assertEqual(markers["action"].tolist(), ["BUY", "SELL"])
        self.assertEqual(markers["action_raw"].tolist(), ["buy", "卖出"])
        self.assertTrue((markers["datetime"].dt.hour == 0).all())


if __name__ == "__main__":
    unittest.main()
