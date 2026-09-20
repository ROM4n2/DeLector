# -*- coding: utf-8 -*-
"""例句 / 搭配 / 语料 全文检索纯函数（spec 2026-09-20 §3.2，Task 1+2）。

**内存扫描版**（ADR-0014：固定词库侧 ≈8175 条，全量扫描 <50ms，无需 FTS5）。
本模块覆盖两层：
  - Task 1：词库侧三源（``lexicon`` / ``prep_dict``）的 ``fold`` / ``iter_vocab_docs`` /
    ``match_score`` / ``search``；
  - Task 2：语料侧 ``iter_corpus_docs`` 以**只读**方式读取 ``articles`` /
    ``encounter_texts``（DB 连接 ``conn`` 由调用方经 ``db_conn`` 传入），并纳入同一
    ``search``。

零新依赖（仅 stdlib + 既有 ``lexicon`` / ``prep_dict``）。所有函数**只读、无副作用**：
不写库、**不改调用方传入的对象**（命中语料 doc 补 ``snippet`` 时走浅拷贝，见 ``search``）。

分层：
    lexicon.LEXICON / RICH / prep_dict.PREP_COLLOCATIONS   （代码常量真值）
                 \\            |            /
              delector/services/search.py  ← fold / iter_vocab_docs / iter_corpus_docs
                                              / match_score / search
                          |
              delector/routes/search.py    → GET /api/search（薄路由，校验 scope/limit）

纪律：
    - ``fold`` **仅用于匹配**，展示一律用原文；
    - 匹配用「折叠后子串」命中（这正是放弃 FTS5 的原因：中文两字词可命中，
      德语变音 schon↔schön / wohnung↔Wohnung / strasse↔straße 亦等价）；
    - 计分表见 ``match_score``；同分排序由 ``search`` 固定序（kind 序 + id 升序）钉死。
"""

import sqlite3
from collections.abc import Iterable, Iterator
from typing import Any, Dict, List, Literal, Tuple, TypedDict

from delector.core.lexicon import LEXICON, RICH
from delector.data.prep_dict import PREP_COLLOCATIONS

__all__ = [
    "SearchDoc",
    "fold",
    "iter_corpus_docs",
    "iter_vocab_docs",
    "match_score",
    "search",
]

# ── 常量 ──────────────────────────────────────────────────────────────────────

Kind = Literal["vocab", "example", "colloc", "corpus"]

# 四组固定顺序（同分排序用；亦为 groups 输出键的顺序）。语料 "corpus" 由 T2 注入。
_KIND_ORDER: Dict[str, int] = {"vocab": 0, "example": 1, "colloc": 2, "corpus": 3}

# 合法 scope 集合；非法值由路由层负责 400（见 search 内注释）。
_VALID_SCOPES = frozenset({"all", "vocab", "example", "colloc", "corpus"})

# 折叠规则：德语变音 → 基本字母（ß 展开为 ss）。
_DIACRITICS: Tuple[Tuple[str, str], ...] = (
    ("ä", "a"),
    ("ö", "o"),
    ("ü", "u"),
    ("ß", "ss"),
)

# 字段权重表（spec §3.2；同字段多键命中取最高）。
_FIELD_WEIGHTS: Tuple[Tuple[str, int], ...] = (
    ("def_zh", 25),
    ("prep", 20),
    ("case", 20),
    ("colloc_zh", 20),
    ("title", 18),
    ("example_de", 15),
    ("example_zh", 12),
    ("text", 8),
)

_MIN_Q = 2  # fold(q) 后长度 < 2 → 空结果（不报错）
_LIMIT_MIN = 1
_LIMIT_MAX = 100


class SearchDoc(TypedDict):
    """四类源（vocab/example/colloc/corpus）统一规范后的检索文档。"""

    kind: Kind
    id: str
    lemma: str
    hw: str
    pos: str
    cefr: str
    fields: Dict[str, str]
    payload: Dict[str, Any]


# ── fold：匹配归一 ────────────────────────────────────────────────────────────


def fold(s: str) -> str:
    """归一化匹配串：小写 + 变音折叠（ä/ö/ü/ß）+ 压缩连续空白为单空格并 strip。

    仅用于匹配（展示用原文）。空/纯空白输入返回空串（不抛错）。
    """
    lowered = s.lower()
    for src, dst in _DIACRITICS:
        lowered = lowered.replace(src, dst)
    return " ".join(lowered.split())


# ── 三源 → 统一 doc ──────────────────────────────────────────────────────────


def iter_vocab_docs() -> Iterator[SearchDoc]:
    """把词库侧三源规范成 ``SearchDoc``（惰性生成）。

    - ``LEXICON``（值 = ``(cefr, pos, gender, plural, def_zh)``）→ ``kind="vocab"``；
    - ``RICH``（``{ipa, example_de, example_zh, topic}``）→ ``kind="example"``；
    - ``PREP_COLLOCATIONS``（``lemma -> ((prep, case, zh, example), ...)``）→
      ``kind="colloc"``，**一个 lemma 的多条搭配各自成一条 doc**，``id=f"{lemma}:{prep}"``。
    """
    for lemma, val in LEXICON.items():
        cefr, pos, gender, plural, def_zh = val[0], val[1], val[2], val[3], val[4]
        yield {
            "kind": "vocab",
            "id": lemma,
            "lemma": lemma,
            "hw": lemma,
            "pos": str(pos) if pos else "",
            "cefr": str(cefr) if cefr else "",
            "fields": {"hw": lemma, "def_zh": str(def_zh) if def_zh else ""},
            "payload": {"cefr": cefr, "pos": pos, "gender": gender, "plural": plural},
        }

    for lemma, rich in RICH.items():
        yield {
            "kind": "example",
            "id": lemma,
            "lemma": lemma,
            "hw": lemma,
            "pos": "",
            "cefr": "",
            "fields": {
                "example_de": str(rich.get("example_de", "")),
                "example_zh": str(rich.get("example_zh", "")),
            },
            "payload": {"ipa": str(rich.get("ipa", ""))},
        }

    for lemma, collocs in PREP_COLLOCATIONS.items():
        for prep, case, zh, example in collocs:
            yield {
                "kind": "colloc",
                "id": f"{lemma}:{prep}",
                "lemma": lemma,
                "hw": lemma,
                "pos": "",
                "cefr": "",
                "fields": {
                    "prep": prep,
                    "case": case,
                    "colloc_zh": zh,
                    "example_de": example,
                },
                "payload": {"prep": prep, "case": case},
            }


# ── 语料：SQLite 行 → corpus doc（Task 2）─────────────────────────────────────


def _as_str(value: Any) -> str:
    """sqlite 取值 → str（None → ''；非 str 值转字符串）。"""
    return "" if value is None else str(value)


def _iter_corpus_rows(conn: sqlite3.Connection) -> Iterator[Tuple[str, int, str, str, str]]:
    """惰性产出 ``(source, ref_id, title, level, text)``。

    先遍历 ``articles`` 全量（按 ``id`` 升序），再接 ``encounter_texts`` 全量（按
    ``id`` 升序）。**惰性迭代**（不 ``fetchall``）以便 hard cap 真正提前停止、不把
    整库读进内存。参数化 SELECT、只读。
    """
    for row in conn.execute("SELECT id, title, raw_text FROM articles ORDER BY id ASC"):
        yield "article", int(row[0]), _as_str(row[1]), "", _as_str(row[2])
    for row in conn.execute("SELECT id, title, level, content FROM encounter_texts ORDER BY id ASC"):
        yield "encounter", int(row[0]), _as_str(row[1]), _as_str(row[2]), _as_str(row[3])


def iter_corpus_docs(
    conn: sqlite3.Connection,
    *,
    max_docs: int = 2000,
    max_chars: int = 2_000_000,
) -> Tuple[List[SearchDoc], bool]:
    """把 ``articles`` 与 ``encounter_texts`` 规范成 ``kind="corpus"`` 的 doc 列表。

    - **只读、无副作用**：参数化 SELECT，不写库；``conn`` 由调用方（T3 路由，经
      ``db_conn``）提供，本函数**不自己开连接**（便于测试注入临时库）。
    - 空 ``text``（``strip()`` 后为空）的文档**整体跳过**：``"" in ""`` 恒真，空串会
      让任意 q 都「命中」，必须挡在 doc 构造之前。
    - **hard cap**：按 ``id`` 升序遍历两表，累计文档数达 ``max_docs`` **或** 累计字符
      超 ``max_chars`` 即停止；此时返回 ``truncated=True``，正常遍历完为 ``False``。
      返回 ``(docs, truncated)``。语料 cap 的 ``truncated`` 与 ``search`` 的 limit 截断
      由路由层（T3）按 OR 合并（spec §3.3）。
    """
    docs: List[SearchDoc] = []
    total_chars = 0
    for source, ref_id, title, level, text in _iter_corpus_rows(conn):
        if not text.strip():
            continue
        if len(docs) >= max_docs or total_chars + len(text) > max_chars:
            return docs, True
        docs.append(
            {
                "kind": "corpus",
                "id": f"{source}:{ref_id}",
                "lemma": "",
                "hw": "",
                # pos/cefr 仅占位：pos 复用 source（article/encounter），cefr 复用 encounter
                # 的 level；二者**不参与 match_score**（语料计分只看 fields 的 title=18 / text=8）。
                "pos": source,
                "cefr": level,  # article 无 level → ""；encounter 用 level 作 cefr
                "fields": {"title": title, "text": text},
                "payload": {"source": source, "ref_id": ref_id, "title": title, "level": level},
            }
        )
        total_chars += len(text)
    return docs, False


def _snippet(text: str, q: str, radius: int = 80) -> str:
    """``text`` 中首个命中的上下文片段（``…`` 包裹）；未命中返回空串。

    定位：先 ``text.lower().find(q.lower())``；未命中再走 ``fold(text).find(fold(q))``。
    **fold 路径的命中位置仅作近似**——``ß→ss`` 会改变字符串长度，折叠坐标与原文坐标
    不严格对齐，窗口边界可能略有偏移；这只影响截断边界、不影响可读性，可接受。

    返回 ``text[max(0,i-radius) : i+len(q)+radius]``（去首尾空白）——超长文本被裁剪，
    **绝不整篇返回**；空 ``text`` / 空 ``q`` 一律空串。
    """
    if not text or not q:
        return ""
    idx = text.lower().find(q.lower())
    if idx < 0:
        idx = fold(text).find(fold(q))
    if idx < 0:
        return ""
    start = max(0, idx - radius)
    end = idx + len(q) + radius
    return f"…{text[start:end].strip()}…"


# ── 计分 ──────────────────────────────────────────────────────────────────────


def match_score(q_folded: str, doc: SearchDoc) -> int:
    """``q_folded`` 对单条 doc 的命中分（取该 doc 的最高命中权重，无命中返回 0）。

    权重表（spec §3.2）：
        hw/lemma 精确=100 · 前缀=60 · 子串=40
        def_zh=25 · prep/case/colloc_zh=20 · example_de=15 · example_zh=12
        （语料）title=18 · text=8
    """
    # 空 q：``startswith('')`` 恒真会误判为前缀命中（60），且 ``'' in ''`` 亦真。
    # 经 ``search`` 不可达（长度守卫），但防未来直调，顶部短路返回 0。
    if not q_folded:
        return 0

    # 词头层（hw 与 lemma 同权，取最高）。
    best = 0
    for head in (doc["hw"], doc["lemma"]):
        head_folded = fold(head)
        if not head_folded:
            continue
        if head_folded == q_folded:
            return 100  # 最高分，无需再看其它字段
        if head_folded.startswith(q_folded):
            best = max(best, 60)
            continue
        if q_folded in head_folded:
            best = max(best, 40)

    # 字段层：任一字段子串命中即取其权重（多字段取最高）。
    fields = doc["fields"]
    for key, weight in _FIELD_WEIGHTS:
        value = fields.get(key, "")
        if not value:
            continue
        if q_folded in fold(value):
            best = max(best, weight)

    return best


# ── 检索入口 ──────────────────────────────────────────────────────────────────


def search(
    q: str,
    *,
    scope: str = "all",
    limit: int = 20,
    corpus_docs: Iterable[SearchDoc] = (),
) -> Dict[str, Any]:
    """对词库侧三源（+ 注入的 ``corpus_docs``）做子串匹配 → 计分 → 排序 → 分组截断。

    返回 ``{"q","scope","total","groups","truncated"}``：

    - ``fold(q)`` 后长度 < 2 → ``total=0`` + 四组空数组（**绝不抛错**）；
    - ``scope`` ∈ {all,vocab,example,colloc,corpus}：非 ``all`` 只回该组，其余组空数组。
      **非法 scope 由路由层校验 400**；纯函数收到非法值时按 ``"all"`` 处理（一致且不抛错）；
    - ``limit`` 钳制 1..100（≤0→1，>100→100），**每组各取前 limit 条**；
    - ``total`` = 去重且 scope 过滤后的命中数（**截断前**）；``truncated`` = 是否有组被
      ``limit`` 截断。（语料侧 hard cap 的 ``truncated`` 由 T2/T3 在路由层 OR 进来。）
    - **去重（仅 ``scope='all'``）**：同一 lemma 若已被词条组命中，则例句组不再重复该
      lemma（词条优先）。**定向 scope（如 ``'example'``）不做去重**——否则目标词自身的
      例句会被其词条命中吞掉，而无关例句却保留（真 UX 缺陷）。
    """
    groups: Dict[str, List[SearchDoc]] = {kind: [] for kind in _KIND_ORDER}
    # 非法 scope 走 "all"（路由层负责 400；此处保持纯函数一致、不抛错）。
    eff_scope = scope if scope in _VALID_SCOPES else "all"

    q_folded = fold(q)
    if len(q_folded) < _MIN_Q:
        return {"q": q, "scope": eff_scope, "total": 0, "groups": groups, "truncated": False}

    clamped = max(_LIMIT_MIN, min(limit, _LIMIT_MAX))

    docs: List[SearchDoc] = list(iter_vocab_docs())
    docs.extend(corpus_docs)

    hits: List[Tuple[int, SearchDoc]] = []
    for doc in docs:
        score = match_score(q_folded, doc)
        if score > 0:
            hits.append((score, doc))

    # 同分排序：分数降序 → kind 固定序（vocab→example→colloc→corpus）→ id 升序（稳定）。
    hits.sort(key=lambda item: (-item[0], _KIND_ORDER[item[1]["kind"]], item[1]["id"]))

    # 去重：**仅在 scope=='all' 时**把「词条已命中的 lemma」从例句组去掉（词条优先）。
    # 定向 scope（example 等）不去重，否则目标词自身例句会被其词条命中吞掉（真 UX 缺陷）。
    vocab_lemmas: set[str] = set()
    if eff_scope == "all":
        vocab_lemmas = {doc["lemma"] for _score, doc in hits if doc["kind"] == "vocab"}

    for _score, doc in hits:
        if doc["kind"] == "example" and doc["lemma"] in vocab_lemmas:
            continue  # 同 lemma 已有词条命中 → 例句并入词条（词条优先）
        if eff_scope != "all" and doc["kind"] != eff_scope:
            continue
        groups[doc["kind"]].append(doc)

    total = sum(len(items) for items in groups.values())

    truncated = False
    for kind, items in groups.items():
        if len(items) > clamped:
            groups[kind] = items[:clamped]
            truncated = True

    # 补 snippet 放在**每组 limit 截断之后**，且**只对最终返回**的 corpus doc 补——
    # 既不为将被截掉的 doc 白算 snippet，也与下方「浅拷贝」共同保证无副作用：
    # 浅拷贝 ``{**doc, "payload": {**doc["payload"]}}`` 后写入，**绝不改写入参 doc**
    # （同一 ``corpus_docs`` 可被不同 q 多次调用，就地写会互相覆盖且违反“无副作用”）。
    groups["corpus"] = [
        {
            **doc,
            "payload": {
                **doc["payload"],
                "snippet": _snippet(doc["fields"].get("text", ""), q),
            },
        }
        for doc in groups["corpus"]
    ]

    return {"q": q, "scope": eff_scope, "total": total, "groups": groups, "truncated": truncated}
