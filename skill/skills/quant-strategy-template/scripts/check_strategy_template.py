#!/usr/bin/env python3
"""Static checks for a portable quant strategy template."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path


REQUIRED_METHODS = {"initialize", "on_data", "generate_signal", "build_target", "risk_check", "on_order_update"}
ORDER_CALL_NAMES = {"buy", "sell", "submit_order", "market_order", "limit_order", "place_order"}


class StrategyVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.methods = set()
        self.signal_order_calls = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.methods.add(node.name)
        if node.name == "generate_signal":
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    name = ""
                    if isinstance(child.func, ast.Name):
                        name = child.func.id
                    elif isinstance(child.func, ast.Attribute):
                        name = child.func.attr
                    if name in ORDER_CALL_NAMES:
                        self.signal_order_calls.append({"line": child.lineno, "call": name})
        self.generic_visit(node)


def check(path: Path) -> dict:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    visitor = StrategyVisitor()
    visitor.visit(tree)
    missing = sorted(REQUIRED_METHODS - visitor.methods)
    status = "PASS"
    if missing or visitor.signal_order_calls:
        status = "FAIL"
    return {
        "status": status,
        "missing_methods": missing,
        "order_calls_inside_generate_signal": visitor.signal_order_calls,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("strategy_file", type=Path)
    args = parser.parse_args()
    result = check(args.strategy_file)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
