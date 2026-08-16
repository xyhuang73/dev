# -*- coding: utf-8 -*-
"""
miniQMT 行情数据下载权限探测。

基于本地已下载数据分析数据范围，并尝试探测各周期的下载权限。

运行方式：
    python scripts/check_data_quota.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from zoneinfo import ZoneInfo
    _TZ_SH = ZoneInfo("Asia/Shanghai")
except Exception:
    _TZ_SH = timezone(timedelta(hours=8))


def _to_date_str(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def _now_sh() -> datetime:
    return datetime.now(_TZ_SH)


def _unix_ts_to_date_range(data: bytes) -> tuple[datetime | None, datetime | None]:
    """从 DAT 文件提取日期范围。"""
    import numpy as np

    try:
        arr = np.frombuffer(memoryview(data), dtype="<u4")
        mask = (arr >= 946684800) & (arr <= 2100000000) & (arr % 86400 == 57600)
        timestamps = arr[mask]
        if len(timestamps) == 0:
            return None, None
        dt_min = datetime.fromtimestamp(int(timestamps.min()), _TZ_SH)
        dt_max = datetime.fromtimestamp(int(timestamps.max()), _TZ_SH)
        return dt_min, dt_max
    except Exception:
        return None, None


def _analyze_date_range(paths: list[Path], sample_size: int = 200) -> tuple[datetime | None, datetime | None]:
    """分析一批 DAT 文件的日期范围（采样分析）。"""
    sample_paths = paths[:min(sample_size, len(paths))]
    all_dates: list[datetime] = []

    for fp in sample_paths:
        try:
            raw = fp.read_bytes()
            dt_min, dt_max = _unix_ts_to_date_range(raw)
            if dt_min:
                all_dates.append(dt_min)
            if dt_max:
                all_dates.append(dt_max)
        except Exception:
            pass

    if not all_dates:
        return None, None
    return min(all_dates), max(all_dates)


def probe_local_data_quota() -> str:
    """基于本地已下载数据分析数据范围。"""
    from qmt_service import get_local_datadir, load_config

    cfg = load_config()
    datadir = get_local_datadir()

    if not datadir.is_dir():
        return f"行情目录不存在: {datadir}"

    lines: list[str] = []
    now = _now_sh()
    today_str = _to_date_str(now)

    # 周期目录名映射
    PERIOD_MAP = {
        "86400": ("日线", "日线"),
        "300": ("5分钟", "5分钟"),
        "60": ("1分钟", "1分钟"),
        "900": ("15分钟", "15分钟"),
        "1800": ("30分钟", "30分钟"),
        "3600": ("60分钟", "60分钟"),
    }

    # 探测 datadir 下所有周期目录
    period_stats: dict[str, dict] = {}
    for market_dir in datadir.iterdir():
        if not market_dir.is_dir() or market_dir.name in ("DividData", "increase", "Weight", "TradeDateAndETFStockListCache", "marketlistinfo"):
            continue
        for period_dir in market_dir.iterdir():
            if not period_dir.is_dir() or not period_dir.name.isdigit():
                continue
            pname = period_dir.name
            period_info = PERIOD_MAP.get(pname, (f"{pname}秒", None))
            plabel = period_info[1] if period_info[1] else period_info[0]

            if plabel not in period_stats:
                period_stats[plabel] = {"files": 0, "stocks": set(), "paths": [], "min_date": None, "max_date": None}

            dat_files = list(period_dir.glob("*.DAT"))
            period_stats[plabel]["files"] += len(dat_files)
            period_stats[plabel]["paths"].extend([str(fp) for fp in dat_files])
            for fp in dat_files:
                market = fp.parent.parent.name
                code = f"{fp.stem}.{market}"
                period_stats[plabel]["stocks"].add(code)

    # ===== 输出报告 =====
    lines.append("")
    lines.append("=" * 60)
    lines.append("       miniQMT 行情数据下载权限探测")
    lines.append("=" * 60)
    lines.append(f"探测时间: {today_str}")
    lines.append(f"行情目录: {datadir}")
    lines.append("-" * 60)

    # 按优先级排序
    period_order = ["日线", "1分钟", "5分钟", "15分钟", "30分钟", "60分钟"]
    other_periods = [k for k in period_stats if k not in period_order]
    ordered_periods = [k for k in period_order if k in period_stats] + sorted(other_periods)

    if not ordered_periods:
        lines.append("")
        lines.append("未发现任何已下载的数据文件。")
        lines.append("请在 QMT 中下载所需的数据后再运行此脚本。")
        return "\n".join(lines)

    # ===== 第一部分：各周期数据统计 =====
    lines.append("")
    lines.append("【一、各周期数据统计】")
    lines.append("-" * 60)
    lines.append(f"{'周期':<10} {'文件数':>10} {'股票数':>10}")
    lines.append("-" * 60)

    for plabel in ordered_periods:
        stats = period_stats[plabel]
        stock_count = len(stats["stocks"])
        file_count = stats["files"]
        lines.append(f"{plabel:<10} {file_count:>10} {stock_count:>10}")

    lines.append("-" * 60)

    # ===== 第二部分：数据时间范围 =====
    lines.append("")
    lines.append("【二、数据时间范围（本地已下载）】")
    lines.append("-" * 60)

    # 精确分析每个周期日期范围
    for plabel in ordered_periods:
        stats = period_stats[plabel]
        if stats["paths"]:
            paths = [Path(p) for p in stats["paths"]]
            dt_min, dt_max = _analyze_date_range(paths, sample_size=200)
            stats["min_date"] = dt_min
            stats["max_date"] = dt_max

            date_range_str = ""
            if dt_min and dt_max:
                years = (dt_max - dt_min).days / 365.0
                date_range_str = f"{dt_min.strftime('%Y年%m月')} ~ {dt_max.strftime('%Y年%m月')} ({years:.1f}年)"

            lines.append(f"{plabel:<10} {date_range_str}")

    lines.append("-" * 60)

    # ===== 第三部分：权限推断 =====
    lines.append("")
    lines.append("【三、下载权限推断】")
    lines.append("=" * 60)

    # 日线权限
    daily_stats = period_stats.get("日线")
    if daily_stats and daily_stats["min_date"] and daily_stats["max_date"]:
        years = (daily_stats["max_date"] - daily_stats["min_date"]).days / 365.0
        lines.append(f"  日线数据: {daily_stats['min_date'].strftime('%Y年%m月')} ~ {daily_stats['max_date'].strftime('%Y年%m月')} (约{years:.1f}年)")
        if years >= 15:
            lines.append("  -> 权限: 日线全量（15年以上）")
        elif years >= 10:
            lines.append("  -> 权限: 日线标准（10年）")
        elif years >= 5:
            lines.append("  -> 权限: 日线标准（5年）")
        else:
            lines.append("  -> 权限: 日线受限（5年以内）")

    # 分钟级权限
    minute_stats = []
    for pname in ["1分钟", "5分钟", "15分钟", "30分钟"]:
        if pname in period_stats and period_stats[pname]["files"] > 0:
            minute_stats.append(pname)

    if minute_stats:
        lines.append(f"  分钟级数据: 有本地数据 ({', '.join(minute_stats)})")
        lines.append("  -> 权限: 分钟级数据已开通")
    else:
        lines.append("  分钟级数据: 无本地数据")
        lines.append("  -> 权限: 分钟级数据未开通或未下载")

    # 小时级权限
    if "60分钟" in period_stats and period_stats["60分钟"]["files"] > 0:
        lines.append("  小时级数据: 有本地数据")
        lines.append("  -> 权限: 小时级数据已开通")
    else:
        lines.append("  小时级数据: 无本地数据")
        lines.append("  -> 权限: 小时级数据未开通或未下载")

    # ===== 第四部分：说明 =====
    lines.append("")
    lines.append("=" * 60)
    lines.append("【四、说明】")
    lines.append("-" * 60)
    lines.append("  * 本报告基于本地已下载数据分析")
    lines.append("  * 实际下载权限由券商和账户类型决定")
    lines.append("  * 部分券商账户可能限制分钟级数据的下载时间范围")
    lines.append("  * 常见权限配置:")
    lines.append("    - 免费/标准账户: 通常只能下载最近5年日线，分钟级受限")
    lines.append("    - 付费/专业账户: 可下载10年以上日线，分钟级全量")
    lines.append("  * 要完整探测权限，请在 QMT 客户端中尝试下载")

    return "\n".join(lines)


def main() -> int:
    try:
        print(probe_local_data_quota())
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
