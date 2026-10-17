# -*- coding: utf-8 -*-
"""桌面壳「启动守卫」域：导入安全 / 流写纪律 / 导入探针 / AppUserModelID 时机。

C6 Task 6 自 `tests/test_desktop_shell.py` 逐字搬出；搬出的段（搬前 `test_desktop_shell.py`
行号，实测，含各段头注释）：
  `652`-`831`   import 安全性（AST：不起服务 / 弹窗 / 拉 GUI）· Task 4 裸输出守卫（AST 顺序契约）
  `1953`-`1967` 子进程实证：`import desktop` 零输出
  `2346`-`2518` Task 4b：AppUserModelID（API / 实参 +「建窗之前」的 AST 时机断言）

断言、用例名与 docstring 逐字未改；只新增本文件的显式 import。跨域共用项
（`REPO_ROOT` / `_mod` / `_parse_desktop` / `_is_main_guard` / `_funcs_by_name` /
`_calls` / `_call_label` / `_RecordingCtypes`）与 autouse 兜底夹具
`_isolate_data_dir` 住在 `tests/server_helpers.py`，按名 import 即在本模块注册。
"""

import ast
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterator, List, Optional, Tuple

import pytest
from server_helpers import (
    REPO_ROOT,
    _call_label,
    _calls,
    _funcs_by_name,
    _is_main_guard,
    _mod,
    _parse_desktop,
    _RecordingCtypes,
)
from server_helpers import _isolate_data_dir as _isolate_data_dir

# ── import 安全性：`import desktop` 不得起服务 / 弹窗 / 拉 GUI ────────────────


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


# ── Task 4：标准流收口前的裸输出守卫（AST 结构级，no-console 顺序契约）──────────
# 判据出处：docs/plans/2026-10-14-no-console-feedback-gaps.md Task 4（怀疑者复核后的事实）：
# CPython 的 print() 在 sys.stdout is None 时是**静默 no-op**（builtin print 内部
# `if file is None: return`），不崩；真会崩的是 `None.write`（argparse 的 file.write
# 路径，Task 1 已修）。故本守卫防的不是"解释器崩"，是**零线索**：--windowed 产物里，
# 收口点之前直接写标准流的代码，要么被静默蒸发（print 到 None），要么当场
# AttributeError（None.write）⇒ 用户面对一扇不出现的窗口、launch.log 零行。
#
# 为什么是 AST 守卫而不是"真启一次"：CI 的子进程 stdout 被重定向进日志 ⇒ 标准流并非
# None，那类回归在 verify_windows_portable.py 的 (c) 步语境下**不会被触发**，扫
# traceback 也瞄不到它（判据从一开始就瞄错了对象）。None 语境只有本文件的
# `sys.stdout=None` 注入单测复现得了；顺序契约则由这里静态钉死。
#
# 收口点（标准流被保证可写的时刻）= 调用 ensure_streams 一族函数的语句：
# - `ensure_streams`：桌面/跨平台共用的收口实现（desktop.py）；
# - `_ensure_entry_streams`：start.py 入口对上述收口的复用包装（内部就是
#   `from desktop import ensure_streams`；其 docstring 明言"复用桌面壳的 launch.log 收口"）；
# - `_redirect_std_streams`：run_desktop 内的兼容接线（内部转调 ensure_streams）。
_STREAM_COVERAGE_CALLS: FrozenSet[str] = frozenset(
    {"ensure_streams", "_ensure_entry_streams", "_redirect_std_streams"}
)
# 受守护的入口模块（相对仓库根）：桌面入口与跨平台入口（Task 1 把两者 __main__ 都改成先收口后解析）。
_STREAM_GUARD_FILES: Tuple[str, ...] = ("desktop.py", "start.py")


def _walk_flat(node: ast.AST) -> Iterator[ast.AST]:
    """walk 但不深入嵌套函数/类/lambda：那些是独立作用域，由各自的语句序列管辖。"""
    yield node
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield from _walk_flat(child)


def _stream_write_violation(call: ast.Call) -> Optional[str]:
    """裸输出调用 ⇒ 人类可读标签；合法调用（带 file= / 非标准流 write）⇒ None。"""
    func = call.func
    if isinstance(func, ast.Name) and func.id == "print":
        if any(kw.arg == "file" for kw in call.keywords):
            return None
        return "无 file= 关键字参数的 print(...)（收口前写到 None 流 = 静默蒸发）"
    if isinstance(func, ast.Attribute) and func.attr == "write":
        target = func.value
        if (
            isinstance(target, ast.Attribute)
            and target.attr in {"stdout", "stderr"}
            and isinstance(target.value, ast.Name)
            and target.value.id == "sys"
        ):
            return f"sys.{target.attr}.write(...)（收口前对 None 流调用 = AttributeError 零线索崩溃）"
    return None


def _direct_coverage_lineno(stmts: List[ast.stmt]) -> Optional[int]:
    """模块级：只认**直接**是收口调用的表达式语句（If/Try 块由各自单位管辖，不进子树）。"""
    for stmt in stmts:
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            func = stmt.value.func
            if isinstance(func, ast.Name) and func.id in _STREAM_COVERAGE_CALLS:
                return stmt.value.lineno
    return None


def _scoped_coverage_lineno(stmts: List[ast.stmt]) -> Optional[int]:
    """函数/入口块：控制流块（try/if/for…）内的收口调用也算界，但不深入嵌套 def/class。"""
    best: Optional[int] = None
    for stmt in stmts:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for node in _walk_flat(stmt):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in _STREAM_COVERAGE_CALLS
            ):
                if best is None or node.lineno < best:
                    best = node.lineno
    return best


def _statement_scopes(tree: ast.Module) -> Iterator[Tuple[str, List[ast.stmt], Optional[int]]]:
    """产出所有线性执行序列 `(作用域名, 语句表, 收口行号)`；无收口行号 ⇒ 该序列不受静态管辖。"""
    yield ("<module>", tree.body, _direct_coverage_lineno(tree.body))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield (node.name, node.body, _scoped_coverage_lineno(node.body))
        elif isinstance(node, ast.If) and _is_main_guard(node):
            yield ("<__main__>", node.body, _scoped_coverage_lineno(node.body))


def _stream_guard_violations(source: str, filename: str) -> List[str]:
    violations: List[str] = []
    tree = ast.parse(source, filename=filename)
    for scope, stmts, boundary in _statement_scopes(tree):
        if boundary is None:
            continue  # 该序列没有收口点 ⇒ 裸输出的执行时机由调用方决定，静态不可判
        for stmt in stmts:
            if stmt.lineno > boundary:
                break  # 已过收口点：标准流此时已保证可写，允许裸 print / write
            for node in _walk_flat(stmt):
                if isinstance(node, ast.Call) and node.lineno < boundary:
                    label = _stream_write_violation(node)
                    if label is not None:
                        violations.append(f"{filename}:{node.lineno}（{scope}）{label}")
    return violations


@pytest.mark.parametrize("relpath", _STREAM_GUARD_FILES)
def test_no_bare_stream_writes_before_stream_coverage(relpath: str) -> None:
    """收口点之前不得出现裸 print / sys.stdout.write / sys.stderr.write（Task 4 结构守卫）。

    先证过"无守卫时抓不到"：临时在两个入口的收口调用前各插一个裸 print，既有 124 条
    用例全绿。本用例落地后再做同样的插入 ⇒ 转红（RED 原文见提交信息）；删除复原 ⇒ 转绿
    （仓库外副本备份 + md5 复核，未用 git checkout/restore）。
    """
    source = (REPO_ROOT / relpath).read_text(encoding="utf-8")
    violations = _stream_guard_violations(source, relpath)

    assert not violations, (
        f"{relpath} 在标准流收口（ensure_streams 一族）之前出现裸输出：\n"
        + "\n".join(f"  - {v}" for v in violations)
        + "\n收口前写标准流 = 无控制台（--windowed）语境下零线索：print 静默蒸发、"
        "sys.stdout/stderr.write 直接 AttributeError。请把输出移到收口调用之后，或显式传 file=。"
    )


def test_import_desktop_has_no_side_effects():
    """子进程实证：`import desktop` 返回 0 且**零输出**（没起服务、没弹窗、没拉 GUI）。"""
    proc = subprocess.run(
        [sys.executable, "-c", "import desktop"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )

    assert proc.returncode == 0, f"import desktop 失败：{proc.stderr}"
    assert proc.stdout.strip() == "", f"import desktop 不得有任何输出：{proc.stdout!r}"
    assert proc.stderr.strip() == "", f"import desktop 不得有任何 stderr：{proc.stderr!r}"


# ── Task 4b：AppUserModelID + CRV 黄牌修复（陈旧地址残留 / 非 UTF-8 坏文件 / 文档漂移）───
# 背景：Task 4a（提交 eb5eaf5）实现 lan-address.txt + 托盘「显示局域网地址」，CRV 验收 PASS
# 但开 4 张黄牌。本轮修：① AppUserModelID（任务栏身份，进程早期、建窗之前）；② 黄牌 1：
# 探不到 LAN 时**清掉**上一轮残留的 lan-address.txt（否则托盘读出过期 IP）；③ 黄牌 3：
# `_read_lan_address` 的 except 扩为 (OSError, UnicodeDecodeError)（坏文件不再漏进托盘回调）；
# ④ 黄牌 4a/4b：文档漂移（本文件 docstring 的托盘四项、package_windows 的 --server-only 文案）。
# 回炉黄牌（4b 验收再开 4 张之一，测试名过度承诺）：隔离调用那条原名
# `..._before_window_creation` 声称"挪去建窗之后都会转红"，但它只隔离调用、无任何顺序/结构
# 断言 ⇒ 名实不符。修法：改名去掉时机承诺（`test_app_user_model_id_is_set_on_win32`），
# 另补一条**位置无关**的 AST 顺序断言（`test_app_user_model_id_is_set_before_window_creation`）：
# 沿调用链钉"每条到达 webview.create_window 的路径必经 _set_app_user_model_id 且更早"——
# 真机若发现任务栏仍归 Python 组、需要调调用时机时，改实现即可，不会被迫删断言。
# 记录型假 ctypes 复用 `test_debug_console_never_calls_win32_api_off_windows` 同款范式：
# __getattr__ 只记账**不抛**（哨兵版会被实现里的 except Exception 吞掉 ⇒ 假绿）。


def test_app_user_model_id_is_set_on_win32(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """win32 下必须调 `shell32.SetCurrentProcessExplicitAppUserModelID("ROM4n2.DeLector")`。

    记录型假 ctypes 钉住**属性链**（windll → shell32 → SetCurrentProcessExplicitAppUserModelID）
    与**实参**（AppUserModelID 常量）：换成别的 API、换了 ID 都会转红。

    刻意**不含**时机承诺（旧名 `..._before_window_creation` 属过度承诺：本用例直接隔离调用
    `_set_app_user_model_id`，没有任何顺序/结构断言，"把调用挪去建窗之后"它照绿）。时机由
    `test_app_user_model_id_is_set_before_window_creation`（AST 顺序断言）钉。
    """
    mod = _mod()
    touched: List[str] = []
    calls: List[Any] = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "ctypes", _RecordingCtypes("ctypes", touched, calls))

    mod._set_app_user_model_id(str(tmp_path / "launch.log"))

    assert "windll" in touched, "必须经 ctypes.windll 走 Win32 API"
    assert "shell32" in touched, "AppUserModelID 属 shell32"
    assert "SetCurrentProcessExplicitAppUserModelID" in touched, (
        "必须调 SetCurrentProcessExplicitAppUserModelID（任务栏/固定快捷方式身份）"
    )
    assert calls and calls[0] == ("ROM4n2.DeLector",), f"实参必须是 AppUserModelID 常量，实际：{calls}"


# ── AppUserModelID 的**时机**钉：建窗之前（AST 顺序断言，位置无关）──────────────────
_APP_USER_MODEL_ID_CALL = "_set_app_user_model_id"


def _is_webview_create_window_call(call: ast.Call) -> bool:
    """`webview.create_window(...)`：属性链锚定 `webview` 对象，防同名方法误判。"""
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "create_window"
        and isinstance(func.value, ast.Name)
        and func.value.id == "webview"
    )


def _call_paths(root: str, target: str, funcs: Dict[str, ast.FunctionDef]) -> List[List[Tuple[str, str, int]]]:
    """从 `root` 到 `target` 的全部调用路径（沿本模块顶层函数调用边，防环）。

    每条路径是边序列 `[(caller, callee, 调用点行号), ...]`；同一对函数有多个调用点时每个
    调用点各产出一条边（行号不同，顺序断言才钉得准）。
    """
    paths: List[List[Tuple[str, str, int]]] = []

    def _dfs(current: str, edges: List[Tuple[str, str, int]], seen: FrozenSet[str]) -> None:
        if current == target:
            paths.append(list(edges))
            return
        for call in _calls(funcs[current]):
            label = _call_label(call)
            if label is None or label not in funcs or label in seen:
                continue
            _dfs(label, edges + [(current, label, call.lineno)], seen | {label})

    _dfs(root, [], frozenset({root}))
    return paths


def test_app_user_model_id_is_set_before_window_creation() -> None:
    """`_set_app_user_model_id` 必须在**任何** `webview.create_window` 之前执行到（AST 顺序断言）。

    为什么隔离调用那条不够：它直接调 `_set_app_user_model_id`，钉得住 API 与实参，钉不住
    **时机** —— 把调用挪进 `_show_window`（create_window 之后）它仍全绿。而任务栏按钮在首个
    窗口出现时定身份，晚设不生效 ⇒ 必须沿调用链钉死"建窗之前"。

    **位置无关**：不断言 set 在哪个函数里，只断言"每条到达建窗的路径上、进入建窗函数之前
    必经 set，且 set 调用点早于该路径上后续每一步"。真机若发现任务栏仍归 Python 组、需要调
    调用时机时，改的是实现（更早 / 换到别的函数都行），不会被迫删断言。
    """
    tree = _parse_desktop()
    funcs = _funcs_by_name(tree)

    creates = sorted(
        (name, call.lineno)
        for name, fn in funcs.items()
        for call in _calls(fn)
        if _is_webview_create_window_call(call)
    )
    assert creates, "desktop.py 必然存在 webview.create_window（不建窗 = 没有桌面壳）"

    for func_name, create_line in creates:
        paths = _call_paths("run_desktop", func_name, funcs)
        assert paths, f"从 run_desktop 到 {func_name}（第 {create_line} 行建窗）没有调用路径：入口漂移了？"
        for path in paths:
            edges = [*path, (func_name, "webview.create_window", create_line)]
            guarded = False
            for caller, callee, call_line in edges:
                set_lines = [
                    call.lineno for call in _calls(funcs[caller]) if _call_label(call) == _APP_USER_MODEL_ID_CALL
                ]
                for set_line in set_lines:
                    assert set_line < call_line, (
                        f"{caller} 里第 {set_line} 行的 _set_app_user_model_id 晚于第 {call_line} 行对 "
                        f"{callee} 的调用：任务栏按钮在首个窗口出现时定身份，AppUserModelID 必须在建窗之前设置"
                    )
                guarded = guarded or bool(set_lines)
            assert guarded, (
                f"到达 webview.create_window（{func_name} 第 {create_line} 行）的这条路径没有经过 "
                f"_set_app_user_model_id：{edges}"
            )


def test_app_user_model_id_never_touches_win32_off_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """非 win32（CI ubuntu）不得触碰任何 Win32 API，且绝不抛。"""
    mod = _mod()
    touched: List[str] = []
    calls: List[Any] = []
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setitem(sys.modules, "ctypes", _RecordingCtypes("ctypes", touched, calls))

    mod._set_app_user_model_id(str(tmp_path / "launch.log"))

    assert touched == [], f"非 win32 不得触碰 Win32 API，实际访问：{touched}"
    assert calls == []


def test_app_user_model_id_failure_logs_and_never_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """设置失败（如 shell32 不可用）⇒ **绝不抛**，且落 launch.log 留痕（范式同 _allocate_debug_console）。"""
    mod = _mod()
    monkeypatch.setattr(sys, "platform", "win32")

    class _BoomCtypes(types.ModuleType):
        def __getattr__(self, name: str) -> Any:
            raise OSError("模拟 shell32 不可用")

    monkeypatch.setitem(sys.modules, "ctypes", _BoomCtypes("ctypes"))
    log_path = tmp_path / "launch.log"

    mod._set_app_user_model_id(str(log_path))  # 不得抛

    assert "AppUserModelID" in log_path.read_text(encoding="utf-8"), "失败必须留痕，不许静默"
