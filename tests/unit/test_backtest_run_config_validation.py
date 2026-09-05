from __future__ import annotations

import unittest

from BackTest.adapters.job_config_adapter import job_to_run_config
from BackTest.models import BacktestJobConfig


def _job(**changes):
    values = {
        "initial_capital": 10_000.0,
        "start_date": "20220101",
        "end_date": "20221230",
        "factor_key": "F000001",
        "strategy_key": "S000001",
        "backtest_mode": "vector",
    }
    values.update(changes)
    return BacktestJobConfig(**values)


class BacktestRunConfigValidationTests(unittest.TestCase):
    def test_legacy_gui_job_becomes_complete_run_config(self) -> None:
        config = job_to_run_config(_job(strategy_params={"lookback_days": 30}))

        self.assertEqual(config.strategy_id, "S000001")
        self.assertEqual(config.strategy_version, "1.0.0")
        self.assertEqual(config.strategy_params["lookback_days"], 30)
        self.assertIn("holdings_num", config.strategy_params)
        self.assertTrue(config.run_id.startswith("BT-"))

    def test_invalid_date_range_is_rejected_before_engine_runs(self) -> None:
        with self.assertRaisesRegex(ValueError, "start_date"):
            job_to_run_config(_job(start_date="20230101", end_date="20220101"))

    def test_out_of_range_strategy_parameter_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "holdings_num"):
            job_to_run_config(_job(strategy_params={"holdings_num": 0}))


if __name__ == "__main__":
    unittest.main()

