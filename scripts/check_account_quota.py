# -*- coding: utf-8 -*-
"""查询 miniQMT 当前账户资金。实现见仓库根目录 ``qmt_account``。"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from qmt_account import build_account_quota_report  # noqa: E402


def main() -> int:
    try:
        print(build_account_quota_report())
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"错误: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
