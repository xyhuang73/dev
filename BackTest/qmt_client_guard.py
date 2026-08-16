# -*- coding: utf-8 -*-
"""
因子回测拉取行情前：检测本机 QMT/miniQMT 是否已启动。

说明::
    ``xtdata`` 为国金 miniQMT 附带原生库；在客户端未启动时调用 ``get_stock_list_in_sector`` /
    ``get_market_data`` 等，可能在 C++ 层触发空指针断言（如 Boost ``shared_ptr``），
    Python 无法捕获。此处用 **进程名粗检** 提前拦截并给出明确提示。

检测可被 ``Config/factor_evaluation.json`` 中 ``skip_qmt_process_check`` 关闭（自担风险）。
"""
from __future__ import annotations

import subprocess
import sys

from .factor_evaluation_settings import load_factor_evaluation_json


def _load_guard_config() -> tuple[bool, list[str]]:
    """返回 (是否跳过检测, 进程名子串列表)；配置统一来自 ``factor_evaluation_settings``。"""
    skip = False
    substrings = ["XtMiniQmt", "miniqmt", "XtItClient", "QMT"]
    try:
        data = load_factor_evaluation_json()
        skip = bool(data.get("skip_qmt_process_check"))
        raw = data.get("qmt_process_name_substrings")
        if isinstance(raw, list) and raw:
            substrings = [str(x) for x in raw]
    except (OSError, TypeError, ValueError, KeyError):
        pass
    return skip, substrings


def _windows_tasklist_blob() -> str:
    if sys.platform != "win32":
        return ""
    try:
        # CREATE_NO_WINDOW：避免弹出控制台闪屏
        kw: dict = {}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        cp = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            **kw,
        )
        return (cp.stdout or "") + "\n" + (cp.stderr or "")
    except (OSError, subprocess.TimeoutExpired):
        return ""


def is_likely_qmt_client_running() -> bool:
    """若 tasklist 中命中任一配置子串（大小写不敏感），视为客户端可能已启动。"""
    _, substrings = _load_guard_config()
    blob = _windows_tasklist_blob().lower()
    if not blob.strip():
        return False
    return any(s.lower() in blob for s in substrings)


def require_qmt_client_for_xtdata_datafeed() -> None:
    """
    在调用任何 xtdata 行情接口之前调用。

    Raises:
        RuntimeError: 未检测到典型 QMT 进程且未配置跳过检测时。
    """
    skip, _ = _load_guard_config()
    if skip:
        return
    if sys.platform != "win32":
        # 非 Windows 暂不检，避免误伤；仍可能需客户端
        return
    if is_likely_qmt_client_running():
        return
    raise RuntimeError(
        "未检测到本机 QMT/miniQMT 相关进程（tasklist）。\n"
        "请先启动并登录「国金证券 QMT / miniQMT」客户端，再点击「因子回测」。\n"
        "在客户端未就绪时调用 xtdata 行情接口，可能触发底层 C++ 断言（如 Boost shared_ptr）。\n"
        "若你确认已在特殊环境下运行仍要跳过检测，可在 Config/factor_evaluation.json 设置 "
        '"skip_qmt_process_check": true（自担风险）。'
    )
