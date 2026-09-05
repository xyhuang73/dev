from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from quant.report.performance import (
    build_nav_comparison,
    calculate_symbol_performance,
    load_performance_summary,
)


class PerformanceSummaryAndBenchmarkNavTests(unittest.TestCase):
    def test_loads_six_header_metrics_and_derives_annualized_return(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "report.xlsx"
            stats = pd.DataFrame(
                [
                    ("simple_return_vs_initial_capital", 0.10),
                    ("max_drawdown", 0.08),
                    ("annualized_sharpe", 1.25),
                    ("all_round_trips_win_rate", 0.60),
                    ("total_round_trips", 2),
                ],
                columns=["key", "value"],
            )
            equity = pd.DataFrame(
                {
                    "datetime": pd.date_range("2022-01-03", periods=4, freq="B"),
                    "unit_nav": [1.0, 1.02, 1.05, 1.10],
                    "drawdown": [0.0, 0.0, 0.0, 0.0],
                }
            )
            with pd.ExcelWriter(report) as writer:
                stats.to_excel(writer, sheet_name="组合级统计", index=False)
                equity.to_excel(writer, sheet_name="净值明细", index=False)

            summary = load_performance_summary(report)

        self.assertIsNotNone(summary)
        self.assertAlmostEqual(summary.total_return, 0.10)
        self.assertAlmostEqual(summary.max_drawdown, 0.08)
        self.assertAlmostEqual(summary.sharpe_ratio, 1.25)
        self.assertAlmostEqual(summary.win_rate, 0.60)
        self.assertAlmostEqual(summary.trade_success_rate, 0.50)
        self.assertEqual(summary.trade_days, 4)
        self.assertIsNotNone(summary.annualized_return)

    def test_builds_strategy_benchmark_and_relative_excess_nav(self) -> None:
        dates = pd.to_datetime(["2022-01-03", "2022-01-04", "2022-01-05"])
        strategy = pd.DataFrame({"datetime": dates, "unit_nav": [1.0, 1.1, 1.2]})
        benchmark = pd.DataFrame({"datetime": dates, "close": [100.0, 105.0, 110.0]})

        comparison = build_nav_comparison(strategy, benchmark)

        self.assertEqual(comparison.columns.tolist(), ["datetime", "strategy_nav", "benchmark_nav", "excess_nav"])
        self.assertAlmostEqual(comparison.iloc[-1]["strategy_nav"], 1.2)
        self.assertAlmostEqual(comparison.iloc[-1]["benchmark_nav"], 1.1)
        self.assertAlmostEqual(comparison.iloc[-1]["excess_nav"], 1.2 / 1.1)

    def test_uses_benchmark_nav_embedded_in_report_without_market_bars(self) -> None:
        strategy = pd.DataFrame(
            {
                "datetime": pd.to_datetime(["2022-01-03", "2022-01-04"]),
                "unit_nav": [1.0, 1.1],
                "benchmark_nav": [1.0, 1.05],
                "excess_nav": [1.0, 1.1 / 1.05],
            }
        )

        comparison = build_nav_comparison(strategy, pd.DataFrame())

        self.assertAlmostEqual(comparison.iloc[-1]["benchmark_nav"], 1.05)
        self.assertAlmostEqual(comparison.iloc[-1]["excess_nav"], 1.1 / 1.05)

    def test_calculates_closed_symbol_round_trip_metrics(self) -> None:
        bars = pd.DataFrame(
            {
                "datetime": pd.to_datetime(["2022-01-03", "2022-01-04", "2022-01-05", "2022-01-06"]),
                "close": [10.0, 11.0, 9.0, 12.0],
            }
        )
        markers = pd.DataFrame(
            {
                "datetime": pd.to_datetime(["2022-01-03", "2022-01-05"]),
                "action": ["BUY", "SELL"],
                "price": [10.0, 9.0],
            }
        )

        summary = calculate_symbol_performance(bars, markers)

        self.assertAlmostEqual(summary.total_return, -0.10)
        self.assertAlmostEqual(summary.max_drawdown, 2.0 / 11.0)
        self.assertEqual(summary.total_round_trips, 1)
        self.assertAlmostEqual(summary.win_rate, 0.0)
        self.assertAlmostEqual(summary.trade_success_rate, 0.25)
        self.assertEqual(summary.equity["unit_nav"].tolist(), [1.0, 1.1, 0.9, 0.9])

    def test_marks_open_symbol_position_to_last_close(self) -> None:
        bars = pd.DataFrame(
            {
                "datetime": pd.to_datetime(["2022-01-03", "2022-01-04", "2022-01-05"]),
                "close": [10.0, 11.0, 12.0],
            }
        )
        markers = pd.DataFrame(
            {
                "datetime": pd.to_datetime(["2022-01-03"]),
                "action": ["BUY"],
                "price": [10.0],
            }
        )

        summary = calculate_symbol_performance(bars, markers)

        self.assertAlmostEqual(summary.total_return, 0.20)
        self.assertEqual(summary.total_round_trips, 0)
        self.assertIsNone(summary.win_rate)
        self.assertAlmostEqual(summary.trade_success_rate, 0.0)
        self.assertIsNotNone(summary.sharpe_ratio)


if __name__ == "__main__":
    unittest.main()
