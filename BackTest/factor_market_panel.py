# -*- coding: utf-8 -*-
"""
通过 xtquant.xtdata 读取本地/缓存日线，组装行情长表（pandas）。

说明（与「是否要连服务器」相关）::
    - **不需要连接远程券商交易服务器** 才能做截面回测逻辑本身。
    - 但 ``xtdata`` 为国金 miniQMT 自带的 **本地原生库**（内含 C++/Boost 等），
      多数用法仍要求 **本机 miniQMT/QMT 客户端已启动并已登录**（或至少进程就绪），
      否则部分接口可能在底层出现空指针类断言（如 Boost ``shared_ptr`` 相关）。
    - 若遇原生库崩溃，请先 **启动并登录 miniQMT** 再跑因子回测；并避免在未就绪时频繁调用 ``get_market_data``。

vnpy Alpha 侧再按需转为 polars；本模块不依赖 polars，避免环境未装 polars 时无法 import。
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from qmt_service import ensure_xtquant_path

from .factor_evaluation_config import is_local_datadir_market_source
from .qmt_client_guard import require_qmt_client_for_xtdata_datafeed


def _yyyymmdd_to_iso(s: str) -> str:
    s = s.strip()
    if len(s) != 8 or not s.isdigit():
        raise ValueError(f"日期须为 YYYYMMDD: {s!r}")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def load_sector_stock_list(max_symbols: int) -> list[str]:
    """从配置板块取股票列表，max_symbols<=0 表示不限制。调用前须已通过 QMT 就绪检测。"""
    cfg: dict[str, Any] = ensure_xtquant_path()
    from xtquant import xtdata  # type: ignore

    if hasattr(xtdata, "enable_hello"):
        xtdata.enable_hello = False  # type: ignore[union-attr]

    sector = str(cfg.get("update_stock_sector") or "沪深A股").strip()
    stock_list = list(xtdata.get_stock_list_in_sector(sector) or [])
    if max_symbols > 0:
        stock_list = stock_list[:max_symbols]
    return stock_list


def _dfdict_to_rows(sym: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    """将单标的 get_market_data 返回的 field→DataFrame 转为行列表。"""
    need = ("open", "high", "low", "close", "volume")
    for k in need:
        if k not in data:
            raise KeyError(f"缺少字段 {k}，现有 {list(data.keys())}")
    c = data["close"]
    if not isinstance(c, pd.DataFrame):
        raise TypeError("close 不是 DataFrame")

    rows: list[dict[str, Any]] = []
    # 情形 A：index=时间，columns 含 sym
    if sym in c.columns:
        time_index = c.index
        for i, ts in enumerate(time_index):
            try:
                o = float(data["open"].iloc[i][sym])
                h = float(data["high"].iloc[i][sym])
                l = float(data["low"].iloc[i][sym])
                cl = float(data["close"].iloc[i][sym])
                v = float(data["volume"].iloc[i][sym])
            except Exception:  # noqa: BLE001
                continue
            if not all(map(lambda x: x == x, [o, h, l, cl, v])):
                continue
            dt = pd.to_datetime(ts).to_pydatetime()
            rows.append(
                {
                    "datetime": dt,
                    "vt_symbol": sym,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": cl,
                    "volume": v,
                }
            )
        return rows

    # 情形 B：仅一列（单标的）
    if c.shape[1] == 1:
        time_index = c.index
        for i, ts in enumerate(time_index):
            try:
                o = float(data["open"].iloc[i, 0])
                h = float(data["high"].iloc[i, 0])
                l = float(data["low"].iloc[i, 0])
                cl = float(data["close"].iloc[i, 0])
                v = float(data["volume"].iloc[i, 0])
            except Exception:  # noqa: BLE001
                continue
            if not all(map(lambda x: x == x, [o, h, l, cl, v])):
                continue
            dt = pd.to_datetime(ts).to_pydatetime()
            rows.append(
                {
                    "datetime": dt,
                    "vt_symbol": sym,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": cl,
                    "volume": v,
                }
            )
        return rows

    raise ValueError(f"无法解析 {sym} 的行情表形状: {c.shape}")


def build_daily_market_panel(
    start_yyyymmdd: str,
    end_yyyymmdd: str,
    max_symbols: int,
    stock_list: list[str] | None = None,
) -> pd.DataFrame:
    """
    逐标的拉取日线并拼接为 pandas 长表（兼容不同 xtdata 返回形状）。

    依赖：已配置 qmt.json 且可 import xtquant；建议先「更新」下载日线。

    若 ``Config/factor_evaluation.json`` 中 ``market_data_source`` 为 ``local_datadir``，
    则仅从本机 ``datadir`` 读取 ``*.DAT``，**不 import xtquant**，避免客户端未启动时原生库断言。

    Args:
        stock_list: 若提供（通常由 ``stock_pool_builder`` 写入 ``stock_pool.json`` 后再读出），
            仅对这些标的拉取行情；为 ``None`` 时仍从板块取列表并按 ``max_symbols`` 截断。
    """
    if is_local_datadir_market_source():
        from .factor_local_datadir_panel import build_daily_market_panel_from_local_datadir

        return build_daily_market_panel_from_local_datadir(
            start_yyyymmdd,
            end_yyyymmdd,
            max_symbols,
            stock_list=stock_list,
        )

    require_qmt_client_for_xtdata_datafeed()
    ensure_xtquant_path()
    from xtquant import xtdata  # type: ignore

    if hasattr(xtdata, "enable_hello"):
        xtdata.enable_hello = False  # type: ignore[union-attr]

    if stock_list is not None:
        syms = list(stock_list)
        if max_symbols > 0:
            syms = syms[:max_symbols]
    else:
        syms = load_sector_stock_list(max_symbols)
    if not syms:
        raise RuntimeError("股票列表为空：请检查板块、max_symbols 或股票池配置")

    field_list = ["open", "high", "low", "close", "volume"]
    all_rows: list[dict[str, Any]] = []
    for sym in syms:
        data = None
        for div in ("front", "none"):
            try:
                data = xtdata.get_market_data(
                    field_list,
                    [sym],
                    period="1d",
                    start_time=start_yyyymmdd,
                    end_time=end_yyyymmdd,
                    count=-1,
                    dividend_type=div,
                    fill_data=True,
                )
                break
            except Exception:  # noqa: BLE001
                data = None
        if data is None:
            continue
        try:
            all_rows.extend(_dfdict_to_rows(sym, data))
        except Exception:  # noqa: BLE001
            continue

    if not all_rows:
        raise RuntimeError(
            "行情长表为空：请确认已下载日线、日期区间有效，或检查 xtdata 是否可用。",
        )
    pdf = pd.DataFrame(all_rows)
    pdf = pdf.sort_values(["vt_symbol", "datetime"]).reset_index(drop=True)
    pdf["vwap"] = (pdf["high"] + pdf["low"] + pdf["close"]) / 3.0
    return pdf


def iso_period_triple(start_yyyymmdd: str, end_yyyymmdd: str) -> tuple[tuple[str, str], tuple[str, str], tuple[str, str]]:
    """train / valid / test 三段区间（与界面起止日期一致）。"""
    a = _yyyymmdd_to_iso(start_yyyymmdd)
    b = _yyyymmdd_to_iso(end_yyyymmdd)
    tp = (a, b)
    return tp, tp, tp
