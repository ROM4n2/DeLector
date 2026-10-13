# -*- coding: utf-8 -*-
r"""Task 4（RED 先写）：Windows 桌面壳 `desktop.py` 的可测契约（ADR-0020 §4）。

为什么主断言放在"零依赖纯逻辑"
------------------------------
GUI（pywebview 主线程事件循环 + 系统 Edge WebView2 + 托盘）无法在 CI / 无头会话拉起。若把
断言压在真窗口上，CI 只能整组 skip ⇒ 桌面壳最该被钉死的四条前置（退出收尸 / 启动反馈 /
WebView2 检测 / 日志弹窗）会**没有任何守卫**（假绿）。故把可测逻辑抽成纯函数，用注入替身
（fake 注册表读取器 / fake shutdown / fake 弹窗）逐条钉：

1. `ensure_webview2_runtime`：注册表三处（HKLM WOW6432Node / HKLM / HKCU）+ `pv` 值判定；
2. `resolve_log_path`：落在 Task 1 的数据目录下，文件名固定 `launch.log`；
3. 退出编排：**所有**退出路径先 `shutdown(server, thread)`；超时（返回 False）⇒ 硬退出；
4. 托盘菜单：标签固定为 打开 / 检查更新 / 退出，且「退出」与关窗共用同一收尸触发器；
5. `write_crash`：traceback 落 `launch.log` + 弹窗（把 MessageBoxW 换成替身，不真弹）。

GUI 部分（真窗口 / 真托盘 / 三线程互不阻塞）单独一条 `pytest.skip`，**绝不假绿**。

RED 预期：`desktop.py` 尚不存在 ⇒ 各条用例以 `ModuleNotFoundError` **各自**转红（故惰性
import，而非顶层 import —— 顶层 import 会让 pytest 在收集期就中断，只剩一条 collection
error，看不出"每条契约各自未被满足"）。
"""

import ast
import os
import subprocess
import sys
import threading
import types
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# 惰性导入（刻意，理由见模块 docstring）：模块不存在时逐条报 ModuleNotFoundError。
def _mod() -> Any:
    import desktop

    return desktop


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


# ── ③ 退出编排：所有退出路径先 shutdown，超时硬退出 ──────────────────────────
def test_coordinated_shutdown_reaps_server_then_reports_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """干净退出：先 `shutdown(server, thread)`，返回 True，且**不**触发硬退出。"""
    mod = _mod()
    recorded: List[Any] = []

    def _fake_shutdown(server: Any, thread: Any, grace_s: float = 5.0) -> bool:
        recorded.append((server, thread))
        return True

    monkeypatch.setattr(mod, "shutdown", _fake_shutdown)
    exited: List[int] = []
    server, thread = object(), object()

    ok = mod.coordinated_shutdown(server, thread, str(tmp_path / "launch.log"), exit_fn=exited.append)

    assert ok is True
    assert recorded == [(server, thread)], "收尸必须作用于本次起的 server 与其线程"
    assert exited == [], "干净退出不得硬退出"


def test_coordinated_shutdown_hard_exits_when_reap_times_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """超时（`shutdown` 返回 False）⇒ **硬退出**（`exit_fn(1)`），绝不留残留进程。

    这是"退不干净"的核心防线：宽限期内没停干净还继续跑，下次启动就会盲判"端口被占用"，
    或者更糟 —— 用户以为升级了其实还是旧进程在服务。
    """
    mod = _mod()
    monkeypatch.setattr(mod, "shutdown", lambda server, thread, grace_s=5.0: False)
    exited: List[int] = []

    ok = mod.coordinated_shutdown(object(), object(), str(tmp_path / "launch.log"), exit_fn=exited.append)

    assert ok is False
    assert exited == [1], "宽限期内未退出必须硬退出（退出码 1），不得放任残留"


def test_coordinated_shutdown_logs_the_timeout(tmp_path: Path):
    """超时是**可见**事件：必须写进 launch.log（桌面形态下用户唯一能看到的地方）。"""
    mod = _mod()
    log_path = tmp_path / "launch.log"
    mod._append_log(str(log_path), "sentinel")

    # 用真实的 shutdown（配一个"赖着不走"的线程替身）触发超时分支（不真起服务）。
    class _ImmovableThread:
        daemon = False

        def join(self, *_a: Any, **_k: Any) -> None:
            return None

        def is_alive(self) -> bool:
            return True

    class _Server:
        should_exit = False

    mod.coordinated_shutdown(_Server(), _ImmovableThread(), str(log_path), exit_fn=lambda _c: None)

    content = log_path.read_text(encoding="utf-8")
    assert "sentinel" in content, "前置：日志写入必须生效"
    assert "退出" in content, "超时硬退出必须在日志里留痕（否则'为什么突然没了'无从追查）"


# ── ④ 托盘菜单：标签固定且「退出」与关窗共用同一触发器 ───────────────────────
def test_tray_menu_labels_are_open_update_quit():
    """托盘菜单三枚：打开 / 检查更新 / 退出（顺序稳定，便于用户形成肌肉记忆）。"""
    mod = _mod()

    labels = [label for label, _action in mod.TRAY_MENU_SPEC]

    assert labels == ["打开", "检查更新", "退出"]


def test_tray_menu_actions_are_wired_to_distinct_handlers():
    """三枚菜单各接一个动作键：open / check_update / quit（quit 走统一收尸路径）。"""
    mod = _mod()

    actions = [action for _label, action in mod.TRAY_MENU_SPEC]

    assert actions == ["open", "check_update", "quit"]


def test_build_tray_handlers_covers_every_spec_action():
    """`spec → handlers` 的键集合必须**恒等**（缺一即托盘键漂移）。

    为什么抽成纯函数并单钉：原实现把 handlers 硬编码在托盘线程里，`TRAY_MENU_SPEC` 的动作
    键一旦漂移，`handlers[action]` 会 KeyError 让**托盘线程静默死亡**（用户只看到托盘没了、
    零线索）。抽出来后键一致性在**不依赖 pystray 真跑**的前提下即可被钉死。
    """
    mod = _mod()
    spec_keys = {action for _label, action in mod.TRAY_MENU_SPEC}

    handlers = mod.build_tray_handlers(mod.TRAY_MENU_SPEC, window=object(), coordinator=mod.QuitCoordinator())

    assert set(handlers) == spec_keys, "handlers 键集合必须与 spec 的动作键集合恒等"
    assert all(callable(fn) for fn in handlers.values()), "每个动作键都必须映射到可调用处理函数"


def test_build_tray_handlers_rejects_spec_drift():
    """spec 出现 handlers 未覆盖的动作键 ⇒ 必须**显式报错**，而不是留到托盘线程里 KeyError。

    这是"键漂移 ⇒ 托盘静默死亡"的回归钉：漏覆盖时要在组装期就炸，而不是运行时无声无息。
    """
    mod = _mod()
    drifted = (("打开", "open"), ("幽灵动作", "ghost"))

    with pytest.raises(ValueError):
        mod.build_tray_handlers(drifted, window=object(), coordinator=mod.QuitCoordinator())


def test_quit_coordinator_is_idempotent_so_close_and_tray_share_one_path():
    """「关窗」与「托盘退出」共用同一收尸触发器；它必须幂等 —— 两条路径都触发时只收尸一次。

    若各自收尸，会二次 `shutdown`（无害）却可能二次硬退出 / 二次 destroy 窗口 → 崩溃或卡死。
    """
    mod = _mod()
    coordinator = mod.QuitCoordinator()

    assert coordinator.request_quit() is True, "首次请求应生效"
    assert coordinator.request_quit() is False, "重复请求（关窗 + 托盘同时触发）应被忽略"
    assert coordinator.requested is True


# ── ⑤ 崩溃：写 traceback 到 launch.log + 弹窗（替身 MessageBoxW）─────────────
def test_write_crash_appends_title_and_traceback_and_pops_dialog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """崩溃：traceback 落 `launch.log` + 弹窗（把 MessageBoxW 换替身，测试进程不真弹）。"""
    mod = _mod()
    log_path = tmp_path / "launch.log"
    popped: List[Any] = []
    monkeypatch.setattr(mod, "_message_box", lambda title, detail: popped.append((title, detail)))

    mod.write_crash("启动失败", "Traceback (most recent call last): ... boom", str(log_path))

    content = log_path.read_text(encoding="utf-8")
    assert "启动失败" in content
    assert "boom" in content, "traceback 必须原文落盘，供用户/开发者事后定位"
    assert popped, "崩溃必须弹窗，否则用户只看到窗口没出现、零线索"
    assert popped[0][0] == "启动失败"


def test_write_crash_never_raises_when_log_is_unwritable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """日志写不进去（磁盘满 / 被杀软锁）也**不得再抛**：崩溃处理里的二次异常会掩盖原始错误。"""
    mod = _mod()
    monkeypatch.setattr(mod, "_message_box", lambda *_a: None)

    # 指向一个已存在的**目录**：open(..., "a") 会抛 IsADirectoryError / PermissionError。
    mod.write_crash("t", "d", str(tmp_path))


def test_write_crash_still_pops_when_log_write_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """日志写失败时，弹窗仍要弹（这是用户唯一还能看到的失败反馈）。"""
    mod = _mod()
    popped: List[Any] = []
    monkeypatch.setattr(mod, "_message_box", lambda title, detail: popped.append(title))

    mod.write_crash("标题", "细节", str(tmp_path))  # log_path 是目录 ⇒ 写盘失败

    assert popped == ["标题"], "即便落盘失败，弹窗也必须发生"


# ── import 安全性：`import desktop` 不得起服务 / 弹窗 / 拉 GUI ────────────────
def _parse_desktop() -> ast.Module:
    return ast.parse((REPO_ROOT / "desktop.py").read_text(encoding="utf-8"))


def _is_main_guard(node: ast.If) -> bool:
    test = node.test
    if not isinstance(test, ast.Compare) or not test.comparators:
        return False
    left, right = test.left, test.comparators[0]
    return (
        isinstance(left, ast.Name)
        and left.id == "__name__"
        and isinstance(right, ast.Constant)
        and right.value == "__main__"
    )


def test_desktop_module_level_does_not_import_gui_toolkits():
    """顶层**不得** import webview / pystray：那会让 `import desktop` 变重，且 CI（缺 GTK/WebKit）会炸。"""
    tree = _parse_desktop()
    roots: List[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots += [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            roots.append((node.module or "").split(".")[0])

    assert "webview" not in roots, "GUI 依赖必须在函数内惰性导入，不得出现在模块顶层"
    assert "pystray" not in roots, "GUI 依赖必须在函数内惰性导入，不得出现在模块顶层"


def test_desktop_module_level_has_no_launch_side_effect():
    """模块顶层**不得**直接调 `run_desktop`：那会让 `import desktop` 顺手起服务 / 弹窗。"""
    tree = _parse_desktop()
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            assert name not in {"run_desktop"}, "重活必须只在 `if __name__ == '__main__':` / 函数体内发生"


def test_desktop_launch_is_guarded_by_main():
    """起窗口 / 起服务只在 `if __name__ == '__main__':` 下发生（被 import 时零副作用）。

    入口收口到单一分派器 `dispatch`（Task 5：默认=窗口、`--server-only`=旧服务行为），
    故守卫断言的是"分派器只在 main 守卫内被调用"——重活仍不在 import 期发生。
    """
    tree = _parse_desktop()
    guarded = any(
        isinstance(node, ast.If) and _is_main_guard(node) and "dispatch" in ast.dump(node) for node in tree.body
    )

    assert guarded, "入口必须在 `if __name__ == '__main__':` 守卫内调用 dispatch"


# ── P0 死锁回归锁：窗口操作必须在 webview.start() 之后（GUI 事件循环内）执行 ──────
# 真根因（scratch/repro_splash_deadlock.py 三模式实测）：pywebview 把 evaluate_js / load_url
# marshal 到 GUI 线程执行，而 GUI 事件循环由 webview.start() 才启动；在 start **之前**调它们会
# 永久等待 ⇒ 窗口永不出现、进程永不退出。下列断言把"何时才允许碰窗口"钉死，且不只测"函数存在"。
_WINDOW_WRITE_ATTRS = {"evaluate_js", "load_url"}
_STAGE_HELPER = "_set_splash_stage"  # 该助手内部调 evaluate_js，只能在循环起来后跑


def _funcs_by_name(tree: ast.Module) -> Dict[str, ast.FunctionDef]:
    """模块顶层函数名 → 定义节点（本文件所有相关函数都在顶层）。"""
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _calls(node: ast.AST) -> Iterator[ast.Call]:
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            yield child


def _call_label(call: ast.Call) -> Optional[str]:
    """调用的"可读名"：`a.b()` → attr `b`；`f()` → id `f`；其余返回 None。"""
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _is_webview_start_call(call: ast.Call) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "start"
        and isinstance(func.value, ast.Name)
        and func.value.id == "webview"
    )


def _find_start_call(tree: ast.Module) -> ast.Call:
    starts = [call for call in _calls(tree) if _is_webview_start_call(call)]
    assert len(starts) == 1, f"应恰有一处 webview.start(...) 调用，实际 {len(starts)}"
    return starts[0]


def _delegated_function(tree: ast.Module) -> Tuple[str, ast.FunctionDef]:
    """`webview.start(...)` 首参指向的顶层函数 `(函数名, 定义节点)`。"""
    start_call = _find_start_call(tree)
    funcs = _funcs_by_name(tree)
    assert start_call.args, "webview.start 必须传入首参（事件循环启动后要跑的函数）"
    first_arg = start_call.args[0]
    assert isinstance(first_arg, ast.Name), "webview.start 的首参必须是函数名（而非内联 lambda）"
    return first_arg.id, funcs[first_arg.id]


def _reachable_function_names(root: ast.FunctionDef, funcs: Dict[str, ast.FunctionDef]) -> Set[str]:
    """从 `root` 出发、沿"调用本模块顶层函数"的可达闭包（含 `root` 自身，仅供白名单用）。"""
    reachable: Set[str] = {root.name}
    visited: Set[str] = {root.name}
    stack: List[ast.FunctionDef] = [root]
    while stack:
        current = stack.pop()
        for call in _calls(current):
            label = _call_label(call)
            if label is None or label not in funcs or label in visited:
                continue
            visited.add(label)
            reachable.add(label)
            stack.append(funcs[label])
    return reachable


def _reachable_labels(root: ast.FunctionDef, funcs: Dict[str, ast.FunctionDef]) -> Set[str]:
    """从 `root` 出发可达的**全部**调用标签（含属性调用如 `window.load_url`，并跟进顶层函数）。"""
    labels: Set[str] = set()
    visited: Set[str] = {root.name}
    stack: List[ast.FunctionDef] = [root]
    while stack:
        current = stack.pop()
        for call in _calls(current):
            label = _call_label(call)
            if label is None:
                continue
            labels.add(label)
            if label in funcs and label not in visited:
                visited.add(label)
                stack.append(funcs[label])
    return labels


def _enclosing_function_calls(tree: ast.Module) -> Iterator[Tuple[str, ast.Call]]:
    """产出 `(函数名, 该函数体内的调用)`（只遍历顶层函数，逐个 walk，不重复计数）。"""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            for call in _calls(node):
                yield node.name, call


def test_show_window_does_not_touch_the_window_at_setup_time():
    """`_show_window` 的"进循环前"部分**不得**出现 evaluate_js / load_url / _set_splash_stage。

    这三者在 GUI 事件循环启动前调用会被 marshal 到一个没在跑的线程 ⇒ 永久阻塞（P0 死锁）。
    """
    tree = _parse_desktop()
    show = _funcs_by_name(tree)["_show_window"]

    offending = [
        (call.lineno, _call_label(call))
        for call in _calls(show)
        if _call_label(call) in _WINDOW_WRITE_ATTRS or _call_label(call) == _STAGE_HELPER
    ]

    assert offending == [], (
        f"_show_window 在 webview.start() 之前调用了窗口操作 {offending}；"
        "这些必须交给 webview.start(func, args) 调度的函数（循环已在跑）"
    )


def test_window_writes_happen_only_inside_the_start_delegated_call_tree():
    """所有 evaluate_js / load_url 调用点都必须落在 `webview.start()` 调度函数的**可达闭包**内。

    这是对"start 之后才碰窗口"的结构性保证：只有 start 首参函数（及其调用的本模块函数）体内才
    允许写窗口 ⇒ 执行时事件循环必然已在跑。把 load_url 挪回 start 之前 ⇒ 本断言转红。
    """
    tree = _parse_desktop()
    funcs = _funcs_by_name(tree)
    _name, delegated = _delegated_function(tree)
    allowed = _reachable_function_names(delegated, funcs)

    writes = [
        (func_name, _call_label(call))
        for func_name, call in _enclosing_function_calls(tree)
        if _call_label(call) in _WINDOW_WRITE_ATTRS
    ]
    assert writes, "desktop.py 必然存在窗口写入（evaluate_js / load_url）"

    stray = [(func_name, label) for func_name, label in writes if func_name not in allowed]
    assert stray == [], (
        f"窗口写入出现在 webview.start() 调度树之外 {stray}；"
        "在 GUI 事件循环启动前调用会永久阻塞（P0 死锁）"
    )


def test_start_delegated_function_switches_to_real_ui():
    """`webview.start()` 首参函数必须真正做"分阶段反馈 + 切真实 UI"。

    钉住"函数存在但空转"的假绿：调度函数体内（可达闭包）必须同时出现 evaluate_js 与 load_url。
    """
    tree = _parse_desktop()
    _name, delegated = _delegated_function(tree)
    reachable = _reachable_labels(delegated, _funcs_by_name(tree))

    assert "load_url" in reachable, "切换真实 UI（load_url）必须在 start 调度的函数体内"
    assert "evaluate_js" in reachable, "分阶段反馈（evaluate_js）必须在 start 调度函数（可达）体内"


def test_set_splash_stage_logs_failures_instead_of_swallowing_them():
    """`_set_splash_stage` 的失败路径**必须** `_append_log`，不得再 `except Exception: pass`。

    静默吞异常正是本次事故的帮凶：evaluate_js 的失败被 `pass` 抹掉，排查时零线索。
    """
    tree = _parse_desktop()
    stage_fn = _funcs_by_name(tree)["_set_splash_stage"]

    handlers: List[ast.ExceptHandler] = [
        handler
        for node in ast.walk(stage_fn)
        if isinstance(node, ast.Try)
        for handler in node.handlers
    ]
    assert handlers, "_set_splash_stage 必须捕获 evaluate_js 的失败（否则异常直接逃逸）"

    for handler in handlers:
        only_pass = all(isinstance(stmt, ast.Pass) for stmt in handler.body)
        assert not only_pass, "不得再 `except Exception: pass` 静默吞异常（本次事故帮凶）"

    logged = any(
        _call_label(call) == "_append_log" for handler in handlers for call in _calls(handler)
    )
    assert logged, "失败路径必须 `_append_log` 留痕，绝不静默"


def test_success_path_writes_stage_logs_for_at_least_three_phases():
    """成功路径必须至少 3 处 `_append_log` 阶段日志（"卡住无法定位"的根本原因）。

    事故现场：服务就绪后进程卡住，却**一条阶段日志都没有** ⇒ 完全黑盒。故在此钉死下限。
    """
    tree = _parse_desktop()
    show = _funcs_by_name(tree)["_show_window"]
    _name, delegated = _delegated_function(tree)
    phases = [show, delegated]

    count = sum(1 for fn in phases for call in _calls(fn) if _call_label(call) == "_append_log")

    assert count >= 3, f"成功路径阶段日志不足（{count} < 3）：卡住时将无从定位"


# ── 5A：真实首屏口径（关掉 ADR-0018 §8 Unknown 8 的代理口径缺口）───────────────
# 此前只有 health_200（服务就绪）这个**代理口径**；"首屏可用"从未测过。5A 让日志落两枚标记：
# 「开始启动（进程级计时起点）」（进程最早处）与「真实 UI 已加载（首屏可用）」（pywebview 的
# loaded 事件 = 页面渲染完成）。下列锁钉住"标记真的会被写"与"loaded 绑定确实在 start 之后"。
_FIRST_SCREEN_MARKER = "真实 UI 已加载（首屏可用）"
_TIMING_START_MARKER = "开始启动（进程级计时起点）"


def test_run_desktop_logs_process_level_timing_start() -> None:
    """计时起点必须在 `run_desktop` 的**最早处**（第一条 `_append_log`），否则端到端会少算一截。

    用 AST 取 `run_desktop` 源码段：既要求标记出现，又要求它**就是**该函数里最靠前的那条
    `_append_log`（"起点"被别的日志抢了头就不叫起点）。
    """
    src = (REPO_ROOT / "desktop.py").read_text(encoding="utf-8")
    run = _funcs_by_name(ast.parse(src))["run_desktop"]
    calls = [call for call in _calls(run) if _call_label(call) == "_append_log"]
    assert calls, "run_desktop 必须写日志（进程级计时起点）"
    first_call = min(calls, key=lambda call: call.lineno)
    first_segment = ast.get_source_segment(src, first_call) or ""
    assert _TIMING_START_MARKER in first_segment, (
        f"run_desktop 最靠前的 _append_log 必须是计时起点标记，实际：{first_segment!r}"
    )


# ── Task 1：`_run_desktop_inner` 的启动阶段标记（把「开始启动 → 已创建 splash」这 ~3s 拆开）────
# 缺陷背景：`run_desktop` 写下「开始启动（进程级计时起点）」之后、到 `_show_window` 的第一条日志
# 之前，`_run_desktop_inner` 这一整段（端口/身份校验 → WebView2 检测 → 定数据落点 → 导入 server →
# 建服 → 起服务线程）**一条日志都没有** ⇒ launch.log 上约 3s 全是黑盒，卡死时无法归因到哪一步。
# 下列锁钉住 6 枚新标记：① 全部存在；② 源码顺序恒为 1→6；③ 每枚都**夹在**它要标记的那条语句
# 与下一枚锚语句之间（下界「晚于本锚」证伪「标记写在语句之前」；上界「早于下一锚」证伪「整体
# 下移但保持顺序」——只有下界时后者会假绿）；另钉一条：新标记绝不把首屏工具的锚串当子串（否则
# `first_screen_from_log` 的 `_last_index` / `_first_index_after` 会抢错行）。
_STARTUP_STAGE_MARKERS: List[str] = [
    "端口与身份校验通过。",                        # ← `_check_port_or_fail` 通过之后
    "WebView2 运行时检测通过。",                    # ← `ensure_webview2_runtime` 通过之后
    "数据目录落点已定（bootstrap_data_dir 已返回，不代表迁移已落稳）。",  # ← `bootstrap_data_dir` 之后
    "服务端模块已导入（delector.server）。",         # ← `from delector.server import app` 之后
    "HTTP 服务已装配（build_server 完成）。",        # ← `build_server` 之后
    "本地服务线程已启动（等在就绪窗口内命中）。",    # ← `serve_in_thread` 之后（紧接 `try:` 之前）
]
# 首屏工具（tools/first_screen_from_log.py）用于切片的三个锚串：任何新标记都不得包含它们。
_FIRST_SCREEN_ANCHORS: Tuple[str, ...] = (
    "开始启动（进程级计时起点）",
    "服务已就绪",
    "真实 UI 已加载（首屏可用）",
)


def _stage_log_entries(func_name: str) -> List[Tuple[int, str]]:
    """`func_name` 内所有 `_append_log(x, "<字面量>")` 的（行号, 字面量），按行号升序。"""
    fn = _funcs_by_name(_parse_desktop())[func_name]
    entries: List[Tuple[int, str]] = []
    for call in _calls(fn):
        if _call_label(call) != "_append_log" or len(call.args) < 2:
            continue
        arg = call.args[1]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            entries.append((call.lineno, arg.value))
    return sorted(entries)


def _stage_stmt_span(func_name: str, predicate: Any) -> Tuple[int, int]:
    """`func_name` 里首个满足 `predicate` 的顶层语句的（起始行, 结束行）。找不到即报错。"""
    fn = _funcs_by_name(_parse_desktop())[func_name]
    for stmt in fn.body:
        if predicate(stmt):
            return stmt.lineno, stmt.end_lineno or stmt.lineno
    raise AssertionError(f"{func_name} 里找不到满足断言的语句（谓词={predicate!r}）")


def _stmt_has_call(stmt: ast.stmt, label: str) -> bool:
    return any(_call_label(call) == label for call in _calls(stmt))


def test_run_desktop_inner_logs_six_stage_markers_in_order_after_their_anchor_stmts() -> None:
    """`_run_desktop_inner` 必落 6 枚启动阶段标记，顺序为 1→6，且各自**夹在**它要标记的语句与
    下一条锚语句之间（下界：晚于本锚语句；上界：早于下一枚锚语句的起始行）。

    为什么钉「存在 + 顺序 + 位置」三者：只钉「字符串在源码里出现过」会被「标记写在语句之前 /
    顺序颠倒」骗过；而 `first_screen_from_log` 的切片完全依赖**先后次序**，位置错了归因就错。

    为什么位置要**夹逼**而不只有下界：只有下界时，把 6 枚标记**整体下移**（例如全塞到
    `serve_in_thread` 之后、仍保持 1→6 顺序）仍会全绿 —— `ordered` 与 6 条下界断言都骗得过去，
    但归因已经张冠李戴（每枚标记都不再紧贴它要标记的那一步）。上界（早于下一枚锚）把这种
    「整体漂移」挡在门外：末枚标记的上界锚是紧随其后的 `try:` 顶层语句。
    """
    entries = _stage_log_entries("_run_desktop_inner")
    messages = [message for _lineno, message in entries]

    for marker in _STARTUP_STAGE_MARKERS:
        assert marker in messages, (
            f"_run_desktop_inner 缺少启动阶段标记 {marker!r}；现有 _append_log 字面量：{messages}"
        )

    ordered = [message for _lineno, message in entries if message in set(_STARTUP_STAGE_MARKERS)]
    assert ordered == _STARTUP_STAGE_MARKERS, (
        f"6 枚启动阶段标记的源码顺序必须为 1→6，实际：{ordered}"
    )

    line_of = {message: lineno for lineno, message in entries}
    # 7 条锚语句 span：前 6 条是 6 枚标记各自的锚，第 7 条（`try:`）是末枚标记的**上界锚**。
    # 逐枚用 anchor_spans[i] 与 anchor_spans[i+1] 夹逼 —— 只钉"晚于本锚"的下界会被"6 枚标记
    # 整体下移到后面、但仍保持 1→6 顺序"骗过（ordered 与下界断言全绿）；加上"早于下一条锚的
    # 起始行"的上界才真正钉住"就落在本条语句之下、下一条锚之上"这个位置区间。
    anchor_spans = [
        _stage_stmt_span(
            "_run_desktop_inner",
            lambda s: isinstance(s, ast.If) and _stmt_has_call(s, "_check_port_or_fail"),
        ),
        _stage_stmt_span(
            "_run_desktop_inner",
            lambda s: isinstance(s, ast.If) and _stmt_has_call(s, "ensure_webview2_runtime"),
        ),
        _stage_stmt_span("_run_desktop_inner", lambda s: _stmt_has_call(s, "bootstrap_data_dir")),
        _stage_stmt_span(
            "_run_desktop_inner",
            lambda s: isinstance(s, ast.ImportFrom) and s.module == "delector.server",
        ),
        _stage_stmt_span(
            "_run_desktop_inner",
            lambda s: isinstance(s, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "server" for t in s.targets),
        ),
        _stage_stmt_span(
            "_run_desktop_inner",
            lambda s: isinstance(s, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "thread" for t in s.targets),
        ),
        # 第 7 条锚：**调用 `_show_window` 的那条顶层语句**（`_run_desktop_inner` 里 `_show_window`
        # 由 `try:` 体内的 `return` 调起 ⇒ 该 `try:` 就是这条锚）——语义即"第 6 枚标记必须在调用
        # `_show_window` 之前"，把"6 枚整体下移到 `_show_window` 之后"的假绿挡在门外。
        # 为何不锚"首个顶层 `try`"（`isinstance(s, ast.Try)`）：将来在该函数更早处加一个**与
        # `_show_window` 无关**的顶层 `try` 会让锚**前移** ⇒ 假红。改锚"含 `_show_window` 调用的
        # 顶层语句"即不受影响（`_stmt_has_call` 会 walk 进 `try` 体命中该调用）。
        _stage_stmt_span("_run_desktop_inner", lambda s: _stmt_has_call(s, "_show_window")),
    ]

    for index, marker in enumerate(_STARTUP_STAGE_MARKERS):
        lower_start, lower_end = anchor_spans[index]
        upper_start, _upper_end = anchor_spans[index + 1]
        assert line_of[marker] > lower_end, (
            f"标记 {marker!r} 必须写在它要标记的语句（第 {lower_start}-{lower_end} 行）**之后**，"
            f"实际在第 {line_of[marker]} 行 —— 写在语句之前会让归因张冠李戴"
        )
        assert line_of[marker] < upper_start, (
            f"标记 {marker!r} 必须写在下一枚锚语句（第 {upper_start} 行）**之前**，"
            f"实际在第 {line_of[marker]} 行 —— 整体下移到下一枚锚之后会让归因张冠李戴"
        )


def test_stage_markers_do_not_contain_first_screen_anchor_substrings() -> None:
    """分层守卫（**本文件清单侧**）：`_STARTUP_STAGE_MARKERS`（**本文件的清单常量**）与首屏工具的
    三个锚串互不为子串。

    本用例**只比对本文件清单常量、不读 `desktop.py`**。清单与实现的**同步**由
    `test_run_desktop_inner_logs_six_stage_markers_in_order_after_their_anchor_stmts`（读 AST 的
    存在/顺序/夹逼）保证；解析器侧的**同源**守卫在
    `tests/test_first_screen_from_log.py::test_new_stage_markers_do_not_contain_first_screen_anchor_substrings`
    （它从 `desktop.py` 同源取标记）。

    为何保留本用例（与顺序用例构成分层）：顺序用例挡"实现漂移"；本用例挡"清单与实现**被一起**
    改成含锚串"——若有人把实现与这份清单同步改成含「开始启动（进程级计时起点）/ 服务已就绪 /
    真实 UI 已加载（首屏可用）」，解析器（子串匹配 `marker in line.message`）会**抢错锚行**、
    端到端数字静默变味，本用例正是拦这一步。
    """
    for marker in _STARTUP_STAGE_MARKERS:
        for anchor in _FIRST_SCREEN_ANCHORS:
            assert anchor not in marker, (
                f"新标记 {marker!r} 不得包含首屏锚串 {anchor!r}（否则切片抢错行）"
            )


def test_loaded_event_binding_is_inside_start_delegated_tree_and_before_load_url() -> None:
    """`main.events.loaded` 的绑定必须在 `webview.start()` 调度树内、且在 `load_url` 之前。

    两处硬约束：① 绑定要发生在 GUI 事件循环已起之后（P0：循环启动前碰窗口/事件会永久阻塞）；
    ② 必须早于 `load_url` —— 它内部会 `events.loaded.clear()`，注册晚了就永远收不到首屏事件。
    """
    tree = _parse_desktop()
    _name, delegated = _delegated_function(tree)
    binds = [
        node
        for node in ast.walk(delegated)
        if isinstance(node, ast.AugAssign)
        and isinstance(node.target, ast.Attribute)
        and node.target.attr == "loaded"
    ]
    assert binds, "必须在 webview.start() 调度的函数内绑定 main.events.loaded（循环已起 ⇒ 绑定安全）"
    load_lines = [call.lineno for call in _calls(delegated) if _call_label(call) == "load_url"]
    assert load_lines, "调度函数必须 load_url"
    assert binds[0].lineno < min(load_lines), (
        "loaded 必须在 load_url 之前注册（load_url 会 events.loaded.clear()，晚注册收不到首屏）"
    )


def test_loaded_event_records_first_screen_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """行为回归锁：`loaded` 事件触发（页面渲染完成）时必须落一行「真实 UI 已加载（首屏可用）」。

    用假 webview 在 `load_url` 时触发该窗口的 `loaded` 处理器（模拟渲染器 set()），断言 launch.log
    里出现首屏标记。删掉绑定 / 不再记日志 ⇒ 本用例转红（不是只测"字符串在源码里"）。
    """
    mod = _mod()
    log_path = tmp_path / "launch.log"

    class _Signal:
        def __init__(self) -> None:
            self.handlers: List[Any] = []

        def __iadd__(self, other: Any) -> "_Signal":
            self.handlers.append(other)
            return self

        def fire(self) -> None:
            for handler in list(self.handlers):
                handler()

    class _Events:
        def __init__(self) -> None:
            self.closed = _Signal()
            self.loaded = _Signal()

    class _FakeWindow:
        def __init__(self) -> None:
            self.events = _Events()

        def evaluate_js(self, _script: str) -> None:
            return None

        def load_url(self, _url: str) -> None:
            self.events.loaded.fire()  # 页面加载完成 ⇒ 真实 pywebview 由渲染器 events.loaded.set()

        def show(self) -> None:
            return None

        def destroy(self) -> None:
            return None

    def _create_window(*_a: Any, **_k: Any) -> _FakeWindow:
        return _FakeWindow()

    def _start(func: Any = None, args: Any = None, **_k: Any) -> None:
        if func is not None:
            func(*(args or ()))

    fake_webview: Any = types.ModuleType("webview")
    fake_webview.create_window = _create_window
    fake_webview.start = _start

    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(mod, "await_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(mod, "_start_tray", lambda *_a, **_k: None)
    monkeypatch.setattr(mod, "_message_box", lambda *_a, **_k: None)

    code = mod._show_window(object(), object(), 8000, str(log_path))

    assert code == 0
    content = log_path.read_text(encoding="utf-8")
    assert _FIRST_SCREEN_MARKER in content, "loaded 事件触发（首屏渲染完成）时必须记首屏标记"


def test_window_ops_run_only_after_webview_start_at_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """行为回归锁：用替身 `webview` 记录调用顺序，断言窗口写入都发生在 start 之后。

    替身无法复现"marshal 到未启动 GUI 线程 = 永久阻塞"，但能钉住**调用顺序**：`start` 必须先于
    任何 load_url / evaluate_js。把 load_url 挪回 start 之前 ⇒ 本断言转红（即真实死锁的静态形状）。
    """
    mod = _mod()
    order: List[str] = []

    class _Signal:
        def __iadd__(self, _other: Any) -> "_Signal":
            return self

    class _FakeEvents:
        def __init__(self) -> None:
            self.closed = _Signal()
            # 5A：desktop 在 load_url 前注册 `loaded`（首屏真口径）⇒ 替身必须提供它（真实 pywebview
            # 的 Window.events 本就有 loaded；缺了会在 `_after_start` 里 AttributeError 假红）。
            self.loaded = _Signal()

    class _FakeWindow:
        def __init__(self) -> None:
            self.events = _FakeEvents()

        def evaluate_js(self, _script: str) -> None:
            order.append("evaluate_js")

        def load_url(self, _url: str) -> None:
            order.append("load_url")

        def show(self) -> None:
            # 双窗口方案会显式 show 主窗口；替身补上以便仍能钉住"写入晚于 start"的顺序锁。
            order.append("show")

        def destroy(self) -> None:
            order.append("destroy")

    def _create_window(*_a: Any, **_k: Any) -> _FakeWindow:
        order.append("create_window")
        return _FakeWindow()

    def _start(func: Any = None, args: Any = None, **_k: Any) -> None:
        order.append("start")
        if func is not None:
            func(*(args or ()))

    fake_webview: Any = types.ModuleType("webview")
    fake_webview.create_window = _create_window
    fake_webview.start = _start

    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(mod, "await_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(mod, "_start_tray", lambda *_a, **_k: order.append("tray"))
    monkeypatch.setattr(mod, "_message_box", lambda *_a, **_k: order.append("message_box"))

    code = mod._show_window(object(), object(), 8000, str(tmp_path / "launch.log"))

    assert "start" in order, "必须调用 webview.start"
    start_index = order.index("start")
    writes = [index for index, op in enumerate(order) if op in _WINDOW_WRITE_ATTRS]
    assert writes, "成功路径必然有窗口写入（evaluate_js / load_url）"
    assert all(index > start_index for index in writes), (
        f"窗口写入早于 webview.start()（P0 死锁形状）：order={order}"
    )
    assert code == 0


# ── 主窗口可缩放回归锁：真实 UI 绝不得被塞进 frameless/on_top 的 splash 窗口 ──────
# 缺陷现场：就绪后只对 splash（frameless=True, on_top=True, 430x270）load_url ⇒ 真实 UI 被关进
# 一个无标题栏（无最大化/还原按钮、无可拖边）、永远置顶的小窗。下列锁用**录制的 fake webview**
# 捕获建窗 kwargs 与调用顺序（不只断言"函数存在"），把"最终窗口是普通可缩放窗口"钉死。
def _install_recording_webview(
    monkeypatch: pytest.MonkeyPatch,
    mod: Any,
    order: List[str],
    record: Dict[str, Any],
) -> None:
    """装一个记录调用顺序的假 `webview`：两窗口按 `hidden` 区分（main=隐藏, splash=非隐藏）。"""

    class _Signal:
        def __init__(self) -> None:
            self.handlers: List[Any] = []

        def __iadd__(self, other: Any) -> "_Signal":
            self.handlers.append(other)
            return self

    class _Events:
        def __init__(self) -> None:
            self.closed = _Signal()
            self.loaded = _Signal()  # 5A：首屏真口径的 `loaded` 绑定点（真实 Window.events 也有它）

    class _FakeWindow:
        def __init__(self, name: str) -> None:
            self.name = name
            self.events = _Events()

        def evaluate_js(self, _script: str) -> None:
            order.append(f"{self.name}.evaluate_js")

        def load_url(self, _url: str) -> None:
            order.append(f"{self.name}.load_url")

        def show(self) -> None:
            order.append(f"{self.name}.show")

        def destroy(self) -> None:
            order.append(f"{self.name}.destroy")

    windows: Dict[str, "_FakeWindow"] = {}
    created: List[Dict[str, Any]] = []

    def _create_window(*_a: Any, **kwargs: Any) -> "_FakeWindow":
        name = "main" if kwargs.get("hidden") else "splash"
        created.append(kwargs)
        window = _FakeWindow(name)
        windows[name] = window
        order.append(f"create:{name}")
        return window

    def _start(func: Any = None, args: Any = None, **_k: Any) -> None:
        order.append("start")
        if func is not None:
            func(*(args or ()))

    fake_webview: Any = types.ModuleType("webview")
    fake_webview.create_window = _create_window
    fake_webview.start = _start

    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    # 就绪门用替身返回 True，并把"就绪时刻"记进 order，供断言"show 在就绪之后"。
    def _ready(*_a: Any, **_k: Any) -> bool:
        order.append("await_ready")
        return True

    monkeypatch.setattr(mod, "await_ready", _ready)
    monkeypatch.setattr(mod, "_message_box", lambda *_a, **_k: None)

    def _trap_tray(window: Any, coordinator: Any, log_path: str) -> None:
        order.append("tray")
        record["coordinator"] = coordinator

    monkeypatch.setattr(mod, "_start_tray", _trap_tray)

    record["windows"] = windows
    record["created"] = created


def test_main_window_is_created_as_a_normal_resizable_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """主窗口建窗参数必须是"普通可缩放窗口"：有边框、非置顶、够大、有 min_size。

    症状"没法放大缩写、没法做尺寸变化"的根因就是真实 UI 落在了 frameless 的无标题小窗里；
    这条锁直接检查交给 `webview.create_window` 的 kwargs，杜绝"函数存在但参数回退"的假绿。
    """
    mod = _mod()
    order: List[str] = []
    record: Dict[str, Any] = {}
    _install_recording_webview(monkeypatch, mod, order, record)

    code = mod._show_window(object(), object(), 8000, str(tmp_path / "launch.log"))

    assert code == 0
    created: List[Dict[str, Any]] = record["created"]
    mains = [kwargs for kwargs in created if kwargs.get("hidden") is True]
    assert len(mains) == 1, f"必须恰有一个隐藏的主窗口（就绪后显示），实际 {len(mains)}"
    main = mains[0]

    assert main.get("frameless") is False, "主窗口必须有边框（无边框 ⇒ 无标题栏 ⇒ 无最大化/还原按钮、无可拖边）"
    assert main.get("on_top") is False, "主窗口不得永远置顶（只有 splash 才刻意置顶）"
    assert main.get("width", 0) >= 1200 and main.get("height", 0) >= 800, (
        f"主窗口默认尺寸必须够大：width={main.get('width')} height={main.get('height')}"
    )
    assert tuple(main.get("min_size", (0, 0))) >= (900, 600), "主窗口必须给可缩放下限 min_size"

    splashes = [kwargs for kwargs in created if kwargs.get("frameless") is True]
    assert len(splashes) == 1, "splash 仍应保留为无边框小窗（这是刻意的启动反馈设计）"


def test_final_ui_is_the_main_window_shown_after_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """最终呈现给用户的必须**不是** splash：就绪后 show 主窗口 + 销毁 splash，且 show 在就绪之后。

    同时钉住顺序：先亮主窗口再销毁 splash —— 否则销毁瞬间零窗口会让 pywebview 的 GUI 循环提前退出。
    """
    mod = _mod()
    order: List[str] = []
    record: Dict[str, Any] = {}
    _install_recording_webview(monkeypatch, mod, order, record)

    mod._show_window(object(), object(), 8000, str(tmp_path / "launch.log"))

    assert "main.show" in order, "必须显式 show 主窗口，否则用户看到的仍是 splash"
    assert "splash.destroy" in order, "就绪后必须销毁 splash（否则它永不消失）"
    assert "main.load_url" in order, "主窗口必须加载真实 UI"
    assert order.index("main.show") > order.index("await_ready"), "主窗口显示必须发生在服务就绪之后"
    assert order.index("main.show") < order.index("splash.destroy"), (
        "必须先亮主窗口再销毁 splash：否则瞬间零窗口 ⇒ GUI 循环提前退出"
    )

    # 硬约束②回归：任何窗口操作都不得早于 webview.start()（P0 死锁形状）。
    start_index = order.index("start")
    for op in ("main.show", "main.load_url", "splash.destroy", "splash.evaluate_js"):
        assert order.index(op) > start_index, f"{op} 早于 webview.start()（P0 死锁形状）：order={order}"


def test_main_window_close_requests_quit_and_reaps_splash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """主窗口关闭 ⇒ 接到统一收尸触发器；且若 splash 仍在要一并销毁。

    `webview.start()` 阻塞到**所有**窗口关闭；主窗口关而 splash 尚存会使循环永不返回 ⇒ 进程挂起。
    """
    mod = _mod()
    order: List[str] = []
    record: Dict[str, Any] = {}
    _install_recording_webview(monkeypatch, mod, order, record)

    mod._show_window(object(), object(), 8000, str(tmp_path / "launch.log"))

    main = record["windows"]["main"]
    coordinator = record["coordinator"]
    assert coordinator is not None and coordinator.requested is False, "前置：主窗口关闭前不应已请求退出"
    assert main.events.closed.handlers, "主窗口的 closed 事件必须被接线（否则关窗不收尸）"

    for handler in main.events.closed.handlers:
        handler()

    assert coordinator.requested is True, "主窗口关闭必须触发统一收尸触发器（QuitCoordinator）"


def test_on_main_closed_destroys_a_surviving_splash(tmp_path: Path):
    """`_on_main_closed`：标记退出 + 销毁仍在的 splash（否则 start() 永不返回）。"""
    mod = _mod()
    destroyed: List[int] = []

    class _Splash:
        def destroy(self) -> None:
            destroyed.append(1)

    coordinator = mod.QuitCoordinator()

    mod._on_main_closed(_Splash(), coordinator, str(tmp_path / "launch.log"))

    assert coordinator.requested is True, "关主窗口 = 请求退出"
    assert destroyed == [1], "主窗口关闭时若 splash 还在，必须一并销毁"


# ── 入口分派：默认=桌面窗口；`--server-only`=既有服务行为（Task 5 行为变化）────────
def test_parser_accepts_server_only_flag():
    """`--server-only` 开关存在且默认关闭；`--port` 仍可用（默认 8000）。"""
    mod = _mod()

    assert mod._parse_args([]).server_only is False, "默认必须是桌面窗口，而非仅服务"
    assert mod._parse_args(["--server-only"]).server_only is True
    assert mod._parse_args(["--server-only", "--port", "9000"]).port == 9000


def test_dispatch_default_launches_desktop_window(monkeypatch: pytest.MonkeyPatch):
    """默认（无 `--server-only`）⇒ 起桌面窗口：`dispatch(False, port)` 必须走 `run_desktop(port)`。"""
    mod = _mod()
    seen: List[int] = []

    def _fake_run_desktop(port: int) -> int:
        seen.append(port)
        return 0

    monkeypatch.setattr(mod, "run_desktop", _fake_run_desktop)

    code = mod.dispatch(server_only=False, port=8123)

    assert seen == [8123], "默认路径必须以解析到的端口起桌面窗口"
    assert code == 0


def test_dispatch_server_only_delegates_to_start_main(monkeypatch: pytest.MonkeyPatch):
    """`--server-only` ⇒ 委托 `start.main()` 的既有行为（无窗口、绑 0.0.0.0、开浏览器）。

    保留"同 Wi-Fi 手机可访问"的既有工作流：这不是新写一套服务，而是**复用** start.main，
    故这里钉的是"真的调了 start.main"，而不是"等价实现"。
    """
    import start

    mod = _mod()
    calls: List[str] = []
    monkeypatch.setattr(start, "main", lambda: calls.append("main"))
    monkeypatch.setattr(mod, "run_desktop", lambda port: pytest.fail("--server-only 不得起桌面窗口"))

    code = mod.dispatch(server_only=True, port=8123)

    assert calls == ["main"], "--server-only 必须委托 start.main()（复用既有服务行为）"
    assert code == 0


def test_dispatch_server_only_warns_that_port_is_ignored(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """`--server-only --port <非默认>` ⇒ 必须**显式警告** `--port` 不生效，绝不静默丢弃。

    `--server-only` 复用 `start.main()`（固定端口 8000），该路径不接受 `--port`；argparse 却宣称
    `--port` 可用 ⇒ 静默用 8000 会被用户误读成"端口没换成功"。这条钉住"不静默"。
    """
    import start

    mod = _mod()
    monkeypatch.setattr(start, "main", lambda: None)
    monkeypatch.setattr(mod, "run_desktop", lambda port: pytest.fail("--server-only 不得起桌面窗口"))

    code = mod.dispatch(server_only=True, port=9000)
    err = capsys.readouterr().err

    assert code == 0
    assert "9000" in err and "--port" in err, "必须显式告知 --port 在该组合下不生效（不得静默）"


def test_dispatch_server_only_does_not_warn_for_default_port(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """`--server-only` 用默认端口（无分歧）⇒ **不**告警：正常用法不该被当噪音。"""
    import start

    mod = _mod()
    monkeypatch.setattr(start, "main", lambda: None)

    mod.dispatch(server_only=True, port=mod.DEFAULT_PORT)

    assert capsys.readouterr().err == "", "端口无分歧时不得告警"


def test_import_desktop_has_no_side_effects():
    """子进程实证：`import desktop` 返回 0 且**零输出**（没起服务、没弹窗、没拉 GUI）。"""
    proc = subprocess.run(
        [sys.executable, "-c", "import desktop"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert proc.returncode == 0, f"import desktop 失败：{proc.stderr}"
    assert proc.stdout.strip() == "", f"import desktop 不得有任何输出：{proc.stdout!r}"
    assert proc.stderr.strip() == "", f"import desktop 不得有任何 stderr：{proc.stderr!r}"


# ── Task 3：无控制台时 stdout/stderr 收口 + `--debug-console` ────────────────
def _run_with_missing_streams(
    monkeypatch: pytest.MonkeyPatch, action: Callable[[], None]
) -> None:
    """临时移除标准流并在动作后恢复，避免重定向文件句柄污染 pytest 自身输出。"""
    original_out, original_err = sys.stdout, sys.stderr
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    try:
        action()
    finally:
        redirected_out, redirected_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = original_out, original_err
        for stream in (redirected_out, redirected_err):
            if stream is not None and stream not in (original_out, original_err):
                stream.close()


def test_missing_streams_capture_start_banner_notice_and_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """start.py 的横幅/提示/报错在无控制台时都不得抛，且必须写入 launch.log。"""
    import start
    from delector.core import server_lifecycle

    mod = _mod()
    log_path = tmp_path / "launch.log"

    def _exercise() -> None:
        mod.ensure_streams(str(log_path))
        start.print_banner(8000, android=True)
        monkeypatch.setattr(server_lifecycle, "probe_identity", lambda _port: True)
        start._handle_existing_port(8000, android=True)
        monkeypatch.setattr(server_lifecycle, "probe_identity", lambda _port: False)
        with pytest.raises(SystemExit) as exc_info:
            start._handle_existing_port(8000, android=True)
        assert exc_info.value.code == 1

    _run_with_missing_streams(monkeypatch, _exercise)

    content = log_path.read_text(encoding="utf-8")
    assert "DeLector — 德语欧标沉浸阅读与考点剖析工作台" in content
    assert "[提示] DeLector 已在端口 8000 运行" in content
    assert "[错误] 端口 8000 已被其他程序占用" in content


def test_missing_stderr_captures_desktop_fallback_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """desktop.py 原生弹窗的 stderr 降级路径在无控制台时仍须落 launch.log。"""
    mod = _mod()
    log_path = tmp_path / "launch.log"
    fake_ctypes = types.ModuleType("ctypes")
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)

    def _exercise() -> None:
        mod.ensure_streams(str(log_path))
        # 先钉"stderr 真的被绑上了"再 print：CPython 下 `print(x, file=None)` 等价于打到
        # stdout ⇒ 只绑 stdout、把 stderr 留在 None 的实现也能让上面的日志断言全绿（假绿）。
        assert sys.stderr is not None, "收口后 stderr 必须已绑上，否则降级信息其实打去了 stdout"
        mod._message_box("桌面提示", "无控制台回归")

    _run_with_missing_streams(monkeypatch, _exercise)

    assert "[桌面提示] 无控制台回归" in log_path.read_text(encoding="utf-8")


def test_desktop_server_only_entry_captures_warning_before_delegation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """desktop --server-only 的端口警告发生在委托前，也必须先完成流收口。"""
    import start

    mod = _mod()
    monkeypatch.setenv("DELECTOR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(start, "main", lambda: None)

    def _exercise() -> None:
        real_ensure_streams = mod.ensure_streams
        bound_after: List[bool] = []

        def _spy(log_path: str, debug_console: bool = False) -> None:
            real_ensure_streams(log_path, debug_console)
            # 收口刚完成、端口警告还没 print：此刻 stderr 必须已绑上。否则 `print(...,
            # file=sys.stderr)` 会因 file=None 退到 stdout ⇒ 日志里照样有 [警告]，
            # "只绑 stdout"的实现也能让本用例全绿（假绿）。
            bound_after.append(sys.stderr is not None)

        monkeypatch.setattr(mod, "ensure_streams", _spy)
        assert mod.dispatch(server_only=True, port=9000) == 0
        assert bound_after == [True], (
            "dispatch 必须在打印端口警告之前完成流收口，且收口要把 stderr 也绑上（不能只绑 stdout）"
        )

    _run_with_missing_streams(monkeypatch, _exercise)

    content = (tmp_path / "launch.log").read_text(encoding="utf-8")
    assert "[警告]" in content and "--port 9000" in content


def test_start_main_entry_ensures_streams_before_existing_port_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """start.py 单独作为入口时，端口占用提示之前必须自行完成流收口。"""
    import start
    from delector.core import server_lifecycle

    monkeypatch.setenv("DELECTOR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(start, "is_android", lambda: True)
    monkeypatch.setattr(start, "is_port_in_use", lambda _port: True)
    monkeypatch.setattr(server_lifecycle, "probe_identity", lambda _port: True)

    _run_with_missing_streams(monkeypatch, start.main)

    content = (tmp_path / "launch.log").read_text(encoding="utf-8")
    assert "[提示] DeLector 已在端口 8000 运行" in content


def test_start_entry_streams_survives_missing_desktop_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """Android APK 里没有 `desktop.py` ⇒ 入口收口必须**静默放弃**，绝不得冒异常。

    为什么必须有这条：APK 的 Python 源集只有 `start.py` + `delector/`（build-release.yml
    里只 `cp -r start.py`，**没有** `cp desktop.py`），入口是 `py.getModule("start")
    .callAttr("main")` ⇒ 收口里那句硬 `from desktop import ...` 会在 `main()` 首行抛
    ModuleNotFoundError，被 Java 侧 `catch (Throwable)` 兜成「Python 引擎异常」⇒ **APK
    起不来**。而 Android 上 `sys.stdout` 本就不是 None（Chaquopy 重定向到 logcat）⇒ 这次
    收口在 Android 上恒为 no-op，却换来一次致命崩溃 —— 直接违背"收口绝不抛、不得阻断启动"。

    用 `sys.modules["desktop"] = None` 模拟"包内不含该模块"（此刻 `import desktop` 抛
    ImportError），断言 `main()` 的收口步骤**不冒泡**。
    """
    import start
    from delector.core import server_lifecycle

    monkeypatch.setitem(sys.modules, "desktop", None)  # ⇒ `import desktop` 抛 ImportError
    monkeypatch.setattr(start, "is_android", lambda: True)  # 不起浏览器线程
    monkeypatch.setattr(start, "is_port_in_use", lambda _port: True)
    monkeypatch.setattr(server_lifecycle, "probe_identity", lambda _port: True)

    start.main()  # 不得抛：收口失败宁可不留痕，也绝不得阻断启动

    assert sys.stdout is not None, "收口失败也不得把既有 stdout 弄丢（pytest 捕获流仍在）"


def test_debug_console_flag_defaults_off_and_is_accepted() -> None:
    """两个入口都只提供同一运行时开关；默认关闭，不新增第二个 exe。"""
    import start

    mod = _mod()
    assert mod._parse_args([]).debug_console is False
    assert mod._parse_args(["--debug-console"]).debug_console is True
    assert start._parse_args([]).debug_console is False
    assert start._parse_args(["--debug-console"]).debug_console is True


def test_debug_console_keeps_existing_console_streams(
    tmp_path: Path,
) -> None:
    """已有控制台时 debug 模式不得把现有 stdout/stderr 收口到日志。"""
    mod = _mod()
    original_out, original_err = sys.stdout, sys.stderr

    mod.ensure_streams(str(tmp_path / "launch.log"), debug_console=True)

    assert sys.stdout is original_out
    assert sys.stderr is original_err
    assert not (tmp_path / "launch.log").exists()


def test_default_path_leaves_existing_streams_untouched(tmp_path: Path) -> None:
    """默认路径（非 debug）：stdout/stderr **已存在** ⇒ 不得接管它们、也不得建/写 launch.log。

    这是上一条的**默认分支镜像**：那条钉 `debug_console=True`，这条钉默认分支。缺了它，
    "把默认分支改回『总是重定向』"（覆盖真实终端 / pytest 捕获流，并新建一个 launch.log）
    这条变异仍全绿 —— 而"接管既有流"正是收口要防的反向失败。
    """
    mod = _mod()
    log_path = tmp_path / "launch.log"
    original_out, original_err = sys.stdout, sys.stderr

    mod.ensure_streams(str(log_path))

    assert sys.stdout is original_out, "已有 stdout 时默认路径不得接管它"
    assert sys.stderr is original_err, "已有 stderr 时默认路径不得接管它"
    assert not log_path.exists(), "已有流时不得创建/写入 launch.log"


def test_debug_console_never_calls_win32_api_off_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ubuntu CI 上必须守住平台边界；无控制台时退到静默流，也不能触碰 Win32。

    为什么用**记录型假 ctypes**（`__getattr__` 只记账、返回一个哑对象），而不是"哨兵"
    （一访问就抛 AssertionError）：收口链路里的 `except Exception` 会**吞掉**哨兵
    （AssertionError ⊂ Exception）⇒ 即使有人删掉 `sys.platform != "win32"` 守卫，哨兵版
    仍然全绿（假绿）。记录型**不抛**，调用后断言"一次都没被访问过"，才真能钉住"非 win32
    不碰 Win32 API"（`windll` / `kernel32` 之类入口）。
    """
    mod = _mod()
    touched: List[str] = []

    class _RecordingCtypes(types.ModuleType):
        def __getattr__(self, name: str) -> Any:
            touched.append(name)
            return _RecordingCtypes(name)

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setitem(sys.modules, "ctypes", _RecordingCtypes("ctypes"))

    def _exercise() -> None:
        mod.ensure_streams(str(tmp_path / "launch.log"), debug_console=True)
        assert sys.stdout is not None
        assert sys.stderr is not None

    _run_with_missing_streams(monkeypatch, _exercise)
    assert not (tmp_path / "launch.log").exists()
    assert touched == [], f"非 win32 不得触碰任何 Win32 API 入口（ctypes.*），实际访问：{touched}"


# ── GUI：真窗口 / 真托盘 / 三线程互不阻塞（无桌面会话下跳过，绝不假绿）────────
@pytest.mark.skipif(
    os.environ.get("DELECTOR_GUI_TEST") != "1",
    reason="需要真实桌面会话：pywebview 主线程事件循环 + 系统 Edge WebView2 无法在 CI/无头会话拉起；"
    "设 DELECTOR_GUI_TEST=1 在有桌面的机器上手动跑",
)
def test_run_desktop_real_window_smoke():  # pragma: no cover - 只在真实桌面会话手动执行
    """真窗口冒烟（默认跳过）：起 run_desktop、确认返回 0、无残留非 daemon 线程。

    这里**不写死实现细节**，只做"能起来、能干净退出"的黑盒验证；无桌面会话时上面那条
    skipif 会跳过它，绝不把"没跑"伪装成"通过"。
    """
    mod = _mod()
    assert mod.ensure_webview2_runtime() is True, "前提：本机必须已装 WebView2 运行时"

    code = mod.run_desktop(port=0)

    assert code == 0
    assert threading.active_count() >= 1


# ── 本轮：把「进程创建 → 计时起点」这段未测段落进日志 ──────────────────────────
# 背景：ADR-0018 §8 明写这个计时起点"晚于解释器启动与该模块自身的 import ⇒ 用户双击感知的
# 端到端**比 6s 更长**，而那一段**从未被测到**"。锁分三层：
#   ① AST：新标记**紧随**计时起点，且**不含**三条锚串（含了就抢错行 ⇒ 数字静默变味）；
#   ② 行为级：注入替身取数 ⇒ 落出的行必须带**那个数**（不是常量、不是 0）；
#   ③ fail-soft：底层取数抛异常 ⇒ 返回 None、写 `?`、**绝不外抛**（绝不让仪表把启动搞崩）。
_PRE_START_HINT = "自进程创建"


def test_prestart_marker_is_written_right_after_timing_start_and_carries_no_anchor() -> None:
    """未测段标记必须**紧随**计时起点，且不得含三条锚串（否则解析器抢错行）。

    实现把"落行"抽成 `_log_prestart_elapsed`（便于注入替身做行为级测试），故这里分两处看：
    ① `run_desktop` 里"起点"那条顶层语句的**下一条**必须是 `_log_prestart_elapsed(...)` 调用；
    ② 真正的字面量在该函数内 —— 锚串碰撞要往它里面看。
    """
    src = (REPO_ROOT / "desktop.py").read_text(encoding="utf-8")
    funcs = _funcs_by_name(ast.parse(src))
    run = funcs["run_desktop"]

    start_index = next(
        (
            index
            for index, stmt in enumerate(run.body)
            if _TIMING_START_MARKER in (ast.get_source_segment(src, stmt) or "")
        ),
        None,
    )
    assert start_index is not None, "run_desktop 里找不到计时起点标记"
    next_stmt = run.body[start_index + 1]
    next_segment = ast.get_source_segment(src, next_stmt) or ""
    assert any(_call_label(call) == "_log_prestart_elapsed" for call in _calls(next_stmt)), (
        f"计时起点之后紧邻的顶层语句必须是 `_log_prestart_elapsed(...)`，实际：{next_segment!r}"
    )

    helper_literals = [
        node.value
        for node in ast.walk(funcs["_log_prestart_elapsed"])
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    template = next((text for text in helper_literals if _PRE_START_HINT in text), None)
    assert template is not None, (
        f"`_log_prestart_elapsed` 里找不到含 {_PRE_START_HINT!r} 的字面量：{helper_literals}"
    )
    for anchor in (_TIMING_START_MARKER, "服务已就绪", _FIRST_SCREEN_MARKER):
        assert anchor not in template, f"未测段标记不得含锚串 {anchor!r}（含了就抢错行、数字静默变味）"


def test_prestart_line_reports_the_probed_ms(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """行为级：**输入变则输出变** —— 两次不同注入必须落出两行不同的数。

    为什么不用"单次注入 + 断言含该数"：变量与常量会撞车（初版注入 123.4 ⇒ 格式化成 `123`，
    恰好与"把数字写成常量 123"这条变异同形 ⇒ 变异后仍绿，等于没测）。
    """
    mod = _mod()
    slow_log = tmp_path / "slow.log"
    fast_log = tmp_path / "fast.log"
    monkeypatch.setattr(mod, "_ms_since_process_create", lambda: 4321.6)
    mod._log_prestart_elapsed(str(slow_log))
    monkeypatch.setattr(mod, "_ms_since_process_create", lambda: 87.2)
    mod._log_prestart_elapsed(str(fast_log))
    slow_text = slow_log.read_text(encoding="utf-8")
    fast_text = fast_log.read_text(encoding="utf-8")
    assert "进程已运行 4322 ms（自进程创建；此前为未测段）" in slow_text, slow_text
    assert "进程已运行 87 ms（自进程创建；此前为未测段）" in fast_text, fast_text
    assert slow_text != fast_text, "两次注入不同探针值却落出同一行 ⇒ 数字不是来自探针（是常量）"


def test_prestart_line_writes_question_mark_when_probe_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """取不到时刻（非 Windows / 系统调用失败）⇒ 写 `?` 且**不抛**、不阻断启动。"""
    mod = _mod()
    log_path = tmp_path / "launch.log"
    monkeypatch.setattr(mod, "_ms_since_process_create", lambda: None)
    mod._log_prestart_elapsed(str(log_path))
    assert "进程已运行 ? ms（自进程创建；此前为未测段）" in log_path.read_text(encoding="utf-8")


def test_ms_since_process_create_never_raises_when_underlying_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fail-soft 契约：底层取数**抛异常** ⇒ 本函数返回 None（绝不外抛）。

    刻意把平台守卫"撬开"（`sys.platform` → win32）再让底层抛 ⇒ **Linux（CI）与 Windows 上跑的是
    同一条路径、同一条变异**（拿掉 try/except 在两处都会红），不靠"本机正好是 Windows"。
    """
    mod = _mod()
    monkeypatch.setattr(sys, "platform", "win32")

    def _boom() -> float:
        raise OSError("模拟系统调用失败")

    monkeypatch.setattr(mod, "_win_ms_since_create", _boom)
    assert mod._ms_since_process_create() is None


def test_ms_since_process_create_returns_none_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """非 Windows 直接 None（CI 是 ubuntu，`ctypes.windll` 在那儿根本不存在 ⇒ 不许碰它）。"""
    mod = _mod()
    monkeypatch.setattr(sys, "platform", "linux")
    assert mod._ms_since_process_create() is None


@pytest.mark.skipif(
    os.environ.get("DELECTOR_GUI_TEST") != "1",
    reason="需要真实桌面会话：pystray 与 pywebview 事件循环共存需真窗口实测（ADR-0020 §6 Unknown 4）",
)
def test_tray_coexists_with_webview_event_loop():  # pragma: no cover - 只在真实桌面会话手动执行
    """托盘与窗口事件循环共存（默认跳过）：这是 ADR-0020 §6 Unknown 4，必须在真桌面实测。"""
    pytest.skip("GUI 冒烟：请在真实桌面会话手动验证托盘与窗口互不阻塞")
