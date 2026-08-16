# -*- coding: utf-8 -*-
"""
本机网络连通性检测：Ping 公网 IP / 域名、查看 ipconfig /all 与 route print，并给出简要结论。

用法（建议在仓库根目录执行）::

    python scripts/network_diag.py

可选：仅输出摘要（不打印完整 ipconfig/route，适合快速扫一眼）::

    python scripts/network_diag.py --brief

说明：需能调用系统自带的 ping、ipconfig、route（Windows）；若被安全软件拦截子进程，可能无输出或报错。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# 仓库根目录（用于文档化路径，便于从任意 cwd 运行）
_ROOT = Path(__file__).resolve().parent.parent

# Windows 控制台常见为 GBK，子进程输出按此解码；其它平台用 utf-8
if sys.platform == "win32":
    _SUBPROC_ENC = "gbk"
else:
    _SUBPROC_ENC = "utf-8"


def _run_cmd(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """
    执行外部命令，返回 (退出码, stdout, stderr)。
    超时或异常时退出码为 -1，错误信息在 stderr 拼接字符串中。
    """
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            encoding=_SUBPROC_ENC,
            errors="replace",
        )
        out = proc.stdout or ""
        err = proc.stderr or ""
        return proc.returncode, out, err
    except subprocess.TimeoutExpired:
        return -1, "", f"命令超时 ({timeout}s): {' '.join(args)}"
    except OSError as e:
        return -1, "", f"无法执行命令: {' '.join(args)} — {e}"


def _ping_ok(text: str) -> bool:
    """
    根据 ping 标准输出判断是否至少收到一次 ICMP 回复（粗略判断，不区分防火墙策略）。
    """
    t = text.lower()
    # 英文环境：Reply from ... bytes= ... time= ... TTL=
    if "ttl=" in t or "reply from" in t:
        return True
    # 中文环境：来自 x.x.x.x 的回复
    if "来自" in text and "的回复" in text:
        return True
    # 统计行：已接收为 0 表示全丢
    if re.search(r"已接收\s*=\s*0", text) or re.search(r"received\s*=\s*0", t):
        return False
    if re.search(r"丢失\s*=\s*[12]\s*\(100%", text) or "100% loss" in t:
        return False
    return False


def _section(title: str) -> None:
    """打印分节标题，便于阅读。"""
    line = "=" * min(72, max(len(title) + 4, 16))
    print()
    print(line)
    print(f" {title}")
    print(line)


def _print_cmd_block(title: str, args: list[str], timeout: int = 25) -> tuple[int, str]:
    """执行命令并打印完整输出，返回 (returncode, stdout)。"""
    _section(title)
    print(f"$ {' '.join(args)}")
    code, out, err = _run_cmd(args, timeout=timeout)
    if out:
        print(out.rstrip())
    if err.strip():
        print(err.rstrip(), file=sys.stderr)
    print(f"[退出码: {code}]")
    return code, out


def _brief_hint(ip_ok: bool, dns_ok: bool) -> None:
    """根据 Ping IP / Ping 域名结果给出简短文字提示。"""
    _section("结论（仅供参考）")
    if ip_ok and dns_ok:
        print("Ping 公网 IP 与域名均正常：本机到互联网路径与 DNS 解析大致无异常。")
        print("若浏览器仍无法上网，请检查：系统代理、浏览器代理扩展、防火墙或安全软件。")
    elif ip_ok and not dns_ok:
        print("Ping 公网 IP 正常，但 Ping 域名失败：多为 DNS 问题。")
        print("可尝试：更换 DNS（如 223.5.5.5 / 119.29.29.29）、检查 hosts、关闭错误的手动代理。")
    elif not ip_ok and not dns_ok:
        print("Ping IP 与域名均失败：请检查网线/Wi‑Fi、路由器、光猫、是否欠费，以及本机是否拿到有效 IP/网关。")
    else:
        # 理论上 IP 不通时域名也可能因解析先失败，此处兜底
        print("结果不一致或无法判断，请结合上方原始输出与 ipconfig / route 排查。")


def main() -> int:
    # 命令行参数：--brief 时跳过冗长的 ipconfig / route 输出
    parser = argparse.ArgumentParser(description="本机网络连通性检测")
    parser.add_argument(
        "--brief",
        action="store_true",
        help="仅打印 ping 与结论，不输出完整 ipconfig / route",
    )
    args = parser.parse_args()

    print(f"工作目录: {Path.cwd()}")
    print(f"脚本位置: {Path(__file__).resolve()}")

    # ---------- Ping：不依赖 DNS ----------
    _, out_ip = _print_cmd_block(
        "1) Ping 公网 IP（检测是否可达外网，不依赖 DNS）",
        ["ping", "-n", "2", "8.8.8.8"],
        timeout=15,
    )
    ip_ok = _ping_ok(out_ip)

    # ---------- Ping：依赖 DNS ----------
    _, out_dns = _print_cmd_block(
        "2) Ping 域名（检测 DNS 解析 + 连通性）",
        ["ping", "-n", "2", "www.baidu.com"],
        timeout=20,
    )
    dns_ok = _ping_ok(out_dns)

    _brief_hint(ip_ok, dns_ok)

    if args.brief:
        print()
        print("（已使用 --brief，跳过 ipconfig / route。去掉 --brief 可查看完整网卡与路由表。）")
        return 0

    # ---------- 网卡与地址（Windows）----------
    if sys.platform == "win32":
        _print_cmd_block(
            "3) 网卡与 IP / 网关 / DNS（ipconfig /all）",
            ["ipconfig", "/all"],
            timeout=15,
        )
        _print_cmd_block(
            "4) 路由表（route print，用于确认默认网关）",
            ["route", "print"],
            timeout=15,
        )
    else:
        _section("3) 非 Windows 系统")
        print("当前脚本主要针对 Windows 的 ipconfig / route。")
        print("在 Linux/macOS 上请手动执行: ip addr / ip route 或 ifconfig / netstat -rn")

    _section("结束")
    print("检测完成。若需刷新本机 DNS 缓存（管理员 CMD/PowerShell）：ipconfig /flushdns")
    return 0


if __name__ == "__main__":
    sys.exit(main())
