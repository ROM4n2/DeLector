# -*- coding: utf-8 -*-
r"""桌面壳「入口分派与服务形态」域：2828 行原 `test_desktop_shell.py` 按被测面切分后的残余（C6 Task 6）。

本文件保留「入口」面：`dispatch` 分派与 `--server-only`（含 lan-address.txt 地址出口）、
无控制台 stdout/stderr 收口 + `--debug-console`、以及入口「先收口后解析」的 None 流回归。

已拆出的域（各自独立成文件，逐字搬迁；搬前行号见各文件段头）：
  `test_desktop_bootstrap.py`        WebView2 检测 / 日志落点 / 轮转
  `test_desktop_tray_exit.py`        退出编排 / 托盘 / 崩溃与失败出口 / 有界退出
  `test_desktop_startup_guards.py`   导入安全 / 流写纪律 / 导入探针 / AppUserModelID
  `test_desktop_window_lifecycle.py` 事件循环时机 / 首屏与阶段标记 / 主窗口 / 预启动计时

跨域共用 helper（`_mod` 等）经 `tests/server_helpers.py` 显式 import（不再依赖隐式同文件可见）。
本文件仍自带 autouse 兜底夹具 `_isolate_data_dir`（`DELECTOR_DATA_DIR` → `tmp_path`）：元测试
`test_all_dispatch_tests_isolate_the_data_dir` 静态扫描**本模块源码**里有没有 autouse fixture
定义，改成 import 注册它会转红；同一夹具的共用副本另在 `tests/server_helpers.py`（供上面四个
文件按名 import），本处保留文件内定义即为该静态扫描的可判据形态。
"""

import ast
import sys
import types
from pathlib import Path
from typing import Any, Callable, Dict, List

import pytest
from server_helpers import _mod


# ── Task 6 卫生：全局把数据目录钉到 tmp_path（autouse 兜底，防漏）────────────────────
# （C6 Task 6：同一夹具亦在 `tests/server_helpers.py` 供四个拆出的域文件按名 import；
#  本处保留文件内定义 —— 元测试 `test_all_dispatch_tests_isolate_the_data_dir` 静态扫描本模块
#  源码找 autouse fixture 定义，改成 import 注册会把它判红。）
@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """任何用例默认把 `DELECTOR_DATA_DIR` 钉到 `tmp_path`：**绝不**落到开发者真实数据目录。

    为什么 autouse：`dispatch()` 的 `--server-only` 路径会读 `os.environ` 解析日志/地址落点
    （`resolve_log_path` → `ensure_streams` → `rotate_log_if_needed`）—— 个别用例漏写 `tmp_path`
    就会滚动真 `launch.log`、写出真 `lan-address.txt`（Task 5 前还会删真 `lan-address.txt`），落进
    `%LOCALAPPDATA%\\DeLector` / `~/.local/share/DeLector`。逐条加易漏，故用**全局兜底**：新增用例
    不写都安全。`resolve_log_path` 的既有用例都显式传 dict（不走 `os.environ`），不受影响；需要别的
    落点的用例自行 `monkeypatch.setenv` 覆盖即可（后设生效）。
    """
    monkeypatch.setenv("DELECTOR_DATA_DIR", str(tmp_path))


# ── 元测试：本文件每条 `dispatch(...)` 用例都必须隔离数据目录（Task 6 测试卫生）─────────
def _calls_dispatch(fn: ast.FunctionDef) -> bool:
    """函数体（含嵌套）里是否有 `xxx.dispatch(...)` 调用。"""
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "dispatch"
        for node in ast.walk(fn)
    )


def _references_data_dir_env(fn: ast.FunctionDef) -> bool:
    """函数体里是否显式引用了 `DELECTOR_DATA_DIR`（字符串常量，用于 monkeypatch.setenv）。"""
    return any(
        isinstance(node, ast.Constant) and node.value == "DELECTOR_DATA_DIR" for node in ast.walk(fn)
    )


def _module_has_autouse_data_dir_fixture(tree: ast.Module) -> bool:
    """本文件是否有 autouse fixture 把 `DELECTOR_DATA_DIR` 全局钉住（`tmp_path` 兜底）。"""
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        autouse = any(
            isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and dec.func.attr == "fixture"
            and any(
                kw.arg == "autouse" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                for kw in dec.keywords
            )
            for dec in node.decorator_list
        )
        if autouse and _references_data_dir_env(node):
            return True
    return False


def test_all_dispatch_tests_isolate_the_data_dir() -> None:
    """元测试：凡调 `dispatch(...)` 的用例都必须隔离数据目录 —— 防污染**真实**落点。

    为什么必须是**元测试**而非逐条断言：隔离是**跨用例**的卫生约束，单条断言只能顾到当下这几条，
    新增一条 `dispatch` 用例忘了 `tmp_path` 时它不会红。`dispatch()` 的 `--server-only` 路径会
    `resolve_log_path(os.environ)` + `ensure_streams` + `rotate_log_if_needed` —— 没隔离就滚动真
    `launch.log`、写出真 `lan-address.txt`（Task 5 前还会删掉真 `lan-address.txt`），落进开发者真实
    数据目录（Windows `%LOCALAPPDATA%\\DeLector` / Linux `~/.local/share/DeLector`）。

    两种隔离方式任一即算通过：用例体里显式 `DELECTOR_DATA_DIR`，或本文件有 autouse fixture 全局兜底。
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    module_guarded = _module_has_autouse_data_dir_fixture(tree)
    offenders = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name.startswith("test_")
        and _calls_dispatch(node)
        and not module_guarded
        and not _references_data_dir_env(node)
    ]
    assert not offenders, (
        "这些 dispatch 用例未隔离数据目录（会滚动真 launch.log、写出真 lan-address.txt 到 "
        f"%LOCALAPPDATA%\\DeLector / ~/.local/share/DeLector）：{offenders}；"
        "请各自加 tmp_path + monkeypatch.setenv('DELECTOR_DATA_DIR', ...)，或补一条 autouse fixture 全局兜底"
    )


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
    # Task 5：dispatch 现在会多传一个**可选** on_serving 回调（地址写入时机），故替身须收下它。
    monkeypatch.setattr(start, "main", lambda **kwargs: calls.append("main"))
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
    # Task 5：替身收下 dispatch 新增的可选 on_serving 回调（地址写入时机）。
    monkeypatch.setattr(start, "main", lambda **kwargs: None)
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
    # Task 5：替身收下 dispatch 新增的可选 on_serving 回调（地址写入时机）。
    monkeypatch.setattr(start, "main", lambda **kwargs: None)

    mod.dispatch(server_only=True, port=mod.DEFAULT_PORT)

    assert capsys.readouterr().err == "", "端口无分歧时不得告警"


# ── `--server-only` 的地址出口：数据目录落 lan-address.txt（无控制台时唯一可见）──
def test_dispatch_server_only_writes_lan_address_after_serving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--server-only` 在**服务真正持有端口之后**把地址写进数据目录 `lan-address.txt`（Task 5）。

    `--windowed` 打包后 stdout 不可见，start.py 的横幅（唯一带 LAN 地址的输出）没了 ⇒
    这份文件是用户拿到 `http://<LAN_IP>:<port>` 的第一出口。写入时机是 Task 5 的要害：
    必须晚于端口校验（由 start.main 在 build_server 成功后回调 on_serving），端口被占 /
    启动失败时不得写（见 `test_dispatch_server_only_leaves_no_address_file_when_port_busy`）。

    这里用替身 start.main **在回调触发的那一刻** 读盘：只要回调一被调用，数据目录就必须
    已有含正确端口的地址文件（端口号取自 start.main 的真相源）。
    """
    import start

    mod = _mod()
    monkeypatch.setenv("DELECTOR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(start, "get_local_ip", lambda: "192.168.1.50")
    captured: Dict[str, str] = {}

    def _fake_main(debug_console: bool = False, on_serving: Any = None) -> None:
        assert on_serving is not None, "dispatch 必须把地址写入回调交给 start.main（端口持有后才写）"
        on_serving(mod.DEFAULT_PORT)  # 模拟 build_server 成功后触发写入
        captured["content"] = (tmp_path / "lan-address.txt").read_text(encoding="utf-8")

    monkeypatch.setattr(start, "main", _fake_main)

    code = mod.dispatch(server_only=True, port=mod.DEFAULT_PORT)

    assert code == 0
    assert "http://" in captured["content"], "文件内容必须是 http:// 开头的地址"
    assert f"http://192.168.1.50:{mod.DEFAULT_PORT}" in captured["content"], (
        "持有端口后必须把 http://<LAN_IP>:<端口> 写进 lan-address.txt"
    )


def test_dispatch_server_only_removes_address_file_on_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """服务退出后不得留下地址文件（Task 5）：它指向已停服务的目标 = 错误目标。

    与上条互补：上条钉"持有时写"，本条钉"退出后删"（`run_server_only` 的 finally 里
    "若已写则删除"）。两态都指向同一不变量：**文件存在 ⟺ 本进程正持有该端口**。
    """
    import start

    mod = _mod()
    monkeypatch.setenv("DELECTOR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(start, "get_local_ip", lambda: "192.168.1.50")

    def _fake_main(debug_console: bool = False, on_serving: Any = None) -> None:
        assert on_serving is not None
        on_serving(mod.DEFAULT_PORT)  # 持有端口 ⇒ 写
        assert (tmp_path / "lan-address.txt").exists(), "写入必须发生在回调触发的那一刻"

    monkeypatch.setattr(start, "main", _fake_main)

    mod.dispatch(server_only=True, port=mod.DEFAULT_PORT)

    assert not (tmp_path / "lan-address.txt").exists(), "退出后必须删除已写地址文件（不留错误目标）"


def test_dispatch_server_only_leaves_no_address_file_when_port_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """端口被占 ⇒ `--server-only` 不得留下 `lan-address.txt`（Task 5，RED-A）。

    旧实现先写地址、后查端口（写地址在 `dispatch`，`start.main` 里才 `is_port_in_use` →
    `sys.exit(1)`）⇒ 端口被别的程序占用时，用户拿到一份**指向别的服务**的地址文件。
    修法：写入挪到服务真正持有端口之后；端口被占即早退，根本没机会写。这里用**真实**
    `start.main`（端口 / 身份探针打桩，不起真服务）复现该路径。
    """
    import start
    from delector.core import server_lifecycle

    mod = _mod()
    monkeypatch.setenv("DELECTOR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(start, "get_local_ip", lambda: "192.168.1.50")  # 有 LAN ⇒ 旧路径会写
    monkeypatch.setattr(start, "is_port_in_use", lambda _port: True)  # 端口被占
    monkeypatch.setattr(server_lifecycle, "probe_identity", lambda *_a, **_k: False)  # 非 DeLector
    monkeypatch.setattr(start, "open_browser", lambda _port: pytest.fail("不得为无关程序打开页面"))

    with pytest.raises(SystemExit):
        mod.dispatch(server_only=True, port=mod.DEFAULT_PORT)

    assert not (tmp_path / "lan-address.txt").exists(), (
        "端口被占时必须早退，绝不得留下指向错误目标的 lan-address.txt"
    )


def test_write_lan_address_skips_when_no_lan_ip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """探不到 LAN IP（离线/仅回环）⇒ 不写文件、不留假地址，但要在 launch.log 说明原因。

    写 `http://127.0.0.1:<port>` 冒充"局域网地址"会让用户拿它连手机然后失败 —— 比没有
    文件更糟；但跳过本身不许静默（否则用户只会以为"功能坏了"）。
    """
    import start

    mod = _mod()
    monkeypatch.setattr(start, "get_local_ip", lambda: "127.0.0.1")
    log_path = tmp_path / "launch.log"

    result = mod.write_lan_address(8000, {"DELECTOR_DATA_DIR": str(tmp_path)}, str(log_path))

    assert result is None, "没有 LAN IP 时不得写文件（写了也是假地址）"
    assert not (tmp_path / "lan-address.txt").exists()
    assert "局域网" in log_path.read_text(encoding="utf-8"), "跳过也要留痕，不许静默"


def test_write_lan_address_failure_does_not_block_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """写 lan-address.txt 失败（磁盘满/被杀软锁）⇒ **不阻断启动**，且原因落 launch.log。

    地址是便利功能，"起不来"比"没有地址"严重得多；但失败必须留痕（哪一步、什么异常），
    不许静默吞掉。
    """
    import start

    mod = _mod()
    monkeypatch.setenv("DELECTOR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(start, "get_local_ip", lambda: "192.168.1.50")
    # 让落点变成一个**目录**：open(..., "w") 必抛 IsADirectoryError（OSError 子类）。
    monkeypatch.setattr(mod, "resolve_lan_address_path", lambda _env: str(tmp_path))

    # Task 5：地址写入现在由 start.main 在持有端口后回调触发 —— 替身须触发它，写失败才会发生。
    def _fake_main(debug_console: bool = False, on_serving: Any = None) -> None:
        if on_serving is not None:
            on_serving(mod.DEFAULT_PORT)

    monkeypatch.setattr(start, "main", _fake_main)

    code = mod.dispatch(server_only=True, port=mod.DEFAULT_PORT)

    assert code == 0, "地址文件写失败不得阻断 --server-only 启动"
    log_text = (tmp_path / "launch.log").read_text(encoding="utf-8")
    assert "lan-address.txt" in log_text and "失败" in log_text, "写失败必须留痕（哪一步、什么异常）"


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
    # Task 5：替身收下 dispatch 新增的可选 on_serving 回调（地址写入时机）。
    monkeypatch.setattr(start, "main", lambda **kwargs: None)

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


def _stub_claim_already_running(
    monkeypatch: pytest.MonkeyPatch, start: Any, tmp_path: Path, port: int = 8000
) -> None:
    """把 `start.claim_instance` 钉成「已有一个同版本实例在跑」。

    Task 6 之后 `main()` 的早退判据是**锁**（`claim_instance`），不再是 `is_port_in_use(8000)`。
    不换注入点的话，`is_port_in_use` 的桩再也拦不住启动 ⇒ 用例会真去起服务并**挂死**。
    """
    from delector.core.instance_lock import LockRecord
    from delector.core.version import APP_VERSION

    record = LockRecord(
        pid=4321,
        version=APP_VERSION,
        port=port,
        data_dir=str(tmp_path),
        acquired_at="2026-10-22T09:00:00+08:00",
    )
    monkeypatch.setattr(
        start, "claim_instance", lambda *a, **k: start.AlreadyRunning(record=record, reason="same")
    )


def test_start_main_entry_ensures_streams_before_existing_port_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """start.py 单独作为入口时，「已在运行」提示之前必须自行完成流收口。"""
    import start
    from delector.core import server_lifecycle

    monkeypatch.setenv("DELECTOR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(start, "is_android", lambda: True)
    monkeypatch.setattr(server_lifecycle, "probe_identity", lambda _port: True)
    _stub_claim_already_running(monkeypatch, start, tmp_path)

    _run_with_missing_streams(monkeypatch, start.main)

    content = (tmp_path / "launch.log").read_text(encoding="utf-8")
    assert "[提示] DeLector 已在运行" in content, f"提示必须先完成收口再输出，实际日志：{content!r}"


def test_start_entry_streams_survives_missing_desktop_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    monkeypatch.setattr(server_lifecycle, "probe_identity", lambda _port: True)
    # Task 6：早退判据是锁（`claim_instance`）而非 `is_port_in_use`；不换注入点 ⇒ 本用例会真去
    # 起服务并挂死（`is_port_in_use` 的桩拦不住新代码）。
    _stub_claim_already_running(monkeypatch, start, tmp_path)

    original_out, original_err = sys.stdout, sys.stderr  # 收口前捕获既有流对象引用

    start.main()  # 不得抛：收口失败宁可不留痕，也绝不得阻断启动

    # 断言「同一对象」而非 `is not None`：`sys.stdout is not None` 在 pytest 下**恒真**
    # （capture 插件必然装入非 None 的流）⇒ 收口若把既有流**替换**成 launch.log（仍是非
    # None 的文件对象）它照样全绿 —— 抓不到自己要防的回归（变异自证：同一变异下旧写法绿、
    # 本条红）。改钉对象同一性，手法同下方 `test_debug_console_keeps_existing_console_streams`。
    assert sys.stdout is original_out, "收口失败也不得把既有 stdout 弄丢/替换（须为同一对象）"
    assert sys.stderr is original_err, "收口失败也不得把既有 stderr 弄丢/替换（须为同一对象）"


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


def test_stale_lan_address_file_is_cleared_when_no_lan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """黄牌 1：探不到 LAN 时必须**清掉**上一轮的 lan-address.txt，否则托盘弹出过期 IP。

    上一轮留下的 `http://10.x.x.x` 若不被清，用户这次离线启动、点「显示局域网地址」看到的
    是**上一轮**的地址 —— 拿着过期 IP 连手机然后失败，比没有文件更糟。清掉后托盘走"可读
    失败"路径（明说本次没有地址）。
    """
    import start

    mod = _mod()
    monkeypatch.setattr(start, "get_local_ip", lambda: "127.0.0.1")
    lan_file = tmp_path / "lan-address.txt"
    lan_file.write_text("http://10.0.0.9:8000\n", encoding="utf-8")  # 上一轮的残留
    log_path = tmp_path / "launch.log"

    result = mod.write_lan_address(8000, {"DELECTOR_DATA_DIR": str(tmp_path)}, str(log_path))

    assert result is None, "没有 LAN IP 时不得写文件"
    leftover = lan_file.exists() and lan_file.read_text(encoding="utf-8").strip()
    assert not leftover, "无 LAN 时上一轮的地址必须被删除或截断（不得残留过期 IP 骗托盘）"


# ── Task 1（本轮）：入口「先收口后解析」—— --windowed 下 None 流的零反馈回归 ──────
# 背景：`--windowed` 产物（package_windows.py:320）里 `sys.stdout`/`sys.stderr` 是 None，
# 而两个 `__main__` 都是「先 `_parse_args`、后收口」⇒ argparse 的 `--help`/错参输出
# 无处可写：本机 CPython 3.11 的 `_print_message` 把 `None.write` 的 AttributeError 吞掉
# （不炸，但文本当场蒸发）；会外抛的版本则是 AttributeError + launch.log 零行。两种表现
# 同一个后果：**用户零线索**（退出码非零、无窗口、无弹窗、日志零行）。修法：把收口
# （`ensure_streams` / `_ensure_entry_streams`）提到 `_parse_args` 之前，debug 开关从
# 原始 argv 探（此刻还没解析完，拿不到 `_args`）。
def _run_entry_module(module_name: str, argv: List[str], monkeypatch: pytest.MonkeyPatch) -> int:
    """以 `__main__` 身份执行入口模块（不真起进程），返回其退出码。

    为什么是 runpy 而不是「直接调 `_parse_args`」：本回归的 RED/GREEN 分界在 `__main__`
    **序列**里（收口与解析的先后）——直接调 `_parse_args` 绕开了那个序列，修复后它照样
    拿不到流，断言永远红、根本绿不了。runpy 以 `__name__="__main__"` exec 真入口；
    `--help`/错参都在 argparse 退出前止住，`dispatch`/`main` 不会被触达（不起服务、不建窗）。

    为什么是 runpy 而不是 subprocess：要复现的 `sys.stdout/stderr is None` 只在
    `--windowed` 打包形态出现，子进程的 stdio 永远是管道，造不出这个状态。

    「不抛」的保证是结构性的：除 argparse 自己的 SystemExit 外，任何异常（如
    `None.write` 的 AttributeError）都会直接穿出本函数把用例转红，无需额外捕获。
    """
    import runpy

    monkeypatch.setattr(sys, "argv", [f"{module_name}.py", *argv])
    try:
        runpy.run_module(module_name, run_name="__main__")
    except SystemExit as exc:
        if exc.code is None:
            return 0  # parser.exit() 的默认语义（--help 走这条）
        if isinstance(exc.code, int):
            return exc.code
        raise
    return 0


def test_desktop_entry_help_lands_in_launch_log_when_streams_are_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--windowed`（stdout/stderr=None）下 `desktop.py --help`：不抛、退出码 0、文本落 launch.log。"""
    monkeypatch.setenv("DELECTOR_DATA_DIR", str(tmp_path))
    log_path = tmp_path / "launch.log"

    def _exercise() -> None:
        code = _run_entry_module("desktop", ["--help"], monkeypatch)
        assert code == 0, "argparse --help 的既有语义是退出码 0（收口不得改变它）"

    _run_with_missing_streams(monkeypatch, _exercise)

    content = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    assert "usage: desktop.py" in content, f"--help 文本必须落进 launch.log，实际：{content!r}"
    assert "--server-only" in content and "--debug-console" in content, (
        f"无控制台时 help 是用户唯一的使用说明，必须含全部开关，实际：{content!r}"
    )


def test_desktop_entry_bad_arg_lands_in_launch_log_when_streams_are_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """错参（--bogus）在 None 流下也必须给出用法+错误，退出码保持 argparse 既有语义（2，非零）。"""
    monkeypatch.setenv("DELECTOR_DATA_DIR", str(tmp_path))
    log_path = tmp_path / "launch.log"

    def _exercise() -> None:
        code = _run_entry_module("desktop", ["--bogus"], monkeypatch)
        assert code == 2, "argparse 错参的既有语义是退出码 2（非零；收口不得吞掉它）"

    _run_with_missing_streams(monkeypatch, _exercise)

    content = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    assert "usage: desktop.py" in content, f"错参也必须给出用法，实际：{content!r}"
    assert "unrecognized arguments: --bogus" in content, f"错误必须点名坏参数，实际：{content!r}"


def test_start_entry_help_lands_in_launch_log_when_streams_are_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`start.py --help` 同款契约（跨平台入口复用 `_ensure_entry_streams`；APK 无 desktop.py）。"""
    monkeypatch.setenv("DELECTOR_DATA_DIR", str(tmp_path))
    log_path = tmp_path / "launch.log"

    def _exercise() -> None:
        code = _run_entry_module("start", ["--help"], monkeypatch)
        assert code == 0, "argparse --help 的既有语义是退出码 0（收口不得改变它）"

    _run_with_missing_streams(monkeypatch, _exercise)

    content = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    assert "usage: start.py" in content, f"--help 文本必须落进 launch.log，实际：{content!r}"
    assert "--debug-console" in content, f"help 必须含调试开关，实际：{content!r}"


def test_start_entry_bad_arg_lands_in_launch_log_when_streams_are_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`start.py` 错参（--bogus）：不抛、退出码 2、用法+错误落 launch.log（契约同 desktop 入口）。"""
    monkeypatch.setenv("DELECTOR_DATA_DIR", str(tmp_path))
    log_path = tmp_path / "launch.log"

    def _exercise() -> None:
        code = _run_entry_module("start", ["--bogus"], monkeypatch)
        assert code == 2, "argparse 错参的既有语义是退出码 2（非零；收口不得吞掉它）"

    _run_with_missing_streams(monkeypatch, _exercise)

    content = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    assert "usage: start.py" in content, f"错参也必须给出用法，实际：{content!r}"
    assert "unrecognized arguments: --bogus" in content, f"错误必须点名坏参数，实际：{content!r}"
