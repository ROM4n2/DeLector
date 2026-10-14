# -*- coding: utf-8 -*-
r"""P0-1 回归锁：桌面壳建服**之前**的端口/身份校验。

已证实的缺陷
------------
`desktop.py` 的 `_run_desktop_inner` 曾直接 `build_server` + `serve_in_thread`，**没有**
端口占用/身份校验（对照 `start.py` 有）。uvicorn 绑定失败走 `sys.exit` ⇒ 被
`threading.excepthook` 静默忽略 ⇒ server 线程真死；而 `await_ready` 对**旧实例**照样
返回 200+身份 ⇒ 照常亮主窗口 ⇒ 用户以为升级了，实际是旧进程在服务。

本组用例钉三分支
----------------
- 端口空闲 ⇒ 正常建服（`build_server` 被调到）；
- 被占且身份是 DeLector ⇒ 弹窗 + 日志 + 退出码 3，**绝不**调 build_server
  （不做"连过去"的窗口复用——拒绝启动是诚实且最简单的处理）；
- 被占但不是 DeLector ⇒ 弹窗 + 日志 + 退出码 3。

Task 3 适配（本文件为何大改）
----------------------------
Task 3 把 `from delector.server import app` / `build_server` / `serve_in_thread` 从
`_run_desktop_inner` 搬进了 `_after_start`（`webview.start()` 调度的事件循环内）。原
`_stub_server_chain` 把 `_show_window` 整个桩掉 ⇒ **build_server 陷阱永不可达**：端口空闲
时它不红（该调没调到也看不见），端口被占时 `not in events` 恒真（vacuous，删不删校验都绿）。
修法：流程级用例改经**假 webview** 驱动 `_show_window` → `_after_start`（范式同
`tests/test_desktop_shell.py` 的录制替身），让陷阱重新可达、重新具备判别力。

**变异自证**：把 `_run_desktop_inner` 里的校验调用删掉 ⇒
`test_run_desktop_inner_does_not_build_server_when_port_is_taken` 立即转红
（流程直达 build_server 陷阱 / 退出码不再是 3）；AST 接线用例同时转红。
"""

import ast
import sys
import types
from pathlib import Path
from typing import Any, List, Tuple

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _mod() -> Any:
    import desktop

    return desktop


def _stub_environment(
    monkeypatch: pytest.MonkeyPatch,
    mod: Any,
    tmp_path: Path,
    events: List[Any],
    *,
    occupied: bool,
    identity: bool,
) -> None:
    """替身环境：WebView2 恒在、bootstrap 不碰真实目录、端口/身份由参数钉死。

    `is_port_in_use` / `probe_identity` 是被测函数**调用点内**惰性 import 的源模块
    属性，故直接 monkeypatch 源模块（`start` / `delector.core.server_lifecycle`）。

    `DELECTOR_DATA_DIR` 钉到 tmp_path、`get_local_ip` 钉成回环：`_run_desktop_inner` 会调
    `write_lan_address`，不钉就会写进**真实**数据目录、还真去探一次局域网 IP（Task 3 后流程
    会一路走到 `_after_start`，这两颗钉子从此是必需项而非可选项）。
    """
    monkeypatch.setattr(mod, "ensure_webview2_runtime", lambda: True)
    monkeypatch.setattr(mod, "bootstrap_data_dir", lambda env: str(tmp_path))
    monkeypatch.setattr(
        mod, "_message_box", lambda title, detail: events.append(("box", title, detail))
    )
    monkeypatch.setenv("DELECTOR_DATA_DIR", str(tmp_path))

    import start
    from delector.core import server_lifecycle

    monkeypatch.setattr(start, "is_port_in_use", lambda port: occupied)
    monkeypatch.setattr(start, "get_local_ip", lambda: "127.0.0.1")
    monkeypatch.setattr(server_lifecycle, "probe_identity", lambda port, **_k: identity)


def _stub_fake_server_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 `delector.server` 换成假模块：`from delector.server import app` 只取 `app` 属性。

    不换就会 import 真 server：那一跑把 DATA_DIR 按仓库根落定（desktop.py 的 ⚠️ 注释即为此），
    直接污染测试隔离 —— 正是测试卫生要防的雷。
    """
    fake_server = types.ModuleType("delector.server")
    fake_server.app = object()  # `from delector.server import app` 只取这个属性
    monkeypatch.setitem(sys.modules, "delector.server", fake_server)


def _stub_server_chain(monkeypatch: pytest.MonkeyPatch, mod: Any, events: List[Any]) -> None:
    """替身服务链：build_server 陷阱记录调用（变异自证的哨兵），其余 noop。

    Task 3 后建服/起服在 `_after_start` 里，故必须配 `_stub_fake_server_module`（否则真 import
    server）。**不再**桩 `_show_window`：端口用例要经它真正走到 `_after_start`，陷阱才可达
    （旧实现桩掉它 ⇒ 端口空闲时建服哨兵永不响、端口被占时 `not in events` 恒真）。
    """
    _stub_fake_server_module(monkeypatch)

    def trap_build_server(host: str, port: int, app: Any) -> Any:
        events.append(("build_server", port))
        return object()

    monkeypatch.setattr(mod, "build_server", trap_build_server)
    monkeypatch.setattr(mod, "serve_in_thread", lambda server: object())
    monkeypatch.setattr(mod, "coordinated_shutdown", lambda *args: None)


def _install_fake_webview(monkeypatch: pytest.MonkeyPatch, mod: Any) -> None:
    """装一个**假 webview**：`start` 同步调度首参函数（`_after_start`），让建服陷阱可达。

    Task 3 后 `build_server` / `serve_in_thread` 只在 `_after_start` 体内，而 `_after_start`
    只有经 `webview.start(func, args)` 才被调到 —— 把 `_show_window` 整个桩掉等于把陷阱所在的
    那一层拆了，端口空闲也永远走不到它。同步调度（不真起 GUI 循环）还让 `server_handoff` 在
    `start` 返回前就装好 server/thread，`_run_desktop_inner` 的 finally 才收得到尸。
    """

    class _Signal:
        def __iadd__(self, _other: Any) -> "_Signal":
            return self

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
            return None

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
    # 就绪判定与托盘都不能真跑：一个会去打真 HTTP（60s 宽限期），一个会拉真 pystray。
    monkeypatch.setattr(mod, "await_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(mod, "_start_tray", lambda *_a, **_k: None)


# ── 分支①：端口空闲 ⇒ 正常建服 ───────────────────────────────────────────────
def test_port_free_proceeds_to_build_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mod = _mod()
    events: List[Any] = []
    _stub_environment(monkeypatch, mod, tmp_path, events, occupied=False, identity=False)
    _stub_server_chain(monkeypatch, mod, events)
    # 经假 webview 驱动 _show_window → _after_start：Task 3 后 build_server 只在后者体内，
    # 桩掉 _show_window 会让本陷阱永不可达（旧实现的假绿形态：该调没调到也全绿）。
    _install_fake_webview(monkeypatch, mod)

    code = mod._run_desktop_inner(8000, str(tmp_path / "launch.log"))

    assert code == 0, "端口空闲 ⇒ 正常启动路径，退出码 0"
    assert ("build_server", 8000) in events, "端口空闲 ⇒ 必须照常建服（不得误拦）"
    assert not any(e[0] == "box" for e in events), "端口空闲 ⇒ 不得弹窗"


# ── 分支②：被占且是 DeLector ⇒ 弹窗 + 日志 + 退出码 3，绝不建服 ────────────────
def test_run_desktop_inner_does_not_build_server_when_port_is_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """被占（任一身份）⇒ 拒绝启动：build_server 陷阱**不得**被调到 —— 这条就是
    "删掉校验调用"变异的红线：校验一删，流程直达 build_server 陷阱，本用例转红。

    Task 3 适配：旧版把 `_show_window` 整个桩掉 ⇒ 陷阱不可达 ⇒ `not in events` 恒真
    （vacuous）。现同分支① 经假 webview 驱动到 `_after_start`，陷阱可达 ⇒ 判别力恢复：
    删掉校验 ⇒ 退出码变 0 且陷阱被调到，两条断言各自都能转红。
    """
    mod = _mod()
    events: List[Any] = []
    _stub_environment(monkeypatch, mod, tmp_path, events, occupied=True, identity=True)
    _stub_server_chain(monkeypatch, mod, events)
    _install_fake_webview(monkeypatch, mod)
    log_path = tmp_path / "launch.log"

    code = mod._run_desktop_inner(8000, str(log_path))

    assert code == 3, "端口被占 ⇒ 必须非零退出（3 = 端口/身份校验失败）"
    assert ("build_server", 8000) not in events, "旧实例在跑 ⇒ 绝不能再建第二个服务"


def test_port_taken_by_delector_pops_dialog_and_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """失败路径必须**弹窗 + 日志**（不许只写日志）：文案点明"已有 DeLector 在运行"。"""
    mod = _mod()
    events: List[Any] = []
    _stub_environment(monkeypatch, mod, tmp_path, events, occupied=True, identity=True)
    _stub_server_chain(monkeypatch, mod, events)
    _install_fake_webview(monkeypatch, mod)
    log_path = tmp_path / "launch.log"

    mod._run_desktop_inner(8000, str(log_path))

    boxes = [e for e in events if e[0] == "box"]
    assert boxes, "必须弹窗（用户唯一可见的失败反馈）"
    assert "DeLector" in boxes[0][1], "弹窗标题必须点名 DeLector 已在运行"
    assert "端口 8000" in boxes[0][2], "弹窗必须写明端口号"
    assert "退出旧实例" in boxes[0][2], "弹窗必须给出行动指引（退出旧实例）"

    content = log_path.read_text(encoding="utf-8")
    assert "8000" in content and "DeLector" in content, "拒绝原因必须落 launch.log"


# ── 分支③：被占但不是 DeLector ⇒ 弹窗 + 日志 + 退出码 3 ───────────────────────
def test_port_taken_by_other_program_pops_dialog_and_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    mod = _mod()
    events: List[Any] = []
    _stub_environment(monkeypatch, mod, tmp_path, events, occupied=True, identity=False)
    _stub_server_chain(monkeypatch, mod, events)
    _install_fake_webview(monkeypatch, mod)
    log_path = tmp_path / "launch.log"

    code = mod._run_desktop_inner(8000, str(log_path))

    assert code == 3, "端口被无关程序占用 ⇒ 同样非零退出"
    assert ("build_server", 8000) not in events

    boxes = [e for e in events if e[0] == "box"]
    assert boxes, "必须弹窗"
    assert "其他程序" in boxes[0][2], "弹窗必须说明端口被其他程序占用"

    content = log_path.read_text(encoding="utf-8")
    assert "其他程序" in content, "拒绝原因必须落 launch.log"


# ── AST 接线钉：校验调用必须在 build_server 之前（Task 3 后两者已不在同一函数）──
def _is_webview_start_call(call: ast.Call) -> bool:
    """`webview.start(...)`：属性链锚定 `webview` 对象，防同名方法误判。"""
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "start"
        and isinstance(func.value, ast.Name)
        and func.value.id == "webview"
    )


def _name_calls_in_source_order(node: ast.AST) -> List[str]:
    """节点内全部 `f(...)`（Name 型 func）调用名，按 (行号, 列号) 排序后返回。

    `ast.walk` 是 BFS 不是源码顺序，比先后必须显式排序后再取下标。
    """
    calls = [
        call
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    ]
    calls.sort(key=lambda call: (call.lineno, call.col_offset))
    return [call.func.id for call in calls]


def test_port_check_is_wired_before_build_server_in_run_desktop_inner():
    """跨函数顺序钉（Task 3 适配）：端口校验在 `_run_desktop_inner` 内、且早于进入 GUI 循环的
    调用；`build_server` 在 `webview.start()` 调度函数（`_after_start`）体内。

    旧断言在**同一函数**里找 `_check_port_or_fail` 与 `build_server` 两个名字 —— Task 3 把建服
    搬进 `_after_start` 后 `names.index("build_server")` 抛 ValueError（本用例当初就这么红的）。
    顺序断言随之改成跨函数：
    - `_check_port_or_fail` 必须在 `_run_desktop_inner` 内、且早于 `_show_window`（后者经
      `webview.start` 调度 `_after_start` 建服）——删掉校验调用 ⇒ 本用例立即转红（变异自证红线）；
    - `build_server` 必须在 `webview.start()` 首参函数体内 —— 搬回循环外 ⇒ 同样转红。
    """
    tree = ast.parse((REPO_ROOT / "desktop.py").read_text(encoding="utf-8"))
    funcs = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    inner = funcs.get("_run_desktop_inner")
    assert inner is not None, "desktop.py 里找不到 _run_desktop_inner（前提变了，需重写用例）"

    inner_names = _name_calls_in_source_order(inner)
    assert "_check_port_or_fail" in inner_names, "建服前必须调用端口/身份校验（删掉 = 变异自证红线）"
    assert "_show_window" in inner_names, "_run_desktop_inner 必须经 _show_window 进 GUI 循环"
    assert inner_names.index("_check_port_or_fail") < inner_names.index("_show_window"), (
        "端口/身份校验必须早于 _show_window（后者经 webview.start 调度 _after_start 建服；"
        "晚一步就失去意义）"
    )

    start_calls = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call) and _is_webview_start_call(call)
    ]
    assert len(start_calls) == 1, f"应恰有一处 webview.start(...) 调用，实际 {len(start_calls)}"
    first_arg = start_calls[0].args[0]
    assert isinstance(first_arg, ast.Name), "webview.start 的首参必须是函数名（而非内联 lambda）"
    delegated = funcs.get(first_arg.id)
    assert delegated is not None, (
        f"webview.start 首参 {first_arg.id!r} 不是顶层函数（前提变了，需重写用例）"
    )
    assert "build_server" in _name_calls_in_source_order(delegated), (
        "build_server 必须在 webview.start() 调度函数（_after_start）体内：Task 3 把重活搬进"
        "事件循环，端口空闲时它仍在校验之后才执行"
    )


# ── Task 3：server_handoff 交接机制（webview.start 返回后必须收尸）──────────────
def test_server_handoff_reaps_the_fake_server_after_start_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Y3：交接容器的**直接**锁（此前该机制零直接测试）。

    Task 3 把建服/起服搬进 `_after_start`（`webview.start()` 调度的后台线程）后，server/thread
    只能经 `server_handoff` 回传主线程收尸。本用例用**真 dict** + 桩 `coordinated_shutdown`，
    断言 `webview.start()` 返回后假 server/thread 真的被收尸 —— 锁住"不留残留服务"。
    删掉 `_after_start` 里的交接写入、或删掉 `_run_desktop_inner` finally 里的收尸 ⇒ 本用例转红。
    """
    mod = _mod()
    events: List[Any] = []
    reaped: List[Tuple[Any, Any]] = []
    _stub_environment(monkeypatch, mod, tmp_path, events, occupied=False, identity=False)
    _stub_server_chain(monkeypatch, mod, events)
    _install_fake_webview(monkeypatch, mod)
    fake_server, fake_thread = object(), object()
    # 覆写建服/起服替身：返回**可辨识的哨兵**（才能断言收尸作用于本次起的 server/thread），
    # 同时保留 build_server 陷阱记录（哨兵与陷阱不是二选一）。
    def _sentinel_build_server(host: str, port: int, app: Any) -> Any:
        events.append(("build_server", port))
        return fake_server

    monkeypatch.setattr(mod, "build_server", _sentinel_build_server)
    monkeypatch.setattr(mod, "serve_in_thread", lambda *_a: fake_thread)

    def _reap(server: Any, thread: Any, log_path: str) -> None:
        reaped.append((server, thread))

    monkeypatch.setattr(mod, "coordinated_shutdown", _reap)

    code = mod._run_desktop_inner(8000, str(tmp_path / "launch.log"))

    assert code == 0
    assert ("build_server", 8000) in events, "前提：建服陷阱确被调到（交接容器里才有东西可收）"
    assert reaped == [(fake_server, fake_thread)], (
        "webview.start() 返回后必须用交接容器里的 server/thread 收尸一次（绝不留在残留服务）"
    )
