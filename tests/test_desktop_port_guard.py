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

**变异自证**：把 `_run_desktop_inner` 里的校验调用删掉 ⇒
`test_run_desktop_inner_does_not_build_server_when_port_is_taken` 立即转红
（build_server 陷阱会被调到 / 退出码不再是 3）；AST 接线用例同时转红。
"""

import ast
from pathlib import Path
from typing import Any, List

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
    """
    monkeypatch.setattr(mod, "ensure_webview2_runtime", lambda: True)
    monkeypatch.setattr(mod, "bootstrap_data_dir", lambda env: str(tmp_path))
    monkeypatch.setattr(
        mod, "_message_box", lambda title, detail: events.append(("box", title, detail))
    )

    import start
    from delector.core import server_lifecycle

    monkeypatch.setattr(start, "is_port_in_use", lambda port: occupied)
    monkeypatch.setattr(server_lifecycle, "probe_identity", lambda port, **_k: identity)


def _stub_server_chain(monkeypatch: pytest.MonkeyPatch, mod: Any, events: List[Any]) -> None:
    """替身服务链：build_server 陷阱记录调用（变异自证的哨兵），其余 noop。"""

    def trap_build_server(host: str, port: int, app: Any) -> Any:
        events.append(("build_server", port))
        return object()

    monkeypatch.setattr(mod, "build_server", trap_build_server)
    monkeypatch.setattr(mod, "serve_in_thread", lambda server: object())
    monkeypatch.setattr(mod, "_show_window", lambda *args: 0)
    monkeypatch.setattr(mod, "coordinated_shutdown", lambda *args: None)


# ── 分支①：端口空闲 ⇒ 正常建服 ───────────────────────────────────────────────
def test_port_free_proceeds_to_build_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mod = _mod()
    events: List[Any] = []
    _stub_environment(monkeypatch, mod, tmp_path, events, occupied=False, identity=False)
    _stub_server_chain(monkeypatch, mod, events)

    code = mod._run_desktop_inner(8000, str(tmp_path / "launch.log"))

    assert code == 0, "端口空闲 ⇒ 正常启动路径，退出码 0"
    assert ("build_server", 8000) in events, "端口空闲 ⇒ 必须照常建服（不得误拦）"
    assert not any(e[0] == "box" for e in events), "端口空闲 ⇒ 不得弹窗"


# ── 分支②：被占且是 DeLector ⇒ 弹窗 + 日志 + 退出码 3，绝不建服 ────────────────
def test_run_desktop_inner_does_not_build_server_when_port_is_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """被占（任一身份）⇒ 拒绝启动：build_server 陷阱**不得**被调到 —— 这条就是
    "删掉校验调用"变异的红线：校验一删，流程落到 build_server 陷阱，本用例转红。"""
    mod = _mod()
    events: List[Any] = []
    _stub_environment(monkeypatch, mod, tmp_path, events, occupied=True, identity=True)
    _stub_server_chain(monkeypatch, mod, events)
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
    log_path = tmp_path / "launch.log"

    code = mod._run_desktop_inner(8000, str(log_path))

    assert code == 3, "端口被无关程序占用 ⇒ 同样非零退出"
    assert ("build_server", 8000) not in events

    boxes = [e for e in events if e[0] == "box"]
    assert boxes, "必须弹窗"
    assert "其他程序" in boxes[0][2], "弹窗必须说明端口被其他程序占用"

    content = log_path.read_text(encoding="utf-8")
    assert "其他程序" in content, "拒绝原因必须落 launch.log"


# ── AST 接线钉：校验调用必须在 build_server 之前（结构层冗余保险） ─────────────
def test_port_check_is_wired_before_build_server_in_run_desktop_inner():
    tree = ast.parse((REPO_ROOT / "desktop.py").read_text(encoding="utf-8"))
    inner = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_run_desktop_inner"),
        None,
    )
    assert inner is not None, "desktop.py 里找不到 _run_desktop_inner（前提变了，需重写用例）"

    calls = [
        call
        for call in ast.walk(inner)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    ]
    # ast.walk 是 BFS 不是源码顺序，必须按 (lineno, col_offset) 排序后再比先后。
    calls.sort(key=lambda c: (c.lineno, c.col_offset))
    names: List[str] = []
    for call in calls:
        assert isinstance(call.func, ast.Name), "前提：func 已在上方过滤为 Name"
        names.append(call.func.id)
    assert "_check_port_or_fail" in names, "建服前必须调用端口/身份校验（删掉 = 变异自证红线）"
    assert names.index("_check_port_or_fail") < names.index("build_server"), (
        "端口/身份校验必须排在 build_server 之前（晚一步就失去意义）"
    )
