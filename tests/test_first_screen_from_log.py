# -*- coding: utf-8 -*-
"""`tools/first_screen_from_log.py` 的回归锁：用**造出来的假日志**钉解析逻辑。

纪律：绝不读用户真实 `launch.log`（内容 / 存在与否都不可控）—— 每条用例都在 `tmp_path` 写一份
**受控**的假日志，再跑脚本、断言输出与退出码。标记字符串必须与写方 desktop.py 同源，由本文件
`test_markers_match_desktop_writer` 另钉（任一侧改了字面量 ⇒ 漂移即红）。
"""

import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest
from server_helpers import stmts_through_try

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "first_screen_from_log.py"
DESKTOP = ROOT / "desktop.py"

# 与 desktop.py / first_screen_from_log.py 逐字对齐的三枚标记。
START = "开始启动（进程级计时起点）"
READY = "服务已就绪"
SCREEN = "真实 UI 已加载（首屏可用）"


def _write_log(path: Path, rows: List[Tuple[str, str]]) -> Path:
    path.write_text("".join(f"[{ts}] {msg}\n" for ts, msg in rows), encoding="utf-8")
    return path


def _run(log_path: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--log", str(log_path)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


def test_markers_match_desktop_writer() -> None:
    """解析器与写日志方（desktop.py）的标记必须**同源**：任一侧改了字面量 ⇒ 本用例转红。"""
    src = DESKTOP.read_text(encoding="utf-8")
    for marker in (START, READY, SCREEN):
        assert marker in src, f"desktop.py 未写入标记「{marker}」：解析器与写方已漂移"


def test_computes_the_three_duration_rows(tmp_path: Path) -> None:
    """正常三行 ⇒ 三段差值都要算对（起点→就绪 3s、就绪→首屏 2s、端到端 5s）。"""
    log = _write_log(
        tmp_path / "launch.log",
        [
            ("2026-10-10 12:00:00", START + "。"),
            ("2026-10-10 12:00:03", READY + "。"),
            ("2026-10-10 12:00:05", SCREEN + "。"),
        ],
    )
    proc = _run(log)
    assert proc.returncode == 0, proc.stderr
    assert "起点 → 服务就绪: 3s" in proc.stdout, proc.stdout
    assert "服务就绪 → 首屏已加载: 2s" in proc.stdout, proc.stdout
    assert "起点 → 首屏已加载（端到端首屏）: 5s" in proc.stdout, proc.stdout


def test_uses_the_last_launch_as_the_epoch(tmp_path: Path) -> None:
    """日志是追加写：必须取**最后一次**启动为计时起点（否则会把上一轮的空档算进来）。"""
    log = _write_log(
        tmp_path / "launch.log",
        [
            ("2026-10-10 11:00:00", START + "。"),
            ("2026-10-10 11:00:10", READY + "。"),
            ("2026-10-10 11:00:20", SCREEN + "。"),
            ("2026-10-10 12:00:00", START + "。"),
            ("2026-10-10 12:00:04", READY + "。"),
            ("2026-10-10 12:00:07", SCREEN + "。"),
        ],
    )
    proc = _run(log)
    assert proc.returncode == 0, proc.stderr
    assert "起点 → 服务就绪: 4s" in proc.stdout, proc.stdout
    assert "服务就绪 → 首屏已加载: 3s" in proc.stdout, proc.stdout
    assert "起点 → 首屏已加载（端到端首屏）: 7s" in proc.stdout, proc.stdout


def test_missing_loaded_line_is_reported_not_guessed(tmp_path: Path) -> None:
    """缺 `loaded` 行（旧日志）⇒ 明确报"不含首屏事件"，**不得**静默给 0（故非零退出）。"""
    log = _write_log(
        tmp_path / "launch.log",
        [
            ("2026-10-10 12:00:00", START + "。"),
            ("2026-10-10 12:00:03", READY + "。"),
        ],
    )
    proc = _run(log)
    assert proc.returncode != 0, "缺 loaded 行必须非零退出（不得静默给 0）"
    assert "不含首屏事件" in (proc.stdout + proc.stderr), proc.stdout + proc.stderr


def test_garbled_log_fails_with_plain_language(tmp_path: Path) -> None:
    """日志存在但格式乱 ⇒ 人话失败、非零退出，**不得**抛栈崩掉。"""
    log = tmp_path / "launch.log"
    log.write_text("\x00\x01 这不是日志\n随机内容\n仍不是\n", encoding="utf-8")
    proc = _run(log)
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0
    assert "Traceback" not in combined, f"格式乱也必须人话失败、不得抛栈：{combined}"
    assert combined.strip(), "必须给出人话原因"


def test_missing_file_exits_nonzero_with_reason(tmp_path: Path) -> None:
    """找不到日志文件 ⇒ 非零退出 + 人话原因（并提示 --log 覆盖路径）。"""
    proc = _run(tmp_path / "nope.log")
    assert proc.returncode != 0
    assert "找不到" in (proc.stdout + proc.stderr), proc.stdout + proc.stderr


# ── Task 2：6 枚新启动标记不得让解析器抢错锚行（行为级 + 结构化守卫）──────────────
# Task 3 后 6 枚标记的落点拆在两个函数：①~③ 留循环外（`_run_desktop_inner` 顶层），④~⑥ 随
# 建服/起服搬进循环内（`_after_start`，即 `webview.start()` 调度函数的 try 体）。只扫一个函数
# 会漏掉半组——本回归锁当初正是这么红的（len(markers)==6 拿到 3）。
_STAGE_MARKER_FUNCS: Tuple[str, ...] = ("_run_desktop_inner", "_after_start")


def _stage_marker_statements(func: ast.FunctionDef) -> List[ast.stmt]:
    """取 `func` 里承载"启动阶段标记"的顶层语句。

    `_run_desktop_inner`：整个函数体顶层即①~③（失败分支的日志嵌在 `if` 内，天然被排除）。

    `_after_start`：它刻意只有单个顶层 try（后台线程必须接住异常），故取 **try 体**；但 try 体里
    除④~⑥ 外还有就绪/切窗阶段的日志，其中「服务已就绪。」**本身就是首屏工具的锚行** —— 把它算进
    "新标记"清单会自我矛盾（清单里出现锚行）。故用结构切口：只取到**第一个 `_set_splash_stage`
    之前**的语句，即"建服/起服段"（`from delector.server import app` → `build_server` →
    `serve_in_thread`）——④~⑥ 正是紧贴这三条语句的归因日志。
    """
    if func.name == "_after_start":
        assert len(func.body) == 1 and isinstance(func.body[0], ast.Try), (
            "_after_start 应只有一个顶层 try（后台线程里未接住的异常会静默杀死线程）"
        )
        stmts = list(func.body[0].body)
        cut = next(
            (index for index, stmt in enumerate(stmts) if _stmt_has_call(stmt, "_set_splash_stage")),
            len(stmts),
        )
        return stmts[:cut]
    # `_run_desktop_inner`：Task 7 起主体被 `try/finally` 包住（放锁），①~③ 因此下沉一层。
    # 用共享的 `stmts_through_try` 展开容器（只展开 `try`、不进 `if/for`：WebView2 失败分支的
    # 日志嵌在 `if` 内，不属于这 6 枚）。不展开 ⇒ 只数到 1 枚，本文件的 6 枚断言会红。
    return list(stmts_through_try(func.body))
    return list(func.body)


def _stmt_has_call(stmt: ast.stmt, label: str) -> bool:
    """语句（含嵌套）里是否出现对 `label(...)` 的调用。"""
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == label
        for node in ast.walk(stmt)
    )


def _new_stage_markers_from_desktop() -> List[str]:
    """从 desktop.py **同源取** 6 枚启动阶段标记（AST 取 `_append_log` 的第二个字符串实参，
    按源码出现顺序）。

    为何同源取而不在本文件复制字面量：复制即**第二份真相源** —— desktop.py 一改标记，副本会
    **静默漂移**，这枚回归锁转而去守护一份过期字面量（正是本项目反复栽过的坑）。

    Task 3 起分两处取（`_STAGE_MARKER_FUNCS`，顺序即写入顺序）：①~③ 取 `_run_desktop_inner`
    顶层，④~⑥ 取 `_after_start` 的 try 体。只取各函数体的**顶层**：失败分支里的日志（如
    「未检测到 WebView2 运行时…」）嵌在 `if` 内、不属于这 6 枚 —— 取顶层即可精确命中。
    """
    tree = ast.parse(DESKTOP.read_text(encoding="utf-8"))
    # 显式建表 + 断言（而非 `next(...)`）：`next` 找不到时抛 `StopIteration`，消息难读；这里给
    # 人话原因，函数被改名/搬走时一眼可见。
    funcs: Dict[str, ast.FunctionDef] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            funcs[node.name] = node
    markers: List[str] = []
    for name in _STAGE_MARKER_FUNCS:
        func = funcs.get(name)
        assert func is not None, f"desktop.py 里找不到 `{name}`（被改名了？）"
        for stmt in _stage_marker_statements(func):
            if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
                continue
            call = stmt.value
            if not (isinstance(call.func, ast.Name) and call.func.id == "_append_log"):
                continue
            if len(call.args) >= 2:
                arg = call.args[1]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    markers.append(arg.value)
    return markers


def test_new_stage_markers_do_not_hijack_first_screen_parser(tmp_path: Path) -> None:
    """6 枚新启动标记**不得**让 `first_screen_from_log.py` 抢错锚行。

    解析器是**子串匹配**（`marker in line.message`）：只要新标记不含三条锚串，端到端三段的锚行
    就仍取自真锚。本用例用**真实（从 desktop.py 同源取）标记**造合成日志，端到端验证三段数字
    未被抢走 —— 一旦某枚新标记含锚串，锚点会先命中它、数字静默变味。
    """
    markers = _new_stage_markers_from_desktop()
    assert len(markers) == 6, (
        f"启动阶段标记应共 6 枚（_run_desktop_inner 顶层 3 枚 + _after_start 的 try 体 3 枚），"
        f"实际 {len(markers)} 枚：{markers}"
        "（标记增删请同步本回归锁，勿让它静默守护过期清单）"
    )

    # 时间戳（秒级）与顺序严格照 desktop.py 的写入次序：**真起点=07**、循环外 3 枚=08→09、
    # splash=10（`_show_window` 内、webview.start 之前）、循环内 3 枚=10→11、服务就绪=13、
    # 首屏=14 ⇒ 期望三段为 6s / 1s / 7s。
    # ⚠️ 真起点（07）**刻意早于** markers[0]（08）：这样一旦 markers[0] 变成含「开始启动（进程级
    # 计时起点）」的形态，解析器的 `_last_index`（取**最后一次**出现）会命中 markers[0] 而非真起点
    # ⇒ 三段数字变味、本用例转红。（旧版把真起点与 markers[0] 都写成 08 ⇒ 起点被抢后三段仍不变，
    # 用例恒真 —— 见 Fix-3 变异自证。）
    # 「已创建 splash 窗口。」是**填充行**（非 6 枚标记之一、也不含任何锚串）：它证明锚行之间的
    # 无关行不会干扰切片；它写在 `_show_window` 里，故时刻必须夹在循环外 3 枚与循环内 3 枚之间。
    log = _write_log(
        tmp_path / "launch.log",
        [
            ("2026-10-10 12:00:07", START + "。"),
            ("2026-10-10 12:00:08", markers[0]),
            ("2026-10-10 12:00:09", markers[1]),
            ("2026-10-10 12:00:09", markers[2]),
            ("2026-10-10 12:00:10", "已创建 splash 窗口。"),
            ("2026-10-10 12:00:10", markers[3]),
            ("2026-10-10 12:00:10", markers[4]),
            ("2026-10-10 12:00:11", markers[5]),
            ("2026-10-10 12:00:13", READY + "。"),
            ("2026-10-10 12:00:14", SCREEN + "。"),
        ],
    )
    proc = _run(log)
    assert proc.returncode == 0, proc.stderr
    # 直接钉"起点锚没被抢"：输出的计时起点必须仍是真起点行（07），而非被某枚新标记顶替。
    assert "计时起点: 2026-10-10 12:00:07" in proc.stdout, proc.stdout
    # 逐行断言（不是"含某个数字"）：三段都必须精确取自真锚行；任一新标记含锚串都会让此处对不上。
    out_lines = proc.stdout.splitlines()
    assert "起点 → 服务就绪: 6s" in out_lines, proc.stdout
    assert "服务就绪 → 首屏已加载: 1s" in out_lines, proc.stdout
    assert "起点 → 首屏已加载（端到端首屏）: 7s" in out_lines, proc.stdout


def test_new_stage_markers_do_not_contain_first_screen_anchor_substrings() -> None:
    """结构化防碰撞守卫（**解析器侧**）：6 枚新标记**各自都不得**把三条首屏锚串当子串。

    与 `tests/test_desktop_shell.py::test_stage_markers_do_not_contain_first_screen_anchor_substrings`
    呼应，但守在这里（解析器侧）：`first_screen_from_log.py` 的 `_last_index` / `_first_index_after`
    用 `marker in line.message` 做子串匹配 ⇒ 某枚新标记一旦含「开始启动（进程级计时起点）/
    服务已就绪 / 真实 UI 已加载（首屏可用）」，锚点会**先命中这枚新标记**、计时切片**抢错行**，
    端到端首屏数字**静默变味**（不报错，只是算成别的意思）。

    6 枚的落点（Task 3）：`_run_desktop_inner` 顶层 3 枚 + `_after_start` 的 try 体 3 枚。
    """
    markers = _new_stage_markers_from_desktop()
    assert len(markers) == 6, (
        f"启动阶段标记应共 6 枚（_run_desktop_inner 顶层 3 枚 + _after_start 的 try 体 3 枚），"
        f"实际 {len(markers)} 枚：{markers}"
    )
    for marker in markers:
        for anchor in (START, READY, SCREEN):
            assert anchor not in marker, (
                f"新标记 {marker!r} 含首屏锚串 {anchor!r}：解析器会抢错行、端到端数字静默变味"
            )


# ── 本轮：未测段（进程创建 → 计时起点）是**可选**行，三种结果必须区分 ──────────────
# 造行不手抄字面量：调 `desktop.py` 的**真写入方** `_log_prestart_elapsed` 生成消息，只把时间戳
# 留给本文件拼（否则测试里就是第二份字面量，写方一改就静默漂移）。
def _prestart_message(monkeypatch: pytest.MonkeyPatch, ms: Optional[float]) -> str:
    """用真写方生成那条消息（`ms=None` ⇒ 走"取不到"分支写 `?`），返回去掉时间戳前缀的消息。"""
    import desktop

    monkeypatch.setattr(desktop, "_ms_since_process_create", lambda: ms)
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "launch.log"
        desktop._log_prestart_elapsed(str(log))
        raw = log.read_text(encoding="utf-8").splitlines()[-1]
    return raw.split("] ", 1)[1]


def test_prestart_row_reports_ms_from_real_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """有未测段行 ⇒ 报**那个毫秒数**，且三行老口径不受影响（未测段行没抢锚）。"""
    log = _write_log(
        tmp_path / "launch.log",
        [
            ("2026-10-10 12:00:08", START + "。"),
            ("2026-10-10 12:00:08", _prestart_message(monkeypatch, 4321.6)),
            ("2026-10-10 12:00:13", READY + "。"),
            ("2026-10-10 12:00:14", SCREEN + "。"),
        ],
    )
    proc = _run(log)
    assert proc.returncode == 0, proc.stderr
    out_lines = proc.stdout.splitlines()
    assert "进程创建 → 计时起点（此前未测段）: 4322 ms" in out_lines, proc.stdout
    assert "起点 → 服务就绪: 5s" in out_lines, proc.stdout
    assert "服务就绪 → 首屏已加载: 1s" in out_lines, proc.stdout
    assert "起点 → 首屏已加载（端到端首屏）: 6s" in out_lines, proc.stdout


def test_prestart_row_absent_for_old_log_keeps_exit_code_ok(tmp_path: Path) -> None:
    """**旧日志没有该行不是错误**：如实报"不含此项"，退出码仍 0（它不是首屏事件）。"""
    log = _write_log(
        tmp_path / "launch.log",
        [
            ("2026-10-10 12:00:08", START + "。"),
            ("2026-10-10 12:00:13", READY + "。"),
            ("2026-10-10 12:00:14", SCREEN + "。"),
        ],
    )
    proc = _run(log)
    assert proc.returncode == 0, proc.stderr
    assert (
        "进程创建 → 计时起点（此前未测段）: 该日志不含此项（旧版本 desktop.py）"
        in proc.stdout.splitlines()
    ), proc.stdout


def test_prestart_row_reports_question_mark_when_probe_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """写方取不到时刻（写 `?`）⇒ 解析器如实报"本机未取到"，**绝不**当成 0 或"很快"。"""
    log = _write_log(
        tmp_path / "launch.log",
        [
            ("2026-10-10 12:00:08", START + "。"),
            ("2026-10-10 12:00:08", _prestart_message(monkeypatch, None)),
            ("2026-10-10 12:00:13", READY + "。"),
            ("2026-10-10 12:00:14", SCREEN + "。"),
        ],
    )
    proc = _run(log)
    assert proc.returncode == 0, proc.stderr
    assert "进程创建 → 计时起点（此前未测段）: 本机未取到（该运行写的是 `?`）" in proc.stdout.splitlines(), proc.stdout
