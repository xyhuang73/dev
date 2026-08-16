#!/usr/bin/env python3
"""Validate live/paper trading configuration safety."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REQUIRED = [
    "stage",
    "environment",
    "strategy_id",
    "secrets_policy.allow_plaintext_in_config",
    "secrets_policy.withdrawal_permission_allowed",
    "limits.max_order_notional",
    "limits.max_daily_loss",
    "alerts.channels",
    "recovery.reconcile_on_startup",
    "recovery.safe_mode_on_mismatch",
]


def get_path(obj: dict, dotted: str):
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def check(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    missing = [key for key in REQUIRED if get_path(cfg, key) in (None, "", [])]
    critical = []

    if get_path(cfg, "stage") == "live" and get_path(cfg, "environment") != "live":
        critical.append("stage is live but environment is not live")
    if get_path(cfg, "secrets_policy.allow_plaintext_in_config") is True:
        critical.append("plaintext secrets are allowed in config")
    if get_path(cfg, "secrets_policy.withdrawal_permission_allowed") is True:
        critical.append("withdrawal permission must be disabled")
    if get_path(cfg, "recovery.allow_new_orders_before_reconcile") is True:
        critical.append("new orders before reconciliation are allowed")

    status = "PASS"
    if missing:
        status = "FAIL"
    if critical:
        status = "BLOCKED"

    return {"status": status, "missing": missing, "critical": critical}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    result = check(args.config)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    sys.exit(main())
