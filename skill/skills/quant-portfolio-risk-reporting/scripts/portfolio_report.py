#!/usr/bin/env python3
"""Small dependency-free portfolio report for return series CSV files."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = mean(values)
    return math.sqrt(sum((x - m) ** 2 for x in values) / (len(values) - 1))


def max_drawdown(returns: list[float]) -> dict:
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    trough_idx = 0
    for idx, ret in enumerate(returns):
        equity *= 1.0 + ret
        if equity > peak:
            peak = equity
        dd = equity / peak - 1.0
        if dd < max_dd:
            max_dd = dd
            trough_idx = idx
    return {"max_drawdown": max_dd, "trough_index": trough_idx}


def read_returns(path: Path, date_col: str, return_col: str) -> tuple[list[str], list[float]]:
    dates, returns = [], []
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if row.get(return_col, "") == "":
                continue
            dates.append(row.get(date_col, ""))
            returns.append(float(row[return_col]))
    return dates, returns


def report(path: Path, date_col: str, return_col: str, periods: int) -> dict:
    dates, returns = read_returns(path, date_col, return_col)
    if not returns:
        return {"status": "BLOCKED", "error": "no returns found"}

    total_return = math.prod(1.0 + r for r in returns) - 1.0
    years = len(returns) / periods
    cagr = (1.0 + total_return) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    vol = stdev(returns) * math.sqrt(periods)
    downside = [min(0.0, r) for r in returns]
    downside_vol = stdev(downside) * math.sqrt(periods)
    sharpe = (mean(returns) * periods) / vol if vol else 0.0
    sortino = (mean(returns) * periods) / downside_vol if downside_vol else 0.0
    dd = max_drawdown(returns)
    calmar = cagr / abs(dd["max_drawdown"]) if dd["max_drawdown"] else 0.0

    monthly = defaultdict(float)
    for date, ret in zip(dates, returns):
        month = date[:7] if len(date) >= 7 else "unknown"
        monthly[month] = (1.0 + monthly[month]) * (1.0 + ret) - 1.0

    return {
        "status": "PASS",
        "observations": len(returns),
        "total_return": total_return,
        "cagr": cagr,
        "annualized_volatility": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        **dd,
        "monthly_returns": dict(sorted(monthly.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("returns_csv", type=Path)
    parser.add_argument("--date-col", default="date")
    parser.add_argument("--return-col", default="return")
    parser.add_argument("--periods", type=int, default=252)
    args = parser.parse_args()
    result = report(args.returns_csv, args.date_col, args.return_col, args.periods)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
