# -*- coding: utf-8 -*-
"""桌面壳「退出·托盘·失败出口」域（C6 Task 6 自 `tests/test_desktop_shell.py` 逐字搬出）。

搬出的段（搬前 `test_desktop_shell.py` 行号，实测，含各段头注释）：
  `266`-`483`   ③ 退出编排（shutdown / 超时硬退出）· ④ 托盘菜单 · ④-b 托盘「显示局域网地址」· ⑤ write_crash
  `519`-`649`   Task 2 失败出口统一（切 UI 异常弹窗 + 全栈落盘；外层弹窗不许吐栈）
  `2545`-`2564` 黄牌 3：托盘读非 UTF-8 地址文件的「可读失败」（不把异常漏进回调）
  `2677`-`2828` A 系列 Task 2：退出路径有界 + 根除「假成功」日志

断言、用例名与 docstring 逐字未改；只新增本文件的显式 import。跨域共用项
（`_mod` / `_parse_desktop` / `_funcs_by_name` / `_calls` / `_call_label` /
`_stub_server_build`）与 autouse 兜底夹具 `_isolate_data_dir` 住在
`tests/server_helpers.py`，按名 import 即在本模块注册。
"""

import ast
import sys
import time
import types
from pathlib import Path
from typing import Any, List, Optional, Tuple

import pytest
from server_helpers import _call_label, _calls, _funcs_by_name, _mod, _parse_desktop, _stub_server_build
from server_helpers import _isolate_data_dir as _isolate_data_dir


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
    """托盘菜单四枚：打开 / 显示局域网地址 / 检查更新 / 退出（顺序稳定，便于用户形成肌肉记忆）。"""
    mod = _mod()

    labels = [label for label, _action in mod.TRAY_MENU_SPEC]

    assert labels == ["打开", "显示局域网地址", "检查更新", "退出"]


def test_tray_menu_actions_are_wired_to_distinct_handlers():
    """四枚菜单各接一个动作键：open / show_lan_address / check_update / quit（quit 走统一收尸路径）。"""
    mod = _mod()

    actions = [action for _label, action in mod.TRAY_MENU_SPEC]

    assert actions == ["open", "show_lan_address", "check_update", "quit"]


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


# ── ④-b 托盘「显示局域网地址」：无控制台形态的第二条地址出口 ─────────────────
def test_tray_menu_includes_show_lan_address_item():
    """「显示局域网地址」必须在托盘菜单里，且其 action 能解析成 handler（缺一即静默丢菜单项）。

    背景：打包切 `--windowed` 后没有控制台，`--server-only` 原先靠 start.py 打印局域网地址，
    桌面用户看不到 ⇒ 托盘是地址的第二出口（第一出口是数据目录的 `lan-address.txt`）。
    """
    mod = _mod()

    labels = [label for label, _action in mod.TRAY_MENU_SPEC]
    assert "显示局域网地址" in labels, "无控制台形态下托盘必须提供局域网地址入口"
    action = dict(mod.TRAY_MENU_SPEC)["显示局域网地址"]

    handlers = mod.build_tray_handlers(mod.TRAY_MENU_SPEC, window=object(), coordinator=mod.QuitCoordinator())

    assert action in handlers, f"动作键 {action!r} 必须在 handlers 里可解析（否则点击即 KeyError）"
    assert callable(handlers[action]), "「显示局域网地址」必须映射到可调用处理函数"


def test_tray_show_lan_address_pops_the_address_from_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """点击「显示局域网地址」⇒ 弹原生窗显示 `lan-address.txt` 里的地址（复用 `_message_box`）。

    弹窗内容必须**原样含文件里的地址**：这项的存在意义就是让用户能当场看到并复制它。
    """
    mod = _mod()
    monkeypatch.setenv("DELECTOR_DATA_DIR", str(tmp_path))
    (tmp_path / "lan-address.txt").write_text("http://192.168.1.50:8000\n", encoding="utf-8")
    popped: List[Tuple[str, str]] = []
    monkeypatch.setattr(mod, "_message_box", lambda title, detail: popped.append((title, detail)))

    handlers = mod.build_tray_handlers(mod.TRAY_MENU_SPEC, window=object(), coordinator=mod.QuitCoordinator())
    handlers[dict(mod.TRAY_MENU_SPEC)["显示局域网地址"]]()

    assert popped, "点击后必须弹窗，否则用户点了没反应（比没有这项更糟）"
    assert "http://192.168.1.50:8000" in popped[0][1], "弹窗必须原样显示文件里的地址"


def test_tray_show_lan_address_fails_readably_when_address_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """拿不到地址（文件缺失/为空）⇒ 必须弹**可读**失败提示并留痕，不许静默。

    "点了一项却什么都没发生"是本任务要消除的一类静默失败：弹窗让用户知道为什么没有地址，
    launch.log 让排障时有线索。
    """
    mod = _mod()
    monkeypatch.setenv("DELECTOR_DATA_DIR", str(tmp_path))  # 空目录：没有 lan-address.txt
    popped: List[str] = []
    monkeypatch.setattr(mod, "_message_box", lambda title, detail: popped.append(title))

    handlers = mod.build_tray_handlers(mod.TRAY_MENU_SPEC, window=object(), coordinator=mod.QuitCoordinator())
    handlers[dict(mod.TRAY_MENU_SPEC)["显示局域网地址"]]()

    assert popped, "拿不到地址时必须给出可见的失败提示，不许静默吞掉"
    log_text = (tmp_path / "launch.log").read_text(encoding="utf-8")
    assert "显示局域网地址" in log_text, "失败也要落 launch.log，不能只有弹窗"


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


# ── Task 2（失败出口统一）：切 UI 异常必须弹窗 + 全栈落盘；外层弹窗不许吐栈 ────
def test_after_start_exception_pops_dialog_and_logs_full_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """`_after_start` 内窗口调用抛异常 ⇒ 必须弹窗，且 `launch.log` 含全栈 traceback。

    缺陷现场：该异常分支此前只写一行 `exc!r` 就 `_abort_windows` 收尸 —— `--windowed` 打包后
    无控制台，用户看到的是"窗口一闪就没、零线索"；而同函数的就绪超时分支反而有弹窗，两条
    失败出口不一致。无头环境把 MessageBoxW 换替身（不真弹），断言弹窗发生且全栈落盘。
    """
    mod = _mod()
    log_path = tmp_path / "launch.log"
    popped: List[Tuple[str, str]] = []
    monkeypatch.setattr(mod, "_message_box", lambda title, detail: popped.append((title, detail)))
    monkeypatch.setattr(mod, "await_ready", lambda *_a, **_k: True)
    _stub_server_build(monkeypatch, mod)  # Task 3 后建服段在 _after_start 里：不起真服务

    class _Signal:
        def __iadd__(self, _other: Any) -> "_Signal":
            return self

    class _Events:
        def __init__(self) -> None:
            self.closed = _Signal()
            self.loaded = _Signal()

    class _Splash:
        def __init__(self) -> None:
            self.events = _Events()

        def evaluate_js(self, _script: str) -> None:
            return None

        def destroy(self) -> None:
            return None

    class _BoomMain:
        def __init__(self) -> None:
            self.events = _Events()

        def show(self) -> None:
            raise RuntimeError("boom-main-show")

        def load_url(self, _url: str) -> None:
            return None

        def destroy(self) -> None:
            return None

    result: List[int] = [0]

    mod._after_start(_Splash(), _BoomMain(), mod.QuitCoordinator(), 8000, str(log_path), result)

    assert result[0] == 1, "异常路径必须置失败退出码（否则 start() 返回后进程装成功）"
    assert popped, "切 UI 阶段异常必须弹窗（无控制台时这是用户唯一可见的失败反馈）"
    content = log_path.read_text(encoding="utf-8")
    assert "Traceback" in content, "launch.log 必须含全栈 traceback（只有 repr 一行不足以定位）"
    assert "boom-main-show" in content, "异常信息必须落盘"


def _assigns_result_failure(stmt: ast.stmt) -> bool:
    """`result[0] = 1`：把回传主线程的退出码容器置为失败。"""
    if not isinstance(stmt, ast.Assign) or len(stmt.targets) != 1:
        return False
    target = stmt.targets[0]
    return (
        isinstance(target, ast.Subscript)
        and isinstance(target.value, ast.Name)
        and target.value.id == "result"
        and isinstance(target.slice, ast.Constant)
        and target.slice.value == 0
        and isinstance(stmt.value, ast.Constant)
        and stmt.value.value == 1
    )


def test_after_start_pins_failure_code_before_write_crash() -> None:
    """结构钉（黄牌 B）：`_after_start` 异常出口必须**先** `result[0] = 1`、**再** `write_crash`。

    `write_crash` 要落盘 + 弹窗，若它二次异常（本不应，防御性）也不能让退出码停留在"成功"——
    先钉死 1，再走可能失败的留痕路径。两条语句一互换就静默违背该不变量，故用 AST 行号钉住次序。
    行为侧由 `test_after_start_exception_pops_dialog_and_logs_full_traceback` 守（异常 ⇒ 码 1 +
    弹窗 + 全栈落盘）；本条守的是行为测试**看不见**的次序不变量。
    """
    tree = _parse_desktop()
    after = _funcs_by_name(tree)["_after_start"]
    handlers = [
        handler
        for node in ast.walk(after)
        if isinstance(node, ast.Try)
        for handler in node.handlers
    ]
    assert handlers, "_after_start 必须接住异常（后台线程里未接住的异常会静默杀死线程）"
    for handler in handlers:
        assigns = [stmt for stmt in handler.body if _assigns_result_failure(stmt)]
        crashes = [call for call in _calls(handler) if _call_label(call) == "write_crash"]
        assert assigns, "异常出口必须把 result[0] 置 1（否则 start() 返回后进程装成功）"
        assert crashes, "异常出口必须 write_crash（全栈落盘 + 弹窗）"
        assert min(stmt.lineno for stmt in assigns) < min(call.lineno for call in crashes), (
            "必须先钉死失败退出码（result[0] = 1）再 write_crash：留痕路径二次异常时退出码不得停留在成功"
        )


def test_run_desktop_outer_failure_pops_one_liner_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """外层失败路径：弹窗只给人话一句（给出日志路径），**不得**原样吐 traceback。

    缺陷现场：`run_desktop` 的 `except Exception` 此前把 `traceback.format_exc()` 原样传给
    `write_crash` ⇒ 完整堆栈进弹窗（无控制台用户被一大段英文栈吓住，也读不出所以然）。
    修法：traceback 只落盘，弹窗一句话"启动失败，详情见 <log_path>"（路径一并给出）。
    """
    mod = _mod()
    monkeypatch.setenv("DELECTOR_DATA_DIR", str(tmp_path))
    log_path = tmp_path / "launch.log"
    popped: List[Tuple[str, str]] = []
    monkeypatch.setattr(mod, "_message_box", lambda title, detail: popped.append((title, detail)))

    def _boom(*_a: Any, **_k: Any) -> int:
        raise RuntimeError("boom-outer")

    monkeypatch.setattr(mod, "_run_desktop_inner", _boom)

    code = mod.run_desktop(port=8000)

    assert code == 1, "外层异常必须以非零码退出"
    assert popped, "外层失败必须弹窗"
    _title, detail = popped[0]
    assert "Traceback" not in detail, f"弹窗文案不得含 traceback（排障信息只许落盘）：{detail!r}"
    assert "Traceback" in log_path.read_text(encoding="utf-8"), "全栈 traceback 必须落盘"
    assert str(log_path) in detail, "弹窗必须给出日志路径，用户/支持者才能定位"


def test_tray_show_lan_address_fails_readably_on_non_utf8_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """黄牌 3：lan-address.txt 含非 UTF-8 字节 ⇒ 走可读失败路径（弹窗 + 留痕），不把异常漏进托盘回调。

    旧实现 except 只捕 OSError：坏文件抛的 UnicodeDecodeError 会穿过 `_read_lan_address` 逃进
    pystray 回调 ⇒ 托盘线程静默死亡。扩为 (OSError, UnicodeDecodeError) 后坏文件与缺失同路。
    """
    mod = _mod()
    monkeypatch.setenv("DELECTOR_DATA_DIR", str(tmp_path))
    (tmp_path / "lan-address.txt").write_bytes(b"\xff\xfe\x80stale-bytes")  # 非 UTF-8 坏文件
    popped: List[str] = []
    monkeypatch.setattr(mod, "_message_box", lambda title, detail: popped.append(title))

    handlers = mod.build_tray_handlers(mod.TRAY_MENU_SPEC, window=object(), coordinator=mod.QuitCoordinator())
    handlers[dict(mod.TRAY_MENU_SPEC)["显示局域网地址"]]()  # 不得抛

    assert popped, "坏文件必须给出可见的失败提示，不许让异常逃逸进托盘回调"
    log_text = (tmp_path / "launch.log").read_text(encoding="utf-8")
    assert "显示局域网地址" in log_text, "失败也要落 launch.log，不能只有弹窗"


# ── 本轮 A 系列 Task 2（P0-2）：退出路径有界 + 根除「假成功」日志 ──────────────────────
# 真因（审计 P0-2，机制经质疑席**纠正**；勿照「uvicorn wait_for(None)」的旧说法改）：
#   ① `start.py` 退出时 `thread.join()` 裸等（无超时）；② uvicorn 线程非 daemon；
#   ③ `shutdown()` 的返回值被丢弃后仍无条件 print「服务已停止」（假成功）；
#   ④ main() 返回后解释器退出时 `threading._shutdown()` 再 join 那个非 daemon 线程
#      ⇒「已停止」已打印、进程仍挂、8000 仍占 ⇒ 下次启动 `_handle_existing_port` 命中旧实例。
# 修法（本组用例钉死）：`build_server` 设 `timeout_graceful_shutdown`；join 带显式超时；
# `shutdown()` 返回 False ⇒ 人话进 stderr + `sys.exit(1)`（干净退出 0 / 不干净退出 1）。
def _stub_main_until_exit_path(
    monkeypatch: pytest.MonkeyPatch, thread: Any, shutdown_result: bool
) -> None:
    """把 `start.main()` 的前置段整体换成替身，只让「退出路径」那段真代码受测。

    不起真 uvicorn、不 import 真 `delector.server`（同该文件既有替身的两条理由：真起服务会
    绑端口/拉 spaCy；`delector.server` 一 import，`database.DATA_DIR` 就按仓库根落定）。
    端口探针 / Android 判定（顺带不起浏览器线程）/ 数据目录引导 / 建服 / 收尸全部压平。
    """
    import start
    from delector.core import server_lifecycle

    fake_server = types.SimpleNamespace(should_exit=False)
    monkeypatch.setattr(start, "is_port_in_use", lambda _port: False)
    monkeypatch.setattr(start, "is_android", lambda: True)  # 走回环、且不起浏览器线程
    monkeypatch.setattr(start, "bootstrap_data_dir", lambda *_a, **_k: "")
    monkeypatch.setattr(server_lifecycle, "build_server", lambda host, port, app: fake_server)
    monkeypatch.setattr(server_lifecycle, "serve_in_thread", lambda server: thread)
    monkeypatch.setattr(server_lifecycle, "shutdown", lambda *_a, **_k: shutdown_result)
    monkeypatch.setitem(sys.modules, "delector.server", types.SimpleNamespace(app=object()))


class _FinishedThread:
    """已结束的 server 线程替身：join 立即返回、is_alive 恒 False（「服务已停」的干净态）。"""

    daemon = False

    def join(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def is_alive(self) -> bool:
        return False


class _NeverEndingThread:
    """「永不结束」的 server 线程替身：is_alive 恒 True；第 N 次 join 抛 KeyboardInterrupt。

    第 N 次 join 抛 KeyboardInterrupt 模拟 Ctrl+C —— 真实里被信号打断的正是那一次等待。
    每次 join 收到的 timeout 都被记录：修复后的实现每次都带显式超时；若退回裸 `join()`
    （本次要根除的缺陷形态），记录到 None ⇒ 断言转红。**桩自身绝不无界等待**：「没给超时」
    由断言捕获，而不是让整套用例挂死 —— 那会把可诊断的「红」变成不可诊断的「挂起」，正违反
    本仓反挂死纪律（禁 join 无超时 / 单用例最坏 <5s）。
    """

    daemon = False

    def __init__(self, interrupt_on_join: int) -> None:
        self.join_timeouts: List[Optional[float]] = []
        self._interrupt_on_join = interrupt_on_join

    def join(self, timeout: Optional[float] = None) -> None:
        self.join_timeouts.append(timeout)
        if len(self.join_timeouts) >= self._interrupt_on_join:
            raise KeyboardInterrupt

    def is_alive(self) -> bool:
        return True


def test_start_main_reports_unclean_shutdown_on_stderr_with_exit_code_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`shutdown()` 如实返回 False ⇒ 不得打印「服务已停止」（假成功），错误进 stderr、退出码 1。

    旧失败现场：返回值被丢弃、`print("[提示] 服务已停止。")` 无条件执行 ⇒ 用户看到「成功」，
    进程随后挂住、8000 仍被占。这条把「停不干净 ⇒ 可见失败 + 退出码 1」钉死。
    """
    import start

    _stub_main_until_exit_path(monkeypatch, _FinishedThread(), shutdown_result=False)

    with pytest.raises(SystemExit) as exc_info:
        start.main()

    assert exc_info.value.code == 1, "停不干净必须以退出码 1 报告（干净路径才是 0）"
    captured = capsys.readouterr()
    assert "[提示] 服务已停止。" not in captured.out, "shutdown 失败时不得打印成功提示（假成功）"
    assert "[错误] 服务未能干净退出（端口可能仍被占用）。" in captured.err, (
        "「停不干净」必须进 stderr（人话、可被日志采集，不许被吞）"
    )


def test_start_main_keeps_stopped_notice_and_clean_return_on_successful_shutdown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """干净路径：`main()` 正常返回（裸调语义下 ⇒ 进程退出码 0）、原提示保留、stderr 无噪音。"""
    import start

    _stub_main_until_exit_path(monkeypatch, _FinishedThread(), shutdown_result=True)

    start.main()  # 不得抛 SystemExit（若抛，本用例直接红）

    captured = capsys.readouterr()
    assert "[提示] 服务已停止。" in captured.out, "干净退出必须保留既有成功提示"
    assert captured.err == "", f"干净路径不得往 stderr 写噪音：{captured.err!r}"


def test_start_main_exit_path_stays_bounded_when_server_thread_never_ends(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """有界性探针：线程**永不结束**时，Ctrl+C 后的「收尸→报告→退出」仍必须在有界时间内完成。

    三层断言：① 每次 join 都带显式超时且与 `SHUTDOWN_GRACE_S` 同一口径（退出路径上不允许
    存在第二个等待数字）；② 整条路径秒级结束（绝不挂死）；③ 停不干净 ⇒ 退出码 1 + stderr 错误。
    """
    import start
    from delector.core import server_lifecycle

    thread = _NeverEndingThread(interrupt_on_join=1)
    _stub_main_until_exit_path(monkeypatch, thread, shutdown_result=False)

    started = time.monotonic()
    with pytest.raises(SystemExit) as exc_info:
        start.main()
    elapsed = time.monotonic() - started

    assert exc_info.value.code == 1
    assert thread.join_timeouts, "退出路径必须真的等待过线程"
    assert all(t is not None for t in thread.join_timeouts), (
        f"每次 join 都必须带显式超时（禁裸 join —— 线程不结束时它就无上界）：{thread.join_timeouts!r}"
    )
    assert all(t == server_lifecycle.SHUTDOWN_GRACE_S for t in thread.join_timeouts), (
        f"join 超时必须与 shutdown() 的宽限同口径（SHUTDOWN_GRACE_S，单一来源）：{thread.join_timeouts!r}"
    )
    assert elapsed < 2.5, f"退出路径必须在有界时间内结束（红线：单用例最坏 <5s），实测 {elapsed:.2f}s"
    captured = capsys.readouterr()
    assert "[提示] 服务已停止。" not in captured.out
    assert "[错误]" in captured.err


def test_build_server_sets_graceful_shutdown_timeout_matching_the_shutdown_grace() -> None:
    """`build_server` MUST 给 uvicorn 设 `timeout_graceful_shutdown`（否则在途请求可无限拖住退出）。

    为什么钉「等于 `SHUTDOWN_GRACE_S`」而非硬编码：uvicorn 侧（本参数）与调用方侧（`shutdown()`
    的 join 宽限、start.py 的轮询超时）必须共用同一个数字 —— 三处各写一个，迟早在慢机器上漂移成
    「uvicorn 还在等、调用方已宣告停不干净」的静默错位。只组装、不启动：不绑端口、不起服务。
    """
    from delector.core import server_lifecycle

    server = server_lifecycle.build_server("127.0.0.1", 9, object())

    assert server.config.timeout_graceful_shutdown == server_lifecycle.SHUTDOWN_GRACE_S, (
        "uvicorn 优雅退出宽限必须与 shutdown()/start.py 同一口径（SHUTDOWN_GRACE_S）"
    )
