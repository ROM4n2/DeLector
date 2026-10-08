# -*- coding: utf-8 -*-
"""`GET /api/update/check` 端点契约（Task 3）。

红线 11：跨边界契约要**行为验证** —— 收尾用 TestClient 真调端点，而非只测内部函数。
本文件**绝不真联网**：所有出网都走注入的 fake fetcher（CI 不可靠且会打 GitHub 限速）。

核心不变式（失败绝不伪装成"已是最新"）：
- ``has_update is None`` 当且仅当 ``error_reason is not None``（双向）；
- 检查失败**绝不**返回 ``has_update: false``；
- ``current`` 来自 ``APP_VERSION``；``has_update`` 判定用 versionCode 语义。
"""

import ast
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import pytest
from fastapi.testclient import TestClient

from delector import server
from delector.core import database
from delector.core.version import APP_VERSION
from delector.routes import update

# 契约的 7 个键，逐字固定（前端与探针依赖）。
CONTRACT_KEYS = {
    "current",
    "latest",
    "has_update",
    "page_url",
    "checked_at",
    "cached",
    "error_reason",
}

RELEASES_TAG = "https://github.com/ROM4n2/DeLector/releases/tag/"

# TTL 边界（与模块内常量同口径）：成功 6h、失败 60s。
_SUCCESS_TTL = 6 * 3600
_FAIL_TTL = 60


def _bump(version: str) -> str:
    """把 patch 段 +1，得到一个 versionCode 严格更大的"有新版"目标。

    从 APP_VERSION 派生而非写死字面量：版本 bump 后这条测试依然表达"新版"语义，
    不会因为真相源前进而变成"同版"从而失去覆盖。
    """
    major, minor, patch = (int(part) for part in version.split("."))
    return f"{major}.{minor}.{patch + 1}"


class FakeFetcher:
    """记录调用次数，并按需返回固定 release 或抛出固定异常的假 fetcher。

    出网注入点，保证测试**零真实网络**。``calls`` 是"零出网"断言的计数钉。
    """

    def __init__(
        self,
        release: Optional[Dict[str, Any]] = None,
        error: Optional[Exception] = None,
    ) -> None:
        self.calls = 0
        self._release = release
        self._error = error

    def __call__(self, timeout: float) -> Dict[str, Any]:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return dict(self._release or {})


@pytest.fixture(autouse=True)
def _reset_cache() -> Any:
    """每个用例前后清空模块级 TTL 缓存，避免用例间串味。"""
    update._cache.clear()
    yield
    update._cache.clear()


@pytest.fixture
def client(tmp_path: Path) -> Any:
    """真 app + TestClient：env 切到 tmp_path throwaway 库，避免污染真实库。"""
    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH")}
    os.environ["DATABASE_PATH"] = str(tmp_path / "update.db")
    os.environ["PROGRESS_DB_PATH"] = str(tmp_path / "update_progress.db")
    database.init_db(os.environ["DATABASE_PATH"])
    yield TestClient(server.create_app(), client=("127.0.0.1", 54321))
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


# ==========================================================================
# 1. 版本判定：有新版 / 同版
# ==========================================================================
def test_has_update_true_when_newer_release() -> None:
    newer = _bump(APP_VERSION)
    fetcher = FakeFetcher(release={"tag_name": "v" + newer, "html_url": RELEASES_TAG + "v" + newer})

    result = update.check_for_update(fetcher=fetcher, now=1_000.0)

    assert set(result) == CONTRACT_KEYS
    assert result["current"] == APP_VERSION
    assert result["latest"] == newer  # 输出不带 v 前缀
    assert result["has_update"] is True
    assert result["page_url"] == RELEASES_TAG + "v" + newer
    assert result["error_reason"] is None
    assert result["cached"] is False
    assert result["checked_at"] == 1_000


def test_has_update_false_when_same_version() -> None:
    fetcher = FakeFetcher(release={"tag_name": "v" + APP_VERSION, "html_url": RELEASES_TAG + "v" + APP_VERSION})

    result = update.check_for_update(fetcher=fetcher, now=1_000.0)

    assert result["has_update"] is False
    assert result["error_reason"] is None
    assert result["latest"] == APP_VERSION


# ==========================================================================
# 2. 错误分类四类：timeout / rate_limited / not_found / network
# ==========================================================================
def test_timeout_yields_none_and_never_false() -> None:
    fetcher = FakeFetcher(error=update.UpdateCheckTimeout("boom"))

    result = update.check_for_update(fetcher=fetcher, now=1_000.0)

    assert result["has_update"] is None
    assert result["has_update"] is not False  # 失败绝不伪装成"已是最新"
    assert result["error_reason"] == "timeout"
    assert result["latest"] is None
    assert result["page_url"] is None


def test_rate_limited_reason() -> None:
    fetcher = FakeFetcher(error=update.UpdateCheckRateLimited("403"))

    result = update.check_for_update(fetcher=fetcher, now=1_000.0)

    assert result["has_update"] is None
    assert result["error_reason"] == "rate_limited"


@pytest.mark.parametrize(
    "release,error",
    [
        (None, update.UpdateCheckNotFound("404")),        # 404
        ({"tag_name": "not-a-version"}, None),            # 坏 tag（不可解析）
        ({"html_url": RELEASES_TAG}, None),               # tag_name 缺失
    ],
)
def test_not_found_reason(release: Optional[Dict[str, Any]], error: Optional[Exception]) -> None:
    fetcher = FakeFetcher(release=release, error=error)

    result = update.check_for_update(fetcher=fetcher, now=1_000.0)

    assert result["has_update"] is None
    assert result["error_reason"] == "not_found"


def test_network_reason_on_unexpected_error() -> None:
    fetcher = FakeFetcher(error=httpx.ConnectError("connection refused"))

    result = update.check_for_update(fetcher=fetcher, now=1_000.0)

    assert result["has_update"] is None
    assert result["error_reason"] == "network"


# ==========================================================================
# 3. 缓存：命中零出网 + 失败短 TTL / 成功长 TTL
# ==========================================================================
def test_cache_hit_serves_without_refetch() -> None:
    newer = _bump(APP_VERSION)
    fetcher = FakeFetcher(release={"tag_name": "v" + newer, "html_url": ""})

    first = update.check_for_update(fetcher=fetcher, now=5_000.0)
    second = update.check_for_update(fetcher=fetcher, now=5_000.0)

    assert first["cached"] is False
    assert second["cached"] is True
    assert fetcher.calls == 1  # 命中缓存 ⇒ 零出网
    assert second["latest"] == first["latest"]


def test_failed_check_cached_short_then_retries() -> None:
    fetcher = FakeFetcher(error=update.UpdateCheckTimeout("t"))

    update.check_for_update(fetcher=fetcher, now=0.0)
    update.check_for_update(fetcher=fetcher, now=_FAIL_TTL - 30)  # 30s 内仍命中缓存
    assert fetcher.calls == 1

    update.check_for_update(fetcher=fetcher, now=_FAIL_TTL + 1)  # 61s 后重试
    assert fetcher.calls == 2


def test_success_cached_six_hours_then_retries() -> None:
    fetcher = FakeFetcher(release={"tag_name": "v" + APP_VERSION, "html_url": ""})

    update.check_for_update(fetcher=fetcher, now=0.0)
    update.check_for_update(fetcher=fetcher, now=_SUCCESS_TTL - 1)  # 6h 内不重试
    assert fetcher.calls == 1

    update.check_for_update(fetcher=fetcher, now=_SUCCESS_TTL + 1)  # 6h+1s 后重试
    assert fetcher.calls == 2


# ==========================================================================
# 4. 跨边界行为验证：TestClient 真调端点
# ==========================================================================
def test_endpoint_returns_exact_contract_keys(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    newer = _bump(APP_VERSION)
    fetcher = FakeFetcher(release={"tag_name": "v" + newer, "html_url": RELEASES_TAG + "v" + newer})
    monkeypatch.setattr(update, "_fetch_latest_release", fetcher)

    resp = client.get("/api/update/check")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == CONTRACT_KEYS  # 恰好 7 个键
    assert body["current"] == APP_VERSION
    assert body["has_update"] is True
    assert isinstance(body["checked_at"], int)
    assert fetcher.calls == 1


def test_endpoint_failure_path_serializes_null_has_update(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """失败路径也必须过 HTTP 层：验证 JSON `null` 在端点反序列化回 Python None。

    锁死"失败绝不伪装成已是最新"到跨边界层面 —— `has_update` 必须是 `None`，
    既不是字符串 ``"null"`` 也不是 ``False``。
    """
    fetcher = FakeFetcher(error=update.UpdateCheckTimeout("boom"))
    monkeypatch.setattr(update, "_fetch_latest_release", fetcher)

    resp = client.get("/api/update/check")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == CONTRACT_KEYS  # 恰好 7 个键
    assert body["has_update"] is None  # 必须是 None，不是 "null"，也不是 False
    assert body["error_reason"] == "timeout"
    assert fetcher.calls == 1


def test_endpoint_cache_hit_keeps_contract(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """命中路径也必须过 HTTP 层：第二次请求经端点返回完整快照且零再出网。

    端点内部用 ``time.time()``；此处 monkeypatch 该时钟（不改生产签名），
    推进时间但不越过 TTL，验证 ``cached: True`` 与快照一致性。
    """
    newer = _bump(APP_VERSION)
    fetcher = FakeFetcher(release={"tag_name": "v" + newer, "html_url": RELEASES_TAG + "v" + newer})
    monkeypatch.setattr(update, "_fetch_latest_release", fetcher)

    clock = {"now": 1_000.0}
    monkeypatch.setattr(update.time, "time", lambda: clock["now"])

    first = client.get("/api/update/check").json()
    clock["now"] = 1_000.0 + _SUCCESS_TTL - 1  # 推进但仍在 TTL 内
    second = client.get("/api/update/check").json()

    assert set(second) == CONTRACT_KEYS  # 命中快照契约仍完整
    assert first["cached"] is False
    assert second["cached"] is True
    assert fetcher.calls == 1  # 命中 ⇒ 零再出网
    assert second["latest"] == first["latest"]


# ==========================================================================
# 5. 源码纪律：无版本号字面量 / 统一 httpx / import 期不联网
# ==========================================================================
def test_source_has_no_version_literal_and_unifies_on_httpx() -> None:
    src = Path(update.__file__).read_text(encoding="utf-8")

    assert not re.search(r"\d+\.\d+\.\d+", src), "update.py 不得出现版本号字面量（不变式 3）"
    banned = re.search(r"^\s*(?:import|from)\s+(requests|aiohttp|urllib\.request)\b", src, re.M)
    assert banned is None, f"出网必须统一 httpx，禁用 {banned.group(1) if banned else ''}"


def test_import_does_not_trigger_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """红线 9：import 期不得联网 —— 顶层若调 _fetch_latest_release 会在此处炸。"""

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("import 期不得联网")

    monkeypatch.setattr(httpx, "get", _boom)
    import importlib

    importlib.reload(update)  # 触发模块顶层重新执行；若联网即失败
    assert hasattr(update, "check_for_update")


# ==========================================================================
# 6. 不变式 1 穷举式**双向**守卫：has_update is None ⇔ error_reason is not None
# ==========================================================================
# 为什么穷举：只看某一类失败或某一成功态，"iff" 的一个方向可能恒真而掩盖另一方向的错。
# 四条失败态各注入对应异常（穷尽四类 error_reason），加两种成功态（有新版 / 同版）——
# 六组一起，才逼出 `has_update is None` 与 `error_reason is not None` 的**等价**，
# 而非"失败时恰好都为真"。
_INVARIANT1_PARAMS: list[Any] = [
    pytest.param(None, httpx.ConnectError("boom"), True, id="fail-network"),
    pytest.param(None, update.UpdateCheckTimeout("boom"), True, id="fail-timeout"),
    pytest.param(None, update.UpdateCheckRateLimited("boom"), True, id="fail-rate-limited"),
    pytest.param(None, update.UpdateCheckNotFound("boom"), True, id="fail-not-found"),
    pytest.param({"tag_name": "v" + _bump(APP_VERSION), "html_url": ""}, None, False, id="ok-newer"),
    pytest.param({"tag_name": "v" + APP_VERSION, "html_url": ""}, None, False, id="ok-same"),
]

# 六组用例的**身份**集合（id），而非基数。理由见下方守卫的 docstring：
# 只钉长度的守卫无法阻止"拿一类失败换另一类"的静默覆盖丢失。
_INVARIANT1_PARAM_IDS = frozenset(
    {"fail-network", "fail-timeout", "fail-rate-limited", "fail-not-found", "ok-newer", "ok-same"}
)


def test_invariant1_paramset_is_not_hollow() -> None:
    """守卫自身不空转：参数集被删到只剩 1 个用例，上面那条仍会绿。故钉死身份。

    为什么钉 id 集合而不是长度：长度相等只保证"个数对"，允许"拿一类失败换另一类"——
    把 fail-rate-limited 换成第二个 fail-timeout，长度仍是 6，但四类 error_reason
    中已有一类静默失去覆盖，而只钉长度的守卫照样绿。钉 id 集合才逐个锁住覆盖。
    """
    assert {p.id for p in _INVARIANT1_PARAMS} == _INVARIANT1_PARAM_IDS


@pytest.mark.parametrize("release,error,is_failure", _INVARIANT1_PARAMS)
def test_invariant1_iff_exhaustive_bidirectional(
    release: Optional[Dict[str, Any]], error: Optional[Exception], is_failure: bool
) -> None:
    """不变式 1 的穷举双向断言：`(has_update is None) == (error_reason is not None)`。

    单个等价表达式同时覆盖两个方向：失败态必 None（左真右真），成功态必非 None
    且 error_reason 为 None（左假右假）。任何一侧漂移都会让等号两侧不等而红。
    """
    fetcher = FakeFetcher(release=release, error=error)

    body = update.check_for_update(fetcher=fetcher, now=1_000.0)

    assert (body["has_update"] is None) == (body["error_reason"] is not None)
    if is_failure:
        # "没查到"绝不伪装成"已是最新"：has_update 必须是 None，而非 False。
        assert body["has_update"] is not False
    else:
        assert body["error_reason"] is None


def test_invariant1_holds_for_cached_failure() -> None:
    """失败结果被缓存后二次调用，iff 仍成立（缓存不得把 None 洗成 False）。"""
    fetcher = FakeFetcher(error=update.UpdateCheckTimeout("boom"))

    update.check_for_update(fetcher=fetcher, now=0.0)
    second = update.check_for_update(fetcher=fetcher, now=_FAIL_TTL - 30)  # 命中失败缓存

    assert second["cached"] is True
    assert (second["has_update"] is None) == (second["error_reason"] is not None)
    assert second["has_update"] is None
    assert second["has_update"] is not False


# ==========================================================================
# 7. 结构级"不写 DB"守卫（用结构证，不用行为碰运气）
# ==========================================================================
# DB 相关模块：导入任一即意味着"可能有写库途径"，用结构 impossible 直接拒掉。
# 本守卫**实际**封堵的范围（勿读成"全部 DB 入口"）：
#   - import 目标为 `sqlite3` / `sqlite3.dbapi2` / `aiosqlite`；
#   - import 目标以 `delector.core.database` 为前缀；
#   - execute/executemany/executescript 上首词为 INSERT/UPDATE/DELETE/REPLACE 的**字面量** SQL。
# **不在**覆盖范围内（据实列举）：
#   - 经 re-export 的其他模块间接触碰 DB（如 services/search.py、core/vocab_pool.py 各自 `import sqlite3`）；
#   - `importlib.import_module("sqlite3")` 这类**动态导入**（AST 上不是 Import/ImportFrom 节点）；
#   - f-string（ast.JoinedStr）拼出来的 SQL（首参不是 ast.Constant，扫描器直接跳过）。
# 为何仍可接受：要经上述路径**真的**写库，仍需先拿到 `conn`，而 `conn` 的获取途径已被
# 上面的 import 封堵——这是**刻意的范围收敛**，不是疏漏。
_BANNED_DB_IMPORT_MODULES = frozenset({"sqlite3", "sqlite3.dbapi2", "aiosqlite"})
_BANNED_DB_IMPORT_PREFIXES = ("delector.core.database",)

_SQL_WRITE_VERBS = frozenset({"INSERT", "UPDATE", "DELETE", "REPLACE"})
_EXECUTE_METHODS = frozenset({"execute", "executemany", "executescript"})


def _imported_module_names(tree: ast.AST) -> set[str]:
    """树里所有 import 的目标模块全名（含 `from m import n` 的 `m.n`）。"""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            for alias in node.names:
                names.add(f"{node.module}.{alias.name}")
    return names


def _sql_write_verbs_in_tree(tree: ast.AST) -> list[str]:
    """收集树里所有 execute 系调用中首词为 SQL 写动词者（update.py 无 execute 即空）。"""
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in _EXECUTE_METHODS:
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        sql = node.args[0].value
        if not isinstance(sql, str):
            continue
        words = sql.strip().split()
        if words and words[0].upper() in _SQL_WRITE_VERBS:
            found.append(words[0].upper())
    return found


def test_structural_db_scanner_is_not_hollow() -> None:
    """反向自证：DB 导入扫描器 MUST 真能看见违禁 import，否则上面那条恒绿。"""
    probe = ast.parse("import sqlite3\nfrom delector.core.database import db_conn\n")

    names = _imported_module_names(probe)

    assert "sqlite3" in names
    assert "delector.core.database" in names


def test_structural_guard_update_route_cannot_write_db() -> None:
    """结构证：`update.py` 在源码结构上**不可能**写库。

    为什么结构证强于行为证：行为证只能证明"这一次运行没写"（可能只是路径未覆盖，
    或运气好），而结构证证明"这段代码**没有任何途径**触碰 DB"—— 没有 sqlite3、
    没有 database 模块、没有 execute 调用，就不存在"某条分支恰好写了库"的可能。
    前者是必要条件（可能失效），后者是充分结构（不可能失效）。

    范围收敛（与上方 `_BANNED_DB_IMPORT_*` 注释同口径）：本守卫封堵的是上述 import 形态
    与**字面量**写 SQL；对经 re-export 的其他模块（如 services/search.py、core/vocab_pool.py）
    间接触碰 DB、动态导入、以及 f-string 拼出的 SQL **不在**覆盖范围内。这属**刻意的范围
    收敛**——要经这些路径真的写库仍需先拿到 `conn`，而其获取途径已被 import 封堵。
    """
    tree = ast.parse(Path(update.__file__).read_text(encoding="utf-8"), filename=update.__file__)

    imported = _imported_module_names(tree)
    offending = sorted(
        name
        for name in imported
        if name in _BANNED_DB_IMPORT_MODULES
        or any(name == prefix or name.startswith(prefix + ".") for prefix in _BANNED_DB_IMPORT_PREFIXES)
    )
    assert not offending, f"update.py 导入了 DB 模块 {offending}，破坏'结构上不能写库'"

    verbs = _sql_write_verbs_in_tree(tree)
    assert not verbs, f"update.py 出现 SQL 写动词 {verbs}，破坏'只读端点'约定"


def _code_identifiers(tree: ast.AST) -> set[str]:
    """树里以**代码标识符**出现的名字（Name/Attribute/import），文档字符串不算。

    为什么不用 `"_require_localhost" not in src` 的子串判断：本端点的 docstring 恰恰
    要**点名**这个闸来解释"为什么刻意不挂"，子串断言会误伤这段说明性文字。只有识别
    Name/Attribute/import 才能区分"真的挂/调了闸"与"仅文档提及闸"。
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.name)
            if node.asname:
                names.add(node.asname)
    return names


def test_structural_guard_update_route_has_no_localhost_gate() -> None:
    """ADR-0017 §4.3 的**显式决定**：update 端点只读、不挂 `_require_localhost`。

    LAN 浏览器版用户同样需要更新可见性，本端点只读、不写库，故刻意**不**加本机闸。
    此条与 `tests/test_localhost_guard.py` 的 20 条 allowlist 零改动互为印证：若有人
    在 update.py 补挂闸，那条 allowlist 会多出第 21 项，两处同时红，交叉锁死同一决定。
    """
    tree = ast.parse(Path(update.__file__).read_text(encoding="utf-8"), filename=update.__file__)

    used = _code_identifiers(tree)

    assert "_require_localhost" not in used, "update.py 以代码方式挂/调了本机闸（ADR-0017 §4.3 显式决定）"
