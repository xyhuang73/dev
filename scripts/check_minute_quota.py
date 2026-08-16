# -*- coding: utf-8 -*-
"""
miniQMT 分钟级数据权限探测。

使用 xtquant.xtdata.download_history_data 从近到远探测 1分钟/5分钟 的下载权限。
独立脚本，不依赖 qmt_service.py（避免 Python 3.6 兼容性问题）。

运行方式：
    python scripts/check_minute_quota.py
"""
from __future__ import print_function

import os
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone

# ===== QMT 路径配置 =====
QMT_INSTALL_PATH = r"D:\MiniQmt\国金证券QMT交易端"
QMT_USERDATA_FOLDER = "userdata_mini"


def _get_qmt_userdata_dir():
    return os.path.join(QMT_INSTALL_PATH, QMT_USERDATA_FOLDER)


def _ensure_xtquant_path():
    """添加 xtquant 路径到 sys.path"""
    site_packages = os.path.join(QMT_INSTALL_PATH, "python", "Lib", "site-packages")
    if site_packages not in sys.path:
        sys.path.insert(0, site_packages)
    return {"qmt_install_path": QMT_INSTALL_PATH, "userdata_folder_name": QMT_USERDATA_FOLDER}


# ===== 时区配置 =====
try:
    from zoneinfo import ZoneInfo
    _TZ_SH = ZoneInfo("Asia/Shanghai")
except Exception:
    _TZ_SH = timezone(timedelta(hours=8))


def _to_date_str(dt):
    return dt.strftime("%Y%m%d")


def _now_sh():
    return datetime.now(_TZ_SH)


def _is_qmt_port_open() -> bool:
    """检测 QMT 客户端的行情服务端口是否可连接（58610）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        result = s.connect_ex(("127.0.0.1", 58610))
        return result == 0
    except Exception:
        return False
    finally:
        s.close()


def _check_qmt_port_readiness() -> str:
    """返回空字符串表示就绪，否则返回错误原因说明。"""
    if not _is_qmt_port_open():
        return (
            "无法连接 miniQMT 行情服务（端口 58610 无响应）。\n"
            "请确认：\n"
            "  1. miniQMT / 国金 QMT 客户端已启动\n"
            "  2. 客户端已登录（账号状态正常）\n"
            "  3. 客户端已开启「行情服务」权限\n"
            "\n"
            "提示：可在任务管理器中搜索 XtMiniQmt、miniqmt、QMT 等进程确认状态。"
        )
    return ""


def probe_minute_quota():
    """探测分钟级数据下载权限。"""
    # ===== 前置检查：QMT 客户端就绪 =====
    port_error = _check_qmt_port_readiness()
    if port_error:
        return "【错误】miniQMT 客户端未就绪\n\n" + port_error

    # 确保 xtquant 路径可用
    cfg = _ensure_xtquant_path()

    try:
        import xtquant.xtdata as xtdata
    except ImportError as e:
        return "无法导入 xtquant: " + str(e)

    # 关闭问候语
    if hasattr(xtdata, "enable_hello"):
        xtdata.enable_hello = False

    lines = []
    now = _now_sh()
    today_str = _to_date_str(now)
    yesterday_str = _to_date_str(now - timedelta(days=1))

    lines.append("")
    lines.append("=" * 70)
    lines.append("       miniQMT 分钟级数据权限探测")
    lines.append("=" * 70)
    lines.append("探测时间: " + today_str)
    lines.append("-" * 70)

    # 测试标的
    test_symbols = ["000001.SZ", "600519.SH"]  # 平安银行、贵州茅台

    # 定义探测周期
    probe_periods = [
        ("1m", "1分钟"),
        ("5m", "5分钟"),
    ]

    # 从近到远探测
    time_probes = [
        (1, "今天"),
        (2, "最近2天"),
        (5, "最近5天"),
        (10, "最近10天"),
        (30, "最近1月"),
        (90, "最近3月"),
        (180, "最近半年"),
        (365, "最近1年"),
    ]

    for period, period_name in probe_periods:
        lines.append("")
        lines.append("【" + period_name + " 数据探测】")
        lines.append("-" * 70)
        lines.append("{:<12} {:<10} {:<15} {:<20}".format("时间范围", "回溯天数", "下载结果", "数据验证"))
        lines.append("-" * 70)

        permission_found = False
        max_days = 0
        max_days_label = ""

        for days_back, label in time_probes:
            start_date = _to_date_str(now - timedelta(days=days_back))
            end_date = yesterday_str

            symbol_success = False
            result_info = ""

            for test_sym in test_symbols:
                try:
                    # 尝试下载数据
                    xtdata.download_history_data(
                        test_sym,
                        period,
                        start_date,
                        end_date,
                    )

                    # 验证数据
                    df = xtdata.get_market_data(
                        field_list=["close"],
                        stock_list=[test_sym],
                        period=period,
                        start_time=start_date,
                        end_time=end_date,
                        count=10,
                    )

                    if df is not None and not df.empty:
                        actual_count = len(df)
                        result_info = "获取到{}条".format(actual_count)
                        symbol_success = True
                        max_days = days_back
                        max_days_label = label
                        permission_found = True
                        break

                except Exception as e:
                    result_info = "异常: " + str(e)[:12]

            if symbol_success:
                success_str = "[OK] 有数据"
            else:
                success_str = "[X] " + (result_info if result_info else "无数据")

            lines.append("{:<12} {:<10} {:<15} {:<20}".format(label, days_back, success_str, result_info))

            # 找到数据后继续探测更远范围
            if not permission_found and days_back > 30:
                break

        # 总结该周期权限
        lines.append("-" * 70)
        if permission_found:
            lines.append("  权限推断: 可以下载" + max_days_label + "以内的" + period_name + "数据")
        else:
            lines.append("  权限推断: 无法下载" + period_name + "数据或权限受限")

    # ===== 总结 =====
    lines.append("")
    lines.append("=" * 70)
    lines.append("       权限探测总结")
    lines.append("=" * 70)
    lines.append("")
    lines.append("说明:")
    lines.append("  * 使用 download_history_data 实时下载数据探测权限")
    lines.append("  * 数据下载到 QMT 本地缓存目录")
    lines.append("  * 从近到远逐步扩大时间范围")
    lines.append("")
    lines.append("常见权限级别:")
    lines.append("  - 基础账户: 通常只能下载最近 3~5 天的分钟数据")
    lines.append("  - 标准账户: 通常可以下载最近 3~6 个月的分钟数据")
    lines.append("  - 高级账户: 可能可以下载 1 年以上的分钟数据")
    lines.append("")
    lines.append("注意: 部分券商可能完全不支持分钟级数据下载")

    return "\n".join(lines)


def main():
    try:
        result = probe_minute_quota()
        # 处理结果（可能有编码问题）
        try:
            print(result)
        except UnicodeEncodeError:
            print(result.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))
    except Exception as e:
        print("错误: " + str(e))
        import traceback
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
