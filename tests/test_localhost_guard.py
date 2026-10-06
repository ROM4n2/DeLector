# -*- coding: utf-8 -*-
"""用 AST 钉住所有显式挂载 ``_require_localhost`` 的 HTTP 路由。

发现方式必须足够宽，否则"将来有人挂了闸但守卫看不见"会静默漏网：
- router 变量名不写死：识别模块级任意 ``X = APIRouter(...)``（``hoeren_router`` 等）；
- prefix 逐个 router 解析：多 router 模块不会取错/取空前缀，撞键时直接报错；
- 闸的本地名不写死：识别 ``from ... import _require_localhost as X`` 与模块级再赋值别名；
- 挂载形态覆盖：``@router.<method>`` 装饰器与 ``router.add_api_route(...)`` 语句。
运行时 ``route.dependant`` **不可替代**本扫描（实测只能枚举到 4 条 ``Depends`` 形式，
看不见函数体内直接调用的 16 条）。
"""

import ast
from pathlib import Path

import pytest

ROUTES_DIR = Path(__file__).resolve().parents[1] / "delector" / "routes"
HTTP_METHODS = frozenset({"delete", "get", "head", "options", "patch", "post", "put"})

PROTECTED_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("DELETE", "/api/articles/{article_id}"),
        ("DELETE", "/api/cards/{card_type}/{card_id}"),
        ("DELETE", "/api/essays/{essay_id}"),
        ("DELETE", "/api/essays/{essay_id}/versions/{version_id}"),
        ("DELETE", "/api/notes/{note_id}"),
        ("GET", "/api/backup/download/{token}"),
        ("GET", "/api/backup/export"),
        ("GET", "/api/wb/backup/download/{token}"),
        ("GET", "/api/wb/state/key"),
        ("POST", "/api/audio/cache/clear"),
        ("POST", "/api/backup/prepare"),
        ("POST", "/api/backup/restore"),
        ("POST", "/api/encounter/import-pack"),
        ("POST", "/api/encounter/pull-pack"),
        ("POST", "/api/encounter/texts"),
        ("POST", "/api/settings"),
        ("POST", "/api/settings/test-key"),
        ("POST", "/api/tools/{tool_name}"),
        ("POST", "/api/wb/backup/prepare"),
        ("POST", "/api/wb/state/key"),
    }
)

RouteFunction = ast.FunctionDef | ast.AsyncFunctionDef


def _local_aliases(tree: ast.Module, canonical: str) -> frozenset[str]:
    """模块级把 ``canonical`` 绑到本地名的所有写法（``import ... as`` 与再赋值别名）。"""
    names: set[str] = {canonical}
    for statement in tree.body:
        if isinstance(statement, ast.ImportFrom):
            for alias in statement.names:
                if alias.name == canonical:
                    names.add(alias.asname or canonical)
        elif isinstance(statement, ast.Assign):
            if isinstance(statement.value, ast.Name) and statement.value.id in names:
                names.update(target.id for target in statement.targets if isinstance(target, ast.Name))
    return frozenset(names)


def _module_routers(tree: ast.Module, source_path: Path, router_class: frozenset[str]) -> dict[str, str]:
    """模块级任意 ``X = APIRouter(...)`` -> ``{X: prefix}``；不写死变量名。"""
    routers: dict[str, str] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            targets: list[ast.expr] = list(statement.targets)
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
        else:
            continue
        call = statement.value
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in router_class):
            continue
        prefix = ""
        for keyword in call.keywords:
            if keyword.arg != "prefix":
                continue
            if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                prefix = keyword.value.value
            else:
                raise AssertionError(f"{source_path}:{call.lineno}: APIRouter prefix 必须是字符串字面量")
        for target in targets:
            if isinstance(target, ast.Name):
                routers[target.id] = prefix
    return routers


def _add_api_route_method(call: ast.Call) -> str:
    """``router.add_api_route(path, endpoint, methods=[...])`` 的 HTTP 方法。"""
    for keyword in call.keywords:
        if keyword.arg != "methods":
            continue
        node = keyword.value
        if not isinstance(node, (ast.List, ast.Tuple)) or not node.elts:
            continue
        literals = [
            element.value
            for element in node.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
        if len(literals) == len(node.elts) and len(set(literals)) == 1:
            return literals[0].upper()
        raise AssertionError(
            f"line {call.lineno}: add_api_route 的 methods 无法静态确定，请改用 @router.<method> 装饰器"
        )
    return "GET"


def _router_owner(node: ast.expr, router_names: frozenset[str]) -> str | None:
    """``X.get(...)`` / ``X.add_api_route(...)`` 里的 router 变量名。"""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in router_names:
        return node.value.id
    return None


def _decorator_mounts(function: RouteFunction, router_names: frozenset[str]) -> list[tuple[ast.Call, str, str]]:
    """``@router.get(...)`` 装饰器挂载点 -> ``(decorator, METHOD, router变量名)``。"""
    mounts: list[tuple[ast.Call, str, str]] = []
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
            continue
        owner = _router_owner(decorator.func, router_names)
        if owner is None or decorator.func.attr not in HTTP_METHODS:
            continue
        mounts.append((decorator, decorator.func.attr.upper(), owner))
    return mounts


def _add_api_route_mounts(
    tree: ast.Module, functions: dict[str, RouteFunction], router_names: frozenset[str], guard_names: frozenset[str]
) -> list[tuple[ast.Call, str, str]]:
    """模块级 ``router.add_api_route(...)`` 语句挂载点（endpoint 挂在具名函数上）。"""
    mounts: list[tuple[ast.Call, str, str]] = []
    for statement in tree.body:
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            continue
        call = statement.value
        if not isinstance(call.func, ast.Attribute) or call.func.attr != "add_api_route":
            continue
        owner = _router_owner(call.func, router_names)
        if owner is None:
            continue
        endpoint = call.args[1] if len(call.args) > 1 else None
        if not (isinstance(endpoint, ast.Name) and endpoint.id in functions):
            continue
        if not _calls_guard_directly(functions[endpoint.id], guard_names):
            continue
        mounts.append((call, _add_api_route_method(call), owner))
    return mounts


def _calls_guard_directly(function: RouteFunction, guard_names: frozenset[str]) -> bool:
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in guard_names
        for statement in function.body
        for node in ast.walk(statement)
    )


def _depends_on_guard(decorator: ast.Call, guard_names: frozenset[str]) -> bool:
    for keyword in decorator.keywords:
        if keyword.arg != "dependencies":
            continue
        for node in ast.walk(keyword.value):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Depends"):
                continue
            candidates: list[ast.expr] = list(node.args)
            candidates.extend(kw.value for kw in node.keywords if kw.arg == "dependency")
            if any(isinstance(candidate, ast.Name) and candidate.id in guard_names for candidate in candidates):
                return True
    return False


def _route_key(call: ast.Call, method: str, prefix: str, source_path: Path) -> tuple[str, str]:
    if not call.args:
        raise AssertionError(f"{source_path}:{call.lineno}: 路由挂载缺少 path")
    path_node = call.args[0]
    if not (isinstance(path_node, ast.Constant) and isinstance(path_node.value, str)):
        raise AssertionError(f"{source_path}:{call.lineno}: 受保护路由 path 必须是字符串字面量")
    return method, prefix + path_node.value


def _record(
    guarded_routes: dict[tuple[str, str], str], key: tuple[str, str], router_name: str, source_path: Path
) -> None:
    previous = guarded_routes.setdefault(key, router_name)
    if previous != router_name:
        raise AssertionError(
            f"{source_path}: 受保护路由 {key[0]} {key[1]} 同时由 {previous} 与 {router_name} 挂闸，"
            "path 键发生碰撞，需人工确认 prefix"
        )


def collect_guarded_routes(routes_dir: Path = ROUTES_DIR) -> set[tuple[str, str]]:
    """扫描函数体直调与路由 ``Depends`` 两种本机闸挂载形式。"""
    guarded_routes: dict[tuple[str, str], str] = {}
    for source_path in sorted(routes_dir.glob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        routers = _module_routers(tree, source_path, _local_aliases(tree, "APIRouter"))
        router_names = frozenset(routers)
        guard_names = _local_aliases(tree, "_require_localhost")
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in functions.values():
            direct_guard = _calls_guard_directly(node, guard_names)
            for call, method, router_name in _decorator_mounts(node, router_names):
                if direct_guard or _depends_on_guard(call, guard_names):
                    _record(
                        guarded_routes,
                        _route_key(call, method, routers[router_name], source_path),
                        router_name,
                        source_path,
                    )
        for call, method, router_name in _add_api_route_mounts(tree, functions, router_names, guard_names):
            _record(
                guarded_routes,
                _route_key(call, method, routers[router_name], source_path),
                router_name,
                source_path,
            )
    return set(guarded_routes)


def _format_routes(routes: set[tuple[str, str]] | frozenset[tuple[str, str]]) -> str:
    if not routes:
        return "  （无）"
    return "\n".join(f"  {method} {path}" for method, path in sorted(routes))


def test_protected_routes_match_explicit_allowlist() -> None:
    actual = collect_guarded_routes()
    missing = PROTECTED_ROUTES - actual
    extra = actual - PROTECTED_ROUTES

    assert not missing and not extra, (
        "受 _require_localhost 保护的路由集合发生漂移\n"
        "缺失（allowlist 有、扫描结果无）:\n"
        f"{_format_routes(missing)}\n"
        "多余（扫描结果有、allowlist 无）:\n"
        f"{_format_routes(extra)}"
    )


def _write(tmp_path: Path, name: str, source: str) -> None:
    (tmp_path / name).write_text(source, encoding="utf-8")


def test_guard_found_on_non_literal_router_name(tmp_path: Path) -> None:
    """洞 1：router 变量名不写死——``hoeren_router`` 上的闸也必须被发现。"""
    _write(
        tmp_path,
        "a1_hoeren.py",
        "from fastapi import APIRouter\n"
        "from delector.core.database import _require_localhost\n"
        "\n"
        "hoeren_router = APIRouter(prefix='/api/a1/hoeren')\n"
        "\n"
        "@hoeren_router.post('/drill')\n"
        "def drill() -> None:\n"
        "    _require_localhost(request)\n",
    )
    assert collect_guarded_routes(tmp_path) == {("POST", "/api/a1/hoeren/drill")}


def test_prefix_resolved_per_router(tmp_path: Path) -> None:
    """洞 2：一模块多 router 时 prefix 逐个解析，同名子路径不得互相覆盖。"""
    _write(
        tmp_path,
        "multi.py",
        "from fastapi import APIRouter\n"
        "from delector.core.database import _require_localhost\n"
        "\n"
        "router = APIRouter(prefix='/api/one')\n"
        "other_router = APIRouter(prefix='/api/two')\n"
        "\n"
        "@router.post('/key')\n"
        "def one() -> None:\n"
        "    _require_localhost(request)\n"
        "\n"
        "@other_router.post('/key')\n"
        "def two() -> None:\n"
        "    _require_localhost(request)\n",
    )
    assert collect_guarded_routes(tmp_path) == {
        ("POST", "/api/one/key"),
        ("POST", "/api/two/key"),
    }


def test_colliding_path_keys_across_routers_raise(tmp_path: Path) -> None:
    """洞 2 续：两个 router 撞出同一个 path 键时必须报错，而不是静默覆盖。"""
    _write(
        tmp_path,
        "collide.py",
        "from fastapi import APIRouter\n"
        "from delector.core.database import _require_localhost\n"
        "\n"
        "router = APIRouter(prefix='/api/same')\n"
        "twin_router = APIRouter(prefix='/api/same')\n"
        "\n"
        "@router.post('/key')\n"
        "def one() -> None:\n"
        "    _require_localhost(request)\n"
        "\n"
        "@twin_router.post('/key')\n"
        "def two() -> None:\n"
        "    _require_localhost(request)\n",
    )
    with pytest.raises(AssertionError, match="path 键发生碰撞"):
        collect_guarded_routes(tmp_path)


def test_guard_alias_from_import_as_is_detected(tmp_path: Path) -> None:
    """洞 3：``from ... import _require_localhost as _guard`` 两种挂载形态都要识别。"""
    _write(
        tmp_path,
        "aliased.py",
        "from fastapi import APIRouter, Depends\n"
        "from delector.core.database import _require_localhost as _guard\n"
        "\n"
        "router = APIRouter(prefix='/api/alias')\n"
        "\n"
        "@router.post('/direct')\n"
        "def direct() -> None:\n"
        "    _guard(request)\n"
        "\n"
        "@router.post('/depends', dependencies=[Depends(dependency=_guard)])\n"
        "def via_depends() -> None:\n"
        "    return None\n",
    )
    assert collect_guarded_routes(tmp_path) == {
        ("POST", "/api/alias/depends"),
        ("POST", "/api/alias/direct"),
    }


def test_module_level_alias_assignment_is_detected(tmp_path: Path) -> None:
    """洞 3 续：模块级 ``_guard = _require_localhost`` 再赋值别名同样要识别。"""
    _write(
        tmp_path,
        "rebound.py",
        "from fastapi import APIRouter\n"
        "from delector.core.database import _require_localhost\n"
        "\n"
        "_guard = _require_localhost\n"
        "router = APIRouter(prefix='/api/rebound')\n"
        "\n"
        "@router.post('/key')\n"
        "def key() -> None:\n"
        "    _guard(request)\n",
    )
    assert collect_guarded_routes(tmp_path) == {("POST", "/api/rebound/key")}


def test_add_api_route_mount_is_detected(tmp_path: Path) -> None:
    """``router.add_api_route(...)`` 挂载形态也要进入扫描。"""
    _write(
        tmp_path,
        "add_api_route.py",
        "from fastapi import APIRouter\n"
        "from delector.core.database import _require_localhost\n"
        "\n"
        "router = APIRouter(prefix='/api/add')\n"
        "\n"
        "def key() -> None:\n"
        "    _require_localhost(request)\n"
        "\n"
        "router.add_api_route('/key', key, methods=['POST'])\n"
        "router.add_api_route('/plain', key)\n",
    )
    assert collect_guarded_routes(tmp_path) == {
        ("POST", "/api/add/key"),
        ("GET", "/api/add/plain"),
    }