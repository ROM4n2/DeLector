# -*- coding: utf-8 -*-
"""根因级 AST 守卫：测试模块 MUST NOT 在**模块级**直接赋值库 env。

背景（2026-09-26 的 `no such table: exam_trials` 事故）：
`delector/server.py` 顶层有 `app = create_app()` 副作用，收集期按当时 env 建库并被多模块共用。
若某测试模块在**模块级**直接 `os.environ["DATABASE_PATH"] = "test_X.db"`：
  1. 它永久污染进程 env（无人还原）；
  2. 后到模块的 `os.environ.setdefault(...)` 因此**失效**（env 已被设置）；
  3. 而 `test_X.db` 又被 X 模块自己的 fixture 在结尾 `os.remove` 掉；
  4. → 后到模块请求时 sqlite 新建空库 → `no such table: exam_trials` ❌
跨平台都存在，只是 ubuntu 上 `os.remove` 常因句柄未释放抛 `OSError` 被吞而**掩盖**了它。

契约（见 docs/specs/2026-09-26-test-db-isolation-design.md §3.1）：
  - C1：MUST NOT 在模块级直接赋值 `DATABASE_PATH` / `PROGRESS_DB_PATH`；
  - C2：需要独立库的模块 → autouse fixture「捕获 saved → 钉 env → init_db() →
        yield → 清理 → 还原 saved」；**函数/fixture 内的赋值是允许的**。

本守卫用 `ast` 而非正则/子进程：零依赖、能区分「模块级」与「函数内」、能报行号。
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = ROOT / "tests"
ROOT_CONFTEST = ROOT / "conftest.py"

_DB_ENV_KEYS = ("DATABASE_PATH", "PROGRESS_DB_PATH")

# 顶层可见的复合语句：它们的直接子语句仍算「模块级」。
_MODULE_LEVEL_COMPOUND = (
    ast.If,
    ast.Try,
    ast.For,
    ast.While,
    ast.With,
    ast.AsyncFor,
    ast.AsyncWith,
)

_FIX_HINT = (
    "模块级直接赋值库 env 会永久污染进程环境（无人还原）→ 后到模块的 "
    "os.environ.setdefault(...) 失效 → 它们命中被删的空库 → "
    "sqlite3.OperationalError: no such table。\n"
    "   正确修法：删掉模块级赋值，改在 autouse fixture 内「捕获 saved → 钉 env → "
    "init_db() → yield → 清理 → 还原 saved」（见 "
    "docs/specs/2026-09-26-test-db-isolation-design.md §3.1 C2）。"
)


def _iter_module_level(stmts):
    """产出模块级语句（含顶层 if/try/with/for 等块的直接子语句），不进入函数/类体。"""
    for node in stmts:
        yield node
        if isinstance(node, _MODULE_LEVEL_COMPOUND):
            for attr in ("body", "orelse", "finalbody"):
                sub = getattr(node, attr, None)
                if sub:
                    yield from _iter_module_level(sub)
            for handler in getattr(node, "handlers", ()):
                yield from _iter_module_level(handler.body)


def _env_key_of_target(target):
    """若 target 形如 `X.environ["DATABASE_PATH"]` 则返回键名，否则 None。"""
    if not isinstance(target, ast.Subscript):
        return None
    value = target.value
    if not (isinstance(value, ast.Attribute) and value.attr == "environ"):
        return None
    key = target.slice
    if isinstance(key, ast.Constant) and key.value in _DB_ENV_KEYS:
        return key.value
    return None


def _module_level_env_assignments(path):
    """返回 [(行号, 键名), ...]：模块级对库 env 的直接赋值。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in _iter_module_level(tree.body):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = (node.target,)
        else:
            continue
        for target in targets:
            key = _env_key_of_target(target)
            if key is not None:
                found.append((node.lineno, key))
    return found


def _scanned_files():
    files = sorted(TESTS_DIR.glob("*.py"))
    if ROOT_CONFTEST.exists():
        files.append(ROOT_CONFTEST)
    return files


def test_no_module_level_database_env_assignment():
    """测试模块 MUST NOT 在模块级直接赋值 DATABASE_PATH / PROGRESS_DB_PATH。

    后果与修法见文件头 docstring 与断言消息；函数/fixture 内赋值不算违规（契约 C2 允许）。
    """
    offenders = []
    for path in _scanned_files():
        for lineno, key in _module_level_env_assignments(path):
            rel = path.relative_to(ROOT).as_posix()
            offenders.append(f"  {rel}:{lineno}  os.environ[{key!r}] = ...")

    assert not offenders, (
        "检测到模块级直接赋值库 env（违反契约 C1）：\n" + "\n".join(offenders) + "\n   " + _FIX_HINT
    )


def test_root_conftest_provides_default_database_path():
    """根 `conftest.py` 必须提供兜底默认库 env（§3.2），保护 `server` 顶层 `init_db()`。

    `setdefault("DATABASE_PATH", ...)` 保证「任何测试模块 import server 之前 env 已有值」，
    使 `server` 顶层 `init_db()` 落到测试库而非仓库根的真实 `delector.db`。
    注意：兜底 conftest 在**仓库根**（`conftest.py`），不是 `tests/conftest.py`。
    """
    assert ROOT_CONFTEST.exists(), (
        "根 conftest.py 不存在：它承担「测试默认库 env 兜底」契约"
        "（见 docs/specs/2026-09-26-test-db-isolation-design.md §3.2）。"
    )
    tree = ast.parse(ROOT_CONFTEST.read_text(encoding="utf-8"), filename=str(ROOT_CONFTEST))
    for node in _iter_module_level(tree.body):
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
            continue
        call = node.value
        func = call.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "setdefault"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "environ"
            and call.args
            and isinstance(call.args[0], ast.Constant)
            and call.args[0].value == "DATABASE_PATH"
        ):
            return
    raise AssertionError(
        '根 conftest.py 缺少模块级 `os.environ.setdefault("DATABASE_PATH", ...)`：'
        "没有它，`server` 顶层 `init_db()` 可能落到仓库根的真实 `delector.db`"
        "（见 docs/specs/2026-09-26-test-db-isolation-design.md §3.2）。"
    )


def test_root_conftest_keeps_sys_path_injection():
    """根 `conftest.py` 的 sys.path 注入是长期需要的，别删（防误删此段）。"""
    text = ROOT_CONFTEST.read_text(encoding="utf-8")
    assert "sys.path.insert" in text, (
        "根 conftest.py 的 sys.path 注入段丢了：`pytest`（非 `python -m pytest`）不会把 CWD "
        "加进 sys.path，缺它则 tests/ 里 `import delector` 直接 ModuleNotFoundError。"
        "这段是长期需要的，别删（文件头注释已说明）。"
    )
