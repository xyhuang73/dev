from __future__ import annotations

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

from BackTest.qixingaozhao_backtest_runner import _attach_benchmark_nav, _run_daily_simulation
from quant.engine.contracts import SignalDirection
from quant.strategy.adapters.s000001 import S000001OutputCollector


class _AlwaysLongStrategy:
    def __init__(self) -> None:
        self.params = {
            "lookback_days": 1,
            "holdings_num": 1,
            "weak_period_ma_lookback": 1,
            "weak_period_max_days": 20,
            "enable_regime_switch": False,
            "enable_profit_protection": False,
            "profit_protection_lookback": 1,
            "profit_protection_threshold": 0.05,
            "enable_avoid_a_share": False,
            "enable_volume_check": False,
            "buy_ma_window": 1,
            "sell_ma_window": 2,
            "sell_upper_ratio": 10.0,
            "sell_lower_ratio": 0.1,
            "sell_upper_enabled": False,
            "sell_lower_enabled": False,
            "sell_priority": "lower_first",
            "sell_trigger_mode": "tp_sl",
        }

    def get_universe(self) -> list[str]:
        return ["600000.SH"]

    def get_active_pool(self, _is_weak: bool) -> list[str]:
        return self.get_universe()

    def select_targets(self, _pool, _closes, _volumes, today_prices, _today_volumes):
        selected = ["600000.SH"] if "600000.SH" in today_prices else []
        return [], selected

    def compute_sell_levels(self, _code, _closes):
        return None, None

    def decide_sell_action(self, *_args):
        return None, None


class QixingaozhaoSimulationTests(unittest.TestCase):
    def test_missing_index_uses_equal_weight_stock_pool_benchmark(self) -> None:
        dates = pd.to_datetime(["2022-01-03", "2022-01-04"])
        equity = pd.DataFrame({"datetime": dates, "unit_nav": [1.0, 1.1]})
        panel = pd.DataFrame(
            [
                {"datetime": dates[0], "vt_symbol": "600001.SH", "close": 10.0},
                {"datetime": dates[1], "vt_symbol": "600001.SH", "close": 11.0},
                {"datetime": dates[0], "vt_symbol": "600002.SH", "close": 20.0},
                {"datetime": dates[1], "vt_symbol": "600002.SH", "close": 22.0},
            ]
        )

        result, benchmark_name = _attach_benchmark_nav(equity, panel, ["600001.SH", "600002.SH"])

        self.assertEqual(benchmark_name, "本次股票池等权基准")
        self.assertAlmostEqual(float(result.iloc[-1]["benchmark_nav"]), 1.1)
        self.assertAlmostEqual(float(result.iloc[-1]["excess_nav"]), 1.0)

    def test_close_signal_executes_at_next_open_and_marks_to_market(self) -> None:
        dates = [pd.Timestamp("2022-01-03"), pd.Timestamp("2022-01-04"), pd.Timestamp("2022-01-05")]
        etf_data = {
            "600000.SH": {
                "dates": dates,
                "opens": [10.0, 11.0, 13.0],
                "highs": [10.5, 12.5, 14.5],
                "lows": [9.5, 10.5, 12.5],
                "closes": [10.0, 12.0, 14.0],
                "volumes": [1000.0, 1000.0, 1000.0],
            }
        }

        collector = S000001OutputCollector()
        trades, _rounds, _per_symbol, equity, positions, portfolio = _run_daily_simulation(
            _AlwaysLongStrategy(), etf_data, {}, dates, 10000.0, None,
            output_collector=collector,
        )

        self.assertEqual(len(trades), 1)
        trade = trades.iloc[0]
        self.assertEqual(pd.Timestamp(trade["signal_datetime"]), pd.Timestamp("2022-01-04"))
        self.assertEqual(pd.Timestamp(trade["datetime"]), pd.Timestamp("2022-01-05"))
        self.assertEqual(float(trade["price"]), 13.0)
        self.assertEqual(trade["execution_basis"], "next_open")
        self.assertAlmostEqual(float(equity.iloc[-1]["total_asset"]), 10100.0)
        self.assertAlmostEqual(float(equity.iloc[-1]["unit_nav"]), 1.01)
        self.assertAlmostEqual(float(portfolio["ending_unrealized_pnl"]), 100.0)
        self.assertAlmostEqual(float(portfolio["simple_return_vs_initial_capital"]), 0.01)
        self.assertEqual(int(positions.iloc[-1]["available"]), 0)
        self.assertEqual(collector.signal_frame.records[-1].signal, SignalDirection.LONG)
        self.assertEqual(collector.target_positions.records[-1].target_volume, 100)
        self.assertEqual(collector.target_positions.records[-1].datetime.date().isoformat(), "2022-01-05")


if __name__ == "__main__":
    unittest.main()
