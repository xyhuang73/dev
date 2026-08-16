"""
本机 datadir 日 K（*.DAT）按自然季度统计「该季度至少有一天本地日 K」的股票只数。

股票信息报表 ``build_stock_quarter_report`` 仅读磁盘二进制，不加载 xtquant、不要求 QMT 客户端运行。
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo

    _TZ_SH = ZoneInfo("Asia/Shanghai")
except Exception:  # noqa: BLE001 — 极少数环境无 tzdata
    _TZ_SH = timezone(timedelta(hours=8))

_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = _ROOT / "Config" / "qmt.json"


def _defaults() -> dict[str, Any]:
    """Config 缺省键值。"""
    return {
        "qmt_install_path": r"D:\MiniQmt\国金证券QMT交易端",
        "userdata_folder_name": "userdata_mini",
        "local_datadir_subpath": "datadir",
        "kline_period_dir_name": "86400",
        "local_scan_batch_size": 80,
        # Prepare「更新股票」子界面：默认日期区间与板块（YYYYMMDD）
        "update_stock_start_day": "20230101",
        "update_stock_end_day": "20231231",
        "update_stock_sector": "沪深A股",
        # 0 表示不限制只数；调试可改为 30、50 等
        "update_stock_max_symbols": 0,
        # XtQuantTrader 资金账号；留空则连接后尝试 query_account_infos 自动发现
        "account_id": "",
    }


def load_config() -> dict[str, Any]:
    """读取 qmt.json；不存在则创建，缺键则补默认并写回。"""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        data = _defaults()
        CONFIG_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    else:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        defaults = _defaults()
        missing = {k: defaults[k] for k in defaults if k not in data}
        if missing:
            data.update(missing)
            CONFIG_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    return data


def _userdata_dir(cfg: dict[str, Any]) -> Path:
    return Path(cfg["qmt_install_path"]) / (cfg.get("userdata_folder_name") or "userdata_mini")


def get_userdata_mini_dir(cfg: dict[str, Any] | None = None) -> Path:
    """返回 miniQMT userdata_mini 目录（XtQuantTrader 会话路径）。"""
    return _userdata_dir(cfg or load_config())


def _local_datadir(cfg: dict[str, Any]) -> Path:
    return _userdata_dir(cfg) / (cfg.get("local_datadir_subpath") or "datadir")


def get_local_datadir() -> Path:
    """
    返回 miniQMT userdata 下的本地行情根目录（通常为 ``.../userdata_mini/datadir``）。

    仅路径解析，不 import xtquant；供离线读取 ``*.DAT`` 与因子回测解耦。
    """
    return _local_datadir(load_config())


def _inject_xtquant_path(cfg: dict[str, Any]) -> None:
    install = Path(cfg["qmt_install_path"])

    # xtquant 包位置：优先读配置中显式指定的子路径，否则按常见目录自动探测
    explicit = cfg.get("xtquant_site_packages_subpath", "").strip()
    if explicit:
        candidates = [install / explicit]
    else:
        candidates = [
            install / "python" / "Lib" / "site-packages",  # 国金/华鑫等常见布局
            install / "Lib" / "site-packages",
            install / "site-packages",
        ]

    site_pkg: Path | None = None
    for c in candidates:
        if (c / "xtquant").is_dir():
            site_pkg = c
            break

    if site_pkg is None:
        # 找不到时给出明确提示，包含已尝试的路径
        tried = ", ".join(str(c) for c in candidates)
        raise FileNotFoundError(
            f"未在以下路径找到 xtquant 包，请在 Config/qmt.json 中设置 "
            f"'xtquant_site_packages_subpath'（相对于 qmt_install_path）：{tried}"
        )

    s = str(site_pkg)
    if s not in sys.path:
        sys.path.insert(0, s)

    # userdata_mini 仍需在 sys.path 中，XtQuantTrader 连接时会用到
    ud = _userdata_dir(cfg)
    if ud.is_dir():
        ud_s = str(ud)
        if ud_s not in sys.path:
            sys.path.insert(0, ud_s)


def ensure_xtquant_path() -> dict[str, Any]:
    """
    读取配置并将 xtquant 所在 site-packages 路径插入 sys.path，供 ``from xtquant import xtdata`` 前调用。

    自动探测 ``<qmt_install_path>/python/Lib/site-packages`` 等常见位置；
    若布局特殊，可在 Config/qmt.json 中添加 ``xtquant_site_packages_subpath`` 显式指定。

    Returns:
        当前配置字典（与 load_config 一致）。
    """
    cfg = load_config()
    _inject_xtquant_path(cfg)
    return cfg


def get_update_stock_date_range() -> tuple[str, str]:
    """返回 (start_yyyymmdd, end_yyyymmdd)，供界面初始化。"""
    cfg = load_config()
    start = str(cfg.get("update_stock_start_day") or "20230101").strip()
    end = str(cfg.get("update_stock_end_day") or "20231231").strip()
    if len(start) == 8 and start.isdigit() and len(end) == 8 and end.isdigit():
        return start, end
    return "20230101", "20231231"


def save_update_stock_date_range(start_yyyymmdd: str, end_yyyymmdd: str) -> None:
    """将起止日期写入 Config/qmt.json。"""
    cfg = load_config()
    cfg["update_stock_start_day"] = start_yyyymmdd
    cfg["update_stock_end_day"] = end_yyyymmdd
    CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _quarter_sort_key(label: str) -> tuple[int, int]:
    """YYYYQn 字符串排序用。"""
    if len(label) >= 6 and label[4] == "Q" and label[:4].isdigit() and label[5].isdigit():
        return int(label[:4]), int(label[5])
    return 9999, 9


def _unix_ts_to_quarter(ts: int) -> str | None:
    """unix 秒时间戳（日线文件内 uint32）→ YYYYQn，按上海时区日历划分季度。"""
    try:
        dt = datetime.fromtimestamp(ts, _TZ_SH)
    except (OSError, OverflowError, ValueError):
        return None
    y, m = dt.year, dt.month
    if not (1990 <= y <= 2036):
        return None
    return f"{y}Q{(m - 1) // 3 + 1}"


def _quarters_from_dat_bytes(data: bytes) -> set[str]:
    """
    纯二进制扫描 miniQMT 日线 .DAT：在样本中交易日时间戳为 uint32 LE，
    且相对 UTC 日界常落在「前一日 16:00」，故 ``ts % 86400 == 57600``。

    不依赖 xtquant，无需启动 QMT 客户端。
    """
    quarters: set[str] = set()
    n = len(data)
    # 优先用 numpy 向量化（本机约数千文件时更快）；无 numpy 则回退逐字扫描
    try:
        import numpy as np

        arr = np.frombuffer(memoryview(data), dtype="<u4")
        mask = (arr >= 946684800) & (arr <= 2100000000) & (arr % 86400 == 57600)
        for ts in np.unique(arr[mask]):
            qk = _unix_ts_to_quarter(int(ts))
            if qk:
                quarters.add(qk)
        return quarters
    except ImportError:
        pass

    for off in range(0, n - 3, 4):
        u = int.from_bytes(data[off : off + 4], "little")
        if u < 946684800 or u > 2100000000:
            continue
        if (u % 86400) != 57600:
            continue
        qk = _unix_ts_to_quarter(u)
        if qk:
            quarters.add(qk)
    return quarters


def _quarters_from_minute_dat(data: bytes, record_size: int = 64) -> set[str]:
    """
    扫描分钟线 .DAT，提取季度信息。

    分钟线格式：每条记录 record_size 字节，时间戳在偏移 8 处。
    时间戳为 unix 秒，无需检查 %86400。

    不依赖 xtquant，无需启动 QMT 客户端。
    """
    quarters: set[str] = set()
    n = len(data)
    ts_offset = 8  # 时间戳在每条记录中的偏移

    try:
        import numpy as np

        arr = np.frombuffer(memoryview(data), dtype="<u4")
        # 分钟线时间戳范围检查：2015-2030 年
        mask = (arr >= 1420000000) & (arr <= 1900000000)
        for ts in np.unique(arr[mask]):
            qk = _unix_ts_to_quarter(int(ts))
            if qk:
                quarters.add(qk)
        return quarters
    except ImportError:
        pass

    # 回退：逐条扫描
    for off in range(ts_offset, n - 3, record_size):
        u = int.from_bytes(data[off : off + 4], "little")
        if u < 1420000000 or u > 1900000000:
            continue
        qk = _unix_ts_to_quarter(u)
        if qk:
            quarters.add(qk)
    return quarters


def _detect_period_dirs(datadir: Path) -> dict[str, Path]:
    """探测 datadir 下所有周期子目录，返回 {周期名: 路径}。"""
    period_map = {}
    if not datadir.is_dir():
        return period_map
    for market_dir in datadir.iterdir():
        if not market_dir.is_dir():
            continue
        for period_dir in market_dir.iterdir():
            if period_dir.is_dir() and period_dir.name.isdigit():
                period_name = _PERIOD_LABELS.get(period_dir.name, f"{period_dir.name}秒")
                if period_name not in period_map:
                    period_map[period_name] = period_dir.parent
                else:
                    # 多个市场目录，取第一个
                    pass
    return period_map


# 常用周期标签映射
_PERIOD_LABELS: dict[str, str] = {
    "86400": "日线",
    "300": "5分钟",
    "60": "1分钟",
    "900": "15分钟",
    "1800": "30分钟",
    "3600": "60分钟",
    "5": "5秒",
    "15": "15秒",
    "30": "30秒",
}


def build_stock_quarter_report() -> str:
    """
    扫描本地 datadir 下各周期 .DAT，按自然季度统计「该季度至少有1条数据」的股票只数。

    仅读取磁盘二进制，不 import xtquant、不要求 QMT 客户端运行。
    """
    cfg = load_config()
    datadir = _local_datadir(cfg)
    if not datadir.is_dir():
        raise FileNotFoundError(f"未找到本机行情目录: {datadir}")

    period_name = str(cfg.get("kline_period_dir_name") or "86400")
    period_label = _PERIOD_LABELS.get(period_name, period_name)

    # 需要进行季度统计的周期（目录名 → 显示名）
    QUARTER_PERIODS: dict[str, str] = {
        period_name: period_label,  # 日线（主周期）
        "300": "5分钟",
        "60": "1分钟",
        "900": "15分钟",
        "1800": "30分钟",
        "3600": "60分钟",
    }

    # 探测所有周期目录（用于概览）
    period_stats: dict[str, dict[str, Any]] = {}

    # 各周期的季度统计
    period_quarters: dict[str, dict[str, set[str]]] = {}

    for market_dir in datadir.iterdir():
        if not market_dir.is_dir():
            continue
        for period_dir in market_dir.iterdir():
            if not period_dir.is_dir() or not period_dir.name.isdigit():
                continue
            pname = period_dir.name
            plabel = _PERIOD_LABELS.get(pname, f"{pname}秒")
            if plabel not in period_stats:
                period_stats[plabel] = {"files": 0, "stocks": set()}
            dat_files = list(period_dir.glob("*.DAT"))
            period_stats[plabel]["files"] += len(dat_files)
            for fp in dat_files:
                market = fp.parent.parent.name
                code = f"{fp.stem}.{market}"
                period_stats[plabel]["stocks"].add(code)

            # 对需要季度统计的周期进行解析
            if pname in QUARTER_PERIODS:
                plabel_for_q = QUARTER_PERIODS[pname]
                if plabel_for_q not in period_quarters:
                    period_quarters[plabel_for_q] = defaultdict(set)

                # 日线用专门的解析函数（检查收盘时间），分钟线用另一套
                if pname == period_name:  # 日线
                    quarter_func = _quarters_from_dat_bytes
                else:  # 分钟线
                    quarter_func = _quarters_from_minute_dat

                for fp in dat_files:
                    market = fp.parent.parent.name
                    code = f"{fp.stem}.{market}"
                    try:
                        raw = fp.read_bytes()
                    except OSError:
                        continue
                    for qk in quarter_func(raw):
                        period_quarters[plabel_for_q][qk].add(code)

    # 检查日线是否存在
    paths = sorted(datadir.glob(f"**/{period_name}/*.DAT"))
    if not paths:
        return "\n".join(
            [
                "──────── 本地行情 ────────",
                "",
                "行情目录（datadir）",
                f"  {datadir}",
                "",
                f"未在「{period_name}」目录下发现 .DAT 文件。",
                "请先在 QMT 中下载日 K 后再统计。",
            ]
        )

    # 排版输出
    lines: list[str] = []

    # ===== 概览区 =====
    lines.append("")
    lines.append("=" * 50)
    lines.append("       本地行情概览")
    lines.append("=" * 50)
    lines.append(f"行情目录: {datadir}")
    lines.append("-" * 50)
    lines.append("各周期数据统计:")
    lines.append("-" * 50)

    # 按优先级排序周期
    period_order = ["日线", "1分钟", "5分钟", "15分钟", "30分钟", "60分钟"]
    other_periods = [k for k in period_stats if k not in period_order]
    ordered_periods = [k for k in period_order if k in period_stats] + sorted(other_periods)

    for plabel in ordered_periods:
        stats = period_stats[plabel]
        if "stocks" in stats:
            stock_count = len(stats["stocks"])
            file_count = stats.get("files", 0)
            lines.append(f"  {plabel:<6}  文件: {file_count:>5} 个    股票: {stock_count:>5} 只")
        else:
            lines.append(f"  {plabel:<6}  文件: {stats['files']:>5} 个")

    lines.append("-" * 50)

    # ===== 季度统计区 =====
    # 按优先级输出各周期的季度统计
    quarter_period_order = ["日线", "5分钟", "1分钟", "15分钟", "30分钟", "60分钟"]
    quarters_to_show = [p for p in quarter_period_order if p in period_quarters]

    for plabel in quarters_to_show:
        qmembers = period_quarters[plabel]
        total_stocks = set()
        for s in qmembers.values():
            total_stocks.update(s)

        lines.append("")
        lines.append("=" * 50)
        lines.append(f"       {plabel}季度统计")
        lines.append("=" * 50)
        lines.append(f"{plabel}股票总数: {len(total_stocks)} 只")
        lines.append("-" * 50)
        lines.append(f"{'年季':<8} {'股票数':>8}  {'分布图':<30}")
        lines.append("-" * 50)

        for qk in sorted(qmembers.keys(), key=_quarter_sort_key):
            n = len(qmembers[qk])
            bar_width = min(n // 10, 20)
            bar = "#" * bar_width
            lines.append(f"{qk:<8} {n:>6} 只  {bar:<30}")

    # ===== 统计说明 =====
    lines.append("")
    lines.append("统计说明:")
    lines.append("  * 方式：直接解析 .DAT 内 uint32 时间戳（不经过 xtquant，无需启动客户端）")
    lines.append("  * 口径：某自然季度内只要存在至少 1 条数据，该股票即计入该季")
    lines.append("  * 股票数：按市场代码去重后的唯一证券数量")

    return "\n".join(lines)
