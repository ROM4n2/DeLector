# -*- coding: utf-8 -*-
r"""X-WB-Key 鉴权收敛回归锁（P2-③）。

背景
----
`delector.core.database.verify_wb_key` 是**恒定时间比较**的统一入口，但「取 `X-WB-Key`
头 → 比对 → 不符即 403」这段封装曾在 `routes/sync.py` 与 `routes/rtc.py` 里**逐字节
重复两份**（`routes/main.py` 的 `PUT /api/wb/state` 另有第三份内联）⇒ **改一处漏一处 =
信令端点鉴权绕过**（信令在 LAN 上中继 SDP，裸奔即把会话描述递给同网段任何人）。现收敛到
`core/wb_auth.py:require_wb_key` 唯一一份（住 `core/` 而非 `routes/`：后者要求每个模块都
定义 APIRouter，见 `test_server.py::test_register_routes_covers_every_module_in_routes_package`）。

钉两件事
--------
1. **行为一致**：相同请求头在 sync / rtc / state 三端点得到同一状态码（HTTP 语义与文案
   在收敛中不得漂移）；
2. **无重复实现**：全仓「调用 `verify_wb_key(` 的实现函数」只有一处（`require_wb_key`），
   路由层不再各写一份 `invalid X-WB-Key` 的 403。

库 env 由 `clean_db` autouse fixture 前后钉定（契约见
`docs/specs/2026-09-26-test-db-isolation-design.md` §3.1）。
"""

import ast
import gc
import os
from pathlib import Path
from typing import List, Tuple

import pytest
from db_cleanup import remove_db_files  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from delector.server import app  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
_DELECTOR = _ROOT / "delector"

# 三端点共用同一鉴权：缺 key / 错 key 形态各一。
_BAD_HEADERS: Tuple[dict, ...] = ({}, {"X-WB-Key": "0" * 32}, {"X-WB-Key": "not-the-key"})


@pytest.fixture
def client():
    # 显式 127.0.0.1 来源：`/api/wb/state/key` 有本机闸，TestClient 默认 host "testclient" 会被拒。
    return TestClient(app, client=("127.0.0.1", 54321))


@pytest.fixture(autouse=True)
def clean_db():
    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH")}
    os.environ["DATABASE_PATH"] = "test_wb_auth_delector.db"
    os.environ["PROGRESS_DB_PATH"] = "test_wb_auth_progress.db"
    gc.collect()
    remove_db_files("test_wb_auth_delector.db", "test_wb_auth_progress.db")
    from delector.server import init_db

    init_db("test_wb_auth_delector.db")
    yield
    gc.collect()
    remove_db_files("test_wb_auth_delector.db", "test_wb_auth_progress.db")
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _iter_py(root: Path) -> List[Path]:
    return sorted(root.rglob("*.py"))


def _functions_calling_verify_wb_key(path: Path) -> List[str]:
    """返回该模块里「函数体内**真实调用** `verify_wb_key(...)`」的函数名。

    AST 而非文本：`verify_wb_key` 这个**定义**在 `database.py` 也有，纯文本搜索会把
    「定义」与「调用」混为一谈、也无法排除注释/docstring 里的字样。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) and inner.func.id == "verify_wb_key":
                names.append(node.name)
                break
    return names


def test_single_wb_key_auth_implementation():
    """全仓「调用 `verify_wb_key(` 的实现函数」必须**恰好一个**，且是 `require_wb_key`。"""
    hits: List[Tuple[str, str]] = []
    for path in _iter_py(_DELECTOR):
        rel = str(path.relative_to(_ROOT)).replace(os.sep, "/")
        hits.extend((rel, name) for name in _functions_calling_verify_wb_key(path))

    assert len(hits) == 1, f"verify_wb_key 的调用实现应全仓唯一（唯一真相 require_wb_key），实得 {hits}"
    rel, name = hits[0]
    assert name == "require_wb_key", f"唯一实现应是 require_wb_key，实得 {name}"
    assert rel.endswith("core/wb_auth.py"), f"唯一实现应住在 core/wb_auth.py，实得 {rel}"


def test_no_route_module_duplicates_the_403_raise():
    """路由层不得再各写一份「401/403 invalid X-WB-Key」——只允许 `core/wb_auth.py` 持有它。"""
    offenders: List[str] = []
    for path in _iter_py(_DELECTOR / "routes"):
        if path.name == "__init__.py":
            continue
        if "invalid X-WB-Key" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    assert not offenders, f"路由层仍各写鉴权（应只住 core/wb_auth.py）：{offenders}"


def _three_statuses(client: TestClient, headers: dict) -> Tuple[int, int, int]:
    """同一请求头在 sync / rtc / state 三端点的状态码。"""
    sync = client.post(
        "/api/wb/sync/store",
        json={"sdp": {"type": "offer", "sdp": "v=0\r\n"}, "role": "offer"},
        headers=headers,
    )
    rtc = client.post(
        "/api/wb/rtc/signal",
        json={"client": "A", "type": "offer", "payload": {"sdp": "v=0"}},
        headers=headers,
    )
    state = client.put("/api/wb/state", json={"payload": {}}, headers=headers)
    return sync.status_code, rtc.status_code, state.status_code


def test_same_headers_same_status_across_endpoints(client):
    """相同请求头在三端点得到同状态码：缺 / 错 key 一律 403（收敛不得改 HTTP 语义）。"""
    for headers in _BAD_HEADERS:
        statuses = _three_statuses(client, headers)
        assert statuses == (403, 403, 403), f"相同请求头在三端点状态码不一致：{headers} -> {statuses}"


def test_valid_key_accepted_on_all_three(client):
    """合法 key（本机端点取得）在三端点全部放行 —— 证明收敛没把鉴权改坏。"""
    key = client.get("/api/wb/state/key").json()["key"]
    statuses = _three_statuses(client, {"X-WB-Key": key})
    assert statuses == (200, 200, 200), f"合法 key 应三端点全 200：{statuses}"
