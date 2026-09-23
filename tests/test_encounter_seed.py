# -*- coding: utf-8 -*-
"""预置遇见区卡包（T4）：数据契约 + 运行时接线 + 幂等与守卫。

契约面
------
- 数据（delector/data/encounter_seed_dict.py）：PRESET_ENCOUNTER_PACKS 每包过
  validate_pack、estimated_cefr ∈ {A1,A2,B1}、pack_id 全局唯一、正文非空且德语、
  glosses == []，且 analysis.lemma_seq 为逐 token 非空 lemma 序列。
- 接线（delector/core/database.py::seed_preset_encounter_texts）：**版本闸 + 只增补装
  + 只补空 + 幂等**（红线 12 / Vault 01-Rules/STORED-DATA-BACKFILL）。空库全量导入 7
  包；非空库只增补缺失 pack_id、对既有行只补空 `analysis.lemma_seq`；成功后写
  `app_settings["encounter_seed_version"]=2`，版本已够则热路径返回 0。
- 装配（delector/server.py::create_app）：在 seed_preset_articles 之后调用
  seed_preset_encounter_texts。用 AST 定位 create_app 函数体再断言（不是"文件里
  出现过该字符串"——那会在 import 行也命中，是死断言）。
- 脚本（tools/build_encounter_seed.py）：同输入两次产物字节一致（spaCy/模型不可用
  → pytest.skip，不因环境缺失变红）。

断言纪律（PYTHON-STANDARDS §8.2）
--------------------------------
每条用例都断言**具体值**，禁止"不抛异常即过"。变异自检见文件末 _MUTATION_TABLE。
"""

import ast
import copy
import gc
import importlib.util
import json
import logging
import os
import subprocess
import sys
import textwrap

import pytest

# 先钉 env 再 import server（模块级 create_app 的 init_db 有副作用），对齐既有测试。
os.environ.setdefault("DATABASE_PATH", "test_encounter_seed.db")
os.environ.setdefault("PROGRESS_DB_PATH", "test_encounter_seed_progress.db")

from delector.core import database  # noqa: E402
from delector.data.encounter_seed_dict import PRESET_ENCOUNTER_PACKS  # noqa: E402
from delector.routes.encounter import validate_pack  # noqa: E402

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BUILD_SCRIPT = os.path.join(_REPO_ROOT, "tools", "build_encounter_seed.py")
_SERVER_SRC = os.path.join(_REPO_ROOT, "delector", "server.py")


def _load_build_under_test():
    """按路径加载 tools/build_encounter_seed.py（tools/ 不是 package）。"""
    spec = importlib.util.spec_from_file_location("build_encounter_seed_under_test", _BUILD_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_build = _load_build_under_test()


@pytest.fixture(autouse=True)
def clean_db(tmp_path):
    """每个用例独立 tmp_path 双 throwaway DB（encounter + progress）。"""
    _db = str(tmp_path / "encounter_seed.db")
    _pdb = str(tmp_path / "encounter_seed_progress.db")
    saved = {k: os.environ.get(k) for k in ("DATABASE_PATH", "PROGRESS_DB_PATH")}
    os.environ["DATABASE_PATH"] = _db
    os.environ["PROGRESS_DB_PATH"] = _pdb
    gc.collect()
    for f in (_db, _pdb):
        for suffix in ("", "-wal", "-shm"):
            p = f + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
    database.init_db(_db)  # 连带 init_progress_db() 落在 tmp_path
    yield
    gc.collect()
    for f in (_db, _pdb):
        for suffix in ("", "-wal", "-shm"):
            p = f + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _count_encounter_rows(db_path) -> int:
    with database.db_conn(db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM encounter_texts").fetchone()[0]


def _row_by_pack_id(db_path, pack_id):
    """按 pack_id 取单行 encounter_texts（dict）；不存在返回 None。"""
    with database.db_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM encounter_texts WHERE pack_id = ?", (pack_id,)).fetchone()
        return dict(row) if row else None


def _read_stored_version(db_path) -> str:
    """直接读 app_settings 表里 encounter_seed_version 的落库值（不走 env 兜底）。"""
    with database.db_conn(db_path) as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = 'encounter_seed_version'").fetchone()
        return row["value"] if row else ""


# ── 1. 数据契约 ───────────────────────────────────────────────────────────────
def test_packs_pass_validate_pack():
    """每包都必须过 routes.encounter.validate_pack（结构契约）。"""
    assert isinstance(PRESET_ENCOUNTER_PACKS, list)
    assert len(PRESET_ENCOUNTER_PACKS) == 7, "对外承诺 7 个预置包（A1×2 + A2×2 + B1×3）"
    for pack in PRESET_ENCOUNTER_PACKS:
        validate_pack(pack)  # 不合法即抛 ValueError → 红


def test_packs_cefr_whitelist():
    """estimated_cefr 必须落在 {A1, A2, B1} 白名单内。"""
    seen = {p["estimated_cefr"] for p in PRESET_ENCOUNTER_PACKS}
    assert seen == {"A1", "A2", "B1"}, f"CEFR 只应为 A1/A2/B1，实际 {seen}"


def test_packs_pack_id_globally_unique():
    """pack_id 全局唯一（幂等键，重复则去重失效）。"""
    ids = [p["pack_id"] for p in PRESET_ENCOUNTER_PACKS]
    assert len(ids) == len(set(ids)), f"pack_id 出现重复: {ids}"


def test_packs_article_text_is_german_prose():
    """正文非空且是德语长文（> 100 字符下限，不只断非空）。"""
    for pack in PRESET_ENCOUNTER_PACKS:
        raw = pack["article"]["raw_text"]
        assert isinstance(raw, str)
        assert len(raw) > 100, f"{pack['pack_id']} 正文过短（{len(raw)}）"
        # 德语特征：含德语变音/ß，且含常见德语功能词（避免英文/空串混入）。
        assert "ä" in raw or "ö" in raw or "ü" in raw or "ß" in raw, f"{pack['pack_id']} 未见德语变音符号，疑非德语正文"
        lowered = raw.lower()
        assert any(w in lowered for w in ("der", "die", "das", "und", "ich")), f"{pack['pack_id']} 未见常见德语功能词"


def test_packs_glosses_empty():
    """glosses 留空（阅读时释义走本地词典，pack 不携带）。"""
    for pack in PRESET_ENCOUNTER_PACKS:
        assert pack["glosses"] == [], f"{pack['pack_id']} glosses 应为 []"


def test_each_pack_has_lemma_seq():
    """每包 analysis.lemma_seq 为逐 token 非空 lemma 序列，长度对齐 tokens_total。

    口径与 routes.encounter._annotate_tokens 同源：剔除 is_space 空白 token、
    保留标点 token。lemma_seq 是后续阶段前端在本机算覆盖率的**权威分母来源**。
    """
    for pack in PRESET_ENCOUNTER_PACKS:
        pid = pack["pack_id"]
        seq = pack["analysis"]["lemma_seq"]
        assert isinstance(seq, list), f"{pid} lemma_seq 应为 list，实际 {type(seq).__name__}"
        assert len(seq) > 0, f"{pid} lemma_seq 不得为空"
        for i, lemma in enumerate(seq):
            assert isinstance(lemma, str), f"{pid} lemma_seq[{i}] 应为 str"
            assert lemma.strip() != "", f"{pid} lemma_seq[{i}] 不得为空白串"
        assert len(seq) == pack["analysis"]["tokens_total"], (
            f"{pid} lemma_seq 长度 {len(seq)} 应等于 tokens_total {pack['analysis']['tokens_total']}"
        )


def test_annotate_lemma_seq_drops_space_keeps_punct():
    """逐 token lemma 序列口径：剔除 is_space 空白 token、保留标点 token。

    真实语料实测 space_tokens == 0，故「删掉 is_space 过滤」不会在聚合测试上变红；
    这里用**人工 fixture** 直接喂 `_annotate_lemma_seq`，让该过滤缺失必红：
    改动实现去掉 `if not tok.get("is_space")` → 结果多出 " " → 本用例 red。
    """
    parsed = {
        "sentences": [
            {
                "tokens": [
                    {"text": "Der", "lemma": "der", "pos": "DET", "is_space": False},
                    {"text": " ", "lemma": " ", "pos": "SPACE", "is_space": True},
                    {"text": "Hund", "lemma": "Hund", "pos": "NOUN", "is_space": False},
                    {"text": ".", "lemma": ".", "pos": "PUNCT", "is_punct": True, "is_space": False},
                    {"text": " ", "lemma": " ", "pos": "SPACE", "is_space": True},
                ]
            }
        ]
    }
    assert _build._annotate_lemma_seq(parsed) == ["der", "Hund", "."]


# ── 2. 版本闸 + 全量导入 + 幂等 ────────────────────────────────────────────────
def test_seed_empty_db_imports_all_and_writes_version(tmp_path):
    """空库 + 无版本记录 → 全量导入 7 行，写入 app_settings["encounter_seed_version"]="2"。"""
    db_path = str(tmp_path / "encounter_seed.db")
    assert _count_encounter_rows(db_path) == 0, "夹具 init_db 不得导入预置（空态语义保留）"

    imported = database.seed_preset_encounter_texts(db_path)
    assert imported == 7, f"空库应全量导入 7 行，实际 {imported}"
    assert _count_encounter_rows(db_path) == 7
    assert _read_stored_version(db_path) == "2", "成功走完必须写入版本 2"


def test_seed_version_gate_shortcircuits_on_empty_db(tmp_path):
    """版本已 >= 2 → 热路径早退返回 0，即便库为空也不得导入任何行。

    这是「版本闸先于空库全量导入」的判据：删掉版本早退 → 本用例必红。
    """
    db_path = str(tmp_path / "encounter_seed.db")
    database.set_setting("encounter_seed_version", "2", db_path=db_path)
    assert _count_encounter_rows(db_path) == 0

    result = database.seed_preset_encounter_texts(db_path)
    assert result == 0, f"版本已 >= 2 必须返回 0，实际 {result}"
    assert _count_encounter_rows(db_path) == 0, "版本闸不得放行空库全量导入"


def test_seed_version_gate_ignores_env_pollution(tmp_path, monkeypatch):
    """版本闸只认库内真值：进程 env 里恰好有 encounter_seed_version 也不得干扰。

    get_setting 尾部有 ``os.environ.get(key, default)`` 兜底；若版本读取改回走
    get_setting，env 强灌 "99" 会让版本闸误判「已够」热退 → 本用例必红。
    """
    db_path = str(tmp_path / "encounter_seed.db")
    monkeypatch.setenv("encounter_seed_version", "99")
    assert _read_stored_version(db_path) == "", "前置：库内确无版本记录（env 不得伪造）"

    imported = database.seed_preset_encounter_texts(db_path)
    assert imported == 7, f"env 不得干扰版本闸：库内无记录应照常补装 7 行，实际 {imported}"
    assert _count_encounter_rows(db_path) == 7, "env 兜底不得让版本闸短路跳过补装"
    assert _read_stored_version(db_path) == "2", "补装完成后版本仍应写库为 2"


def test_seed_idempotent(tmp_path):
    """空库 seed 一次返回 7、库里 7 行；二次调用返回 0 且仍 7 行，既有行 pack_json 逐字节不变。"""
    db_path = str(tmp_path / "encounter_seed.db")
    first = database.seed_preset_encounter_texts(db_path)
    assert first == 7, f"首次应导入 7 行，实际 {first}"
    assert _count_encounter_rows(db_path) == 7

    pid = PRESET_ENCOUNTER_PACKS[0]["pack_id"]
    before_pack = _row_by_pack_id(db_path, pid)["pack_json"]

    second = database.seed_preset_encounter_texts(db_path)
    assert second == 0, f"二次调用应因版本闸返回 0，实际 {second}"
    assert _count_encounter_rows(db_path) == 7, "二次调用不得重复插入"

    after_pack = _row_by_pack_id(db_path, pid)["pack_json"]
    assert after_pack == before_pack, "二次调用（版本闸早退）不得改动既有行 pack_json"


def test_seed_does_not_resurrect_deleted_preset(tmp_path):
    """版本已 2 → 再次调用返回 0；用户删除的预置行不得复活（不引墓碑）。"""
    db_path = str(tmp_path / "encounter_seed.db")
    assert database.seed_preset_encounter_texts(db_path) == 7

    victim = PRESET_ENCOUNTER_PACKS[0]["pack_id"]
    with database.db_conn(db_path) as conn:
        conn.execute("DELETE FROM encounter_texts WHERE pack_id = ?", (victim,))
    assert _count_encounter_rows(db_path) == 6

    again = database.seed_preset_encounter_texts(db_path)
    assert again == 0, f"版本已 2：再次调用必须早退返回 0，实际 {again}"
    assert _count_encounter_rows(db_path) == 6, "被删除的预置行不得复活"
    assert _row_by_pack_id(db_path, victim) is None, "被删除的 pack_id 不得重新出现"


# ── 3. 非空库：只增补装 + 不动用户行 ───────────────────────────────────────────
def test_seed_nonempty_db_only_adds_missing_presets(tmp_path):
    """非空库（1 篇手工文本）+ 无版本记录 → 只增补装 7 预置；用户行逐字段不变。"""
    db_path = str(tmp_path / "encounter_seed.db")
    user_id = database.create_encounter_text(
        title="手工短文",
        level="A2",
        source="manual",
        content="Das ist mein eigener Text.",
        db_path=db_path,
    )
    assert _count_encounter_rows(db_path) == 1
    before = database.get_encounter_text(user_id, db_path=db_path)

    imported = database.seed_preset_encounter_texts(db_path)
    assert imported == 7, f"非空库 + 无版本记录应补装全部 7 个缺失预置，实际 {imported}"
    assert _count_encounter_rows(db_path) == 8, "1 篇手工 + 7 预置 == 8"

    after = database.get_encounter_text(user_id, db_path=db_path)
    for col in ("title", "level", "content", "source", "created_at"):
        assert after[col] == before[col], f"用户已有行的 {col} 不得被改动"

    preset_ids = {p["pack_id"] for p in PRESET_ENCOUNTER_PACKS}
    with database.db_conn(db_path) as conn:
        got = {r["pack_id"] for r in conn.execute("SELECT pack_id FROM encounter_texts")}
    assert preset_ids <= got, "7 个预置 pack_id 应全部补装进库"
    assert _read_stored_version(db_path) == "2"


# ── 4. 只补空：既有行的 analysis.lemma_seq ────────────────────────────────────
def test_seed_backfills_missing_lemma_seq_only(tmp_path):
    """既有 pack_id 缺 analysis.lemma_seq → 只补该字段；列与 pack_json 其余键逐字段不变。"""
    db_path = str(tmp_path / "encounter_seed.db")
    src = PRESET_ENCOUNTER_PACKS[0]
    old_pack = copy.deepcopy(src)
    del old_pack["analysis"]["lemma_seq"]
    database.import_encounter_pack(old_pack, db_path=db_path)

    before = _row_by_pack_id(db_path, src["pack_id"])
    before_pack = json.loads(before["pack_json"])
    assert "lemma_seq" not in before_pack["analysis"], "前置：旧行应确缺 lemma_seq"

    imported = database.seed_preset_encounter_texts(db_path)
    assert imported == 6, f"只补空不算新建：应只新建其余 6 个缺失预置，实际 {imported}"

    after = _row_by_pack_id(db_path, src["pack_id"])
    for col in ("title", "level", "content", "source", "created_at"):
        assert after[col] == before[col], f"补分析序列不得触碰其它列：{col}"

    after_pack = json.loads(after["pack_json"])
    # 补装只应**新增** analysis.lemma_seq，不得改动 pack_json 任何其它键：
    # 变异「把 analysis 整体替换为 {lemma_seq}」会丢掉 tokens_total / known_count /
    # known_rate / unknown_lemmas / level_hint 或顶层键 → 下面两条断言必红。
    assert {k: v for k, v in after_pack["analysis"].items() if k != "lemma_seq"} == {
        k: v for k, v in before_pack["analysis"].items() if k != "lemma_seq"
    }, "补装只应新增 lemma_seq，analysis 其余键必须逐字段不变"
    assert {k: v for k, v in after_pack.items() if k != "analysis"} == {
        k: v for k, v in before_pack.items() if k != "analysis"
    }, "补装不得改动 pack_json 顶层其余键"

    seq = after_pack["analysis"]["lemma_seq"]
    assert seq == src["analysis"]["lemma_seq"] and len(seq) > 0, "缺失的 lemma_seq 应补为新包的非空序列"


def test_seed_does_not_overwrite_nonempty_lemma_seq(tmp_path):
    """既有 lemma_seq 非空（哨兵值）→ 不覆盖（能力闸门：只补空）。"""
    db_path = str(tmp_path / "encounter_seed.db")
    src = PRESET_ENCOUNTER_PACKS[0]
    pid = src["pack_id"]
    database.import_encounter_pack(src, db_path=db_path)

    packed = json.loads(_row_by_pack_id(db_path, pid)["pack_json"])
    packed["analysis"]["lemma_seq"] = ["__SENTINEL__"]
    with database.db_conn(db_path) as conn:
        conn.execute(
            "UPDATE encounter_texts SET pack_json = ? WHERE pack_id = ?",
            (json.dumps(packed, ensure_ascii=False), pid),
        )

    database.seed_preset_encounter_texts(db_path)
    after_seq = json.loads(_row_by_pack_id(db_path, pid)["pack_json"])["analysis"]["lemma_seq"]
    assert after_seq == ["__SENTINEL__"], "非空序列（哨兵）不得被覆盖"


# ── 5. 逐包异常隔离 ───────────────────────────────────────────────────────────
def test_seed_survives_single_pack_failure(tmp_path, monkeypatch, caplog):
    """单个包导入失败 → logging.error、其余包继续导入、不崩启动。"""
    db_path = str(tmp_path / "encounter_seed.db")
    good = PRESET_ENCOUNTER_PACKS[0]
    bad = {"schema": "encounter-pack/v1", "pack_id": "seed-corpus-broken", "article": {}}
    monkeypatch.setattr(
        "delector.data.encounter_seed_dict.PRESET_ENCOUNTER_PACKS",
        [bad, good],
    )

    with caplog.at_level(logging.ERROR):
        imported = database.seed_preset_encounter_texts(db_path)

    assert imported == 1, f"坏包失败、其余包继续：应只成功 1 个，实际 {imported}"
    assert _count_encounter_rows(db_path) == 1
    assert _row_by_pack_id(db_path, good["pack_id"]) is not None, "好包应已落库"
    assert any("seed_preset_encounter_texts" in r.getMessage() for r in caplog.records), "包失败必须 logging.error"


def test_seed_survives_non_dict_pack(tmp_path, monkeypatch, caplog):
    """列表里混入非 dict 项（损坏数据模块）→ 不得外溢崩启动；正常包照常落库。

    真实逃逸路径：``_try_seed_or_backfill_preset_pack`` 的 except 日志行若用
    ``(pack or {}).get("pack_id")``，非空**非 dict** 项会在**日志行再次** .get 抛
    AttributeError → 异常逃逸出整个 seeder → 违反「单包失败不得崩启动」→ 本用例必红。
    """
    db_path = str(tmp_path / "encounter_seed.db")
    good = PRESET_ENCOUNTER_PACKS[0]
    monkeypatch.setattr(
        "delector.data.encounter_seed_dict.PRESET_ENCOUNTER_PACKS",
        ["not-a-dict", good],
    )

    with caplog.at_level(logging.ERROR):
        imported = database.seed_preset_encounter_texts(db_path)  # 旧实现此处会抛 AttributeError

    assert imported == 1, f"非 dict 项失败、正常包继续：应只成功 1 个，实际 {imported}"
    assert _row_by_pack_id(db_path, good["pack_id"]) is not None, "正常包应已落库"
    assert any("seed_preset_encounter_texts" in r.getMessage() for r in caplog.records), "失败包必须 logging.error"


# ── 6. 脚本可复现 ─────────────────────────────────────────────────────────────
def test_build_script_deterministic(tmp_path):
    """subprocess 跑两次（固定 --created-at）→ 字节一致；spaCy 不可用则 skip。"""
    pytest.importorskip("spacy")
    try:
        from delector.nlp_engine import processor
    except Exception:  # pragma: no cover - 环境相关
        pytest.skip("delector.nlp_engine 不可导入")
    if getattr(processor, "nlp", None) is None:
        pytest.skip("spaCy 德语模型不可用，脚本会 SystemExit：环境缺失跳过")

    out_a = tmp_path / "seed_a.py"
    out_b = tmp_path / "seed_b.py"
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    for out in (out_a, out_b):
        proc = subprocess.run(
            [sys.executable, _BUILD_SCRIPT, "--out", str(out), "--created-at", "2026-09-10"],
            cwd=_REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            pytest.skip(f"脚本退出码 {proc.returncode}（环境缺失）：{proc.stderr[-200:]}")

    assert out_a.read_bytes() == out_b.read_bytes(), "同输入两次产物必须字节一致"
    # 产物非空且含期望符号，避免"两次都产出空文件也算一致"的假绿。
    text = out_a.read_text(encoding="utf-8")
    assert "PRESET_ENCOUNTER_PACKS" in text and "seed-corpus-" in text


# ── 7. 静态探针：create_app 函数体确实调用 seeder ─────────────────────────────
def test_create_app_calls_seed_encounter_texts():
    """AST 定位 create_app 函数体，断言其内部真的调用 seed_preset_encounter_texts。

    不用"整个文件出现过该字符串"——该字符串在 import 行 / __all__ 也出现，是死断言；
    必须切到 create_app 函数体。
    """
    src = open(_SERVER_SRC, encoding="utf-8").read()
    tree = ast.parse(src)

    create_app = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "create_app":
            create_app = node
            break
    assert create_app is not None, "server.py 中找不到 create_app 定义"

    # 仅取 create_app 函数体的调用名（排除 def 行、嵌套函数等噪声）。
    called = set()
    for child in ast.walk(create_app):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)

    assert "seed_preset_encounter_texts" in called, "create_app 函数体内未见 seed_preset_encounter_texts 调用"


def test_create_app_seed_order_after_articles():
    """接线顺序：seed_preset_encounter_texts 的源码位置应在 seed_preset_articles 之后。"""
    src = open(_SERVER_SRC, encoding="utf-8").read()
    tree = ast.parse(src)
    create_app = next(
        n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "create_app"
    )

    # 用行号定位两条调用的先后（函数体内唯一出现）。
    def _first_call_lineno(name):
        for child in ast.walk(create_app):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == name:
                return child.lineno
        return None

    art = _first_call_lineno("seed_preset_articles")
    enc = _first_call_lineno("seed_preset_encounter_texts")
    assert art is not None and enc is not None
    assert enc > art, "encounter seeder 必须在 seed_preset_articles 之后调用"


# ── 变异自检推演表（断言纪律 PYTHON-STANDARDS §8.2 要求）──────────────────────
_MUTATION_TABLE = textwrap.dedent(
    """
| 变异 | 预期变红的用例 | 说明 |
| --- | --- | --- |
| 删掉 seeder 的版本早退（`version >= PRESET_SEED_VERSION` 提前返回） | """
    """test_seed_idempotent / test_seed_version_gate_shortcircuits_on_empty_db / """
    """test_seed_does_not_resurrect_deleted_preset | 热路径失效 → 二次调用重复插入 / 复活已删行 → red |
| 把「只补空」改成无条件覆盖 lemma_seq | test_seed_does_not_overwrite_nonempty_lemma_seq | """
    """哨兵值被新序列覆盖 → red |
| 把 `_backfill_pack_lemma_seq` 的合并行改成 `patched["analysis"] = {"lemma_seq": new_seq}` | """
    """test_seed_backfills_missing_lemma_seq_only | 丢掉 analysis 其余键（tokens_total/known_count/"""
    """known_rate/unknown_lemmas/level_hint）→ red（R1 核心变异，本轮必红）|
| 把 except 日志行改回 `(pack or {}).get("pack_id")` | test_seed_survives_non_dict_pack | """
    """非空非 dict 项在日志行二次 .get 抛 AttributeError 逃逸 → red |
| 把 `_read_preset_seed_version` 改回走 `get_setting`（含 env 兜底） | """
    """test_seed_version_gate_ignores_env_pollution | env 强灌 encounter_seed_version=99 误热退 → red |
| 二次调用改写既有行 pack_json | test_seed_idempotent | 版本闸早退后 pack_json 仍被改 → red |
| 把逐包循环改成只处理第一个包 | test_seed_empty_db_imports_all_and_writes_version / """
    """test_seed_nonempty_db_only_adds_missing_presets | 行数骤减、返回非 7 → red |
| 去掉 seeder 的逐包 try/except 异常隔离 | test_seed_survives_single_pack_failure | """
    """坏包直接抛出 → 用例崩溃、好包未落库 → red |
| 「只增」改成「覆盖已存在行」 | test_seed_nonempty_db_only_adds_missing_presets / """
    """test_seed_backfills_missing_lemma_seq_only | 用户行 / 既有行的 title 等列被改写 → red |
| 去掉 create_app 里的 seeder 调用 | test_create_app_calls_seed_encounter_texts / """
    """test_create_app_seed_order_after_articles | AST 找不到调用 → red |
| 把 seeder 调用移到 seed_preset_articles 之前 | test_create_app_seed_order_after_articles | enc 行号 < art 行号 → red |
| 改坏某包包结构（删 article.raw_text） | test_packs_pass_validate_pack / """
    """test_packs_article_text_is_german_prose | validate_pack 抛 ValueError / 空正文 → red |
| 两包复用同一 pack_id | test_packs_pack_id_globally_unique | 去重集合比长度短 → red |
| 把正文换成英文 | test_packs_article_text_is_german_prose | 无变音/无德语功能词 → red |
| 去掉 _annotate_lemma_seq 的 `is_space` 过滤 | test_annotate_lemma_seq_drops_space_keeps_punct | """
    """人工 fixture 带空白 token → 结果多出 " " → red（真实语料 space==0，聚合测试不红） |
| 把 _DEFAULT_LEVELS 改回 "A1,A2" | test_packs_pass_validate_pack / test_packs_cefr_whitelist / """
    """test_seed_empty_db_imports_all_and_writes_version | 篇数回落 4 → red |
"""
)
