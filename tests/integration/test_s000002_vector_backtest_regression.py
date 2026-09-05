from __future__ import annotations

import unittest
from unittest.mock import patch

from BackTest.models import BacktestJobConfig, BacktestResult
from BackTest.runner import run_backtest


class S000002VectorBacktestRegressionTests(unittest.TestCase):
    def test_gui_compatible_job_reaches_registered_s000002_runner(self) -> None:
        captured = {}

        def fake_runner(job, *, progress=None):
            captured["job"] = job
            return BacktestResult(True, "S000002 runner reached", "fake.xlsx")

        job = BacktestJobConfig(10_000.0, "20220101", "20221230", "F000001", "S000002", "vector")
        with patch("quant.strategy.spec.StrategySpec.load_vector_runner", return_value=fake_runner):
            result = run_backtest(job)

        self.assertTrue(result.ok)
        self.assertEqual(captured["job"].strategy_key, "S000002")
        self.assertEqual(captured["job"].strategy_params, {})
        self.assertIn("decision_mode", captured["job"].resolved_strategy_params)
        self.assertTrue(captured["job"].run_id.startswith("BT-"))


if __name__ == "__main__":
    unittest.main()
