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
import atexit
import contextlib
import gc
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from db_cleanup import (  # noqa: E402
    describe_root_db_diff,
    iter_root_db_names,
    remove_db_files,
    root_db_snapshot,
)

from delector import routes, server  # noqa: E402
from delector.core.database import db_conn as real_db_conn  # noqa: E402
from delector.core.database import init_db  # noqa: E402
from delector.nlp_engine import processor  # noqa: E402
from delector.nlp_engine.processor import _process_german_text_pure_python  # noqa: E402

# 库路径 MUST 是**绝对路径**（审计 P1-1 治因）：裸相对文件名由 sqlite 按进程 CWD 解析，
# 「从仓库根跑 pytest」就把库写进仓库根。这里用**显式临时目录**（`tempfile.mkdtemp`：
# 模块级常量在夹具里用，夹具的 `tmp_path_factory` 不能喂给模块级常量），
# 目录由 atexit 尽力清理。
_DB_TMP_DIR = tempfile.mkdtemp(prefix="delector_get_writes_db_")
atexit.register(shutil.rmtree, _DB_TMP_DIR, ignore_errors=True)
DB = os.path.join(_DB_TMP_DIR, "test_get_writes_delector.db")
PROGRESS = os.path.join(_DB_TMP_DIR, "test_get_writes_progress.db")

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

    # articles.py 是 `from ... import db_conn`，故须打在 routes.articles 的命名空间上（C5 搬迁）
    monkeypatch.setattr(routes.articles, "db_conn", traced_db_conn)
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
# 守卫 C：本模块的库落点（治因 —— 裸相对文件名 ⇒ 仓库根）
# ==========================================================================
# 病因（2026-10-16 审计 P1-1）：本模块曾把 `DB` / `PROGRESS` 写成裸文件名
# （`test_get_writes_delector.db`）。裸名由 sqlite **按进程 CWD** 解析 ⇒ 「从仓库根跑
# pytest」就把库写进仓库根。后果不只是脏：`tests/conftest.py` 的会话守卫当时只比
# `delector.db` / `progress.db` 两种名字（`db_cleanup.ROOT_DB_NAMES`），`test_*.db`
# 完全在视野外，而 `*.db` 被 `.gitignore` 挡住 ⇒ 泄漏可无限期无人发现。
#
# 修法（不是症状）：路径改为**显式临时目录的绝对路径** —— 绝对路径与 CWD 无关，
# 从任何目录跑都落在 tmp，仓库根既不新增也不被改写。
#
# 为什么本文件要子进程取证：`from delector import server` 是**模块级 import**，
# 进程内任何快照都是「泄漏之后」的状态；只有新起一个子进程、`cwd=仓库根`、并清掉
# 库 env（模拟「开发者清空 env 后从仓库根跑」），才能从零观察落点。
# ==========================================================================
# 批次 = **整个模块**（不是单条）。为什么整模块：库落点有两个入口，
#   ① 模块级 `import ... server`（收集期就 `init_db()`，用根 `conftest.py` 的默认库名）；
#   ② 各用例的 `client` 夹具（钉本模块的 `DB` / `PROGRESS`）。
# 只跑单条只盖住 ②，① 会漏 —— 而 ① 正是「默认值是不是绝对路径」的唯一判据。
BATCH_TARGET = "tests/test_get_endpoints_with_writes.py"

# 递归哨兵（F1）：子进程里跑的是**整个模块**，其中包含守着本行为的那两条守卫
# ⇒ 不拦截就是「子进程再开子进程」的无界递归（探针实证：每 2~3 秒生成下一代，
# 外层 600s timeout 只杀直接子进程，管不了自我续命的进程链）。
# 两道防线各修一条路（互为冗余）：
#   防线一 env 令牌：父进程把**自己的 PID** 写进子进程 env（`_run_batch_in_subprocess`），
#     `batch_run` 夹具只跳过「令牌 == 本进程 getppid()」的**真子进程**；令牌存在但不匹配
#     ⇒ fail-loud，绝不静默 skip —— 否则外部残留的 `DELECTOR_BATCH_CHILD` 会让两条守卫
#     **永远 skip**（安全的假绿，但哨兵已被拆掉）。真子进程的 getppid() 就是父 pytest 的
#     pid（本机 Windows 实测 token_match=True；父进程在 subprocess.run 期间存活 ⇒ ppid
#     语义稳定），故真子进程不会被漏过、递归仍被拦住。
#   防线二 `-k` 排除：子进程命令行点名排除两条守卫（防 env 被外部清掉/改写）。
BATCH_CHILD_ENV = "DELECTOR_BATCH_CHILD"
BATCH_GUARD_SELECTOR = "not repo_root_gains_no_db_files and not repo_root_unchanged_by_the_batch"


def _run_batch_in_subprocess(target: str) -> "subprocess.CompletedProcess[str]":
    """在**仓库根**为 CWD 的子进程里跑一批用例，并清空库 env（不继承父进程的绝对路径）。

    清 env 是有意的：这正是「开发者本地从仓库根跑 pytest」的现实环境，
    也是 `conftest.py` 默认值唯一会被用到的场景 —— 守卫要判的就是它。

    递归防护（两道防线，见常量的注释）：`-k` 排除两条守卫 + 给子进程打
    `BATCH_CHILD_ENV` **令牌**（令牌 = 本进程 PID；`batch_run` 夹具只对
    「令牌 == getppid()」的真子进程 skip，其它情况 fail-loud）。子进程正常
    8s 上下（实测），`timeout=60` 只兜底「子进程卡死」这类异常 —— 递归已由
    两道防线阻断，timeout 不承担拦截递归的职责：靠 timeout 拦递归已证明
    不可行，它只杀直接子进程，孙进程链会自我续命（探针实证：9s 内 4 代）。
    """
    env = dict(os.environ)
    env.pop("DATABASE_PATH", None)
    env.pop("PROGRESS_DB_PATH", None)
    env["PYTHONIOENCODING"] = "utf-8"
    env[BATCH_CHILD_ENV] = str(os.getpid())
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            target,
            "-q",
            "-p",
            "no:cacheprovider",
            "-k",
            BATCH_GUARD_SELECTOR,
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )


_DbStat = Dict[str, Tuple[float, int]]


def _root_db_stat_fingerprint(root: str) -> _DbStat:
    """仓库根库文件「指纹」：名字 → (mtime, 字节数)（含 `-wal` / `-shm`）。

    为什么不能只用 `root_db_snapshot`（它只记字节数）：落点错时，库被
    `remove_db_files` 删掉再 `init_db()` 建回来，**重建后字节数可以逐字节相同**
    （schema 幂等）—— 只看字节数的快照会漏判。mtime 分辨得出来，且"库被动过"
    正是要禁的不变量。

    展开口径 MUST 与 `root_db_snapshot` 同源：复用 `db_cleanup.iter_root_db_names`
    （`ROOT_DB_NAMES` 的通配项如 `test_*.db` 也走 glob 展开）。曾按 `ROOT_DB_NAMES`
    **字面**拼路径 ⇒ `test_*.db` 的 `isfile` 恒 False ⇒ 对 `test_*.db` 的原地改写
    失明（与 `root_db_snapshot` 口径不一致）。不许自造扫描口径。
    """
    fingerprint: _DbStat = {}
    for _pattern, name in iter_root_db_names(root):
        for suffix in ("", "-wal", "-shm"):
            path = os.path.join(root, f"{name}{suffix}")
            if os.path.isfile(path):
                stat = os.stat(path)
                fingerprint[f"{name}{suffix}"] = (stat.st_mtime, stat.st_size)
    return fingerprint


def _describe_fingerprint_diff(before: _DbStat, after: _DbStat) -> str:
    """指纹差异说人话（新出现 / 被改动 / 消失；被改动带上 mtime 与字节数）。"""
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(name for name in set(after) & set(before) if after[name] != before[name])
    parts = []
    if added:
        parts.append(f"新出现：{', '.join(added)}")
    if changed:
        parts.append(
            "被改动：" + ", ".join(f"{name}(mtime/size {before[name]} → {after[name]})" for name in changed)
        )
    if removed:
        parts.append(f"消失：{', '.join(removed)}")
    return "；".join(parts) if parts else "无差异"


@pytest.fixture(scope="module")
def batch_run() -> "Dict[str, Any]":
    """跑一次那批用例，返回 `{"before": 快照, "after": 快照, "before_fp": 指纹, ...}`。

    两个守卫共用同一次子进程调用（module 作用域）：子进程很贵，且两条判据
    读的必须是**同一次运行**的前后快照/指纹，否则第二条可能把第一条的副作用算进来。

    递归哨兵（F1）：本夹具会 spawn 子进程，而子进程跑的是**整个模块**（含本夹具）
    ⇒ 子进程里若还进这里就是无界递归。`_run_batch_in_subprocess` 会把**父进程 PID**
    作为令牌写进子进程 env；只有令牌 == 本进程 `os.getppid()`（真子进程）才 skip。
    令牌存在但不匹配（外部残留污染）⇒ `pytest.fail` fail-loud：静默 skip 会让两条
    守卫可被环境整体拆除（安全的假绿，仍是洞）。必须在任何 spawn / 快照动作**之前**
    检查。（防线二是子进程命令行的 `-k` 排除，两道都在 `_run_batch_in_subprocess`
    附近有注释。）
    """
    marker = os.environ.get(BATCH_CHILD_ENV)
    if marker is not None:
        if marker == str(os.getppid()):
            pytest.skip("嵌套批次子进程：守卫自身不再递归（由 _run_batch_in_subprocess 以父 PID 打令牌）")
        pytest.fail(
            f"检测到外部残留的 {BATCH_CHILD_ENV}={marker!r}（本进程父 PID 为 {os.getppid()}）——"
            "它不是本模块递归防护打的令牌，却会让两条守卫静默 skip（哨兵被拆的假绿）。"
            f"请 unset {BATCH_CHILD_ENV} 后重跑。"
        )
    before = root_db_snapshot(ROOT)
    before_fp = _root_db_stat_fingerprint(ROOT)
    proc = _run_batch_in_subprocess(BATCH_TARGET)
    after = root_db_snapshot(ROOT)
    after_fp = _root_db_stat_fingerprint(ROOT)
    assert proc.returncode == 0, (
        f"子进程跑 {BATCH_TARGET} 失败（退出码 {proc.returncode}）——\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    # 子进程确实跑到了用例：0 collected / 0 passed 会让下面两条守卫变成空转。
    assert "passed" in proc.stdout, f"子进程没真正跑到用例：\n{proc.stdout}\n{proc.stderr}"
    return {"before": before, "after": after, "before_fp": before_fp, "after_fp": after_fp}


def test_guard_c_repo_root_gains_no_db_files(batch_run: "Dict[str, Any]") -> None:
    """跑完那批用例 ⇒ 仓库根**不新增任何** `*.db`（`test_*.db` 也在内）。

    取证口径：`root_db_snapshot` / `describe_root_db_diff`（测试侧数据库文件关注的
    **既有唯一实现**，勿另造一套）在子进程前后的差值 —— 不比对「根目录必须空」
    （本机可能先就有别的库 / 便携模式本来就合法）。

    ⚠️ 耗时登记：本用例经 module 级 `batch_run` 夹具 spawn 一个完整 pytest 子进程
    （实测 ~8-15s，两条守卫共用同一次调用）—— **超计划 Global 的「单用例 <5s」预算**，
    为知情取舍：子进程取证是「模块级 import 落点」的唯一判据（进程内快照永远在泄漏
    之后，见守卫 C 文件头），无法压进 5s。
    """
    before = batch_run["before"]
    after = batch_run["after"]
    assert set(after) - set(before) == set(), (
        f"仓库根新增了库文件：{describe_root_db_diff(before, after)}。\n"
        "根因：某条路径用了**裸相对文件名** —— 裸名由 sqlite 按进程 CWD 解析，"
        "「从仓库根跑 pytest」就写进仓库根。"
        "注意 `*.db` 被 .gitignore 挡住 ⇒ 这种泄漏可以无限期无人发现。"
    )


def test_guard_c_repo_root_unchanged_by_the_batch(batch_run: "Dict[str, Any]") -> None:
    """更严的判据：仓库根库文件指纹（`(mtime, 字节数)`）**前后一致**。

    为什么必须比「不新增」更严：落点错时库被 `remove_db_files` 删掉再 `init_db()`
    建回来，**重建后字节数可以与原来完全相同**（schema 幂等）—— 只看字节数的
    快照会漏判，mtime 不会。本机仓库根常有旧泄漏残留，它们被原地改写同样算"落点错"：
    落点正确时，那些文件根本不会被打开。

    （与上一条共用同一次 module 级子进程 —— 其耗时登记见上一条 docstring。）
    """
    before_fp = batch_run["before_fp"]
    after_fp = batch_run["after_fp"]
    assert after_fp == before_fp, (
        "本次运行改动了仓库根的库文件 —— 落点不是绝对路径。\n"
        f"差异：{_describe_fingerprint_diff(before_fp, after_fp)}"
    )


def test_guard_c_root_db_snapshot_covers_test_dbs(tmp_path: Path) -> None:
    """守卫视野检查：`root_db_snapshot` MUST 看得见 `test_*.db`（含其 `-wal` / `-shm`）。

    为什么必须钉这一条：会话守卫的判别力**完全**来自 `db_cleanup.ROOT_DB_NAMES`。
    它曾只有 `delector.db` / `progress.db` 两种名字 ⇒ 本模块这类 `test_*.db` 泄漏
    在守卫视野**之外**（而 `*.db` 被 `.gitignore` 挡住 ⇒ 无人发现）。本条把这个
    视野本身钉住：把范围收回原状 ⇒ 本用例红（变异自证见提交说明）。

    全部在 `tmp_path` 里造（**不在仓库根**写任何东西）：本用例只验快照口径。
    """
    (tmp_path / "delector.db").write_bytes(b"x" * 10)
    (tmp_path / "test_probe_leak.db").write_bytes(b"y" * 3)
    (tmp_path / "test_probe_leak.db-wal").write_bytes(b"z")
    (tmp_path / "unrelated_notes.db").write_bytes(b"n" * 5)

    snap = root_db_snapshot(str(tmp_path))

    assert snap == {
        "delector.db": 10,
        "test_probe_leak.db": 3,
        "test_probe_leak.db-wal": 1,
    }, (
        "root_db_snapshot 的视野不对：`delector.db` 与 `test_*.db`（含侧文件）都 MUST 在，"
        f"非库名的 `*.db` MUST 不在。实际：{snap}"
    )


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
                verbs = {
                    e.value.upper()
                    for e in kw.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                }
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
    # 单一真相源：articles.py 与 main.py MUST NOT 再持有写死版本字面量
    articles_src = open(
        os.path.join(ROOT, "delector", "routes", "articles.py"), encoding="utf-8"
    ).read()
    main_src = open(
        os.path.join(ROOT, "delector", "routes", "main.py"), encoding="utf-8"
    ).read()
    for src, fname in [(articles_src, "articles.py"), (main_src, "main.py")]:
        tree = ast.parse(src)
        literals = {
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value == "3.4.0"
        }
        assert not literals, f"{fname} 又出现了写死的 processed_json 版本字面量（判据会再漂移）"

    # 判据 MUST 引用常量
    assert "PROCESSED_JSON_VERSION" in articles_src or "PROCESSED_JSON_VERSION" in main_src
    exported = processor.PROCESSED_JSON_VERSION
    assert isinstance(exported, str) and exported

    # 两条返回路径 MUST 都等于该常量（含无 spaCy 的回退路径）
    assert _process_german_text_pure_python(RAW_TEXT)["version"] == exported
    if processor.nlp is not None:
        assert processor.process_german_text(RAW_TEXT)["version"] == exported