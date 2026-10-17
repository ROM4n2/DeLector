# -*- coding: utf-8 -*-
"""桌面壳「启动前置」域：WebView2 检测 / 日志落点 / 轮转（C6 Task 6 自 `tests/test_desktop_shell.py` 逐字搬出）。

搬出的段（搬前 `test_desktop_shell.py` 行号，实测，含各段头注释）：
  `61`-`263`   ① WebView2 运行时检测（注册表三处 + pv 值）· ② 日志落点 · ②' 轮转与顺序

断言、用例名与 docstring 逐字未改；只新增本文件的显式 import。跨域共用项
（`_mod` / `_parse_desktop` / `_is_main_guard` / `_calls` / `_call_label`）与
autouse 兜底夹具 `_isolate_data_dir` 住在 `tests/server_helpers.py`，按名 import
即在本模块注册。
"""

import ast
import os
from pathlib import Path
from typing import List, Optional

import pytest
from server_helpers import _call_label, _calls, _is_main_guard, _mod, _parse_desktop
from server_helpers import _isolate_data_dir as _isolate_data_dir


# ── ① WebView2 运行时检测：注册表三处 + pv 值 ────────────────────────────────
def test_webview2_registry_targets_the_edgeupdate_client_guid():
    """检测锚点必须对准 Edge WebView2 的 EdgeUpdate 客户端项（漏/错 ⇒ 已装机器被误报缺失）。

    GUID 与子路径是本任务从本机**实测**读到的落点；写错一位就会让"Win11 自带运行时"被判缺失，
    进而每次启动都弹"请安装 WebView2"——这正是"检测"要防的反向失败。
    """
    mod = _mod()

    assert mod.WEBVIEW2_GUID == "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    assert "EdgeUpdate" in mod.WEBVIEW2_REG_SUBPATH
    assert mod.WEBVIEW2_GUID in mod.WEBVIEW2_REG_SUBPATH, "子路径必须指向该 GUID 的 Clients 项"
    assert mod.WEBVIEW2_PV_VALUE == "pv", "判定值就是注册表项的 pv 字段（本机实测可读）"


def test_webview2_checks_all_three_registry_branches():
    """三处**都要查**：HKLM\\WOW6432Node / HKLM / HKCU（不同机器 / 安装方式落点不同）。

    只查一处 ⇒ 部分已装机器被判缺失。顺序与成员均须稳定：数量少一处 = 漏查。
    """
    mod = _mod()

    assert list(mod.WEBVIEW2_BRANCHES) == ["HKLM_WOW6432", "HKLM", "HKCU"], (
        "必须覆盖 HKLM 的 WOW6432Node、HKLM 原生、HKCU 三处（缺一即可能漏判已装）"
    )


def test_webview2_detected_when_any_branch_has_pv():
    """任一分支读到非空 `pv` ⇒ 判为已装（返回 True）。"""
    mod = _mod()
    seen: List[str] = []

    def fake_read(branch: str) -> Optional[str]:
        seen.append(branch)
        return "154.0.4258.62" if branch == "HKCU" else None

    assert mod.ensure_webview2_runtime(read_pv=fake_read) is True
    assert seen == ["HKLM_WOW6432", "HKLM", "HKCU"], "读到值前必须按序尝试前面的分支"


def test_webview2_missing_when_no_branch_has_pv():
    """三处都没有 `pv`（值缺失 / 空串 / None）⇒ 判为缺失（返回 False），供上层引导安装。"""
    mod = _mod()

    assert mod.ensure_webview2_runtime(read_pv=lambda _b: None) is False
    assert mod.ensure_webview2_runtime(read_pv=lambda _b: "") is False, "空串同样视为缺失"
    assert mod.ensure_webview2_runtime(read_pv=lambda _b: "   ") is False, "纯空白视为缺失"


def test_webview2_stops_at_first_hit_without_touching_later_branches():
    """首个分支命中即短路：不再读后续分支（HKCU 无键时也不得让整条判定失败）。"""
    mod = _mod()
    seen: List[str] = []

    def fake_read(branch: str) -> Optional[str]:
        seen.append(branch)
        return "1.2.3"

    assert mod.ensure_webview2_runtime(read_pv=fake_read) is True
    assert seen == ["HKLM_WOW6432"], "首个命中后不得再读后续分支"


def test_missing_webview2_message_gives_an_install_path():
    """缺失时**不得只抛异常**：提示文案必须给出安装入口（URL），否则"解压即用"被打破。"""
    mod = _mod()

    message = mod.webview2_missing_message()

    assert mod.WEBVIEW2_DOWNLOAD_URL in message, "缺失提示必须含官方安装 URL，用户才知道怎么补"
    assert mod.WEBVIEW2_DOWNLOAD_URL.startswith("https://"), "安装入口必须是可点击的 https 链接"


# ── ② 日志落点：必须在 Task 1 的数据目录下 ───────────────────────────────────
def test_resolve_log_path_lands_in_explicit_data_dir(tmp_path: Path):
    """显式 `DELECTOR_DATA_DIR` ⇒ 日志落该目录下的 `launch.log`（不落程序目录）。"""
    mod = _mod()

    assert mod.resolve_log_path({"DELECTOR_DATA_DIR": str(tmp_path)}) == str(tmp_path / "launch.log")


def test_resolve_log_path_follows_windows_default_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """未显式指定 ⇒ 跟随 Task 1 的 Windows 默认落点 `%LOCALAPPDATA%\\DeLector`。

    复用 `data_dir_bootstrap.resolve_data_dir`（而非自己再推一遍）：两处推法一旦漂移，日志就
    会落到一个"用户不知道、清理时也不会看"的地方 —— 正是崩溃现场丢失的成因。
    """
    from delector.core import data_dir_bootstrap

    mod = _mod()
    monkeypatch.setattr(data_dir_bootstrap, "_is_windows", lambda: True)

    expected = str(tmp_path / "Local" / "DeLector" / "launch.log")

    assert mod.resolve_log_path({"LOCALAPPDATA": str(tmp_path / "Local")}) == expected


def test_resolve_log_path_is_absolute_and_named_launch_log(tmp_path: Path):
    """落点是绝对路径且文件名恒为 `launch.log`（打包后相对路径会落到不可预期的 CWD）。"""
    mod = _mod()

    resolved = mod.resolve_log_path({"DELECTOR_DATA_DIR": str(tmp_path)})

    assert os.path.isabs(resolved)
    assert os.path.basename(resolved) == "launch.log"


# ── ②' 日志轮转：超限滚动为 launch.log.1，新文件从空开始（行为级 + 变异自证）──────
def test_rotate_log_rolls_over_limit_and_resets_new_file(tmp_path: Path):
    """超限的 launch.log 必须滚动为 launch.log.1，且新 launch.log 从空开始。

    **行为级**（不只看源码字符串）：造一份超限的假日志 ⇒ `rotate_log_if_needed` ⇒
    旧档里是原始内容、新路径不再指向旧内容。**变异自证**：注释掉函数体里的 `os.replace`
    ⇒ 本用例转红。
    """
    mod = _mod()
    log_path = tmp_path / "launch.log"
    payload = "x" * (mod.LOG_MAX_BYTES + 1024)
    log_path.write_text(payload, encoding="utf-8")

    rolled = mod.rotate_log_if_needed(str(log_path))

    assert rolled is True, "超限日志必须被滚动（否则 launch.log 无界增长）"
    backup = tmp_path / ("launch.log" + mod.LOG_BACKUP_SUFFIX)
    assert backup.is_file(), "旧档必须滚动到 launch.log.1"
    assert backup.read_text(encoding="utf-8") == payload, "旧档内容必须逐字保留"
    assert not log_path.exists() or log_path.read_text(encoding="utf-8") == "", (
        "滚动后新的 launch.log 必须为空/不存在（从空开始，不残留旧内容）"
    )


def test_rotate_log_keeps_small_file_untouched(tmp_path: Path):
    """未超限 ⇒ 不滚动（原文件原样保留，返回 False）——防止把正常日志也清掉。"""
    mod = _mod()
    log_path = tmp_path / "launch.log"
    log_path.write_text("small\n", encoding="utf-8")

    assert mod.rotate_log_if_needed(str(log_path)) is False
    assert log_path.read_text(encoding="utf-8") == "small\n"
    assert not (tmp_path / "launch.log.1").exists()


def test_rotate_log_overwrites_previous_backup(tmp_path: Path):
    """只保留**一份**旧的：第二次滚动覆盖第一次的 `launch.log.1`。"""
    mod = _mod()
    log_path = tmp_path / "launch.log"
    backup = tmp_path / "launch.log.1"
    backup.write_text("old-backup", encoding="utf-8")
    log_path.write_text("y" * (mod.LOG_MAX_BYTES + 1), encoding="utf-8")

    assert mod.rotate_log_if_needed(str(log_path)) is True
    assert backup.read_text(encoding="utf-8").startswith("yyy"), "旧档必须被本次滚动覆盖"


def test_run_desktop_rotates_before_redirecting_streams():
    """接线钉（**结构层**，非行为）：`run_desktop` 必须在 `_redirect_std_streams` **之前**轮转。

    为什么是结构断言：真跑 `run_desktop` 会进 GUI 循环，CI 拉不起。但它能钉住"轮转确实接进
    启动路径、且在打开两个追加句柄之前"这一顺序约束——少了它，超大日志永不被滚动；
    顺序反了则 Windows 上对已打开文件的 `os.replace` 失败、轮转静默失效。
    """
    mod = _mod()
    src = Path(mod.__file__).read_text(encoding="utf-8")
    body = src.split("def run_desktop(", 1)[1]
    assert "rotate_log_if_needed(" in body, "run_desktop 必须调用 rotate_log_if_needed（否则无界增长）"
    assert body.index("rotate_log_if_needed(") < body.index("_redirect_std_streams("), (
        "轮转必须在重定向/打开追加句柄之前（Windows 上对已打开文件 os.replace 会失败）"
    )


def test_main_guard_rotates_before_ensuring_streams() -> None:
    """接线钉（**结构层**）：`__main__` 里日志轮转必须早于 `ensure_streams`（黄牌 A）。

    比照 `test_run_desktop_rotates_before_redirecting_streams`：那条钉 `run_desktop` 内的同一约束，
    这条钉**入口**（`if __name__ == "__main__":`）。Task 1 把收口提到最前后，入口自己也会
    "先开句柄、后轮转"；顺序一反，Windows 上对已打开文件 `os.replace` 失败、轮转被静默跳过
    ⇒ launch.log 无界增长。真跑 `__main__` 会进 GUI 循环，故只做结构断言（不跑真入口）。

    同时钉 Y5：`resolve_log_path(os.environ)` 在 `__main__` 只应解析**一次**（旧代码轮转、收口
    各解析一遍）。合并后两处共用同一落点，不会因中途改 env 而两处不一致。
    """
    tree = _parse_desktop()
    guard = next(
        (node for node in tree.body if isinstance(node, ast.If) and _is_main_guard(node)),
        None,
    )
    assert guard is not None, "desktop.py 里找不到 `if __name__ == '__main__':` 守卫（前提变了，需重写用例）"

    def _lines(label: str) -> List[int]:
        return [
            call.lineno for stmt in guard.body for call in _calls(stmt) if _call_label(call) == label
        ]

    rotate_lines = _lines("rotate_log_if_needed")
    ensure_lines = _lines("ensure_streams")
    resolve_lines = _lines("resolve_log_path")
    assert rotate_lines, "__main__ 必须先轮转（否则超大 launch.log 无界增长）"
    assert ensure_lines, "__main__ 必须收口标准流（Task 1：--windowed 下 None 流的零线索路径）"
    assert min(rotate_lines) < min(ensure_lines), (
        "轮转必须在收口（打开 launch.log 追加句柄）之前（Windows 上对已打开文件 os.replace 会失败）"
    )
    assert len(resolve_lines) == 1, (
        f"resolve_log_path 在 __main__ 只应解析一次（轮转/收口共用同一落点），实际 {len(resolve_lines)} 次"
    )
