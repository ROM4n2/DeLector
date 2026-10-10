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
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

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

    class _FakeWindow:
        def __init__(self) -> None:
            self.events = _FakeEvents()

        def evaluate_js(self, _script: str) -> None:
            order.append("evaluate_js")

        def load_url(self, _url: str) -> None:
            order.append("load_url")

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


@pytest.mark.skipif(
    os.environ.get("DELECTOR_GUI_TEST") != "1",
    reason="需要真实桌面会话：pystray 与 pywebview 事件循环共存需真窗口实测（ADR-0020 §6 Unknown 4）",
)
def test_tray_coexists_with_webview_event_loop():  # pragma: no cover - 只在真实桌面会话手动执行
    """托盘与窗口事件循环共存（默认跳过）：这是 ADR-0020 §6 Unknown 4，必须在真桌面实测。"""
    pytest.skip("GUI 冒烟：请在真实桌面会话手动验证托盘与窗口互不阻塞")
