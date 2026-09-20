# -*- coding: utf-8 -*-
"""``delector.services.search`` 纯函数契约测试（spec 2026-09-20 §3.2 / §4，Task 1）。

TDD：先红后绿。覆盖
  - ``fold``：小写 + 德语变音折叠（ä/ö/ü/ß）+ 空白压缩；
  - 中文两字词子串命中（``公寓`` → ``wohnung``，FTS5 弃用理由的回归锚点）；
  - 德语变音折叠命中（``schon`` ↔ ``schön``）；
  - ``match_score`` 权重表逐条 + 取最高分；
  - 构造输入的排序：hw 精确(100) > 前缀(60) > 子串(40)；
  - 同分按 ``id`` 升序稳定序；
  - ``scope`` 过滤（非 all 只回该组；**定向 scope 不去重**，完整返回该组）；
  - ``limit`` 钳制 1..100（0/负 → 1，>100 → 100；100 为精确边界）；
  - 空 / 单字符 q → 四组空数组、``total==0``、绝不抛错；空 ``q_folded`` → 0；
  - vocab 优先去重**仅 scope='all'**（定向例如 example 保留目标词自身例句）。
"""

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Tuple, cast

from delector.services.search import (
    SearchDoc,
    _snippet,
    fold,
    iter_corpus_docs,
    iter_vocab_docs,
    match_score,
    search,
)

# ── 构造用 doc 工厂（注入 corpus_docs 用，避免依赖真实词库的偶然分布）──────────


def _doc(**over: Any) -> SearchDoc:
    base: Dict[str, Any] = {
        "kind": "vocab",
        "id": "x",
        "lemma": "",
        "hw": "",
        "pos": "",
        "cefr": "",
        "fields": {},
        "payload": {},
    }
    base.update(over)
    return cast(SearchDoc, base)


# ── 1. fold：小写 + 变音 + ß + 空白压缩 ───────────────────────────────────────


def test_fold_lowercases_diacritics_and_ss():
    """变音折叠：ä→a / ö→o / ü→u / ß→ss，大小写归一。"""
    assert fold("Schön") == "schon"
    assert fold("Straße") == "strasse"
    assert fold("STRASSE") == "strasse"
    assert fold("Ärger") == "arger"
    assert fold("über") == "uber"


def test_fold_collapses_whitespace():
    """连续空白压缩为单空格并 strip。"""
    assert fold("  A   B ") == "a b"
    assert fold(" a\t\tb\n") == "a b"


# ── 2. 中文两字词子串命中（放弃 FTS5 的核心依据）─────────────────────────────


def test_search_chinese_two_char_substring_hits_wohnung():
    """``公寓`` 两字词应命中词条 ``wohnung``（FTS5 trigram ≥3 字符会漏掉）。"""
    res = search("公寓")
    vocab_lemmas = [d["lemma"] for d in res["groups"]["vocab"]]
    assert "wohnung" in vocab_lemmas


def test_constructed_chinese_two_char_substring_hits():
    """构造对照（Y4）：中文两字词命中**合成 doc** 的 ``def_zh``，不依赖真实词库分布。

    与 ``..._wohnung`` 真数据断言互为对照：即便真实词库分布变动，本用例仍锁死
    「两字中文子串可命中」这一语义（``match_score`` 权重 25）。
    """
    doc = _doc(kind="vocab", id="zzz", lemma="zzz", hw="zzz", fields={"def_zh": "公寓，住宅"})
    assert match_score("公寓", doc) == 25
    res = search("公寓", corpus_docs=[doc])
    assert "zzz" in [d["id"] for d in res["groups"]["vocab"]]


# ── 3. 德语变音折叠命中例句 ───────────────────────────────────────────────────


def test_search_diacritic_query_folds_to_example():
    """``schon``（无变音）应命中含 ``schön``（有变音）的例句。"""
    res = search("schon")
    examples = res["groups"]["example"]
    assert examples, "应至少命中一条含 schön 的例句"
    assert any("schön" in d["fields"].get("example_de", "") for d in examples)
    # 折叠等价：schön 与 schon 折叠后同为 schon → 命中集合一致
    res_umlaut = search("schön")
    assert [d["id"] for d in res_umlaut["groups"]["example"]] == [
        d["id"] for d in examples
    ]


# ── 4. match_score 权重表（逐条 + 取最高分）──────────────────────────────────


def test_match_score_weight_table():
    """权重表逐条：hw/lemma 精确 100 / 前缀 60 / 子串 40；各字段 25/20/18/15/12/8。"""
    assert match_score("haus", _doc(lemma="haus", hw="haus")) == 100
    assert match_score("haus", _doc(lemma="hausaufgabe", hw="hausaufgabe")) == 60
    assert match_score("haus", _doc(lemma="bauhaus", hw="bauhaus")) == 40
    assert match_score("公寓", _doc(lemma="wohnung", hw="wohnung", fields={"def_zh": "公寓，住所"})) == 25
    assert match_score("auf", _doc(fields={"prep": "auf"})) == 20
    assert match_score("akk", _doc(fields={"case": "Akk"})) == 20
    assert match_score("着眼", _doc(fields={"colloc_zh": "着眼于"})) == 20
    assert match_score("wetter", _doc(fields={"example_de": "Das Wetter ist schön."})) == 15
    assert match_score("天气", _doc(fields={"example_zh": "今天天气好。"})) == 12
    assert match_score("heute", _doc(fields={"title": "Heute Journal"})) == 18
    assert match_score("artikel", _doc(fields={"text": "ein langer Artikel"})) == 8
    assert match_score("zxq", _doc(lemma="haus", hw="haus")) == 0


def test_match_score_takes_highest_only():
    """同一 doc 多处命中 → 取最高分（hw 精确 100 压过 def_zh 25）。"""
    doc = _doc(lemma="haus", hw="haus", fields={"def_zh": "房屋，房子"})
    assert match_score("haus", doc) == 100


def test_match_score_empty_field_is_safe():
    """空 ``q_folded`` 守卫（Y2/Y3）：空 q → 0，且空字段不误命中、不抛错。

    若删去 ``if not q_folded: return 0`` 顶部守卫，前两条断言必红：
      - 非空词头 + 空 q：``startswith('')`` 恒真 → 60；
      - 空字段 + 空 q：``'' in ''`` 恒真 → def_zh 权重 25。
    """
    assert match_score("", _doc(lemma="haus", hw="haus")) == 0
    assert match_score("", _doc(lemma="", hw="", fields={"def_zh": ""})) == 0
    # 空字段不误命中（空串不包含非空 q），且不抛错。
    assert match_score("haus", _doc(lemma="", hw="", fields={"def_zh": ""})) == 0


# ── 5. 排序：构造输入断言精确 > 前缀 > 子串 ──────────────────────────────────


def test_constructed_order_exact_then_prefix_then_substring():
    """构造 3 条输入：hw 精确(100) 排在 前缀(60) 之前，再排在 子串(40) 之前。"""
    docs = [
        _doc(kind="vocab", id="sub", lemma="bazqx", hw="bazqx"),
        _doc(kind="vocab", id="exact", lemma="zqx", hw="zqx"),
        _doc(kind="vocab", id="pre", lemma="zqxfoo", hw="zqxfoo"),
    ]
    res = search("zqx", corpus_docs=docs)
    assert [d["id"] for d in res["groups"]["vocab"]] == ["exact", "pre", "sub"]


def test_hw_exact_precedes_prefix_precedes_substring_realdata():
    """真实数据：``haus`` 精确命中排首，``haus*`` 前缀排在 ``*haus`` 子串之前。"""
    vocab = [d["lemma"] for d in search("haus")["groups"]["vocab"]]
    assert vocab[0] == "haus"
    assert vocab.index("hausaufgabe") < vocab.index("krankenhaus")


def test_constructed_haus_like_order_exact_prefix_substring():
    """构造对照（Y4，haus 同形）：合成精确/前缀/子串各一条，断言 100>60>40 的稳定序。

    与 ``..._realdata`` 互为对照：即便真实词库分布变动，本用例仍锁死排序语义。
    查询 ``hauszqx`` 为合成串，不与真实词库任何 lemma 碰撞。
    """
    docs = [
        _doc(kind="vocab", id="sub", lemma="krankenhauszqx", hw="krankenhauszqx"),
        _doc(kind="vocab", id="exact", lemma="hauszqx", hw="hauszqx"),
        _doc(kind="vocab", id="pre", lemma="hauszqxab", hw="hauszqxab"),
    ]
    res = search("hauszqx", corpus_docs=docs)
    assert [d["id"] for d in res["groups"]["vocab"]] == ["exact", "pre", "sub"]


# ── 6. 同分按 id 升序（稳定）────────────────────────────────────────────────


def test_equal_score_sorted_by_id_ascending():
    """同分同 kind → 按 id 升序稳定排序。"""
    docs = [
        _doc(kind="corpus", id="b", fields={"text": "zqx tail"}),
        _doc(kind="corpus", id="a", fields={"text": "zqx head"}),
    ]
    res = search("zqx", corpus_docs=docs)
    assert [d["id"] for d in res["groups"]["corpus"]] == ["a", "b"]


# ── 7. scope 过滤 ────────────────────────────────────────────────────────────


def test_scope_example_only_returns_example_group():
    """scope='example' → 仅例句组**非空**且含目标词自身例句，其余三组空数组。"""
    res = search("wohnung", scope="example")
    assert res["groups"]["vocab"] == []
    assert res["groups"]["colloc"] == []
    assert res["groups"]["corpus"] == []
    # Y1：定向 scope 不去重 → 例句组必非空，且包含 wohnung 自身例句 doc。
    assert res["groups"]["example"], "scope='example' 必须完整返回例句组（非空）"
    assert any(
        d["id"] == "wohnung" and "Wohnung" in d["fields"].get("example_de", "")
        for d in res["groups"]["example"]
    )


def test_scope_example_not_swallowed_by_vocab_constructed():
    """构造对照（Y1）：同 lemma 同时命中 vocab 与 example → scope='example' 保留该例句。"""
    docs = [
        _doc(kind="vocab", id="zqx", lemma="zqx", hw="zqx", fields={"def_zh": "构造词"}),
        _doc(
            kind="example",
            id="zqx",
            lemma="zqx",
            hw="zqx",
            fields={"example_de": "Das ist ein zqx Satz."},
        ),
    ]
    only_ex = search("zqx", scope="example", corpus_docs=docs)
    assert [d["id"] for d in only_ex["groups"]["example"]] == ["zqx"]
    assert only_ex["groups"]["vocab"] == []


def test_scope_all_still_dedups_same_lemma_example():
    """Y1 对照：scope='all' 仍去重 → wohnung 词条命中，例句组不重复 wohnung lemma。"""
    res = search("wohnung", scope="all")
    vocab_lemmas = [d["lemma"] for d in res["groups"]["vocab"]]
    example_lemmas = [d["lemma"] for d in res["groups"]["example"]]
    assert "wohnung" in vocab_lemmas
    assert "wohnung" not in example_lemmas

    # 构造对照：同一合成 doc 集合在 all 下被去重（例句组空）。
    docs = [
        _doc(kind="vocab", id="zqx", lemma="zqx", hw="zqx"),
        _doc(
            kind="example",
            id="zqx",
            lemma="zqx",
            hw="zqx",
            fields={"example_de": "Das ist ein zqx Satz."},
        ),
    ]
    res_c = search("zqx", corpus_docs=docs)
    assert [d["id"] for d in res_c["groups"]["vocab"]] == ["zqx"]
    assert res_c["groups"]["example"] == []


def test_scope_vocab_only_returns_vocab_group():
    """scope='vocab' → 仅词条组非空，其余三组为空数组。"""
    res = search("wohnung", scope="vocab")
    assert [d["lemma"] for d in res["groups"]["vocab"]][:1] == ["wohnung"]
    assert res["groups"]["example"] == []
    assert res["groups"]["colloc"] == []
    assert res["groups"]["corpus"] == []


def test_invalid_scope_treated_as_all():
    """非法 scope 由路由层 400；纯函数收到非法值按 'all' 处理（一致且不抛错）。"""
    res_bad = search("wohnung", scope="bogus")
    res_all = search("wohnung")
    assert res_bad["groups"] == res_all["groups"]
    assert res_bad["total"] == res_all["total"]


# ── 8. limit 钳制 1..100 ─────────────────────────────────────────────────────


def test_limit_clamped_high_to_100():
    """limit=999 钳到 100：高频查询每组恰 ≤100。"""
    res = search("en", limit=999)
    assert len(res["groups"]["vocab"]) == 100
    assert all(len(v) <= 100 for v in res["groups"].values())


def test_limit_clamped_low_to_1():
    """limit=0 / 负 → 钳到 1：每组恰 ≤1。"""
    for bad_limit in (0, -5):
        res = search("en", limit=bad_limit)
        assert len(res["groups"]["vocab"]) == 1
        assert all(len(v) <= 1 for v in res["groups"].values())


def test_limit_exact_upper_boundary_100_and_101():
    """精确边界（Y2）：limit=100 不被下钳；limit=101 上钳到 100（同 100 条）。

    用 150 条合成命中：limit=100 取满 100（合法上限）；limit=101 上钳到 100，
    若未钳则应给出 101 条 —— 故两条结果须一致为 100 条。
    """
    docs = [
        _doc(kind="corpus", id=f"c{i:03d}", fields={"text": f"zqx item {i}"})
        for i in range(150)
    ]
    res100 = search("zqx", limit=100, corpus_docs=docs)
    res101 = search("zqx", limit=101, corpus_docs=docs)
    assert len(res100["groups"]["corpus"]) == 100
    assert len(res101["groups"]["corpus"]) == 100  # 101 上钳到 100 → 非 101
    assert [d["id"] for d in res101["groups"]["corpus"]] == [
        d["id"] for d in res100["groups"]["corpus"]
    ]
    assert res100["truncated"] is True  # 150 > 100 → 被截断


# ── 9. 空 / 单字符 q → 零结果、不抛错 ────────────────────────────────────────


def test_short_or_empty_query_returns_empty_groups_without_error():
    """fold 后长度 <2（空/单字符/纯空白）→ total=0、四组空数组、绝不抛错。"""
    for q in ("", "x", " ", "  a  "):
        res = search(q)
        assert res["total"] == 0
        assert res["groups"] == {"vocab": [], "example": [], "colloc": [], "corpus": []}


# ── 10. vocab 优先去重 ───────────────────────────────────────────────────────


def test_vocab_wins_dedup_over_same_lemma_example():
    """``aber`` 同时命中词条与例句 → 合并一条（词条优先），例句组不再重复该 lemma。"""
    res = search("aber")
    vocab_lemmas = [d["lemma"] for d in res["groups"]["vocab"]]
    example_lemmas = [d["lemma"] for d in res["groups"]["example"]]
    assert "aber" in vocab_lemmas
    assert "aber" not in example_lemmas
    all_lemmas = [
        d["lemma"] for group in res["groups"].values() for d in group if d["lemma"] == "aber"
    ]
    assert all_lemmas == ["aber"]


# ── 11. 响应形状 ─────────────────────────────────────────────────────────────


def test_response_shape_and_group_keys():
    """响应含 q/scope/total/groups/truncated，groups 键集固定为四类且均为列表。"""
    res = search("haus")
    assert set(res) == {"q", "scope", "total", "groups", "truncated"}
    assert set(res["groups"]) == {"vocab", "example", "colloc", "corpus"}
    assert all(isinstance(v, list) for v in res["groups"].values())


# ── 12. iter_vocab_docs：三源规范化 ─────────────────────────────────────────


def test_iter_vocab_docs_normalizes_three_sources():
    """三源规范：lexicon→vocab、RICH→example、PREP→colloc，字段/载荷按 spec。"""
    docs = list(iter_vocab_docs())
    by_id = {(d["kind"], d["id"]): d for d in docs}

    vocab = by_id[("vocab", "wohnung")]
    assert vocab["fields"]["hw"] == "wohnung"
    assert "公寓" in vocab["fields"]["def_zh"]
    assert vocab["payload"]["cefr"] == "A1"
    assert vocab["payload"]["pos"] == "NOUN"
    assert vocab["payload"]["gender"] == "Fem"
    assert vocab["payload"]["plural"] == "-en"

    example = by_id[("example", "aber")]
    assert "aber" in example["fields"]["example_de"]
    assert example["fields"]["example_zh"]
    assert example["payload"]["ipa"]

    colloc = by_id[("colloc", "abgeben:mit")]
    assert colloc["lemma"] == "abgeben"
    assert colloc["fields"]["prep"] == "mit"
    assert colloc["fields"]["case"] == "Dat"
    assert colloc["fields"]["colloc_zh"]
    assert colloc["fields"]["example_de"]


# ── 13. iter_corpus_docs：语料规范化 + hard cap（Task 2）─────────────────────
#
# 一律用 ``tmp_path`` 下的**临时 sqlite 库**（仅 articles + encounter_texts 最小
# schema），绝不触碰仓库根 ``delector.db``。查询串用合成 token ``Zorblax``，不与
# 真实词库任何 lemma 碰撞，避免真实数据分布导致断言偶发漂移。


def _make_corpus_db(tmp_path: Path) -> sqlite3.Connection:
    """建临时语料库（最小 schema，够 iter_corpus_docs 读即可）。"""
    conn = sqlite3.connect(str(tmp_path / "corpus.db"))
    conn.execute(
        "CREATE TABLE articles ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, raw_text TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE encounter_texts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, pack_id TEXT UNIQUE, title TEXT NOT NULL, "
        "level TEXT NOT NULL DEFAULT 'A2', content TEXT NOT NULL)"
    )
    return conn


def _seed_corpus(
    conn: sqlite3.Connection,
    articles: List[Tuple[str, str]],
    encounters: List[Tuple[str, str, str]] | None = None,
) -> None:
    """塞入语料：articles = [(title, raw_text)]；encounters = [(title, level, content)]。"""
    for title, text in articles:
        conn.execute("INSERT INTO articles (title, raw_text) VALUES (?, ?)", (title, text))
    for title, level, content in encounters or []:
        conn.execute(
            "INSERT INTO encounter_texts (title, level, content) VALUES (?, ?, ?)",
            (title, level, content),
        )
    conn.commit()


def test_iter_corpus_docs_normalizes_articles_and_encounters(tmp_path: Path) -> None:
    """2 篇 article + 1 篇 encounter → 3 条 corpus doc；字段/载荷按 spec，无 snippet。"""
    conn = _make_corpus_db(tmp_path)
    _seed_corpus(
        conn,
        articles=[
            ("Erster Artikel", "Zorblax steht im ersten Text."),
            ("Zweiter Artikel", "Zweiter Text ohne Treffer."),
        ],
        encounters=[("Begegnung", "A2", "Zorblax in einer Begegnung.")],
    )
    docs, truncated = iter_corpus_docs(conn)
    assert truncated is False
    assert len(docs) == 3
    assert all(d["kind"] == "corpus" for d in docs)
    by_id = {d["id"]: d for d in docs}
    assert set(by_id) == {"article:1", "article:2", "encounter:1"}

    art = by_id["article:1"]
    assert art["fields"]["title"] == "Erster Artikel"
    assert art["fields"]["text"] == "Zorblax steht im ersten Text."
    assert art["lemma"] == "" and art["hw"] == ""
    assert art["pos"] == "article" and art["cefr"] == ""
    assert art["payload"]["source"] == "article"
    assert art["payload"]["ref_id"] == 1
    assert art["payload"]["level"] == ""
    assert "snippet" not in art["payload"]  # snippet 依赖 q，只在 search 命中时补

    enc = by_id["encounter:1"]
    assert enc["pos"] == "encounter"
    assert enc["cefr"] == "A2"  # encounter 用 level 作 cefr
    assert enc["fields"]["text"] == "Zorblax in einer Begegnung."
    assert enc["payload"]["source"] == "encounter"
    assert enc["payload"]["title"] == "Begegnung"
    assert enc["payload"]["level"] == "A2"
    assert "snippet" not in enc["payload"]


def test_search_corpus_hit_adds_bounded_snippet(tmp_path: Path) -> None:
    """命中 corpus doc → payload 补 snippet：含查询片段且长度有界（≤ 2*radius+len(q)+4）。"""
    conn = _make_corpus_db(tmp_path)
    _seed_corpus(conn, articles=[("Bericht", "Ein kurzer Text mit Zorblax mitten drin.")])
    docs, _ = iter_corpus_docs(conn)
    res = search("Zorblax", corpus_docs=docs)
    group = res["groups"]["corpus"]
    assert [d["id"] for d in group] == ["article:1"]
    snippet = group[0]["payload"]["snippet"]
    assert "Zorblax" in snippet
    assert len(snippet) <= 2 * 80 + len("Zorblax") + 4


def test_search_does_not_mutate_caller_corpus_docs(tmp_path: Path) -> None:
    """纯度（Y2）：``search`` **不得改写调用方传入的** corpus doc。

    同一 ``corpus_docs`` 连调两次不同 q：若 ``search`` 就地写入 ``payload["snippet"]``，
    则入参 doc 会被污染且两次调用互相覆盖。断言入参每个 doc 的 ``payload`` 始终无
    ``snippet`` 键（第 4 行断言在“取消浅拷贝、恢复就地写入”的变异下必红）。
    返回值仍应各带对应 q 的 snippet（结果正确性不受拷贝影响）。
    """
    conn = _make_corpus_db(tmp_path)
    _seed_corpus(conn, articles=[("Bericht", "Ein Text mit Zorblax und Quuxor.")])
    docs, _ = iter_corpus_docs(conn)

    search("Zorblax", corpus_docs=docs)
    search("Quuxor", corpus_docs=docs)

    assert all("snippet" not in d["payload"] for d in docs)  # 入参不被改动

    res1 = search("Zorblax", corpus_docs=docs)
    assert "Zorblax" in res1["groups"]["corpus"][0]["payload"]["snippet"]
    res2 = search("Quuxor", corpus_docs=docs)
    assert "Quuxor" in res2["groups"]["corpus"][0]["payload"]["snippet"]


def test_corpus_title_hit_outranks_text_hit(tmp_path: Path) -> None:
    """同文本下 title 命中（18）排在 text 命中（8）之前。

    故意让 title 命中 doc 的 id（2）大于 text 命中 doc 的 id（1）——若权重写反/相等，
    回退到 id 升序会给出 [1, 2]，本断言必红。
    """
    conn = _make_corpus_db(tmp_path)
    _seed_corpus(
        conn,
        articles=[
            ("Reisebericht", "Hier steht Zorblax im Fliesstext."),  # text 命中（id=1）
            ("Zorblax Report", "Ein Bericht ohne das Suchwort."),  # title 命中（id=2）
        ],
    )
    docs, _ = iter_corpus_docs(conn)
    res = search("Zorblax", corpus_docs=docs)
    assert [d["id"] for d in res["groups"]["corpus"]] == ["article:2", "article:1"]


def test_empty_corpus_text_skipped(tmp_path: Path) -> None:
    """空正文 article 必须整体跳过（``"" in ""`` 恒真坑）。

    空正文那条的 title 故意含查询串：若删去空 text 跳过，它会被 title 命中混进结果，
    ``ids`` 与 corpus 组断言必红。
    """
    conn = _make_corpus_db(tmp_path)
    _seed_corpus(
        conn,
        articles=[
            ("Zorblax Leer", ""),  # 空正文 + 命中标题 → 必须整体跳过
            ("Zorblax Voll", "Echter Text mit Zorblax."),
        ],
    )
    docs, _ = iter_corpus_docs(conn)
    assert [d["id"] for d in docs] == ["article:2"]  # article:1 空正文被跳过
    res = search("Zorblax", corpus_docs=docs)
    assert [d["id"] for d in res["groups"]["corpus"]] == ["article:2"]


def test_iter_corpus_docs_hard_cap_max_docs_truncates(tmp_path: Path) -> None:
    """累计文档数达 max_docs → 停止且 truncated=True，doc 数受限于上限。"""
    conn = _make_corpus_db(tmp_path)
    _seed_corpus(
        conn,
        articles=[("A", "Zorblax eins."), ("B", "Zorblax zwei."), ("C", "Zorblax drei.")],
    )
    docs, truncated = iter_corpus_docs(conn, max_docs=1)
    assert truncated is True
    assert len(docs) == 1
    assert docs[0]["id"] == "article:1"


def test_iter_corpus_docs_hard_cap_max_chars_truncates(tmp_path: Path) -> None:
    """累计字符超 max_chars → 停止且 truncated=True。"""
    conn = _make_corpus_db(tmp_path)
    _seed_corpus(conn, articles=[("A", "Zorblax eins zwei drei.")])
    docs, truncated = iter_corpus_docs(conn, max_chars=1)
    assert truncated is True
    assert len(docs) == 0


def test_iter_corpus_docs_max_docs_exact_boundary_not_truncated(tmp_path: Path) -> None:
    """恰等边界（Y4）：文档数恰为 ``max_docs=N`` → ``truncated is False``。

    锁死 max_docs 的 off-by-one：3 条恰好收满、**不**被判为截断。若把收满判断写成
    「append 后再比 ``>=``」之类的错位写法，第 3 条会被当作已达上限而截断 → 本断言变红。
    """
    conn = _make_corpus_db(tmp_path)
    _seed_corpus(
        conn,
        articles=[("A", "Zorblax eins."), ("B", "Zorblax zwei."), ("C", "Zorblax drei.")],
    )
    docs, truncated = iter_corpus_docs(conn, max_docs=3)
    assert truncated is False
    assert len(docs) == 3


def test_iter_corpus_docs_max_chars_exact_boundary_not_truncated(tmp_path: Path) -> None:
    """恰等边界（Y4）：单篇 ``len(text)`` 恰为 ``max_chars`` → ``truncated is False``。

    实现用 ``total_chars + len(text) > max_chars``（**严格 ``>``**）：恰等收下、仅超一
    字符才截断。若误写成 ``>=``，则恰等即被判超限 → 本篇被丢且 ``truncated=True``，
    两条断言必红。
    """
    conn = _make_corpus_db(tmp_path)
    text = "Zorblax eins zwei drei."
    _seed_corpus(conn, articles=[("A", text)])
    docs, truncated = iter_corpus_docs(conn, max_chars=len(text))
    assert truncated is False
    assert len(docs) == 1
    assert docs[0]["fields"]["text"] == text


# ── 14. _snippet：上下文片段（命中定位 / 裁剪 / 变音近似）─────────────────────


def test_snippet_no_match_returns_empty() -> None:
    """未命中 / 空文本 / 空 q → 空串（不抛错）。"""
    assert _snippet("irgendein Text ohne Treffer", "zznotfound") == ""
    assert _snippet("", "ab") == ""
    assert _snippet("Text", "") == ""


def test_snippet_trims_long_text_to_bounded_context() -> None:
    """超长文本只返回有界上下文窗口，绝不整篇返回。"""
    text = ("x" * 500) + "Zorblax" + ("y" * 500)
    out = _snippet(text, "Zorblax")
    assert "Zorblax" in out
    assert len(out) <= 2 * 80 + len("Zorblax") + 4


def test_snippet_diacritic_query_locates_via_fold() -> None:
    """直接 find 未命中时走 fold 近似路径定位（ß→ss / ö→o）；位置近似可接受。"""
    out_ss = _snippet("Die Straße ist lang und die Straße ist schön.", "strasse")
    assert out_ss != ""
    assert "Straße" in out_ss

    out_umlaut = _snippet("Das Wetter ist schön heute.", "schon")
    assert out_umlaut != ""
    assert "schön" in out_umlaut
