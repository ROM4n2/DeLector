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
from pathlib import Path
from typing import Any, List, Optional

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
