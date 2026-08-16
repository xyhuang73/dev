# -*- coding: utf-8 -*-
"""
因子评估用股票池：按代码规则与（可选）xtdata 合约详情做「第一步」剔除。

设计说明::
    - 本模块 **不依赖** pandas / PySide；纯函数与字符串规则可单测；
    - B 股等可用代码段判定；ST / 退市等优先读 ``xtdata.get_instrument_detail`` 返回的简称字段；
    - 不同 miniQMT 版本字段名可能略有差异，解析处做了多键名兜底；
    - 未拿到详情时（例如仅本地 dat、不启动客户端），ST/退市类规则可自动跳过并交由调用方记入统计。
"""
from __future__ import annotations

import re
from typing import Any


def split_vt_symbol(vt: str) -> tuple[str, str]:
    """
    将 ``600000.SH`` 拆成 ``('600000', 'SH')``；无点时视为无市场后缀。
    """
    s = (vt or "").strip()
    if "." not in s:
        return s.upper(), ""
    code, mkt = s.rsplit(".", 1)
    return code.strip().upper(), mkt.strip().upper()


def is_b_share(vt: str) -> bool:
    """
    沪深 B 股常见代码段（不依赖行情接口）::

        - 沪市 B：900xxx.SH
        - 深市 B：200xxx.SZ
    """
    code, mkt = split_vt_symbol(vt)
    if mkt == "SH" and code.startswith("900"):
        return True
    if mkt == "SZ" and code.startswith("200"):
        return True
    return False


def _normalize_instrument_name(name: str) -> str:
    """去空白，便于简称规则匹配。"""
    return (name or "").strip()


def instrument_name_suggests_st(name: str) -> bool:
    """
    依据证券简称判断是否为风险警示（*ST / ST / S*ST 等）。

    说明::
        - 科创板等简称中可能含其它字母组合，此处采用前缀与常见片段，降低误杀；
        - 若接口简称不规范，仍可能漏判或误判，以交易所规则为准。
    """
    s = _normalize_instrument_name(name)
    if not s:
        return False
    # 典型：*STxxx、STxxx、S*STxxx（沪深风险警示）
    if s.startswith("*ST") or s.startswith("S*ST") or s.startswith("ST"):
        return True
    # 少数客户端返回英文 ST 开头
    if re.match(r"^ST[\s\*]", s, re.IGNORECASE):
        return True
    return False


def instrument_name_suggests_delisting_board(name: str) -> bool:
    """
    依据简称识别「退市整理」等极端情形（启发式）。

    若详情接口已给出更可靠状态，应优先用 ``detail_suggests_delisted``。
    """
    s = _normalize_instrument_name(name)
    if not s:
        return False
    if "退市" in s and ("整理" in s or "期" in s):
        return True
    return False


def _detail_str(d: dict[str, Any], keys: tuple[str, ...]) -> str:
    """多键名兜底读取字符串字段。"""
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def detail_suggests_delisted(detail: dict[str, Any] | None) -> bool:
    """
    根据合约详情判断是否已终止上市或不可交易（字段依客户端版本而异，尽力而为）。

    若无法识别，返回 False（不剔除），避免误伤。
    """
    if not detail:
        return False
    name = _detail_str(
        detail,
        ("InstrumentName", "InstrumentNameStr", "instrument_name", "name"),
    )
    if instrument_name_suggests_delisting_board(name):
        return True
    # 部分版本用文本状态；不明确则不误判
    st = str(detail.get("ListState") or detail.get("listingState") or "").strip()
    if st and any(x in st for x in ("终止", "退市", "摘牌")):
        return True
    return False


def should_keep_for_factor_pool(
    vt: str,
    detail: dict[str, Any] | None,
    *,
    exclude_b_shares: bool,
    exclude_st_by_name: bool,
    exclude_delisted_meta: bool,
) -> tuple[bool, str]:
    """
    综合判断是否纳入因子评估股票池。

    Returns:
        (是否保留, 原因标签)；原因用于 ``stock_pool`` 构建统计。

    当 ``detail is None`` 且需要 ST/退市判断时，若无法判断则 **保留** 并返回
    ``keep_no_detail``，由上层统计「未校验 ST」数量。
    """
    if exclude_b_shares and is_b_share(vt):
        return False, "drop_b_share"

    need_text = exclude_st_by_name or exclude_delisted_meta
    if not need_text:
        return True, "keep"

    if detail is None:
        return True, "keep_no_detail"

    name = _detail_str(
        detail,
        ("InstrumentName", "InstrumentNameStr", "instrument_name", "name"),
    )
    if exclude_st_by_name and instrument_name_suggests_st(name):
        return False, "drop_st"
    if exclude_delisted_meta and detail_suggests_delisted(detail):
        return False, "drop_delisted"
    if exclude_delisted_meta and instrument_name_suggests_delisting_board(name):
        return False, "drop_delisted_name"

    return True, "keep"


def fetch_xt_instrument_detail(vt: str) -> dict[str, Any] | None:
    """
    调用 ``xtdata.get_instrument_detail``；失败或返回类型异常时返回 None。

    说明：仅在已能安全 import ``xtquant`` 的场景调用（例如已做过 QMT 进程检测）。
    """
    try:
        from xtquant import xtdata  # type: ignore

        raw: Any = xtdata.get_instrument_detail(vt)
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, (list, tuple)) and raw:
            first = raw[0]
            if isinstance(first, dict):
                return first
    except Exception:  # noqa: BLE001 — 接口或环境问题，退回无详情
        return None
    return None
