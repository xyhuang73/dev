#!/usr/bin/env python3
"""Validate a quant experiment manifest.

Usage:
  python3 validate_manifest.py experiment_manifest.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REQUIRED_PATHS = [
    "experiment_id",
    "hypothesis.summary",
    "hypothesis.asset_universe",
    "hypothesis.decision_time",
    "hypothesis.execution_time",
    "data.snapshot_id",
    "data.path",
    "data.pit_policy",
    "code.commit",
    "code.entrypoints.prepare_data",
    "code.entrypoints.train",
    "code.entrypoints.backtest",
    "config.path",
    "config.random_seed",
    "backtest.fee_model",
    "backtest.slippage_model",
    "backtest.fill_rule",
    "results.metrics_path",
    "results.orders_path",
    "results.positions_path",
    "promotion_gate.stage",
    "promotion_gate.verdict",
]

VALID_VERDICTS = {"PASS", "WARN", "FAIL", "BLOCKED"}


def get_path(obj: dict, dotted: str):
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def is_blank(value) -> bool:
    return value is None or value == "" or value == [] or value == {}


def validate(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [key for key in REQUIRED_PATHS if is_blank(get_path(data, key))]
    warnings = []

    verdict = get_path(data, "promotion_gate.verdict")
    if verdict and verdict not in VALID_VERDICTS:
        warnings.append(f"promotion_gate.verdict should be one of {sorted(VALID_VERDICTS)}")

    fill_rule = str(get_path(data, "backtest.fill_rule") or "").lower()
    if "same" in fill_rule:
        warnings.append("same-bar fill rule requires tick/quote evidence and should be reviewed")

    pit_policy = str(get_path(data, "data.pit_policy") or "").lower()
    if "available_time" not in pit_policy and "pit" not in pit_policy:
        warnings.append("data.pit_policy does not explicitly mention available_time or PIT")

    status = "PASS" if not missing and not warnings else "WARN"
    if missing:
        status = "FAIL"

    return {
        "manifest": str(path),
        "status": status,
        "missing_required_fields": missing,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()

    try:
        result = validate(args.manifest)
    except Exception as exc:  # pragma: no cover - command-line guard
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, indent=2))
        return 2

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    sys.exit(main())
