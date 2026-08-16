# -*- coding: utf-8 -*-
"""
miniQMT 账户资金查询：经 XtQuantTrader 读取资产（需客户端已启动并登录）。

CLI：``python scripts/check_account_quota.py``
"""
from __future__ import annotations

import json
import random
from typing import Any

from qmt_service import ensure_xtquant_path, get_userdata_mini_dir

ASSET_HIGHLIGHT_KEYS = (
    "cash",
    "frozen_cash",
    "market_value",
    "total_asset",
    "fetch_balance",
    "enable_balance",
    "asset_balance",
    "current_balance",
    "avl_balance",
)

_ACCOUNT_ID_KEYS = ("account_id", "accountId", "m_strAccountID", "fund_account")


def xt_object_to_dict(obj: Any) -> dict[str, Any]:
    """将 XtAsset / 账号信息对象转为可序列化字典。"""
    if obj is None:
        return {}
    out: dict[str, Any] = {}
    for name in dir(obj):
        if name.startswith("_"):
            continue
        try:
            val = getattr(obj, name)
        except Exception:
            continue
        if not callable(val):
            out[name] = val
    return out


def _account_ids_from_infos(infos: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for info in infos:
        for key in _ACCOUNT_ID_KEYS:
            value = info.get(key)
            if value:
                ids.append(str(value))
                break
    return ids


def _query_account_infos(trader: Any) -> list[dict[str, Any]]:
    fn = getattr(trader, "query_account_infos", None)
    if not callable(fn):
        return []
    try:
        raw = fn() or []
    except Exception:
        return []
    return [item if isinstance(item, dict) else xt_object_to_dict(item) for item in raw]


def resolve_account_ids(trader: Any, cfg: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    """合并 query_account_infos 与 Config 中的 account_id。"""
    infos = _query_account_infos(trader)
    ids = _account_ids_from_infos(infos)
    cfg_account_id = str(cfg.get("account_id") or "").strip()
    if cfg_account_id and cfg_account_id not in ids:
        ids.insert(0, cfg_account_id)
    return ids, infos


def build_account_quota_report(*, check_process: bool = True) -> str:
    """
    连接交易端并生成账户资金文本报告。

    Raises:
        FileNotFoundError: userdata_mini 不存在
        RuntimeError: 连接失败或无可用资金账号
    """
    from BackTest.qmt_client_guard import is_likely_qmt_client_running

    cfg = ensure_xtquant_path()
    ud = get_userdata_mini_dir(cfg)
    lines: list[str] = [
        f"userdata_mini: {ud}",
        f"目录存在: {ud.is_dir()}",
    ]
    if check_process:
        lines.append(f"QMT 进程可能已启动: {is_likely_qmt_client_running()}")

    if not ud.is_dir():
        raise FileNotFoundError("userdata_mini 目录不存在，请检查 Config/qmt.json 中 qmt_install_path。")

    from xtquant.xttrader import XtQuantTrader  # type: ignore
    from xtquant.xttype import StockAccount  # type: ignore

    trader = XtQuantTrader(str(ud), random.randint(100_000, 999_999))
    trader.start()
    try:
        ret = trader.connect()
        lines.append(f"connect 返回值: {ret}（0 通常表示成功）")
        if ret != 0:
            raise RuntimeError("无法连接交易端。请先启动并登录 miniQMT / 国金 QMT 客户端。")

        account_ids, infos = resolve_account_ids(trader, cfg)
        if infos:
            lines.extend(["", "账号列表:", json.dumps(infos, ensure_ascii=False, indent=2, default=str)])
        if not account_ids:
            raise RuntimeError(
                '未获取到资金账号。请在 miniQMT 中登录，或在 Config/qmt.json 设置 "account_id"。'
            )

        for account_id in account_ids:
            lines.append(f"\n──────── 账户 {account_id} ────────")
            try:
                account = StockAccount(account_id, "STOCK")
            except TypeError:
                account = StockAccount(account_id)
            sub = trader.subscribe(account)
            lines.append(f"subscribe 返回值: {sub}")
            asset = trader.query_stock_asset(account)
            if asset is None:
                lines.append("query_stock_asset 返回 None（账号未订阅或尚未登录）")
                continue
            asset_dict = xt_object_to_dict(asset)
            lines.append(json.dumps(asset_dict, ensure_ascii=False, indent=2, default=str))
            highlighted = [f"  {key}: {asset_dict[key]}" for key in ASSET_HIGHLIGHT_KEYS if key in asset_dict]
            if highlighted:
                lines.append("── 常用字段 ──")
                lines.extend(highlighted)
    finally:
        try:
            trader.stop()
        except Exception:
            pass

    lines.append("\n查询完成。")
    return "\n".join(lines)
