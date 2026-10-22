# -*- coding: utf-8 -*-
"""桌面壳「窗口生命周期」域：事件循环时机 / 首屏与阶段标记 / 主窗口 / 预启动计时。

C6 Task 6 自 `tests/test_desktop_shell.py` 逐字搬出；搬出的段（搬前 `test_desktop_shell.py`
行号，实测，含各段头注释）：
  `834`-`1657`  P0 死锁回归锁 · 5A 真实首屏口径 · Task 1 启动阶段标记 · 主窗口可缩放回归锁
  `2197`-`2343` GUI 真窗口 / 真托盘冒烟（无桌面会话下跳过）· 进程创建→计时起点日志

断言、用例名与 docstring 逐字未改；只新增本文件的显式 import。跨域共用项
（`REPO_ROOT` / `_mod` / `_parse_desktop` / `_funcs_by_name` / `_calls` /
`_call_label` / `_stub_server_build` / `_RecordingCtypes`）与 autouse 兜底夹具
`_isolate_data_dir` 住在 `tests/server_helpers.py`，按名 import 即在本模块注册。
"""

import ast
import os
import sys
import threading
import types
from pathlib import Path
from typing import Any, Dict, Iterator, List, Set, Tuple

import pytest
from server_helpers import (
    REPO_ROOT,
    _call_label,
    _calls,
    _funcs_by_name,
    _mod,
    _parse_desktop,
    _RecordingCtypes,
    _stub_server_build,
    stmts_through_try,
)
from server_helpers import _isolate_data_dir as _isolate_data_dir

# ── P0 死锁回归锁：窗口操作必须在 webview.start() 之后（GUI 事件循环内）执行 ──────
# 真根因（scratch/repro_splash_deadlock.py 三模式实测）：pywebview 把 evaluate_js / load_url
# marshal 到 GUI 线程执行，而 GUI 事件循环由 webview.start() 才启动；在 start **之前**调它们会
# 永久等待 ⇒ 窗口永不出现、进程永不退出。下列断言把"何时才允许碰窗口"钉死，且不只测"函数存在"。
_WINDOW_WRITE_ATTRS = {"evaluate_js", "load_url"}
_STAGE_HELPER = "_set_splash_stage"  # 该助手内部调 evaluate_js，只能在循环起来后跑
# P0 硬约束点名的**全部**窗口 API（evaluate_js / load_url / show / destroy，"等"以外就这些）。
# 行为锁 `test_window_ops_run_only_after_webview_start_at_runtime` 按这个全集断言，而不是只查
# `_WINDOW_WRITE_ATTRS`：只查 evaluate_js/load_url 会被"把 `main.show()` 挪到 `webview.start()`
# 之前"的变异骗过 —— show 同样是窗口 API，提前调用同样被 marshal 到未启动的 GUI 线程 ⇒ 永久阻塞。
_WINDOW_OPS = {"evaluate_js", "load_url", "show", "destroy"}


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
# Task 3 后 6 枚标记的落点随语句拆成两半：①~③ 留循环外（`_run_desktop_inner`），④~⑥ 随建服/
# 起服搬进循环内（`_after_start` 的 try 体）。下列锁分组钉住：① 全部存在；② 组内源码顺序
# （1→3 / 4→6）；③ 每枚都**夹在**它要标记的那条语句与下一枚锚语句之间（下界「晚于本锚」证伪
# 「标记写在语句之前」；上界「早于下一锚」证伪「整体下移但保持顺序」——只有下界时后者会假绿）；
# 另钉一条：新标记绝不把首屏工具的锚串当子串（否则 `first_screen_from_log` 的 `_last_index` /
# `_first_index_after` 会抢错行）。
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
    """`func_name` 里首个满足 `predicate` 的语句的（起始行, 结束行）。找不到即报错。

    Task 7 适配：端口判定整段被 `try:`（放锁）包住 ⇒ `ensure_webview2_runtime` 与
    `_show_window` 从「函数顶层语句」变成「顶层 `try` 体里的语句」。故候选集合 = 函数顶层
    语句 **+ 一层** `ast.Try` 的 body / handlers / orelse / finalbody —— 只下潜一层是有意的：
    夹逼断言的语义是"标记夹在相邻两条语句之间"，下潜到任意深度会让锚点漂到内层无关语句上，
    反而失去判别力。
    """
    fn = _funcs_by_name(_parse_desktop())[func_name]
    for stmt in stmts_through_try(fn.body):
        if predicate(stmt):
            return stmt.lineno, stmt.end_lineno or stmt.lineno
    raise AssertionError(f"{func_name} 里找不到满足断言的语句（谓词={predicate!r}）")


def _stmt_has_call(stmt: ast.stmt, label: str) -> bool:
    return any(_call_label(call) == label for call in _calls(stmt))


_PRE_LOOP_MARKERS: List[str] = _STARTUP_STAGE_MARKERS[:3]  # ①~③：循环外（_run_desktop_inner）
_IN_LOOP_MARKERS: List[str] = _STARTUP_STAGE_MARKERS[3:]  # ④~⑥：循环内（_after_start，Task 3 搬入）


def _after_start_try_body() -> List[ast.stmt]:
    """`_after_start` 的 try 体语句（Task 3：建服段搬进循环内，且必须在 try 里）。

    为什么必须在 try 里：`_after_start` 跑在 `webview.start()` 调度的**后台线程**，未接住的
    异常会让线程静默死亡（又回到"窗口不出、零线索"）。故实现应是"单个顶层 try 包住全部"，
    这里把该形状钉死；④~⑥ 的锚点要从 try 体里取（而不是函数顶层）。
    """
    fn = _funcs_by_name(_parse_desktop())["_after_start"]
    assert len(fn.body) == 1 and isinstance(fn.body[0], ast.Try), (
        "_after_start 应只有一个顶层 try（后台线程里的异常必须被接住并留痕）"
    )
    return list(fn.body[0].body)


def _stmt_span_in(stmts: List[ast.stmt], predicate: Any) -> Tuple[int, int]:
    """`stmts` 里首个满足 `predicate` 的语句的（起始行, 结束行）。找不到即报错。"""
    for stmt in stmts:
        if predicate(stmt):
            return stmt.lineno, stmt.end_lineno or stmt.lineno
    raise AssertionError(f"语句列表里找不到满足断言的语句（谓词={predicate!r}）")


def test_stage_markers_stay_with_their_anchor_statements_across_the_move() -> None:
    """6 枚启动阶段标记必须**贴着**它们要标记的语句：①~③ 留循环外（`_run_desktop_inner`），
    ④~⑥ 随搬移进循环内（`_after_start` 的 try 体）。每组各钉"存在 + 顺序 + 夹逼"。

    为什么钉「存在 + 顺序 + 位置」三者：只钉「字符串在源码里出现过」会被「标记写在语句之前 /
    顺序颠倒」骗过；而 `first_screen_from_log` 的切片完全依赖**先后次序**，位置错了归因就错。

    为什么位置要**夹逼**而不只有下界：只有下界时，把一组标记**整体下移**（仍保持组内顺序）
    仍会全绿，但归因已经张冠李戴（每枚标记都不再紧贴它要标记的那一步）。上界（早于下一枚锚）
    把这种「整体漂移」挡在门外。

    Task 3 的背景：建服/起服搬进 `webview.start()` 调度的事件循环后，④~⑥ 若**留在**
    `_run_desktop_inner`（循环外、语句之前），launch.log 的时间线就会说谎（标记写在重活之前）
    —— 正是本断言要防的"归因张冠李戴"。故 ④~⑥ 必须随语句搬进 `_after_start` 的 try 体。
    """
    run_entries = _stage_log_entries("_run_desktop_inner")
    run_messages = [message for _lineno, message in run_entries]
    run_line_of = {message: lineno for lineno, message in run_entries}
    for marker in _PRE_LOOP_MARKERS:
        assert marker in run_messages, (
            f"循环外标记 {marker!r} 必须仍在 _run_desktop_inner；现有 _append_log 字面量：{run_messages}"
        )
    ordered_pre = [m for m in run_messages if m in set(_PRE_LOOP_MARKERS)]
    assert ordered_pre == _PRE_LOOP_MARKERS, f"循环外三枚标记的源码顺序必须为 1→3，实际：{ordered_pre}"

    loop_entries = _stage_log_entries("_after_start")
    loop_messages = [message for _lineno, message in loop_entries]
    loop_line_of = {message: lineno for lineno, message in loop_entries}
    for marker in _IN_LOOP_MARKERS:
        assert marker in loop_messages, (
            f"循环内标记 {marker!r} 必须随语句搬进 _after_start；现有 _append_log 字面量：{loop_messages}"
        )
    ordered_loop = [m for m in loop_messages if m in set(_IN_LOOP_MARKERS)]
    assert ordered_loop == _IN_LOOP_MARKERS, f"循环内三枚标记的源码顺序必须为 4→6，实际：{ordered_loop}"

    # 循环外锚：前 3 条是 ①~③ 各自的锚，第 4 条（含 `_show_window` 的顶层语句）是 ③ 的上界锚。
    run_anchors = [
        _stage_stmt_span(
            "_run_desktop_inner",
            lambda s: isinstance(s, ast.If) and _stmt_has_call(s, "_check_port_or_fail"),
        ),
        _stage_stmt_span(
            "_run_desktop_inner",
            lambda s: isinstance(s, ast.If) and _stmt_has_call(s, "ensure_webview2_runtime"),
        ),
        _stage_stmt_span("_run_desktop_inner", lambda s: _stmt_has_call(s, "bootstrap_data_dir")),
        # 锚"含 `_show_window` 调用的顶层语句"（`_run_desktop_inner` 里由 `try:` 体内的 `return`
        # 调起）——语义即"③ 必须在调用 `_show_window` 之前"。为何不锚"首个顶层 `try`"：将来加一个
        # 与 `_show_window` 无关的顶层 `try` 会让锚前移 ⇒ 假红。
        _stage_stmt_span("_run_desktop_inner", lambda s: _stmt_has_call(s, "_show_window")),
    ]
    for index, marker in enumerate(_PRE_LOOP_MARKERS):
        lower_start, lower_end = run_anchors[index]
        upper_start, _upper_end = run_anchors[index + 1]
        assert run_line_of[marker] > lower_end, (
            f"标记 {marker!r} 必须写在它要标记的语句（第 {lower_start}-{lower_end} 行）**之后**，"
            f"实际在第 {run_line_of[marker]} 行 —— 写在语句之前会让归因张冠李戴"
        )
        assert run_line_of[marker] < upper_start, (
            f"标记 {marker!r} 必须写在下一枚锚语句（第 {upper_start} 行）**之前**，"
            f"实际在第 {run_line_of[marker]} 行 —— 整体下移到下一枚锚之后会让归因张冠李戴"
        )

    # 循环内锚（`_after_start` 的 try 体）：import app → assign server → assign thread →
    # `_set_splash_stage`（④~⑥ 各自夹在前后两个锚之间）。
    loop_stmts = _after_start_try_body()
    loop_anchors = [
        _stmt_span_in(
            loop_stmts,
            lambda s: isinstance(s, ast.ImportFrom) and s.module == "delector.server",
        ),
        _stmt_span_in(
            loop_stmts,
            lambda s: isinstance(s, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "server" for t in s.targets),
        ),
        _stmt_span_in(
            loop_stmts,
            lambda s: isinstance(s, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "thread" for t in s.targets),
        ),
        _stmt_span_in(loop_stmts, lambda s: _stmt_has_call(s, "_set_splash_stage")),
    ]
    for index, marker in enumerate(_IN_LOOP_MARKERS):
        lower_start, lower_end = loop_anchors[index]
        upper_start, _upper_end = loop_anchors[index + 1]
        assert loop_line_of[marker] > lower_end, (
            f"标记 {marker!r} 必须写在它要标记的语句（第 {lower_start}-{lower_end} 行）**之后**，"
            f"实际在第 {loop_line_of[marker]} 行 —— 写在语句之前会让归因张冠李戴"
        )
        assert loop_line_of[marker] < upper_start, (
            f"标记 {marker!r} 必须写在下一枚锚语句（第 {upper_start} 行）**之前**，"
            f"实际在第 {loop_line_of[marker]} 行 —— 整体下移到下一枚锚之后会让归因张冠李戴"
        )


def test_server_build_phase_lives_inside_the_start_delegated_function() -> None:
    """Task 3 阶段顺序（结构锁）：建服/起服必须在 `webview.start()` 调度的函数体内。

    把 `from delector.server import app` / `build_server` / `serve_in_thread` 留在
    `_run_desktop_inner`（循环外）⇒ 本断言转红 —— 这正是当前实现的形状（RED）。搬进
    `_after_start` 后，重活发生在 splash 已可见之后，首次双击的反馈起点从"重活全干完"
    提前到"splash 出现"（4~6.5s 零反馈的修法）。

    同时钉计划规格的另一半：端口校验与 WebView2 检测**留在循环外**（它们快且有弹窗）。
    """
    tree = _parse_desktop()
    funcs = _funcs_by_name(tree)
    name, delegated = _delegated_function(tree)
    inner_labels = _reachable_labels(delegated, funcs)

    for label in ("build_server", "serve_in_thread"):
        assert label in inner_labels, (
            f"{label} 必须搬进 webview.start() 调度的函数（{name}）体内（splash 可见之后才建服）"
        )
    in_loop_imports = [
        node
        for node in ast.walk(delegated)
        if isinstance(node, ast.ImportFrom) and node.module == "delector.server"
    ]
    assert in_loop_imports, "`from delector.server import app` 必须在 start 调度的函数体内"

    run_inner = funcs["_run_desktop_inner"]
    run_inner_labels = {_call_label(call) for call in _calls(run_inner)}
    for label in ("build_server", "serve_in_thread"):
        assert label not in run_inner_labels, (
            f"{label} 不得留在 _run_desktop_inner：循环外的重活正是 4~6.5s 零反馈的成因"
        )
    run_inner_imports = [
        node
        for node in ast.walk(run_inner)
        if isinstance(node, ast.ImportFrom) and node.module == "delector.server"
    ]
    assert not run_inner_imports, "`from delector.server import app` 不得留在 _run_desktop_inner"

    # 计划规格：端口校验与 WebView2 检测留在循环外（快且有弹窗，不必等 splash 可见）。
    assert "_check_port_or_fail" in run_inner_labels, "端口/身份校验必须留在循环外（_run_desktop_inner）"
    assert "ensure_webview2_runtime" in run_inner_labels, "WebView2 检测必须留在循环外（_run_desktop_inner）"


def test_stage_markers_do_not_contain_first_screen_anchor_substrings() -> None:
    """分层守卫（**本文件清单侧**）：`_STARTUP_STAGE_MARKERS`（**本文件的清单常量**）与首屏工具的
    三个锚串互不为子串。

    本用例**只比对本文件清单常量、不读 `desktop.py`**。清单与实现的**同步**由
    `test_stage_markers_stay_with_their_anchor_statements_across_the_move`（读 AST 的
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
    # Task 3 后建服/起服在 _after_start 里：不起真服务、不 import 真 delector.server。
    _stub_server_build(monkeypatch, mod)
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

    code = mod._show_window(object(), 8000, str(log_path))

    assert code == 0
    content = log_path.read_text(encoding="utf-8")
    assert _FIRST_SCREEN_MARKER in content, "loaded 事件触发（首屏渲染完成）时必须记首屏标记"


def test_window_ops_run_only_after_webview_start_at_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """行为回归锁：用替身 `webview` 记录调用顺序，断言窗口写入都发生在 start 之后。

    替身无法复现"marshal 到未启动 GUI 线程 = 永久阻塞"，但能钉住**调用顺序**：`start` 必须先于
    任何 load_url / evaluate_js。把 load_url 挪回 start 之前 ⇒ 本断言转红（即真实死锁的静态形状）。

    Task 3 追加（Y2 黄牌修法）：同一份 `order` 也喂给 `_stub_server_build`，于是"建服/起服晚于
    `webview.start()`"这条 docstring 承诺**第一次有了观测者** —— 此前 6 个调用点无一传 `order`，
    承诺无人验证。把 build_server/serve_in_thread 挪回 `_show_window`（start 之前）⇒ 本断言转红。
    """
    mod = _mod()
    # Task 3 后建服/起服在 _after_start 里：不起真服务、不 import 真 delector.server。
    # order 必须在此先建后传入：替身要把 build_server/serve_in_thread 也记进同一份顺序表。
    order: List[str] = []
    _stub_server_build(monkeypatch, mod, order)

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

    code = mod._show_window(object(), 8000, str(tmp_path / "launch.log"))

    assert "start" in order, "必须调用 webview.start"
    start_index = order.index("start")
    # 全集而不仅是 evaluate_js/load_url：show / destroy 也是窗口 API，提前调用同样被 marshal 到
    # 未启动的 GUI 线程 ⇒ 永久阻塞（P0 硬约束原文：evaluate_js / load_url / show / destroy 等）。
    window_ops = [index for index, op in enumerate(order) if op in _WINDOW_OPS]
    assert window_ops, "成功路径必然有窗口操作（evaluate_js / load_url / show / destroy）"
    assert all(index > start_index for index in window_ops), (
        f"窗口操作早于 webview.start()（P0 死锁形状）：order={order}"
    )
    # Task 3 / Y2：建服与起服同样必须晚于 start（它们已搬进 _after_start，即 start 调度函数体内）。
    # 少了这条，"把 build_server 挪回 _show_window（start 之前）"会让 4~6.5s 零反馈复活而全绿。
    for server_op in ("build_server", "serve_in_thread"):
        assert server_op in order, f"{server_op} 必须被调到（order={order}）"
        assert order.index(server_op) > start_index, (
            f"{server_op} 早于 webview.start()（Task 3 回退形状：splash 前的重活零反馈）：order={order}"
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
    # Task 3 后建服/起服在 _after_start 里：不起真服务、不 import 真 delector.server。
    _stub_server_build(monkeypatch, mod)
    order: List[str] = []
    record: Dict[str, Any] = {}
    _install_recording_webview(monkeypatch, mod, order, record)

    code = mod._show_window(object(), 8000, str(tmp_path / "launch.log"))

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
    # Task 3 后建服/起服在 _after_start 里：不起真服务、不 import 真 delector.server。
    _stub_server_build(monkeypatch, mod)
    order: List[str] = []
    record: Dict[str, Any] = {}
    _install_recording_webview(monkeypatch, mod, order, record)

    mod._show_window(object(), 8000, str(tmp_path / "launch.log"))

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
    # Task 3 后建服/起服在 _after_start 里：不起真服务、不 import 真 delector.server。
    _stub_server_build(monkeypatch, mod)
    order: List[str] = []
    record: Dict[str, Any] = {}
    _install_recording_webview(monkeypatch, mod, order, record)

    mod._show_window(object(), 8000, str(tmp_path / "launch.log"))

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
    """非 Windows 直接 None，且**绝不触碰** `ctypes.windll` 链（CI 是 ubuntu，那儿根本不存在）。

    记录型假 ctypes（同 `_RecordingCtypes`）记账每一次属性访问且**不抛**：`sys.platform="linux"` 下
    平台守卫还在 ⇒ `_ms_since_process_create` 在 `import ctypes` 之前就早退 ⇒ `touched == []`。

    **变异自证**（为什么必须断言 `touched == []` 而非只断言 `is None`）：删掉 `desktop.py` 里
    `_ms_since_process_create` 的平台守卫后，`_win_ms_since_create` 会走 `ctypes.windll.kernel32 …`
    —— 假 ctypes 记账（`touched` 非空）、`GetProcessTimes(...)` 返回 0 ⇒ 底层抛 `OSError` 被
    `except Exception` 吞掉**仍返回 None**。旧版只断言 `is None` 时这会**照样绿**（恒绿：静默吞异常
    骗过了"不许碰 Win32"的承诺）；本版由 `touched == []` 钉死，删守卫即转红。
    """
    mod = _mod()
    touched: List[str] = []
    calls: List[Any] = []
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setitem(sys.modules, "ctypes", _RecordingCtypes("ctypes", touched, calls))

    assert mod._ms_since_process_create() is None
    assert touched == [], f"非 Windows 不得触碰 Win32 API（ctypes.windll 链），实际访问：{touched}"


@pytest.mark.skipif(
    os.environ.get("DELECTOR_GUI_TEST") != "1",
    reason="需要真实桌面会话：pystray 与 pywebview 事件循环共存需真窗口实测（ADR-0020 §6 Unknown 4）",
)
def test_tray_coexists_with_webview_event_loop():  # pragma: no cover - 只在真实桌面会话手动执行
    """托盘与窗口事件循环共存（默认跳过）：这是 ADR-0020 §6 Unknown 4，必须在真桌面实测。"""
    pytest.skip("GUI 冒烟：请在真实桌面会话手动验证托盘与窗口互不阻塞")
