# -*- coding: utf-8 -*-
"""
从 miniQMT 已下载的本地日线 ``*.DAT`` 组装 pandas 行情长表，**不 import xtquant**。

根本原因说明::
    ``xtquant.xtdata`` 为 C++/Boost 原生扩展；即便数据已在 ``userdata_mini/datadir``，
    调用 ``get_market_data`` / ``get_stock_list_in_sector`` 等仍会经过同一套运行时，
    在客户端未就绪时可能对空 ``shared_ptr`` 断言（Python 无法捕获）。
    本模块仅做二进制读取，与客户端进程解耦；需事先用 miniQMT「下载」或同步过日线文件。

    **miniQMT 86400 日线 .DAT（已实测多标的）**：文件头 8 字节固定魔数，之后每条 K 线 **64 字节**；
    时间戳后紧跟 **4×int32 的 OHLC**，价位为 **实际价格×1000**（千分之一元精度），**不是 float32**。
    若误按 ``<fffff>`` 解析，会把整数价位当成 IEEE754 尾数，从而出现 Excel 中 **1e-9 级极小价**、
    **与成交量同量级的大整数误当收盘价** 等现象；策略回测路径上 ``attach_base_ohlcv`` 也无法纠正，
    因源面板本身已错。
"""
from __future__ import annotations

import struct
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from qmt_service import get_local_datadir, load_config

from .stock_pool_universe_filter import split_vt_symbol


def resolve_daily_dat_file(datadir: Path, period_name: str, vt: str) -> Path | None:
    """
    将 ``600000.SH`` 解析为 ``datadir/SH/{period}/600000.DAT``（兼容大小写目录名）。
    """
    code, mkt = split_vt_symbol(vt)
    if not mkt:
        return None
    for folder in (mkt, mkt.lower()):
        direct = datadir / folder / period_name / f"{code}.DAT"
        if direct.is_file():
            return direct
    # 兜底：目录层级与约定不一致时按文件名 + 市场文件夹匹配
    for fp in datadir.glob(f"**/{period_name}/{code}.DAT"):
        if str(fp.parent.parent.name).upper() == mkt:
            return fp
    return None


def list_daily_dat_files_for_symbols(
    datadir: Path,
    period_name: str,
    symbols: list[str],
) -> list[tuple[Path, str]]:
    """
    按 ``symbols`` 顺序解析本地日线文件；不存在的标的跳过（返回列表可能短于输入）。
    """
    out: list[tuple[Path, str]] = []
    for vt in symbols:
        fp = resolve_daily_dat_file(datadir, period_name, vt)
        if fp is not None:
            out.append((fp, vt))
    return out


def _shanghai_dt_from_ts(ts: int) -> datetime:
    """将 K 线时间戳（秒或毫秒）转为 naive datetime（按本地习惯用于与界面日期比较）。"""
    # 毫秒时间戳（字段偶发为 ms）
    if ts > 10_000_000_000:
        ts = int(ts // 1000)
    return datetime.fromtimestamp(ts)


def _fingerprint_daily_unix(u: int) -> bool:
    """
    与 ``qmt_service._quarters_from_dat_bytes`` 一致：日线样本中 uint32 时间戳指纹。

    用于在二进制流中定位「可能是 bar 起点」的偏移，再推断 stride。
    """
    return 946684800 <= u <= 2_100_000_000 and (u % 86400) == 57600


def _fingerprint_daily_unix_loose(u: int) -> bool:
    """
    宽松时间戳：仅 unix 秒落在常见范围（新版客户端可能不再满足 ``% 86400 == 57600`` 的旧约定）。
    """
    return 946684800 <= u <= 2_100_000_000


# 本机 miniQMT userdata_mini/datadir 下日 K（86400）实测：8 字节魔数 + 64 字节/条，OHLC 为 int32×1000
_XT_MINIQMT_DAILY_MAGIC8 = bytes.fromhex("feffffffffffff7f")
_XT_MINIQMT_DAILY_HEADER = 8
_XT_MINIQMT_DAILY_STRIDE = 64
# int32 价位 ÷1000 为元（与 600000、600030、000001 等样本逐字节核对一致）
_XT_MINIQMT_PRICE_INT_SCALE = 0.001


def _is_xt_miniqmt_daily_dat(raw: bytes) -> bool:
    """判断是否为本仓库已验证的迅投日 K 二进制头（避免误走 float32 自推断路径）。"""
    return len(raw) >= _XT_MINIQMT_DAILY_HEADER + _XT_MINIQMT_DAILY_STRIDE and raw[:8] == _XT_MINIQMT_DAILY_MAGIC8


def _decode_xt_miniqmt_daily_record_64(chunk: bytes, vt_symbol: str) -> dict[str, Any] | None:
    """
    解析单条 64 字节日 K 记录的前 28 字节：uint32 秒时间戳 + int32×4 OHLC + 两个 uint32（常为 0 与成交量相关）。

    返回值与历史 float 路径一致，便于 ``build_daily_market_panel_from_local_datadir`` 复用。
    """
    if len(chunk) < 28:
        return None
    ts_u, o_i, h_i, l_i, c_i, _aux0, vol_u = struct.unpack_from("<IiiiiII", chunk, 0)
    if not _fingerprint_daily_unix(ts_u):
        if not _fingerprint_daily_unix_loose(ts_u):
            return None
    sc = float(_XT_MINIQMT_PRICE_INT_SCALE)
    o, h, l, c = float(o_i) * sc, float(h_i) * sc, float(l_i) * sc, float(c_i) * sc
    if not _ohlc_sane(o, h, l, c):
        return None
    vol = float(vol_u)
    if not _vol_sane(vol):
        vol = 0.0
    dt = _shanghai_dt_from_ts(int(ts_u))
    return {
        "datetime": dt,
        "vt_symbol": vt_symbol,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": vol,
    }


def _parse_xt_miniqmt_daily_dat_body(raw: bytes, vt_symbol: str) -> list[dict[str, Any]]:
    """魔数头已匹配时：固定头 8 字节、步长 64 顺序扫描（不走步长枚举，避免误判）。"""
    body = raw[_XT_MINIQMT_DAILY_HEADER :]
    stride = _XT_MINIQMT_DAILY_STRIDE
    out: list[dict[str, Any]] = []
    for off in range(0, len(body) - stride + 1, stride):
        row = _decode_xt_miniqmt_daily_record_64(body[off : off + stride], vt_symbol)
        if row:
            out.append(row)
    return out


# 日线单条记录常见字节步长（迅投系多为 32，亦有 28/40/48 等变体）
_STRIDE_CANDIDATES: tuple[int, ...] = (
    24,
    28,
    30,
    32,
    36,
    40,
    44,
    48,
    52,
    56,
    60,
    64,
    72,
    80,
    96,
)
# 文件头可能为魔数/版本号，跳过后再按 stride 对齐
_HEADER_SKIP_CANDIDATES: tuple[int, ...] = (0, 4, 8, 12, 16, 24, 32, 40, 48, 64, 128, 256)

# 价格下限与 ``_decode_bar_at`` 一致：过滤解码噪声
_MIN_PX = 1e-8


def _ohlc_sane(o: float, h: float, l: float, c: float) -> bool:
    """OHLC 是否在合理区间且高低价包容开收。"""
    if not (_MIN_PX < o < 1e6 and _MIN_PX < c < 1e6 and h >= l and h > _MIN_PX and l > _MIN_PX):
        return False
    if h + 1e-6 < max(o, c) or l - 1e-6 > min(o, c):
        return False
    return True


def _vol_sane(vol: float) -> bool:
    """成交量非负且不过大（避免把价格误读成 volume）。"""
    return 0.0 <= float(vol) < 1e15


def _infer_stride(data: bytes) -> int:
    """扫描文件前部，根据相邻指纹点间距估计单条 K 线字节长度（仅严格指纹，避免误报）。"""
    positions: list[int] = []
    cap = min(len(data), 256 * 1024)
    for off in range(0, cap - 4, 4):
        u = int.from_bytes(data[off : off + 4], "little")
        if _fingerprint_daily_unix(u):
            positions.append(off)
        if len(positions) >= 120:
            break
    if len(positions) < 3:
        return 0
    diffs = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
    cand = [d for d in diffs if 20 <= d <= 96]
    if not cand:
        return 0
    return Counter(cand).most_common(1)[0][0]


def _decode_bar_at(
    chunk: bytes,
    vt_symbol: str,
    *,
    strict_fingerprint: bool = True,
) -> dict[str, Any] | None:
    """
    兼容入口：与历史调用约定一致，内部统一走 ``_decode_bar_any_layout``（多时间戳/多 OHLC 布局）。
    """
    return _decode_bar_any_layout(chunk, vt_symbol, prefer_strict_ts=strict_fingerprint)


def _decode_bar_u32_f32(
    chunk: bytes,
    vt_symbol: str,
    *,
    strict_ts: bool,
) -> dict[str, Any] | None:
    """布局 A：uint32 LE 时间戳 + 5×float32（OHLCV），小端。"""
    if len(chunk) < 24:
        return None
    ts = struct.unpack_from("<I", chunk, 0)[0]
    if strict_ts:
        if not _fingerprint_daily_unix(ts):
            return None
    elif not _fingerprint_daily_unix_loose(ts):
        return None
    o, h, l, c, vol = struct.unpack_from("<fffff", chunk, 4)
    if not _ohlc_sane(o, h, l, c) or not _vol_sane(vol):
        return None
    dt = _shanghai_dt_from_ts(ts)
    return {
        "datetime": dt,
        "vt_symbol": vt_symbol,
        "open": float(o),
        "high": float(h),
        "low": float(l),
        "close": float(c),
        "volume": float(vol),
    }


def _decode_bar_u64_f32(chunk: bytes, vt_symbol: str) -> dict[str, Any] | None:
    """布局 B：uint64 LE 时间戳（秒或毫秒）+ 5×float32 OHLCV。"""
    if len(chunk) < 28:
        return None
    ts64 = struct.unpack_from("<Q", chunk, 0)[0]
    if ts64 > 10**12:
        ts = int(ts64 // 1000)
    elif ts64 > 10**11:
        ts = int(ts64 // 1000)
    else:
        ts = int(ts64)
    if not _fingerprint_daily_unix_loose(ts):
        return None
    o, h, l, c, vol = struct.unpack_from("<fffff", chunk, 8)
    if not _ohlc_sane(o, h, l, c) or not _vol_sane(vol):
        return None
    dt = _shanghai_dt_from_ts(ts)
    return {
        "datetime": dt,
        "vt_symbol": vt_symbol,
        "open": float(o),
        "high": float(h),
        "low": float(l),
        "close": float(c),
        "volume": float(vol),
    }


def _decode_bar_u32_f64ohlc_f32vol(chunk: bytes, vt_symbol: str, *, strict_ts: bool) -> dict[str, Any] | None:
    """布局 C：uint32 秒 + 4×float64（OHLC）+ float32 volume（共 40 字节）。"""
    if len(chunk) < 40:
        return None
    ts = struct.unpack_from("<I", chunk, 0)[0]
    if strict_ts:
        if not _fingerprint_daily_unix(ts):
            return None
    elif not _fingerprint_daily_unix_loose(ts):
        return None
    o, h, l, c = struct.unpack_from("<dddd", chunk, 4)
    (vol,) = struct.unpack_from("<f", chunk, 36)
    if not _ohlc_sane(o, h, l, c) or not _vol_sane(vol):
        return None
    dt = _shanghai_dt_from_ts(ts)
    return {
        "datetime": dt,
        "vt_symbol": vt_symbol,
        "open": float(o),
        "high": float(h),
        "low": float(l),
        "close": float(c),
        "volume": float(vol),
    }


def _decode_bar_any_layout(chunk: bytes, vt_symbol: str, *, prefer_strict_ts: bool) -> dict[str, Any] | None:
    """对单条记录依次尝试多种布局，返回第一个合法结果。"""
    attempts: list[tuple[str, Any]] = [
        ("u32_f32_strict", lambda: _decode_bar_u32_f32(chunk, vt_symbol, strict_ts=True)),
        ("u32_f32_loose", lambda: _decode_bar_u32_f32(chunk, vt_symbol, strict_ts=False)),
        ("u64_f32", lambda: _decode_bar_u64_f32(chunk, vt_symbol)),
        ("u32_f64ohlc_f32v_strict", lambda: _decode_bar_u32_f64ohlc_f32vol(chunk, vt_symbol, strict_ts=True)),
        ("u32_f64ohlc_f32v_loose", lambda: _decode_bar_u32_f64ohlc_f32vol(chunk, vt_symbol, strict_ts=False)),
    ]
    if not prefer_strict_ts:
        attempts = attempts[1:] + [attempts[0]]
    for _name, fn in attempts:
        row = fn()
        if row:
            return row
    return None


def _score_decode_params(body: bytes, vt_symbol: str, header: int, stride: int, *, max_bars: int) -> int:
    """在 body[header:] 上按 stride 扫描，统计能成功解码的条数（用于自调参）。"""
    if stride < 24 or header < 0 or header + stride > len(body):
        return 0
    buf = body[header:]
    n = 0
    scanned = 0
    for off in range(0, len(buf) - stride + 1, stride):
        chunk = buf[off : off + stride]
        if _decode_bar_any_layout(chunk, vt_symbol, prefer_strict_ts=True):
            n += 1
        scanned += 1
        if scanned >= max_bars:
            break
    return n


def _pick_best_decode_params(raw: bytes, vt_symbol: str) -> tuple[int, int]:
    """
    在前部样本上枚举 header_skip × stride，选出成功解码条数最多的组合。

    Returns:
        (header_skip, stride)
    """
    sample_len = min(len(raw), 524_288)
    sample = raw[:sample_len]
    best_h, best_s, best_score = 0, 32, -1

    inferred = _infer_stride(raw)
    strides_to_try: list[int] = []
    if inferred > 0:
        strides_to_try.append(inferred)
    strides_to_try.extend(s for s in _STRIDE_CANDIDATES if s not in strides_to_try)

    for H in _HEADER_SKIP_CANDIDATES:
        if H >= len(sample):
            continue
        for S in strides_to_try:
            sc = _score_decode_params(sample, vt_symbol, H, S, max_bars=4000)
            if sc > best_score:
                best_score, best_h, best_s = sc, H, S

    return (best_h, best_s) if best_score > 0 else (0, 32)


def _parse_single_dat(path: Path, vt_symbol: str) -> list[dict[str, Any]]:
    """读取单个 ``.DAT``：优先迅投日 K 固定布局；否则再自动 header/步长与 float 布局推断。"""
    raw = path.read_bytes()
    if len(raw) < 24:
        return []

    # 与实测 miniQMT datadir 一致：8 字节魔数 + 64 字节/条 + int32 价位（×1000），必须先于 float 推断
    if _is_xt_miniqmt_daily_dat(raw):
        rows = _parse_xt_miniqmt_daily_dat_body(raw, vt_symbol)
        if rows:
            return rows

    header_skip, stride = _pick_best_decode_params(raw, vt_symbol)
    body = raw[header_skip:]
    out: list[dict[str, Any]] = []
    for off in range(0, len(body) - stride + 1, stride):
        chunk = body[off : off + stride]
        row = _decode_bar_any_layout(chunk, vt_symbol, prefer_strict_ts=True)
        if row:
            out.append(row)

    # 若仍为空，保留旧逻辑再扫一遍（极少数样本上自调参失败时）
    if not out:
        out = _parse_single_dat_legacy_fallback(raw, vt_symbol)
    return out


def _parse_single_dat_legacy_fallback(raw: bytes, vt_symbol: str) -> list[dict[str, Any]]:
    """旧版推断步长 + 严格/宽松指纹扫描，作为最后兜底。"""
    if len(raw) < 32:
        return []

    def _scan(body: bytes, stride: int, strict_fp: bool) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for off in range(0, len(body) - stride + 1, stride):
            chunk = body[off : off + stride]
            row = _decode_bar_u32_f32(chunk, vt_symbol, strict_ts=strict_fp)
            if row:
                rows.append(row)
        return rows

    stride = _infer_stride(raw)
    if stride <= 0:
        for s in (32, 40, 36, 28, 48, 24):
            if len(raw) >= s and _decode_bar_u32_f32(raw[:s], vt_symbol, strict_ts=True):
                stride = s
                break
        else:
            stride = 32

    rows = _scan(raw, stride, strict_fp=True)
    if not rows:
        for s in (stride, 32, 40, 36, 28, 48, 24, 44, 56):
            if s <= 0 or len(raw) < s:
                continue
            rows = _scan(raw, s, strict_fp=False)
            if rows:
                break
    return rows


def _list_daily_dat_files(datadir: Path, period_name: str, max_symbols: int) -> list[tuple[Path, str]]:
    """
    枚举 ``datadir/**/{period}/*.DAT``，返回 (路径, vt_symbol)。

    目录约定与 ``qmt_service.build_stock_quarter_report`` 一致：父级目录名为市场 ``SH``/``SZ``。
    """
    paths = sorted(datadir.glob(f"**/{period_name}/*.DAT"))
    out: list[tuple[Path, str]] = []
    for fp in paths:
        market = fp.parent.parent.name
        code = fp.stem
        vt = f"{code}.{market}"
        out.append((fp, vt))
        if max_symbols > 0 and len(out) >= max_symbols:
            break
    return out


def _filter_consecutive_close_outliers(df: pd.DataFrame, *, max_jump_ratio: float = 120.0) -> pd.DataFrame:
    """
    按标的、按时间排序后，剔除「相对上一根收盘价」倍数极端的 K 线。

    说明：``.DAT`` 自动推断步长/头偏移时，仍可能偶发插入一条通过 ``_ohlc_sane`` 的错位记录；
    表现为相邻日收盘价跨多个数量级。正常 A 股日线极少相邻日超过 ``max_jump_ratio`` 倍
    （已远大于涨跌停与常见拆合股），故用作噪声过滤。
    """
    if df.empty or "vt_symbol" not in df.columns or "close" not in df.columns:
        return df
    parts: list[pd.DataFrame] = []
    for _, g in df.groupby("vt_symbol", sort=False):
        g2 = g.sort_values("datetime", kind="mergesort").reset_index(drop=True)
        c = pd.to_numeric(g2["close"], errors="coerce")
        prev = c.shift(1)
        ratio = c / prev
        first_bar = prev.isna()
        ratio_ok = ratio.isna() | ((ratio >= 1.0 / max_jump_ratio) & (ratio <= max_jump_ratio))
        keep = first_bar | ratio_ok
        parts.append(g2.loc[keep])
    return pd.concat(parts, ignore_index=True) if parts else df


def build_daily_market_panel_from_local_datadir(
    start_yyyymmdd: str,
    end_yyyymmdd: str,
    max_symbols: int,
    stock_list: list[str] | None = None,
) -> pd.DataFrame:
    """
    仅从本地 ``datadir`` 日线文件构建与 ``factor_market_panel.build_daily_market_panel`` 列一致的 DataFrame。

    不调用 xtdata；要求 ``Config/qmt.json`` 中安装路径下已存在已下载的 ``*.DAT``。

    Args:
        stock_list: 若提供（通常来自 ``stock_pool.json``），仅加载这些 vt；否则按 ``max_symbols``
            截取枚举顺序下的前若干文件。
    """
    cfg = load_config()
    datadir = get_local_datadir()
    if not datadir.is_dir():
        raise FileNotFoundError(
            f"未找到本地行情目录: {datadir}\n"
            "请确认 Config/qmt.json 中 qmt_install_path / userdata_mini 配置正确，"
            "并已在可启动 miniQMT 时执行过日线下载。",
        )
    period_name = str(cfg.get("kline_period_dir_name") or "86400")
    if stock_list is not None:
        files = list_daily_dat_files_for_symbols(datadir, period_name, stock_list)
        if not files:
            raise RuntimeError(
                f"股票池中的标的在 {datadir} 下未匹配到任何 **/{period_name}/*.DAT，"
                "请确认已下载对应代码或重建股票池。",
            )
    else:
        files = _list_daily_dat_files(datadir, period_name, max_symbols)
    if not files:
        raise RuntimeError(
            f"在 {datadir} 下未找到日线文件（期望 **/{period_name}/*.DAT）。\n"
            "请先下载历史日线，或将 market_data_source 改为 xtdata 并启动客户端。",
        )

    start_day = datetime.strptime(start_yyyymmdd.strip(), "%Y%m%d").date()
    end_day = datetime.strptime(end_yyyymmdd.strip(), "%Y%m%d").date()

    all_rows: list[dict[str, Any]] = []
    parsed_any = 0
    for fp, vt in files:
        chunk = _parse_single_dat(fp, vt)
        parsed_any += len(chunk)
        for row in chunk:
            d = row["datetime"]
            if not isinstance(d, datetime):
                continue
            day = d.date()
            if day < start_day or day > end_day:
                continue
            all_rows.append(row)

    if not all_rows:
        if parsed_any == 0:
            raise RuntimeError(
                "本地 .DAT 文件存在，但未能解码出任何 K 线。\n"
                "常见原因：① 周期目录名与 ``Config/qmt.json`` 的 ``kline_period_dir_name`` 不一致（常见为 ``86400`` 或客户端实际目录名）；"
                "② 本机 miniQMT 日线二进制布局与解析器仍不匹配（已尝试多种步长/文件头偏移与字段布局）。\n"
                "可尝试：将 ``factor_evaluation.json`` 的 ``market_data_source`` 改为 ``xtdata`` 并在客户端就绪后重试；"
                "或核对 datadir 下日 K 目录名与 ``kline_period_dir_name`` 是否一致；"
                "若仍失败，请向项目反馈单个样本 .DAT 前 256 字节的 hex 以便扩展解析器。",
            )
        raise RuntimeError(
            f"已从本地解码约 {parsed_any} 条 K 线，但均不在区间 "
            f"{start_yyyymmdd}～{end_yyyymmdd} 内。\n"
            "请扩大回测起止日期或重新下载覆盖该区间的日线。",
        )

    pdf = pd.DataFrame(all_rows)
    pdf = pdf.sort_values(["vt_symbol", "datetime"]).reset_index(drop=True)
    # 剔除步长误判产生的孤立「天价/地价」柱，避免后续因子与成交模拟被污染
    _n_before = len(pdf)
    _jump_cap = 120.0
    pdf = _filter_consecutive_close_outliers(pdf, max_jump_ratio=_jump_cap)
    _dropped = _n_before - len(pdf)
    if _n_before > 0 and _dropped / _n_before > 0.005:
        print(
            f"[local_datadir] 剔除相邻收盘倍数>{_jump_cap:g} 的疑似噪声 K 线: "
            f"{_dropped}/{_n_before} 条。",
            flush=True,
        )
    pdf["vwap"] = (pdf["high"] + pdf["low"] + pdf["close"]) / 3.0
    return pdf
