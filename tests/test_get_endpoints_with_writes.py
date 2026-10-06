"""GET 端点写操作守卫（登记项 Fog 2 真 bug 的防回归测试）。

背景：`GET /api/articles/{article_id}` 里的惰性迁移分支曾是「每次 GET 都重跑
spaCy 并 UPDATE articles」——因为写入端（processor 两条返回路径）返回
`"3.5.0"`，而判据端（routes/main.py）硬编码 `"3.4.0"`，两份字面量漂移导致
判据恒真。版本字符串看着一致、行为全错，所以纯断言版本号的测试永远抓不到。
这里一律用**行为证据**：数真正执行到的 SQL 首词。

守卫 A：带写操作的 GET 端点白名单（防将来有人给别的 GET 加写而不被察觉）。
守卫 B：已迁移文章二次 GET 不再触发 UPDATE（B1/B2/B3）。
"""

import ast
import contextlib
import gc
import json
import os
import sqlite3
import sys
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from db_cleanup import remove_db_files  # noqa: E402

from delector import routes, server  # noqa: E402
from delector.core.database import db_conn as real_db_conn  # noqa: E402
from delector.core.database import init_db  # noqa: E402
from delector.nlp_engine import processor  # noqa: E402
from delector.nlp_engine.processor import _process_german_text_pure_python  # noqa: E402

DB = "test_get_writes_delector.db"
PROGRESS = "test_get_writes_progress.db"

RAW_TEXT = "Der Hund läuft schnell durch den Park."


def _written_version() -> str:
    """写入端实际会落的 version。

    优先取导出的常量（单一真相源）；常量尚未导出时，退回纯 Python 返回路径的
    实测值——而不是在本文件里再写一份字面量（那正是本 bug 的成因）。
    """
    exported = getattr(processor, "PROCESSED_JSON_VERSION", None)
    if isinstance(exported, str):
        return exported
    return str(_process_german_text_pure_python(RAW_TEXT)["version"])


# --------------------------------------------------------------------------
# 计数手段：包装 db_conn + 包一层 sqlite3.Connection，记录每次 execute 的 SQL 首词
# --------------------------------------------------------------------------
class TracingConn:
    """透明代理 sqlite3.Connection，只在 execute 上留痕。"""

    def __init__(self, conn: sqlite3.Connection, spy: "SqlSpy") -> None:
        self._conn = conn
        self._spy = spy

    def execute(self, sql: str, *args: Any, **kwargs: Any) -> sqlite3.Cursor:
        first = sql.strip().split()[0].upper() if sql.strip() else ""
        self._spy.record(first)
        return self._conn.execute(sql, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


class SqlSpy:
    """收集真正执行过的 SQL 首词，并提供按动词计数。"""

    def __init__(self) -> None:
        self.statements: List[str] = []
        self.counts: Dict[str, int] = {}

    def record(self, verb: str) -> None:
        self.statements.append(verb)
        self.counts[verb] = self.counts.get(verb, 0) + 1

    def of(self, verb: str) -> int:
        return self.counts.get(verb, 0)

    def reset(self) -> None:
        self.statements.clear()
        self.counts.clear()


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Iterator[SqlSpy]:
    recorder = SqlSpy()

    @contextlib.contextmanager
    def traced_db_conn(db_path: Any = None) -> Iterator[TracingConn]:
        with real_db_conn(db_path) as conn:
            yield TracingConn(conn, recorder)

    # main.py 是 `from ... import db_conn`，故须打在 routes.main 的命名空间上
    monkeypatch.setattr(routes.main, "db_conn", traced_db_conn)
    yield recorder


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH")}
    os.environ["DATABASE_PATH"] = DB
    os.environ["PROGRESS_DB_PATH"] = PROGRESS
    gc.collect()
    remove_db_files(DB, PROGRESS)
    init_db(DB)
    yield TestClient(server.create_app(), client=("127.0.0.1", 54321))
    gc.collect()
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _insert_article(processed_json: str, raw_text: str = RAW_TEXT) -> int:
    with real_db_conn(DB) as conn:
        cur = conn.execute(
            "INSERT INTO articles (title, raw_text, processed_json) VALUES (?, ?, ?)",
            ("Hund", raw_text, processed_json),
        )
        return int(cur.lastrowid or 0)


def _writer_payload() -> Dict[str, Any]:
    """让真实的写入端（process_german_text）产出一份 processed_json。

    刻意不用常量拼一个假 payload：已迁移数据本来就是上一轮 GET 调写入端落下的，
    用真实写入端产出才忠实。若某条返回路径的 version 漂移（与常量脱钩），
    用这个种子就能被 B1 的 UPDATE 计数抓住 —— 用常量拼种子则抓不到。
    """
    payload = processor.process_german_text(RAW_TEXT)
    assert isinstance(payload, dict) and "stats" in payload
    return payload


def _migrated_payload() -> Dict[str, Any]:
    """构造一份「已迁移」的 processed_json：当前写入版本 + stats。"""
    return {
        "version": _written_version(),
        "sentence_count": 1,
        "sentences": [{"id": 0, "text": RAW_TEXT, "tokens": [], "topology": {}, "clause_tree": {}}],
        "stats": {"word_count": 6, "total_words": 6},
    }


# ==========================================================================
# 守卫 B：惰性迁移语义（行为测试，数真实执行的 SQL）
# ==========================================================================
def test_b1_migrated_article_get_does_not_update(client: TestClient, spy: SqlSpy) -> None:
    """B1 已迁移文章 ⇒ GET 不执行 UPDATE，且返回数据完整。"""
    aid = _insert_article(json.dumps(_migrated_payload(), ensure_ascii=False))
    spy.reset()

    resp = client.get(f"/api/articles/{aid}")

    assert resp.status_code == 200
    assert spy.of("UPDATE") == 0, f"B1 违反：已迁移文章仍执行了 UPDATE，SQL={spy.statements}"
    body = resp.json()
    assert body["version"] == _written_version()
    assert body["stats"]["word_count"] == 6
    assert body["raw_text"] == RAW_TEXT


def test_b1b_article_seeded_by_real_writer_does_not_update(
    client: TestClient, spy: SqlSpy
) -> None:
    """B1b 种子来自【真实写入端】的已迁移文章 ⇒ GET 同样零 UPDATE。

    B1 用常量拼种子，B1b 用 `process_german_text` 的真实产出。两者合起来才盖全：
    若某条返回路径的 version 与常量脱钩（本 bug 的原始形态），B1b 会在
    「存量数据其实是上一轮写入端落的」这一真实场景下抓到多余的 UPDATE，
    而 B1 抓不到。
    """
    aid = _insert_article(json.dumps(_writer_payload(), ensure_ascii=False))
    spy.reset()

    resp = client.get(f"/api/articles/{aid}")

    assert resp.status_code == 200
    assert spy.of("UPDATE") == 0, (
        f"B1b 违反：写入端落下的数据再次 GET 仍触发 UPDATE，SQL={spy.statements}"
    )


def test_b3_second_get_after_migration_does_not_update(client: TestClient, spy: SqlSpy) -> None:
    """B3 修完后再次 GET 同一篇文章 ⇒ 仍不执行 UPDATE。

    证明 B1 不是「这次恰好没写」蒙对的：先让老数据触发一次迁移写回，
    再 GET 第二次，迁移结果已是当前版本，此时必须零写。
    """
    aid = _insert_article("{}")  # 老数据：首次 GET 会迁移
    spy.reset()

    first = client.get(f"/api/articles/{aid}")
    assert first.status_code == 200
    assert first.json()["version"] == _written_version()

    spy.reset()
    second = client.get(f"/api/articles/{aid}")

    assert second.status_code == 200
    assert spy.of("UPDATE") == 0, f"B3 违反：二次 GET 仍执行了 UPDATE，SQL={spy.statements}"
    assert second.json()["version"] == _written_version()


def test_b2_legacy_data_get_migrates_exactly_once(client: TestClient, spy: SqlSpy) -> None:
    """B2 老数据 ⇒ GET 执行【恰好一次】UPDATE，且写回值带当前版本常量。

    参数化覆盖三种老数据形态：空 `{}`、缺 `stats`、版本是旧值。
    迁移语义 MUST 保留 —— 修 bug 不是「把迁移删了」。
    """
    legacy_payloads: List[Tuple[str, str]] = [
        ("empty-json", "{}"),
        (
            "missing-stats",
            json.dumps({"version": _written_version(), "sentence_count": 1}),
        ),
        (
            "stale-version",
            json.dumps({"version": "0.0.1-ancient", "stats": {"word_count": 6}}),
        ),
    ]
    for case_id, raw_pj in legacy_payloads:
        aid = _insert_article(raw_pj)
        spy.reset()

        resp = client.get(f"/api/articles/{aid}")

        assert resp.status_code == 200
        assert spy.of("UPDATE") == 1, (
            f"B2 违反（case={case_id}）：期望恰好 1 次 UPDATE，"
            f"实际 {spy.of('UPDATE')} 次，SQL={spy.statements}"
        )
        # 写回的值必须带当前真相源版本
        with real_db_conn(DB) as conn:
            stored = conn.execute(
                "SELECT processed_json FROM articles WHERE id = ?", (aid,)
            ).fetchone()
        assert stored is not None
        written = json.loads(stored["processed_json"])
        assert written["version"] == _written_version()
        assert "stats" in written


# ==========================================================================
# 守卫 A：带写操作的 GET 端点白名单
# ==========================================================================
WRITE_VERBS = frozenset({"INSERT", "UPDATE", "DELETE", "REPLACE"})

# 唯一允许「GET 里带写」的端点：惰性迁移兼容（老 processed_json 首次 GET 时回写）。
# 这个写是有意为之的，所以钉死它才有意义 —— 不能用「GET 不该有写」的粗判据，
# 那样会把这条兼容路径逼成删掉迁移分支。
EXPECTED_WRITE_GET_ENDPOINTS = frozenset({"GET /api/articles/{article_id}"})


def _decorator_path_and_is_get(decorator: ast.expr) -> Optional[Tuple[str, bool]]:
    """取 @router.get("/x") / @router.api_route("/x", methods=[...]) 的路径与是否 GET。

    非 router 装饰器（Depends 等）返回 None。
    """
    if not isinstance(decorator, ast.Call):
        return None
    func = decorator.func
    if not isinstance(func, ast.Attribute):
        return None
    attr = func.attr

    path = ""
    if decorator.args and isinstance(decorator.args[0], ast.Constant):
        path = str(decorator.args[0].value)
    else:
        return None  # 非字面量路径，交给人工判断，不静默漏掉

    if attr == "get":
        return path, True
    if attr == "api_route":
        for kw in decorator.keywords:
            if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                verbs = {e.value.upper() for e in kw.value.elts if isinstance(e, ast.Constant)}
                return path, "GET" in verbs
    return None


def _write_verbs_in(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> List[str]:
    """函数体内所有 execute 类调用中，首个 SQL 词属于写动词的那些。

    只认首参是字符串字面量的调用（SQL 拼接的动态调用无法静态判定，
    宁可漏报也不误报 —— 漏报会在人 review 时补上）。
    """
    found: List[str] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"execute", "executemany", "executescript"}:
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        sql = node.args[0].value
        if not isinstance(sql, str):
            continue
        words = sql.strip().split()
        if not words:
            continue
        verb = words[0].upper()
        if verb in WRITE_VERBS:
            found.append(verb)
    return found


def _collect_get_endpoints_with_writes() -> Dict[str, List[str]]:
    routes_dir = os.path.join(ROOT, "delector", "routes")
    result: Dict[str, List[str]] = {}
    for filename in sorted(os.listdir(routes_dir)):
        if not filename.endswith(".py"):
            continue
        path = os.path.join(routes_dir, filename)
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                parsed = _decorator_path_and_is_get(decorator)
                if parsed is None:
                    continue
                path_str, is_get = parsed
                if not is_get:
                    continue
                verbs = _write_verbs_in(node)
                if verbs:
                    result[f"GET {path_str}"] = verbs
    return result


def test_guard_a_get_endpoints_with_writes_whitelist() -> None:
    """守卫 A：带写操作的 GET 端点集合 MUST 恰好等于已知的惰性迁移端点。"""
    found = _collect_get_endpoints_with_writes()

    assert set(found) == set(EXPECTED_WRITE_GET_ENDPOINTS), (
        "带写操作的 GET 端点集合变了。新增意味着 GET 出现未预期的写（副作用/性能/一致性）；"
        "移除意味着惰性迁移端点不再回写。"
    )
    assert found["GET /api/articles/{article_id}"], "白名单端点应当确实含有写操作"


def test_guard_a_scanner_can_actually_see_writes() -> None:
    """反向验证：AST 扫描器 MUST 真能看见写操作，否则上面那条是恒绿。

    构造一个带写 GET 的假源码片段喂给扫描逻辑，断言它被判为「有写」。
    """
    src = '''
@router.get("/api/probe")
def probe(conn: object) -> dict:
    conn.execute("SELECT 1")
    conn.execute("UPDATE articles SET raw_text = ? WHERE id = ?", ("x", 1))
    return {}
'''
    tree = ast.parse(src)
    funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    assert funcs, "源码片段解析失败"
    assert _write_verbs_in(funcs[0]) == ["UPDATE"]

    # 只读的 GET 函数 MUST 不被判为有写（证明扫描器不是无脑全报）
    ro_src = '''
@router.get("/api/probe2")
def probe2(conn: object) -> dict:
    row = conn.execute("SELECT * FROM articles WHERE id = ?", (1,)).fetchone()
    return dict(row)
'''
    ro_tree = ast.parse(ro_src)
    ro_funcs = [n for n in ast.walk(ro_tree) if isinstance(n, ast.FunctionDef)]
    assert _write_verbs_in(ro_funcs[0]) == []


def test_guards_use_single_source_version_constant() -> None:
    """单一真相源：`routes/main.py` MUST NOT 再持有 processed_json 版本字面量。"""
    main_src = open(
        os.path.join(ROOT, "delector", "routes", "main.py"), encoding="utf-8"
    ).read()
    tree = ast.parse(main_src)
    literals = {
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value == "3.4.0"
    }
    assert not literals, "main.py 又出现了写死的 processed_json 版本字面量（判据会再漂移）"

    # 判据 MUST 引用常量
    assert "PROCESSED_JSON_VERSION" in main_src
    exported = processor.PROCESSED_JSON_VERSION
    assert isinstance(exported, str) and exported

    # 两条返回路径 MUST 都等于该常量（含无 spaCy 的回退路径）
    assert _process_german_text_pure_python(RAW_TEXT)["version"] == exported
    if processor.nlp is not None:
        assert processor.process_german_text(RAW_TEXT)["version"] == exported