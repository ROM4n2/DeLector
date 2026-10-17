# 本文件含「正常模式需要、--follow-imports=skip 下 unused」的动态面 type: ignore
# （BaseRoute 静态无 endpoint/path、运行时必为 APIRoute 的动态访问）——门禁用
# `mypy --follow-imports=skip tests` 跑，skip 下 fastapi 降 Any 使这些 ignore 变
# unused，故文件级豁免 unused-ignore（其它错误码仍全查）。
# mypy: disable-error-code="unused-ignore"
import ast
import json
import os
import re

import pytest

# clean_db 是夹具：用 `as 同名` 显式再导出写法（pyflakes 据此不判「导入未用」；
# 夹具由 pytest 按名解析，静态看不见使用）。
from server_helpers import ROOT, _calls_named, _package_windows_build_windows_fn
from server_helpers import clean_db as clean_db

from delector.core.database import db_conn
from delector.server import init_db

# --- C6 Task 3（去重）：原先按「新文件独立可跑」纪律本地化的三件（clean_db autouse /
# _package_windows_build_windows_fn / _calls_named）已上收为 tests/server_helpers.py 的**唯一
# 实现**，本文件按名 import（夹具导入即在本模块注册，autouse 作用域仍限本模块）。
# 禁止再本地复制：第三份起必漂移。------------------------------------------------


# ── v4.7.0 架构与数据完整性改造 TDD 契约 ───────────────────────────────────────


def test_backup_covers_essays_and_essay_versions_roundtrip(client):
    """备份导出与还原必须完整包含 essays 和 essay_versions 写作台全量数据。

    未包含 = 用户导出备份换机或重装后，作文草稿与版本演进历史全部静默丢失。
    """
    # 1. 创建一篇作文与一个版本
    res_essay = client.post("/api/essays", json={"title": "Mein Urlaub", "content": "Ich fahre nach Berlin."})
    assert res_essay.status_code == 200
    essay_id = res_essay.json()["id"]

    res_ver = client.post(
        f"/api/essays/{essay_id}/versions", json={"message": "初稿修改", "content": "Ich fahre morgen nach Berlin."}
    )
    assert res_ver.status_code == 200

    # 2. 导出备份
    exp = client.get("/api/backup/export").json()
    assert "essays" in exp, "备份导出必须包含 essays 表"
    assert "essay_versions" in exp, "备份导出必须包含 essay_versions 表"
    assert any(e["title"] == "Mein Urlaub" for e in exp["essays"])
    assert any(v["message"] == "初稿修改" for v in exp["essay_versions"])

    # 3. 清空后还原
    restore_payload = {
        "version": 2,
        "essays": [
            {
                "id": 888,
                "title": "Restored Essay",
                "content": "Restored content.",
                "analysis_json": "{}",
                "cefr_level": "B1",
                "error_count": 0,
                "sentence_count": 1,
                "created_at": "2026-08-29 12:00:00",
                "updated_at": "2026-08-29 12:00:00",
            }
        ],
        "essay_versions": [
            {
                "id": 8881,
                "essay_id": 888,
                "content": "Restored content v1",
                "analysis_json": "{}",
                "message": "Restored version",
                "created_at": "2026-08-29 12:00:00",
            }
        ],
    }
    res_rest = client.post("/api/backup/restore", json=restore_payload)
    assert res_rest.status_code == 200

    # 4. 验证还原后可查
    res_get = client.get("/api/essays/888")
    assert res_get.status_code == 200
    assert res_get.json()["title"] == "Restored Essay"

    res_v_get = client.get("/api/essays/888/versions")
    assert res_v_get.status_code == 200
    assert len(res_v_get.json()) >= 1
    assert any(v["message"] == "Restored version" for v in res_v_get.json())


def test_backup_grammar_cards_preserves_error_type_and_corrected_form(client):
    """grammar_cards 备份必须保留 corrected_form 和 error_type 字段。"""
    payload = {
        "version": 2,
        "grammar_cards": [
            {
                "id": 777,
                "article_id": None,
                "sentence_context": "In dem Buch.",
                "grammar_name": "Dativ mit Präposition",
                "cefr_level": "A1",
                "explanation_zh": "in支配三格",
                "rule_formula": "in + Dat",
                "examples_zh": "",
                "corrected_form": "in dem Buch",
                "error_type": "kasus",
                "created_at": "2026-08-29 10:00:00",
            }
        ],
    }
    assert client.post("/api/backup/restore", json=payload).status_code == 200

    with db_conn("test_delector.db") as conn:
        row = dict(conn.execute("SELECT * FROM grammar_cards WHERE id = 777").fetchone())
    assert row["corrected_form"] == "in dem Buch"
    assert row["error_type"] == "kasus"

    exp = client.get("/api/backup/export").json()
    card = next(c for c in exp["grammar_cards"] if c["id"] == 777)
    assert card["corrected_form"] == "in dem Buch"
    assert card["error_type"] == "kasus"


def test_vocab_card_accepts_and_saves_plural(client):
    """POST /api/cards/vocab 必须接收并持久化 plural 字段。"""
    req_body = {
        "word": "Buch",
        "lemma": "Buch",
        "pos": "NOUN",
        "gender": "Neut",
        "plural": "Bücher",
        "cefr_level": "A1",
        "definition_zh": "书",
        "sentence_context": "Das Buch ist gut.",
    }
    res = client.post("/api/cards/vocab", json=req_body)
    assert res.status_code == 200
    card_id = res.json()["id"]

    cards_res = client.get("/api/cards").json()
    vcard = next(c for c in cards_res["vocab_cards"] if c["id"] == card_id)
    assert vcard.get("plural") == "Bücher"


def test_sync_sdp_cache_capacity_and_size_limit(client):
    """WebRTC SDP 暂存必须有条目上限（FIFO 淘汰）与体积极限，防止内存无界膨胀。"""
    from delector.server import MAX_SYNC_CACHE_ENTRIES, _sync_sdp_cache

    key = client.get("/api/wb/state/key").json()["key"]

    # 1. 超过最大容量时自动剔除老数据
    for i in range(MAX_SYNC_CACHE_ENTRIES + 10):
        sdp = {"type": "offer", "sdp": f"mock_sdp_{i}"}
        res = client.post("/api/wb/sync/store", json={"sdp": sdp, "role": "offer"}, headers={"X-WB-Key": key})
        assert res.status_code == 200

    assert len(_sync_sdp_cache) <= MAX_SYNC_CACHE_ENTRIES

    # 2. 超大 payload 拒绝（400）——鉴权在前，带对 key 才会走到体积检查
    huge_sdp = {"type": "offer", "sdp": "A" * (65 * 1024)}
    res_huge = client.post("/api/wb/sync/store", json={"sdp": huge_sdp, "role": "offer"}, headers={"X-WB-Key": key})
    assert res_huge.status_code == 400


def test_db_busy_timeout_and_concurrency_guard():
    """SQLite 连接必须启用 WAL + busy_timeout + synchronous=NORMAL 守卫，避免并发读写锁库。"""
    with db_conn("test_delector.db") as conn:
        jmode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        sync_mode = conn.execute("PRAGMA synchronous").fetchone()[0]
    assert jmode.lower() == "wal"  # 写不阻塞读、崩溃恢复更稳（2026-09-28 swarm 审计 P1）
    assert busy_timeout >= 5000
    assert sync_mode in (1, 2)  # NORMAL or FULL


def test_vocab_cards_has_unified_pool_columns(client):
    """ADR-0016 Phase 1：vocab_cards 具备统一池列（source + FSRS-6），新卡默认 source='user'。

    本轮为**加性** schema（无人读写）——只钉"列在、默认值对"，为 Phase 2 的派生投影打底。
    """
    with db_conn("test_delector.db") as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(vocab_cards)").fetchall()}
    assert {"source", "fsrs_s", "fsrs_d", "fsrs_lapses"} <= cols, (
        f"vocab_cards 缺统一池列（ADR-0016 Phase 1），实际列：{sorted(cols)}"
    )
    with db_conn("test_delector.db") as conn:
        conn.execute(
            "INSERT INTO vocab_cards (word, lemma, definition_zh, sentence_context) VALUES (?, ?, ?, ?)",
            ("Haus", "Haus", "房子", "Das Haus."),
        )
        row = conn.execute(
            "SELECT source, fsrs_s, fsrs_d, fsrs_lapses FROM vocab_cards ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row["source"] == "user"  # 默认来源；官方/手编/AI 由 Phase 2 派生投影写
    assert row["fsrs_s"] is None and row["fsrs_d"] is None and row["fsrs_lapses"] == 0


def test_init_db_migrates_legacy_vocab_cards_to_unified_pool_columns(tmp_path):
    """旧库（无统一池列）跑 init_db 自动补列并回填 source='user'（加性迁移，ADR-0016 Phase 1）。"""
    import sqlite3 as _sqlite3

    legacy = str(tmp_path / "legacy_pool.db")
    raw = _sqlite3.connect(legacy)
    # 拟真旧 schema：有 article_id（否则 idx_vocab_article 建索引会失败），无 SRS/统一池列。
    raw.execute(
        "CREATE TABLE vocab_cards (id INTEGER PRIMARY KEY AUTOINCREMENT, article_id INTEGER, "
        "word TEXT NOT NULL, lemma TEXT NOT NULL, pos TEXT, gender TEXT, plural TEXT, "
        "cefr_level TEXT, definition_zh TEXT NOT NULL, sentence_context TEXT NOT NULL, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    raw.execute(
        "INSERT INTO vocab_cards (word, lemma, definition_zh, sentence_context) VALUES ('alt', 'alt', '旧', 'Alt.')"
    )
    raw.commit()
    raw.close()

    init_db(legacy)

    raw = _sqlite3.connect(legacy)
    raw.row_factory = _sqlite3.Row
    cols = {r[1] for r in raw.execute("PRAGMA table_info(vocab_cards)").fetchall()}
    row = raw.execute("SELECT source, fsrs_lapses FROM vocab_cards").fetchone()
    raw.close()
    assert {"source", "fsrs_s", "fsrs_d", "fsrs_lapses"} <= cols
    assert row["source"] == "user"  # 存量行回填（ADD COLUMN 常量默认值）
    assert row["fsrs_lapses"] == 0


def test_source_class_maps_provenance_to_pool_values():
    """ADR-0016 Phase 2：provenance 来源集合 → 统一池 source 值域（official/manual/ai/user）。"""
    from delector.core import lexicon as LX

    assert LX.source_class([]) == "user"
    assert LX.source_class(["ai"]) == "ai"
    assert LX.source_class(["manual"]) == "manual"
    assert LX.source_class(["workbench-a1"]) == "manual"  # 工作台 A1 内容属人工
    assert LX.source_class(["official"]) == "official"
    assert LX.source_class(["goethe-a1"]) == "official"  # 考纲 A1 属官方
    # 多来源按权威次序收敛：official > manual > ai
    assert LX.source_class(["ai", "manual"]) == "manual"
    assert LX.source_class(["ai", "manual", "official"]) == "official"


def test_add_vocab_card_sets_source_from_lexicon(client):
    """`POST /api/cards/vocab` 按主干 provenance 落定 source（懒物化，ADR-0016 Phase 2）。"""
    from delector.core import lexicon as LX

    assert LX.primary_source("ab") == "official"  # "ab" 在官方 A1 词表
    client.post(
        "/api/cards/vocab",
        json={"word": "ab", "lemma": "ab", "definition_zh": "从…起", "sentence_context": "Ab morgen."},
    )
    client.post(
        "/api/cards/vocab",
        json={"word": "zzzquux", "lemma": "zzzquux", "definition_zh": "造词", "sentence_context": "Zzz quux."},
    )
    with db_conn("test_delector.db") as conn:
        rows = {r["lemma"]: r["source"] for r in conn.execute("SELECT lemma, source FROM vocab_cards").fetchall()}
    assert rows["ab"] == "official"  # 主干收录 → 官方
    assert rows["zzzquux"] == "user"  # 主干未收录的自定义词


def test_known_lemmas_endpoint_reflects_studied_cards_only(client):
    """GET /api/cards/known-lemmas：只回「已学」主卡原形（三条来源任一成立即算已知）。

    2026-09-28 swarm 审计 P1：i+1 已知词池原只读背词工作台 deck，主路径（/api/cards）
    的词永不进池 → 打通后该端点供前端 mergeKnownLemmas 并入。这里钉住「已学」判据：
    1. mastered=1（用户在卡盒手动置「已掌握」）；
    2. repetition_count>0（在卡盒 DSR 复习过至少一次）；
    3. fsrs_s>0（在背词工作台 FSRS 学过至少一次，统一池投影写入）——第三条为 2026-09-28 补入。
    **仅加入卡盒**（mastered=0 且 repetition_count=0 且 fsrs_s 空）**不算**已知（承项目既有约定）。
    """
    with db_conn("test_delector.db") as conn:
        for word, mastered, reps in (("Abfahrt", 0, 0), ("Haus", 0, 2), ("Baum", 1, 0)):
            conn.execute(
                "INSERT INTO vocab_cards (word, lemma, definition_zh, sentence_context, "
                "mastered, repetition_count) VALUES (?, ?, ?, ?, ?, ?)",
                (word, word, "释义", f"Ein Satz mit {word}.", mastered, reps),
            )
    res = client.get("/api/cards/known-lemmas")
    assert res.status_code == 200
    # 已复习(Haus) 与已掌握(Baum) 入选；仅保存未学(Abfahrt) 落选
    assert sorted(res.json()["lemmas"]) == ["Baum", "Haus"]




def test_a1_hoeren_routes(client):
    """验证 A1 听力工坊相关 REST API 路由与判分持久化。"""
    res_list = client.get("/api/a1/hoeren/sets")
    assert res_list.status_code == 200
    assert len(res_list.json()["sets"]) == 5

    res_set = client.get("/api/a1/hoeren/set/1")
    assert res_set.status_code == 200
    assert res_set.json()["set_id"] == 1

    grade_res = client.post(
        "/api/a1/hoeren/grade", json={"set_id": 1, "duration_seconds": 600, "answers": {"a1_h_01_t1_q01": "B"}}
    )
    assert grade_res.status_code == 200
    assert "score_official" in grade_res.json()

    hist_res = client.get("/api/a1/hoeren/history")
    assert hist_res.status_code == 200
    assert len(hist_res.json()["history"]) >= 1


def test_a1_lesen_routes(client):
    """验证 A1 阅读工坊相关 REST API 路由与判分持久化。"""
    res_list = client.get("/api/a1/lesen/sets")
    assert res_list.status_code == 200
    assert len(res_list.json()["sets"]) == 6

    res_set = client.get("/api/a1/lesen/set/1")
    assert res_set.status_code == 200
    assert res_set.json()["set_id"] == 1

    grade_res = client.post(
        "/api/a1/lesen/grade", json={"set_id": 1, "duration_seconds": 750, "answers": {"a1_l_01_t1_q01": "R"}}
    )
    assert grade_res.status_code == 200
    assert "score_official" in grade_res.json()

    hist_res = client.get("/api/a1/lesen/history")
    assert hist_res.status_code == 200
    assert len(hist_res.json()["history"]) >= 1


# ── 打包三加固：.env 泄漏闸 / 构建指纹 / 版本 fallback ─────────────────────────
# 背景（用户双击便携版时真实踩到的坑）：
# ① 担心 .env（内含 DEEPSEEK_API_KEY）随包发出去 —— 目前产物里确实没有，但**没有任何守卫**
#    拦住"哪天有人把 .env 放进构建目录"；② 无法分辨自己双击的是哪个构建（本地不设
#    GITHUB_REF_NAME 时产物被命名成 v3.8.0，而 App 实为 v5.16.0，排查中"以为是新包、
#    其实是旧包"白浪费大半轮）；③ 版本 fallback 写死误导名 v3.8.0。
# 三条共用同一批 AST 辅助函数（_package_windows_build_windows_fn / _calls_named），
# 把"函数定义存在"提升为"真的在 build_windows() 构建路径上被调用"，删调用即红。


def test_windows_portable_declares_env_leak_guard():
    """便携包必须**构建后自检**产物里没有 .env，且命中即**硬失败**。

    为什么这是"最该有"的一条：便携版"解压即用"，整包会被转发给任何人。一旦 .env
    （内含 DEEPSEEK_API_KEY）混进产物，API Key 就随包发出去 —— 与漏收 WebView2 DLL
    同款的"本地全绿、打包后静默出事"，只是后果从白屏升级成密钥泄露。故断言：
    ① 扫描 + 执行入口两个函数在场（自检与失败处置分离，更好测）；② 走非零退出的硬失败；
    ③ 文案点明"API Key 随包发出去"的后果，让后人看懂为何不能删掉这道闸。
    """
    pkg = open(os.path.join(ROOT, "package_windows.py"), encoding="utf-8").read()

    assert "find_env_files" in pkg, "缺 .env 扫描函数：混进构建目录的 .env 会静默随包发出"
    assert "assert_no_env_in_payload" in pkg, "缺「命中即失败」的执行入口（自检与失败处置分离更好测）"
    assert "API Key" in pkg, "失败文案必须点明后果（API Key 随包发出去），否则后人会把自检当噪音删掉"


def test_build_windows_actually_invokes_env_leak_check():
    """`assert_no_env_in_payload(...)` 的调用点 MUST 落在 `build_windows()` 函数体内。

    只断言"函数名出现在源码里"是不够的：把 build_windows() 里那行调用删掉，闸就**失效**
    而全套测试仍绿。AST 把"定义存在"提升为"真的在构建路径上被调用"，删调用即红。
    """
    build_fn = _package_windows_build_windows_fn()

    assert _calls_named(build_fn, "assert_no_env_in_payload"), (
        "build_windows() 内必须真调用 assert_no_env_in_payload()：否则 .env 闸形同虚设（删调用全套仍绿）"
    )


def test_find_env_files_detects_dotenv_and_variants(tmp_path):
    """行为级：`.env` 与 `*.env` 变体都要命中，裸 `.env` 之外的改名（`prod.env`）同样会带走 Key。"""
    import package_windows

    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=sk-secret\n", encoding="utf-8")
    nested = tmp_path / "_internal"  # 改名变体：与裸 .env 不同目录，避免大小写不敏感 FS 覆盖
    nested.mkdir()
    (nested / "prod.env").write_text("X=1\n", encoding="utf-8")
    other = tmp_path / "_other"
    other.mkdir()
    (other / "PROD.ENV").write_text("X=1\n", encoding="utf-8")  # 大写变体：扫描须大小写不敏感
    (tmp_path / "not_env.txt").write_text("safe\n", encoding="utf-8")

    hits = package_windows.find_env_files(str(tmp_path))

    assert ".env" in hits, f"裸 .env 必须命中，实际 {hits}"
    assert sorted(hits) == sorted(
        [".env", os.path.join("_internal", "prod.env"), os.path.join("_other", "PROD.ENV")]
    ), f"命中清单必须精确覆盖 .env 与 *.env 变体、且不误伤 not_env.txt，实际 {hits}"


def test_find_env_files_clean_dir_returns_empty(tmp_path):
    """干净产物目录 ⇒ 空清单（否则每次正常构建都会被自己的自检拒掉）。"""
    import package_windows

    (tmp_path / "DeLector.exe").write_bytes(b"")
    (tmp_path / "说明_README.txt").write_text("hi", encoding="utf-8")

    assert package_windows.find_env_files(str(tmp_path)) == []


def test_assert_no_env_in_payload_hard_fails_when_env_present(tmp_path):
    """产物夹带 .env ⇒ **非零退出**（`SystemExit`），绝不能只打印警告就放行。

    这是本任务的核心守卫：闸**必须真的会让构建失败**，否则 Key 照样随包发布。
    """
    import package_windows

    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=sk-secret\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        package_windows.assert_no_env_in_payload(str(tmp_path))

    assert excinfo.value.code != 0, "产物夹带 .env 时必须非零退出（构建失败）"


def test_assert_no_env_in_payload_passes_on_clean_dir(tmp_path):
    """干净目录 ⇒ 不抛、正常返回（否则每次正常构建都会被自己的自检拒掉）。"""
    import package_windows

    (tmp_path / "DeLector.exe").write_bytes(b"")

    package_windows.assert_no_env_in_payload(str(tmp_path))  # 不抛即通过


def test_windows_portable_declares_build_fingerprint():
    """产物必须写一份**机器可读**构建指纹，键至少含 commit / built_at / app_version / entry。"""
    pkg = open(os.path.join(ROOT, "package_windows.py"), encoding="utf-8").read()

    assert "write_build_fingerprint" in pkg, "缺构建指纹写入函数：产物无法机器识别是哪个构建"
    for key in ("commit", "built_at", "app_version", "entry"):
        assert f'"{key}"' in pkg, f"指纹内容键缺 {key!r}"


def test_build_windows_actually_invokes_build_fingerprint():
    """`write_build_fingerprint(...)` 的调用点 MUST 落在 `build_windows()` 函数体内（否则指纹不落进产物）。"""
    build_fn = _package_windows_build_windows_fn()

    assert _calls_named(build_fn, "write_build_fingerprint"), (
        "build_windows() 内必须真调用 write_build_fingerprint()：否则指纹文件根本不生成"
    )


def test_write_build_fingerprint_creates_machine_readable_file(tmp_path):
    """行为级：指纹文件被生成、内容键齐全、取值逐字落盘（用临时目录，不跑 PyInstaller）。"""
    import package_windows

    path = package_windows.write_build_fingerprint(
        str(tmp_path), "v5.16.0", "desktop.py", "abc1234", "2026-10-08T12:00:00"
    )

    assert os.path.exists(path), "指纹文件必须真被写到产物目录"
    assert os.path.basename(path) == package_windows.BUILD_INFO_FILENAME

    info = json.loads(open(path, encoding="utf-8").read())
    assert info == {
        "commit": "abc1234",
        "built_at": "2026-10-08T12:00:00",
        "app_version": "v5.16.0",
        "entry": "desktop.py",
    }, f"指纹内容键/取值不符，实际 {info}"


def test_current_commit_short_sha_falls_back_to_unknown_without_git(tmp_path):
    """非 git 环境取不到 sha ⇒ 回落 'unknown'，**绝不抛**（源码包也要能构建）。"""
    import package_windows

    assert package_windows.current_commit_short_sha(str(tmp_path)) == "unknown"


def test_readme_has_human_fingerprint_line():
    """README 顶部 MUST 有一行人读指纹（版本 + 短 sha + 构建时间），供用户分辨双击的是哪个包。"""
    import package_windows

    readme = package_windows.release_readme("v5.16.0", "abc1234", "2026-10-08T12:00:00")

    assert "v5.16.0" in readme, "人读指纹必须含版本号"
    assert "abc1234" in readme, "人读指纹必须含短 sha"
    assert "2026-10-08T12:00:00" in readme, "人读指纹必须含构建时间"


def test_resolve_version_prefers_github_ref_name(monkeypatch):
    """CI 注入 GITHUB_REF_NAME 且语境为 tag 时优先取它（tag 即发布版本）。

    显式设 GITHUB_REF_TYPE=tag：GitHub Actions 会给 pytest 步骤带上 GITHUB_REF_TYPE
    环境变量（PR/push 为 branch），不设它就会让"是否采纳该名"取决于**运行环境**而非被测
    逻辑（本机绿、CI 红）。设成 tag 才是这条用例真正要表达的发布语境。

    为什么用**预发布** tag（`v<APP_VERSION>-rc1`）而不是任意 tag：2026-10-11 起真 tag 语境必须过
    `assert_tag_matches_app_version`（tag 名与 APP_VERSION 分叉会让产物自称 tag、应用报旧版本）。
    而一个与 APP_VERSION **完全相同**的 tag 就无法再区分"tag 优先"与"回落 APP_VERSION"——
    预发布 tag 是唯一**既合法、又与回落值不同**的形态，用它才保住这条用例的判别力。
    """
    import package_windows
    from delector.core.version import APP_VERSION

    monkeypatch.setenv("GITHUB_REF_TYPE", "tag")
    monkeypatch.setenv("GITHUB_REF_NAME", f"v{APP_VERSION}-rc1")
    assert package_windows.resolve_version() == f"v{APP_VERSION}-rc1"


def test_resolve_version_falls_back_to_app_version(monkeypatch):
    """不设 GITHUB_REF_NAME ⇒ 回落 APP_VERSION（单一真相源，带 'v' 前缀）。"""
    import package_windows
    from delector.core.version import APP_VERSION

    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    assert package_windows.resolve_version() == f"v{APP_VERSION}", (
        "本地构建的版本必须来自 APP_VERSION，而不是写死的 v3.8.0 误导名"
    )


# ── 回归锁：版本号含斜杠（CI 闸第一次上线就抓到的产物嵌套）──────────────────────
# 症状：pull_request 事件里 GITHUB_REF_NAME = `128/merge`，被当版本后产物目录嵌套成
# dist/DeLector-128/merge-Windows-x64-Portable —— 构建步报成功、验包步（只扫第一层）
# 找不到产物。下面四条把"tag 语境判断 + 分隔符净化 + 硬失败"钉死，防回潮。


def test_resolve_version_pr_ref_name_yields_no_path_separator(monkeypatch):
    """PR 语境（GITHUB_REF_NAME=128/merge）⇒ 版本不含路径分隔符，且回落 APP_VERSION。

    "不含路径分隔符"是硬要求：一旦带上 `/`，产物目录就嵌套、下游验包 / 压缩步扫不到它。
    """
    import package_windows
    from delector.core.version import APP_VERSION

    monkeypatch.setenv("GITHUB_REF_TYPE", "branch")
    monkeypatch.setenv("GITHUB_REF_NAME", "128/merge")
    version = package_windows.resolve_version()

    assert "/" not in version and "\\" not in version, (
        f"版本号 {version!r} 含路径分隔符：产物目录会被嵌套成 dist/DeLector-128/merge-…，"
        "验包 / 压缩步（只扫第一层）扫不到 —— 构建报成功却没人能用"
    )
    assert version == f"v{APP_VERSION}", "非 tag 语境必须回落 APP_VERSION"


def test_resolve_version_branch_ref_type_falls_back_to_app_version(monkeypatch):
    """GITHUB_REF_TYPE=branch ⇒ 即使 GITHUB_REF_NAME 形如 v* 也回落 APP_VERSION。"""
    import package_windows
    from delector.core.version import APP_VERSION

    monkeypatch.setenv("GITHUB_REF_TYPE", "branch")
    monkeypatch.setenv("GITHUB_REF_NAME", "v9.9.9")
    assert package_windows.resolve_version() == f"v{APP_VERSION}"


def test_resolve_version_tag_ref_type_keeps_tag_name(monkeypatch):
    """防把发布命名改坏：GITHUB_REF_TYPE=tag ⇒ 版本串仍是那个 tag 名（而不是回落值）。

    用**预发布** tag（`v<APP_VERSION>-rc1`）：2026-10-11 起真 tag 语境必须过
    `assert_tag_matches_app_version`（tag 名与 APP_VERSION 分叉会让产物自称 tag、应用报旧版本），
    而与 APP_VERSION **完全相同**的 tag 又无法区分"保留 tag 名"与"回落 APP_VERSION"——
    预发布 tag 是唯一既合法又不同的形态。
    """
    import package_windows
    from delector.core.version import APP_VERSION

    monkeypatch.setenv("GITHUB_REF_TYPE", "tag")
    monkeypatch.setenv("GITHUB_REF_NAME", f"v{APP_VERSION}-rc1")
    assert package_windows.resolve_version() == f"v{APP_VERSION}-rc1"


def test_sanitize_version_replaces_path_separators():
    """含非法分隔符的版本串 ⇒ 被净化成合法 slug（版本串不含路径分隔符）。

    为什么从"经 `resolve_version()` 集成验证"改成**直测纯函数**（2026-10-11）：新守卫
    `assert_tag_matches_app_version` 要求真 tag 语境的名字必须匹配 `v`+APP_VERSION，而
    `v1.2.3/rc1` 这类名字**永远不可能匹配** ⇒ 那条集成路径已不可达。真正的事故面（PR 事件里
    `GITHUB_REF_NAME=128/merge`）由 `test_resolve_version_pr_ref_name_yields_no_path_separator`
    独立覆盖，不依赖本用例；净化器本身仍作为纵深防御保留，故直测它。
    """
    import package_windows

    version = package_windows.sanitize_version("v1.2.3/rc1")

    assert "/" not in version and "\\" not in version, f"净化后仍含分隔符：{version!r}"
    assert version == "v1.2.3-rc1", f"分隔符应被替换为 '-'，实际 {version!r}"


def test_resolve_version_rejects_tag_with_path_separator(monkeypatch):
    """真 tag 语境下含分隔符的 tag 名 ⇒ 被守卫①拒（`SystemExit`），不再进入净化路径。

    钉住的是**优先级**：版本身份（tag 必须匹配 APP_VERSION）先于目录合法性判定 —— 顺序反了会
    给出一条"已净化"的错版本号，而那正是历史事故（产物目录嵌套）想要的结果。
    """
    import package_windows

    monkeypatch.setenv("GITHUB_REF_TYPE", "tag")
    monkeypatch.setenv("GITHUB_REF_NAME", "v1.2.3/rc1")
    with pytest.raises(SystemExit):
        package_windows.resolve_version()


def test_assert_no_path_separator_hard_fails():
    """净化后仍含分隔符的版本串 ⇒ 非零退出（构建期硬失败），绝不产出嵌套目录。"""
    import package_windows

    with pytest.raises(SystemExit) as excinfo:
        package_windows.assert_no_path_separator("v1/2")
    assert excinfo.value.code != 0, "含路径分隔符的版本号必须非零退出（构建失败）"


def test_without_github_ref_type_local_v_tag_is_adopted(monkeypatch):
    """GITHUB_REF_TYPE 未设（本地手工设变量）时，形如 v* 且不含分隔符的名仍被采纳。

    用**预发布** tag（`v<APP_VERSION>-rc1`）而非与 APP_VERSION 完全相同的名：2026-10-11 起
    真 tag 语境必须过 `assert_tag_matches_app_version`，写死的旧版本名会直接被守卫拒（本用例
    原用 `v5.16.0`，bump 到 5.17.0 后即红）；而与 APP_VERSION 相同的名又无法区分"采纳 tag"
    与"回落 APP_VERSION"，预发布 tag 是唯一既合法又不同的形态。
    """
    import package_windows
    from delector.core.version import APP_VERSION

    monkeypatch.delenv("GITHUB_REF_TYPE", raising=False)
    monkeypatch.setenv("GITHUB_REF_NAME", f"v{APP_VERSION}-rc1")
    assert package_windows.resolve_version() == f"v{APP_VERSION}-rc1"


def test_version_fallback_targets_app_version_not_hardcoded():
    """守卫：版本 fallback 指向 APP_VERSION，且代码里**不得**再出现写死的 'v3.8.0' 字符串常量。

    用 AST 收集字符串**常量**而非子串匹配源码：注释/文档里说明"曾写死 v3.8.0"应当允许，
    真正要拦的是可执行的 `os.environ.get("GITHUB_REF_NAME", "v3.8.0")` 这类字面量。
    """
    pkg = open(os.path.join(ROOT, "package_windows.py"), encoding="utf-8").read()

    assert "APP_VERSION" in pkg, "版本 fallback 必须来自 delector.core.version.APP_VERSION（单一真相源）"

    literals = {
        node.value
        for node in ast.walk(ast.parse(pkg))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "v3.8.0" not in literals, (
        "不得再写死误导版本名 'v3.8.0'：本地构建会命名成它，而 App 实为 v5.16.0，用户无从分辨"
    )


def test_register_routes_covers_every_module_in_routes_package():
    """`delector/routes/` 下每个模块定义的路由都必须真的挂进 app。

    防范的正是本仓库踩过的那类事故：路由模块存在、也被 server 静态 import，
    但没人 include_router —— 端点静默 404 或打包后 ModuleNotFoundError，
    而"模块文件在"这种断言全绿。

    比对的是 **HTTP 语义键**（完整 path + methods）而非**端点函数对象身份**：
    前者是框架文档化契约、跨版本稳定；后者是纯实现细节（无任何向后兼容承诺）。
    starlette ≥1.6 随 fastapi ≥0.141 漂移后，`include_router`/`APIRoute` 不再
    保持对原函数对象的引用 → 对象身份比对会把**全部**路由误判 missing。改用
    HTTP 语义键后，本守卫对上游 `include_router`/`APIRoute` 的实现细节漂移免疫，
    同时真漏挂时仍能精确定位到具体 path。

    已注册侧取自 `app.openapi()["paths"]`（FastAPI 文档化的 HTTP 契约）而非
    `probe.routes` 的展平结构：fastapi ≥0.141 起 `include_router` 把子路由改为
    **嵌套**（`app.routes` 里是 `_IncludedRouter`，无 `path` 属性），实测
    `probe.routes` 只剩 4 条默认路由 → 展平式枚举会把**全部**路由误判 missing。
    OpenAPI paths 是"挂进 app 的 HTTP 端点"的规范化视图，两版 fastapi 下均可靠。

    定义侧：`route.path` 即完整挂载 path —— FastAPI 的 `add_api_route` 在**定义
    时**就把 `router.prefix` 烘进了 `route.path`（`self.prefix + path`），
    `register_routes` 的 `include_router` 未再叠加前缀，故**不能**再加 `router.prefix`
    （否则双拼）。仅需把路径转换器语法 `{name:int}` 归一化为 `{name}` 与 OpenAPI 对齐。
    """
    import importlib
    import pkgutil

    from fastapi import APIRouter, FastAPI

    import delector.routes as routes_pkg
    from delector.routes import register_routes

    def _semantic_path(path: str) -> str:
        # 归一化路径转换器语法 `{name:int}` → `{name}`：route.path 保留转换器后缀，
        # 而 OpenAPI 契约只暴露参数名 —— 两侧对齐后才能当同一个 HTTP 语义键来比。
        return re.sub(r"\{(\w+):[^}]+\}", r"{\1}", path)

    probe = FastAPI()
    register_routes(probe)
    # 已注册侧 = app 暴露的 (path, method) HTTP 语义键集合（OpenAPI 契约）。
    # 逐 method 展开而非按 path 聚合成 frozenset：同一 path 可挂多个方法（如
    # GET 列表 + POST 新建），须与定义侧"每 route 一组方法"逐条对齐才不漏比。
    registered = {
        (_semantic_path(path), method.upper())
        for path, ops in probe.openapi().get("paths", {}).items()
        for method in ops
    }

    missing = []
    covered_modules = []
    for mod_info in pkgutil.iter_modules(routes_pkg.__path__):
        mod = importlib.import_module(f"delector.routes.{mod_info.name}")
        routers = [v for v in vars(mod).values() if isinstance(v, APIRouter)]
        assert routers, f"delector/routes/{mod_info.name}.py 里没有 APIRouter —— 不是路由模块就别放 routes/ 包里"
        covered_modules.append(mod_info.name)
        for router in routers:
            for route in router.routes:
                # router.routes 静态标为 BaseRoute，但经装饰器注册的路由运行时必是
                # APIRoute（path/methods 是其 HTTP 语义属性），属刻意的动态面访问。
                # route.path 已含 router.prefix（见 docstring），勿再拼 prefix。
                path = _semantic_path(route.path)  # type: ignore[attr-defined]  # BaseRoute 静态无 path，运行时必为 APIRoute（见上注释）
                for method in getattr(route, "methods", ()) or ():
                    if (path, method) not in registered:
                        missing.append(f"{mod_info.name}:{path}")

    assert "main" in covered_modules, "routes/main.py（通用 handler）没被扫描到"
    assert not missing, f"这些路由定义了却没挂进 app（漏 include_router）: {missing}"
