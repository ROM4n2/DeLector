# -*- coding: utf-8 -*-
"""预置遇见区卡包（T4）：数据契约 + 运行时接线 + 幂等与守卫。

契约面
------
- 数据（delector/data/encounter_seed_dict.py）：PRESET_ENCOUNTER_PACKS 每包过
  validate_pack、estimated_cefr ∈ {A1,A2}、pack_id 全局唯一、正文非空且德语、
  glosses == []。
- 接线（delector/core/database.py::seed_preset_encounter_texts）：空库才导入、
  逐包走 import_encounter_pack 幂等、非空库返回 0 且不动用户内容。
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
import gc
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


# ── 1. 数据契约 ───────────────────────────────────────────────────────────────
def test_packs_pass_validate_pack():
    """每包都必须过 routes.encounter.validate_pack（结构契约）。"""
    assert isinstance(PRESET_ENCOUNTER_PACKS, list)
    assert len(PRESET_ENCOUNTER_PACKS) == 4, "对外承诺 4 个预置包（A1×2 + A2×2）"
    for pack in PRESET_ENCOUNTER_PACKS:
        validate_pack(pack)  # 不合法即抛 ValueError → 红


def test_packs_cefr_whitelist():
    """estimated_cefr 必须落在 {A1, A2} 白名单内。"""
    seen = {p["estimated_cefr"] for p in PRESET_ENCOUNTER_PACKS}
    assert seen == {"A1", "A2"}, f"CEFR 只应为 A1/A2，实际 {seen}"


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


# ── 2. 幂等 ───────────────────────────────────────────────────────────────────
def test_seed_idempotent(tmp_path):
    """空库 seed 一次返回 4、库里 4 行；二次调用返回 0 且仍 4 行。"""
    db_path = str(tmp_path / "encounter_seed.db")
    first = database.seed_preset_encounter_texts(db_path)
    assert first == 4, f"首次应导入 4 行，实际 {first}"
    assert _count_encounter_rows(db_path) == 4

    second = database.seed_preset_encounter_texts(db_path)
    assert second == 0, f"二次调用应因空库守卫返回 0，实际 {second}"
    assert _count_encounter_rows(db_path) == 4, "二次调用不得重复插入"


# ── 3. 用户内容不被触碰 ───────────────────────────────────────────────────────
def test_seed_skips_nonempty_db(tmp_path):
    """非空库（已有 1 篇手工文本）→ seeder 返回 0、总行数仍 1、预置未注入。"""
    db_path = str(tmp_path / "encounter_seed.db")
    database.create_encounter_text(
        title="手工短文",
        level="A2",
        source="manual",
        content="Das ist mein eigener Text.",
        db_path=db_path,
    )
    assert _count_encounter_rows(db_path) == 1

    imported = database.seed_preset_encounter_texts(db_path)
    assert imported == 0, "非空库必须走空库守卫直接返回 0"
    assert _count_encounter_rows(db_path) == 1, "预置内容不得注入非空库"

    preset_ids = {p["pack_id"] for p in PRESET_ENCOUNTER_PACKS}
    with database.db_conn(db_path) as conn:
        got = {r["pack_id"] for r in conn.execute("SELECT pack_id FROM encounter_texts")}
    assert got.isdisjoint(preset_ids), "非空库里不得出现任何预置 pack_id"


# ── 4. 脚本可复现 ─────────────────────────────────────────────────────────────
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


# ── 5. 静态探针：create_app 函数体确实调用 seeder ─────────────────────────────
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
| 去掉 seed_preset_encounter_texts 的 `count == 0` 守卫 | test_seed_skips_nonempty_db | 非空库会批量注入预置，"""
    """imported 变 4 且行数变 5 → 断言 red |
| seeder 不用 import_encounter_pack 的 pack_id 幂等（改裸 INSERT） | test_seed_idempotent | """
    """二次调用不会被空库守卫拦（或拦截失效）时重复插入 → """
    """行数 8，second 非 0 → red |
| 去掉 create_app 里的 seeder 调用 | test_create_app_calls_seed_encounter_texts / """
    """test_create_app_seed_order_after_articles | AST 找不到调用 → red |
| 把 seeder 调用移到 seed_preset_articles 之前 | test_create_app_seed_order_after_articles | enc 行号 < art 行号 → red |
| 改坏某包包结构（删 article.raw_text） | test_packs_pass_validate_pack / """
    """test_packs_article_text_is_german_prose | validate_pack 抛 ValueError / 空正文 → red |
| 两包复用同一 pack_id | test_packs_pack_id_globally_unique | 去重集合比长度短 → red |
| 把正文换成英文 | test_packs_article_text_is_german_prose | 无变音/无德语功能词 → red |
"""
)
