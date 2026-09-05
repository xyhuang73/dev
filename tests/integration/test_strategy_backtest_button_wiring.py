from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class StrategyBacktestButtonWiringTests(unittest.TestCase):
    def test_clicking_strategy_backtest_button_reaches_backtest_entry(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication, QPushButton, QWidget
            from BackTest import backtest_dialog
            from BackTest.backtest_ui import load_backtest_window
            from BackTest.models import BacktestResult
        except (ImportError, OSError) as exc:
            self.skipTest(f"当前解释器无法加载 Qt，GUI 冒烟测试跳过: {exc}")

        app = QApplication.instance() or QApplication([])
        owner = QWidget()
        called = []

        def fake_run(job, *, progress=None):
            called.append(job)
            return BacktestResult(True, "button smoke ok")

        with (
            patch.object(backtest_dialog, "run_backtest", side_effect=fake_run),
            patch.object(backtest_dialog, "ensure_backtest_excel_report", return_value=None),
            patch.object(backtest_dialog, "_restore_report_for_current_selection", return_value=False),
            patch.object(backtest_dialog, "_load_stock_list_to_combo_from_latest_report"),
            patch.object(backtest_dialog, "_render_k_plot"),
        ):
            window = load_backtest_window()
            backtest_dialog.wire_backtest_dialog(window, owner)
            button = window.findChild(QPushButton, "pushButton")
            self.assertIsNotNone(button)
            button.click()
            app.processEvents()

        self.assertEqual(len(called), 1)
        self.assertIn(called[0].strategy_key, {"S000001", "S000002"})
        window.close()
        owner.close()

    def test_event_placeholder_report_preserves_previous_vector_stock_list(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            import pandas as pd
            from PySide6.QtWidgets import QApplication, QComboBox
            from BackTest import backtest_dialog
            from BackTest.backtest_ui import load_backtest_window
        except (ImportError, OSError) as exc:
            self.skipTest(f"当前解释器无法加载 Qt，GUI 冒烟测试跳过: {exc}")

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vector_report = root / "vector.xlsx"
            event_placeholder = root / "event-placeholder.xlsx"
            with pd.ExcelWriter(vector_report, engine="openpyxl") as writer:
                pd.DataFrame(
                    [("strategy_key", "S000001"), ("backtest_mode", "vector")],
                    columns=["key", "value"],
                ).to_excel(writer, sheet_name="回测任务", index=False)
                pd.DataFrame(
                    [{"vt_symbol": "600053.SH", "datetime": "2022-01-05", "action": "BUY", "price": 13.0}],
                ).to_excel(writer, sheet_name="逐笔买卖明细", index=False)
            with pd.ExcelWriter(event_placeholder, engine="openpyxl") as writer:
                pd.DataFrame(
                    [("strategy_key", "S000001"), ("backtest_mode", "event")],
                    columns=["key", "value"],
                ).to_excel(writer, sheet_name="回测任务", index=False)
                pd.DataFrame([{"ok": True}]).to_excel(writer, sheet_name="运行状态", index=False)

            window = load_backtest_window()
            combo = window.findChild(QComboBox, "comboBox_stock_list")
            self.assertIsNotNone(combo)
            self.assertTrue(
                backtest_dialog._load_stock_list_to_combo_from_latest_report(window, None, vector_report),
            )
            self.assertEqual(combo.currentText(), "600053.SH")
            bound_before = getattr(window, "_latest_strategy_excel_path")

            self.assertFalse(
                backtest_dialog._load_stock_list_to_combo_from_latest_report(window, None, event_placeholder),
            )
            self.assertEqual(combo.currentText(), "600053.SH")
            self.assertEqual(getattr(window, "_latest_strategy_excel_path"), bound_before)
            window.close()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
