# -*- coding: utf-8 -*-
"""真机 APK 安装辅助：自动点掉 MIUI 的「USB 安装」确认页。

背景（2026-11-13 arm64 真机点检，Redmi Note 8 / MIUI 12 / Android 11）：
`adb install` 在 MIUI 上必然返回
``INSTALL_FAILED_USER_RESTRICTED: Install canceled by user``。**不是**驱动问题、
也**不是**「USB安装」开关没开——而是 MIUI 每次安装都会拉起
``com.miui.securitycenter/.../AdbInstallActivity`` 确认页，**12 秒内无人点
「继续安装」就超时**，并把这个超时报成 "canceled by user"。
``pm install``（shell 权限）、``install --no-streaming``、
``install-create/write/commit`` 分步**全部同样被拦**，唯一有效路径是点那个确认页。

本工具把这条路径固化成一条命令：后台起 ``adb install`` → 轮询
``uiautomator dump`` → 找到确认按钮就 ``input tap`` → 等安装结束、按退出码判定。
``parse_confirm_button()`` 是纯函数，可在无设备环境单测（见
``tests/test_install_apk_helper.py``）。

用法::

    python tools/install_apk.py app-device-debug.apk
    python tools/install_apk.py app.apk --serial cdb66c --adb D:/Android/sdk/platform-tools/adb.exe
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time

# 确认按钮的文本白名单。MIUI 是「继续安装」，AOSP 是「安装」/「Install」。
CONFIRM_TEXTS = ("继续安装", "安装", "Install", "继续", "确定", "確定")
# 「拒绝/取消」必须排除：MIUI 的拒绝按钮会带倒计时（如「拒绝(7)」），
# 若只按「包含『继续』」匹配不会误中，但「安装」会被「继续安装」与
# 某些语言包的「安装应用？」同时命中，故保留显式黑名单。
DENY_WORDS = ("拒绝", "取消", "Cancel", "Deny", "Reject")

_NODE_RE = re.compile(r"<node\b[^>]*>")
_TEXT_RE = re.compile(r'\btext="([^"]*)"')
_BOUNDS_RE = re.compile(r'\bbounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')


def parse_confirm_button(xml: str) -> tuple[int, int] | None:
    """从 ``uiautomator dump`` 的 XML 里找确认按钮中心点；找不到返回 None。

    纯函数：只吃 XML 文本，不碰设备，便于用真实 dump 片段做阳性/阴性/变异自证。
    """
    for node in _NODE_RE.findall(xml):
        m_text = _TEXT_RE.search(node)
        m_bounds = _BOUNDS_RE.search(node)
        if not m_text or not m_bounds:
            continue
        text = m_text.group(1).strip()
        if not text or any(bad in text for bad in DENY_WORDS):
            continue
        if text not in CONFIRM_TEXTS:
            continue
        x1, y1, x2, y2 = (int(g) for g in m_bounds.groups())
        if x2 <= x1 or y2 <= y1:
            continue  # bounds=[0,0][0,0] = 未布局，不可点
        return (x1 + x2) // 2, (y1 + y2) // 2
    return None


def _adb_cmd(adb: str, serial: str | None, *args: str) -> list[str]:
    cmd = [adb]
    if serial:
        cmd += ["-s", serial]
    cmd += list(args)
    return cmd


def _dump_ui(adb: str, serial: str | None, remote: str) -> str:
    subprocess.run(
        _adb_cmd(adb, serial, "shell", "uiautomator", "dump", remote),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    cat = subprocess.run(
        _adb_cmd(adb, serial, "shell", "cat", remote),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    return cat.stdout or ""


def install(
    apk: str,
    *,
    adb: str = "adb",
    serial: str | None = None,
    poll_seconds: float = 20.0,
    timeout: float = 300.0,
) -> tuple[bool, bool, str]:
    """跑一次安装并自动点确认页。

    返回 ``(succeeded, tapped, output)``：
    - ``succeeded``：``adb install`` 退出码为 0
    - ``tapped``：是否真的点到了确认页（False 常见于非 MIUI 设备，无需点）
    """
    cmd = _adb_cmd(adb, serial, "install", "-r", "-t", apk)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    remote = "/sdcard/uiautomator-install.xml"
    tapped = False
    deadline = time.monotonic() + poll_seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break  # 已经装完（非 MIUI 设备通常在 10s 内返回）
        time.sleep(0.8)
        pos = parse_confirm_button(_dump_ui(adb, serial, remote))
        if pos is None:
            continue
        subprocess.run(
            _adb_cmd(adb, serial, "shell", "input", "tap", str(pos[0]), str(pos[1])),
            capture_output=True,
            timeout=30,
        )
        tapped = True
        break

    try:
        out = proc.communicate(timeout=timeout)[0] or ""
    except subprocess.TimeoutExpired:
        proc.kill()
        out = (proc.communicate()[0] or "") + "\n[install_apk] adb install 超时被终止"
    succeeded = proc.returncode == 0
    return succeeded, tapped, out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="安装 APK 并自动点掉 MIUI 的 USB 安装确认页")
    parser.add_argument("apk", help="APK 路径")
    parser.add_argument("--adb", default=shutil.which("adb") or "adb", help="adb 可执行文件路径")
    parser.add_argument("--serial", default=None, help="多设备时指定序列号")
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=20.0,
        help="等确认页出现的上限（默认 20s；MIUI 的确认页倒计时只有 12s）",
    )
    args = parser.parse_args(argv)

    succeeded, tapped, out = install(
        args.apk, adb=args.adb, serial=args.serial, poll_seconds=args.poll_seconds
    )
    tail = "\n".join(line for line in out.strip().splitlines() if line.strip())[-1200:]
    print(tail)
    print(f"[install_apk] tapped_confirm={tapped} succeeded={succeeded}")
    if not succeeded:
        print(
            "[install_apk] 失败：若输出含 INSTALL_FAILED_USER_RESTRICTED，先确认"
            "「开发者选项 → USB安装」已开（点右侧开关，点文字区无效），再重跑本工具。",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
