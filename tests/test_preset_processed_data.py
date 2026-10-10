# -*- coding: utf-8 -*-
"""预置文章预生成数据（spaCy 口径）的守门测试（子计划 2A）。

要消灭的缺陷
------------
预置文章落库原走纯 Python 口径且**故意不带 version**，靠既有「惰性迁移」在首次打开时升级为
spaCy 口径 ⇒ 列表（纯 Python 口径）与详情（spaCy 口径）难度不同，用户看到「列表显示 A2 →
点进去变成 A1」的跳变。根因：预置文本是**随代码发布的固定文本**，却把「算准」推迟到了运行时。

钉住什么（防恒真）
------------------
1. 数据文件存在、可解析、schema 可识别；
2. **覆盖每一篇** PRESET_ARTICLES（按文本哈希逐篇断言，缺一篇即红）；
3. 每个条目 version == PROCESSED_JSON_VERSION（**「不会再跳变」的判据**）+ 顶层口径一致；
4. **无多余条目**（预置文本改了却忘了重生成 ⇒ 必红）；
5. 运行时**命中**预生成数据（落库即 spaCy 口径 + version）；
6. 运行时**未命中回退可见**（WARNING + 纯 Python 口径）——不许静默降级。

口径一致性（生成器 ↔ 服务端）
------------------------------
生成器与服务端**共用同一个 `process_german_text`** 与同一个 `preset_text_hash`，并以
`PROCESSED_JSON_VERSION` 校验；条目里记下生成时的模型名，运行/CI 与本机模型一致时再做
逐字比对（模型不同则 skip —— 换机/换模型属预期，不是回归）。
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterator

import pytest

from delector.core import database
from delector.nlp_engine.processor import PROCESSED_JSON_VERSION

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """每个用例：库路径钉进 tmp、并清掉预生成数据缓存（防跨用例串味）。"""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("PROGRESS_DB_PATH", str(tmp_path / "t_progress.db"))
    database._reset_preset_processed_cache()
    yield
    database._reset_preset_processed_cache()


def _load_data() -> Dict[str, Any]:
    """读预生成数据文件；缺失即 fail 并给出可操作提示。"""
    path = Path(database.preset_processed_data_path())
    assert path.is_file(), (
        f"缺少预生成数据文件：{path}\n"
        "它是预置文章 spaCy 口径 processed_json 的单一真相；用 `python tools/gen_preset_processed.py` 生成。"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"数据文件顶层必须是 JSON 对象，实际 {type(data).__name__}"
    return data


def test_data_file_exists_parsable_and_schema_recognized() -> None:
    """① 数据文件存在、可解析、schema 可识别。"""
    data = _load_data()
    assert data.get("schema") == database.PRESET_PROCESSED_SCHEMA, (
        f"schema 不可识别：{data.get('schema')!r}（期望 {database.PRESET_PROCESSED_SCHEMA!r}）"
    )
    assert data.get("processed_json_version") == PROCESSED_JSON_VERSION, (
        "顶层 processed_json_version 与当前 PROCESSED_JSON_VERSION 不一致——数据已过期，需重生成"
    )
    assert isinstance(data.get("entries"), dict) and data["entries"], "entries 必须是非空映射"


def test_covers_every_preset_article() -> None:
    """② 覆盖每一篇 PRESET_ARTICLES（按文本哈希逐篇断言，缺一篇即红）。"""
    entries = _load_data()["entries"]
    expected = {database.preset_text_hash(art["text"]): art["title"] for art in database.PRESET_ARTICLES}
    missing = sorted(title for text_hash, title in expected.items() if text_hash not in entries)
    assert not missing, (
        f"预生成数据缺这些预置文章：{missing}\n"
        "——生成器漏跑，或预置文本改了却没重跑 `python tools/gen_preset_processed.py`。"
    )


def test_has_no_extra_entries() -> None:
    """④ 无多余条目：数据文件里的键必须**恰是**当前 PRESET_ARTICLES 的文本哈希集合。"""
    entries = _load_data()["entries"]
    expected = {database.preset_text_hash(art["text"]) for art in database.PRESET_ARTICLES}
    extra = sorted(text_hash for text_hash in entries if text_hash not in expected)
    assert not extra, (
        f"预生成数据有 {len(extra)} 条多余条目（其文本已不在 PRESET_ARTICLES）：{extra[:5]}\n"
        "——预置文本被改/删，但数据文件没重新生成；陈旧条目会让守卫误判为「已覆盖」。"
    )


def test_every_entry_carries_current_version() -> None:
    """③ 每条 version == PROCESSED_JSON_VERSION ——「首次打开不会再跳变」的判据。

    只要条目 version 等于当前版本，单篇 GET 的惰性迁移判据（`pj.get("version") !=
    PROCESSED_JSON_VERSION`）就不成立 ⇒ 不会再重算 ⇒ 列表预览与详情一致。
    """
    entries = _load_data()["entries"]
    bad = [
        text_hash
        for text_hash, entry in entries.items()
        if not isinstance(entry, dict) or entry.get("version") != PROCESSED_JSON_VERSION
    ]
    assert not bad, f"这些条目的 version 缺或与当前 {PROCESSED_JSON_VERSION} 不一致：{bad}"
    nested_bad = [
        text_hash
        for text_hash, entry in entries.items()
        if not isinstance(entry.get("processed"), dict)
        or entry["processed"].get("version") != PROCESSED_JSON_VERSION
    ]
    assert not nested_bad, f"这些条目内层 processed.version 与当前不一致：{nested_bad}"


def test_runtime_seed_uses_pregenerated_spacy_json(tmp_path: Path) -> None:
    """⑤ 行为级：预置文章落库即用**预生成**数据（含 version）⇒ 首次打开不再惰性迁移跳变。"""
    db_path = str(tmp_path / "seed.db")
    database.init_db(db_path)
    entries = _load_data()["entries"]
    with database.db_conn(db_path) as conn:
        rows = conn.execute("SELECT raw_text, processed_json FROM articles").fetchall()
    by_hash = {database.preset_text_hash(row["raw_text"]): row["processed_json"] for row in rows}
    assert by_hash, "预置文章没被 seed 进库"
    for art in database.PRESET_ARTICLES:
        text_hash = database.preset_text_hash(art["text"])
        assert text_hash in by_hash, f"预置文章未落库：{art['title']}"
        stored = json.loads(by_hash[text_hash])
        assert stored.get("version") == PROCESSED_JSON_VERSION, (
            f"落库 processed_json 缺 version（{art['title']}）⇒ 首次打开会跳变"
        )
        assert stored == entries[text_hash]["processed"], (
            f"落库内容与预生成数据不一致（{art['title']}）——运行时没走预生成口径"
        )


def test_missing_data_file_falls_back_visibly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """⑥ 未命中/文件缺失 ⇒ **可见** WARNING + 回退纯 Python 口径（不许静默降级）。"""
    monkeypatch.setattr(database, "preset_processed_data_path", lambda: str(tmp_path / "nope.json"))
    database._reset_preset_processed_cache()
    with caplog.at_level(logging.WARNING, logger="delector"):
        raw = database.preset_processed_json(database.PRESET_ARTICLES[0]["text"])
    warnings = [record for record in caplog.records if record.levelno >= logging.WARNING]
    assert warnings, "数据文件缺失必须打出**可见**告警（否则是静默降级）"
    parsed = json.loads(raw)
    assert "version" not in parsed, "回退路径是纯 Python 口径（**不带** version），靠惰性迁移在首次打开时升级"


def test_stored_entry_matches_live_output_when_model_matches() -> None:
    """口径一致性（生成器 ↔ 服务端）的行为级证据：模型一致时逐字相等，不同则 skip。

    生成器与服务端共用同一个 `process_german_text`（见 tools/gen_preset_processed.py）；本断言
    是它的**行为**补强：若生成器改用别的函数 / 旧版模型 / 手工拼 JSON，运行时同源时必红。
    运行时签名（spaCy 版本 + 模型名）与生成时不同（换机、CI 装到别的版本、本机装 md）属**预期**
    差异，skip 而非 fail —— `requirements` 是 `spacy>=3.8.16`（上不封顶），跨版本逐字比对会抖动。
    """
    from delector.nlp_engine import processor
    from delector.nlp_engine.processor import process_german_text

    data = _load_data()
    generated_runtime = str(data.get("runtime", "")).strip()
    art = database.PRESET_ARTICLES[0]
    live = process_german_text(art["text"])
    live_runtime = str(processor.NLP_ENGINE_DETAIL).strip()
    if generated_runtime and generated_runtime != live_runtime:
        pytest.skip(
            f"本机运行时 {live_runtime!r} 与生成时 {generated_runtime!r} 不同：口径比对不适用（属预期）"
        )
    assert live.get("version") == PROCESSED_JSON_VERSION
    assert data["entries"][database.preset_text_hash(art["text"])]["processed"] == live, (
        "预生成条目与本机现跑的 process_german_text 输出不一致 ⇒ 生成器与服务端口径漂移"
    )
