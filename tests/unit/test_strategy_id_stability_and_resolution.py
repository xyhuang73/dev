from __future__ import annotations

import unittest
from unittest.mock import patch

from InnerStrategy.inner_registry import build_registry_dict
from quant.strategy.registry import get_strategy_spec, list_strategy_specs


class StrategyIdStabilityAndResolutionTests(unittest.TestCase):
    def test_official_strategy_ids_are_explicit_and_stable(self) -> None:
        specs = list_strategy_specs()
        self.assertEqual([spec.strategy_id for spec in specs], ["S000001", "S000002"])
        self.assertEqual(get_strategy_spec("S000001").class_name, "QixingaozhaoEtfRotationStrategy")
        self.assertEqual(get_strategy_spec("S000002").class_name, "StratifiedLongShortSharpeEqualWeightStrategy")

    def test_registry_build_does_not_number_strategies_from_file_scan(self) -> None:
        with patch("InnerStrategy.inner_registry._parse_strategy_classes", side_effect=AssertionError("不应扫描策略类编号")):
            registry = build_registry_dict()

        self.assertEqual([row["id"] for row in registry["strategies"]], ["S000001", "S000002"])

    def test_parameter_schema_rejects_unknown_parameters(self) -> None:
        schema = get_strategy_spec("S000001").parameter_schema
        with self.assertRaisesRegex(ValueError, "未知策略参数"):
            schema.validate({"unknown_switch": True})


if __name__ == "__main__":
    unittest.main()

