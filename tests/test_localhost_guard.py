# -*- coding: utf-8 -*-
"""用 AST 钉住所有显式挂载 ``_require_localhost`` 的 HTTP 路由。"""

import ast
from pathlib import Path

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


def _router_prefix(tree: ast.Module, source_path: Path) -> str:
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "router" for target in statement.targets):
            continue
        call = statement.value
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "APIRouter"):
            continue
        for keyword in call.keywords:
            if keyword.arg != "prefix":
                continue
            if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                return keyword.value.value
            raise AssertionError(f"{source_path}: APIRouter prefix 必须是字符串字面量")
    return ""


def _route_decorators(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Call]:
    decorators = []
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
            continue
        owner = decorator.func.value
        if isinstance(owner, ast.Name) and owner.id == "router" and decorator.func.attr in HTTP_METHODS:
            decorators.append(decorator)
    return decorators


def _calls_guard_directly(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_require_localhost"
        for statement in function.body
        for node in ast.walk(statement)
    )


def _depends_on_guard(decorator: ast.Call) -> bool:
    for keyword in decorator.keywords:
        if keyword.arg != "dependencies":
            continue
        for node in ast.walk(keyword.value):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Depends"):
                continue
            if node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == "_require_localhost":
                return True
    return False


def _route_key(decorator: ast.Call, prefix: str, source_path: Path) -> tuple[str, str]:
    if not decorator.args:
        raise AssertionError(f"{source_path}:{decorator.lineno}: 路由装饰器缺少 path")
    path_node = decorator.args[0]
    if not (isinstance(path_node, ast.Constant) and isinstance(path_node.value, str)):
        raise AssertionError(f"{source_path}:{decorator.lineno}: 受保护路由 path 必须是字符串字面量")
    assert isinstance(decorator.func, ast.Attribute)
    return decorator.func.attr.upper(), prefix + path_node.value


def collect_guarded_routes() -> set[tuple[str, str]]:
    """扫描函数体直调与路由 ``Depends`` 两种本机闸挂载形式。"""
    guarded_routes: set[tuple[str, str]] = set()
    for source_path in sorted(ROUTES_DIR.glob("*.py")):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        prefix = _router_prefix(tree, source_path)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            route_decorators = _route_decorators(node)
            direct_guard = _calls_guard_directly(node)
            for decorator in route_decorators:
                if direct_guard or _depends_on_guard(decorator):
                    guarded_routes.add(_route_key(decorator, prefix, source_path))
    return guarded_routes


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
