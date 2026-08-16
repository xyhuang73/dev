#!/usr/bin/env python3
"""Audit a CSV for basic point-in-time data risks using only stdlib."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


def parse_time(value: str):
    if value is None or value == "":
        return None
    value = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def audit(path: Path, symbol_col: str, time_col: str, available_col: str | None, decision_col: str | None) -> dict:
    duplicate_keys = Counter()
    missing = Counter()
    parse_errors = Counter()
    non_monotonic = defaultdict(int)
    last_time_by_symbol = {}
    pit_violations = []
    rows = 0

    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        required = [symbol_col, time_col]
        if available_col:
            required.append(available_col)
        absent = [col for col in required if col not in fields]
        if absent:
            return {"status": "BLOCKED", "error": f"missing columns: {absent}", "fields": fields}

        for row in reader:
            rows += 1
            symbol = row.get(symbol_col, "")
            event_time = parse_time(row.get(time_col, ""))
            available_time = parse_time(row.get(available_col, "")) if available_col else None
            decision_time = parse_time(row.get(decision_col, "")) if decision_col else None

            for col, value in row.items():
                if value == "":
                    missing[col] += 1

            if event_time is None:
                parse_errors[time_col] += 1
            if available_col and available_time is None:
                parse_errors[available_col] += 1
            if decision_col and decision_time is None:
                parse_errors[decision_col] += 1

            key = (symbol, row.get(time_col, ""))
            duplicate_keys[key] += 1

            if symbol and event_time:
                prev = last_time_by_symbol.get(symbol)
                if prev and event_time < prev:
                    non_monotonic[symbol] += 1
                last_time_by_symbol[symbol] = event_time

            if event_time and available_time and available_time < event_time:
                pit_violations.append({"row": rows, "reason": "available_time_before_event_time"})
            if available_time and decision_time and available_time > decision_time:
                pit_violations.append({"row": rows, "reason": "available_after_decision_time"})

    duplicates = sum(count - 1 for count in duplicate_keys.values() if count > 1)
    status = "PASS"
    if parse_errors or pit_violations or duplicates:
        status = "FAIL"
    elif missing or non_monotonic:
        status = "WARN"

    return {
        "status": status,
        "rows": rows,
        "duplicate_key_count": duplicates,
        "missing_counts": dict(missing.most_common(20)),
        "parse_errors": dict(parse_errors),
        "non_monotonic_symbols": dict(list(non_monotonic.items())[:20]),
        "pit_violations_sample": pit_violations[:20],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--symbol-col", default="symbol")
    parser.add_argument("--time-col", default="event_time")
    parser.add_argument("--available-col", default="available_time")
    parser.add_argument("--decision-col", default=None)
    args = parser.parse_args()

    result = audit(args.csv_path, args.symbol_col, args.time_col, args.available_col, args.decision_col)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    sys.exit(main())
