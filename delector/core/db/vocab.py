# -*- coding: utf-8 -*-
r"""词汇契约与富字段（A1 工作台词库、12 字段词对象契约、reader 生词富字段回填）。

本模块由 `delector/core/database.py` 按职责切分搬出（database-split / Task 4）。
搬出纪律：**纯移动 + 显式 re-export** —— `database.py` 逐名
`from delector.core.db.vocab import X` 再导出，公开面零变化。

本片承载的整组职责：
- A1 工作台词库加载与缓存：`_load_a1_workbench_words` / `_load_a1_workbench_dict_module`
- 词对象契约（12 字段）：`_contract_item` / `_contract_from_a1_row` /
  `_contract_from_core_entry` / `format_vocab_headword`
- reader 生词富字段回填：`_reader_lemma_key` / `_reader_rich_fields`
- 对外取词入口：`get_vocab_by_cefr`

**词库缓存随本片同迁、全仓仅此一份**：`_A1_WORKBENCH_WORDS_CACHE` / `_A2_VOCAB_CACHE`
住本模块，两级缓存不得在别处出现第二份副本。
"""

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

# 循环导入纪律：`database.py` 在**定义完连接访问器之后**才 re-export 本模块，
# 故此处 import 拿到的 database 模块对象已完成到该点（下列名字均已绑定）。
from delector.core.database import db_conn, get_db_path

_A1_WORKBENCH_WORDS_CACHE: Optional[List[Dict[str, Any]]] = None
_A2_VOCAB_CACHE: Optional[List[Dict[str, Any]]] = None

# A1 名词元数据补全（S7 / ADR-0012 §4-4 派生）：seed 的 ``hw`` 归一化后到主干视图
# ``lexicon.A1_LEMMA_META`` join gender / plural。冠词剥离集合（仅剥离**首个词**）。
_A1_ARTICLE_PREFIXES = ("der", "die", "das", "den", "dem", "des", "ein", "eine")


def _normalize_a1_headword(hw: str) -> str:
    """把 A1 seed 的 ``hw`` 归一化为可 join ``lexicon`` 的 lemma 键。

    规则（严格顺序）：小写 → 剥首个词冠词（``der/die/das/den/dem/des/ein/eine``）
    → 去除括号内容（如 ``(sich)`` / ``(pl.)``）→ 取**逗号前**首段 → 去尾 ``-``
    → 去首尾空白。例：``die Adresse,-en``→``adresse``；``der Apfel, -Ä``→``apfel``；
    ``(sich) anmelden``→``anmelden``；``zum Beispiel/z. B.``→``zum beispiel/z. b.``。

    纯函数、只读入参（不触碰任何全局状态）。
    """
    s = (hw or "").strip().lower()
    parts = s.split(None, 1)  # 仅按首个空白切一次：剥「首个词」冠词
    if parts and parts[0] in _A1_ARTICLE_PREFIXES:
        s = parts[1] if len(parts) > 1 else ""
    s = re.sub(r"\([^)]*\)", "", s)  # 去括号内容，如 (sich) / (pl.)
    s = s.split(",", 1)[0]  # 取逗号前首段（逗号后是复数/变音标记）
    s = s.rstrip("-")  # 去尾 '-'，如 all- / ander-
    return s.strip()


def _a1_noun_meta(hw: str) -> Tuple[Optional[str], str]:
    """归一化 ``hw`` → join ``lexicon.A1_LEMMA_META`` → 返回 ``(gender, plural)``。

    A1 名词元数据的唯一真相来自**主干 LEXICON**（``lexicon.A1_LEMMA_META`` 是其只读薄封装，
    ``{"gender", "plural"}`` 直取主干 5 元组 ``v[2]`` / ``v[3]``）——两端格式同构，
    故本层**直接取用**（唯一的规约化：主干以字面量 ``"None"`` 表示「无性别 / 无复数」，
    与 ``_contract_from_core_entry`` 同规约，须归一化为 ``None`` / ``""``）：

    - gender = ``meta["gender"]``（``Masc/Fem/Neut/Plur``；``"None"`` / 缺 → ``None``）；
    - plural = ``meta["plural"]``（后缀标记，如 ``"-en"`` / ``"-.."`` / ``"-"``；
      ``"None"`` / 缺 → ``""``）。

    未命中（lemma 不在主干 LEXICON）→ ``(None, "")``，**绝不编造**。

    惰性导入主干视图（与 ``_contract_from_core_entry`` 的 ``rich_of`` 同策略，
    导入期零副作用）；主干缺失 = 打包损坏，直接 ImportError 炸出（红线 2）。
    """
    from delector.core.lexicon import a1_lemma_meta_of

    lemma = _normalize_a1_headword(hw)
    if not lemma:
        return None, ""
    meta = a1_lemma_meta_of(lemma)
    if meta is None:
        return None, ""
    # 与 _contract_from_core_entry 同规约：主干非名词条目（PRON/ADJ 等）以字面量 "None"
    # 表示无性别 / 无复数（842 条），契约层须归一化，禁止把字符串 "None" 泄漏进契约。
    gender = meta.get("gender")
    plural = meta.get("plural")
    if gender == "None":
        gender = None
    if plural in (None, "None"):
        plural = ""
    return gender, plural


def _a1_workbench_row(w: Dict[str, Any], core: bool) -> Dict[str, Any]:
    """把数据模块的一条 A1 词条映射为内部行
    {id, hw, pos, gender, plural, de, zh, ipa, example_zh, core, cefr, letter}。

    de/zh 派生规则与改造前逐字相同（ADR-0011：输出逐条不变，除新增字段）：
    de = (ex and ex[0].de) or de or ""；zh = gloss or zh or (ex and ex[0].zh) or ""。
    新增字段（S3，供契约 9 → 11）：
    ipa = w.ipa or ""（seed 逐条带音标）；example_zh = ex[0].zh or ""（种子 682/682 全覆盖）。
    新增字段（S7，A1 卡片补齐）：gender/plural 由 ``hw`` 归一化后 join
    ``lexicon.A1_LEMMA_META``（源 = 主干 LEXICON，格式同构）**直取**（见 ``_a1_noun_meta``）；
    未命中 → None/""（不编造）。
    新增字段（S1，ADR-0014 §6-S1）：letter = w.letter or "" —— **seed 原值逐字透传，
    绝不派生**（前端 letterOf 派生会在 10 条上与内联 seed 值漂移，导致字母分组静默错位）。
    """
    ex = w.get("ex")
    gender, plural = _a1_noun_meta(w.get("hw", ""))
    return {
        "id": w.get("id", ""),
        "hw": w.get("hw", ""),
        "pos": w.get("pos", ""),
        "gender": gender,
        "plural": plural,
        "de": (ex and ex[0].get("de")) or w.get("de") or "",
        "zh": w.get("gloss") or w.get("zh") or (ex and ex[0].get("zh")) or "",
        "ipa": w.get("ipa") or "",
        "example_zh": (ex and ex[0].get("zh")) or "",
        "core": core,
        "cefr": "A1",
        "letter": w.get("letter") or "",
    }


def _load_a1_workbench_dict_module() -> Any:
    """导入 A1 词库数据模块（单一真相）；缺失即抛清晰异常，绝不静默回退（ADR-0011 红线 2）。"""
    try:
        import delector.data.a1_workbench_dict as a1_wb
    except ImportError as exc:
        raise RuntimeError(
            "A1 词库数据模块 delector.data.a1_workbench_dict 导入失败：它是 A1 工作台词库"
            "的单一真相，缺失说明安装/打包不完整。禁止静默回退（ADR-0011 红线 2）。"
        ) from exc
    return a1_wb


def _load_a1_workbench_words() -> List[Dict[str, Any]]:
    """加载并缓存 A1 词库（单一真相 = delector.data.a1_workbench_dict 数据模块）。"""
    global _A1_WORKBENCH_WORDS_CACHE
    if _A1_WORKBENCH_WORDS_CACHE is not None:
        return _A1_WORKBENCH_WORDS_CACHE

    a1_wb = _load_a1_workbench_dict_module()
    seeds = a1_wb.A1_WORKBENCH_SEED
    customs = a1_wb.A1_WORKBENCH_CUSTOM
    core_ids = a1_wb.A1_WORKBENCH_CORE_IDS
    if not isinstance(seeds, list) or not isinstance(customs, list):
        raise TypeError(
            "a1_workbench_dict 形状损坏：A1_WORKBENCH_SEED / A1_WORKBENCH_CUSTOM "
            "必须是 List，实际 %s / %s" % (type(seeds).__name__, type(customs).__name__)
        )
    if not isinstance(core_ids, (set, frozenset)):
        raise TypeError(
            "a1_workbench_dict 形状损坏：A1_WORKBENCH_CORE_IDS 必须是 Set/FrozenSet，"
            "实际 %s" % type(core_ids).__name__
        )

    words = [_a1_workbench_row(w, w.get("id", "") in core_ids) for w in seeds]
    words.extend(_a1_workbench_row(w, True) for w in customs)
    _A1_WORKBENCH_WORDS_CACHE = words
    return words


def _reset_a1_workbench_cache() -> None:
    """清空 A1 词库缓存（测试在 monkeypatch 数据模块常量后用它重置，保证可测试性）。"""
    global _A1_WORKBENCH_WORDS_CACHE
    _A1_WORKBENCH_WORDS_CACHE = None


GENDER_ARTICLE_MAP: Dict[str, str] = {
    "Masc": "der",
    "Fem": "die",
    "Neut": "das",
}


def format_vocab_headword(lemma: str, pos: str, gender: Optional[str] = None) -> str:
    """对德语词条进行规范化展示格式拼装。
    名词首字母大写并前缀定冠词 (如 'das Abenteuer')；动词/形容词等保持小写。
    """
    if not lemma:
        return ""
    pos_upper = (pos or "").upper()
    if pos_upper == "NOUN" and gender in GENDER_ARTICLE_MAP:
        art = GENDER_ARTICLE_MAP[gender]
        cap_lemma = lemma[0].upper() + lemma[1:] if len(lemma) > 1 else lemma.upper()
        return f"{art} {cap_lemma}"
    elif pos_upper == "NOUN":
        return lemma[0].upper() + lemma[1:] if len(lemma) > 1 else lemma.upper()
    return lemma.lower()


# ── 词对象契约统一（ADR-0011 决策 2，仅作用输出侧；存储 5 元组 schema 冻结 §5-#6）──


def _contract_item(
    vocab_id: str,
    hw: str,
    pos: str,
    gender: Optional[str],
    plural: str,
    de: str,
    zh: str,
    ipa: str,
    example_zh: str,
    core: bool,
    cefr: str,
    letter: str,
) -> Dict[str, Any]:
    """「存储视图 → 契约条目」的唯一映射点：所有分支产出同一 **12 字段**集
    ``{id, hw, pos, gender, plural, de, zh, ipa, example_zh, core, cefr, letter}``，
    缺失字段显式空值（ADR-0013 §4-1：契约 9 → 11；ADR-0014 §6-S1：契约 11 → 12）。

    - ``de`` 语义 = **德语例句**；``zh`` = 中文释义；``example_zh`` = 例句中文对照。
    - ``ipa`` = 音标（主干富字段，未登记 lemma 显式空串）。
    - ``letter`` = 字母分组建表键（A1 首装靠它做字母分组）。**各分支口径不同**：
      A1 = seed 原值逐字透传（``A1_WORKBENCH_SEED[*].letter``，缺失空串，**不派生** ——
      派生会在 10 条上与内联 seed 漂移）；非 A1 = 与前端现行派生逐字一致的首字母大写
      （``(hw or " ")[0].toUpperCase()``，对应 ``syncB1CardsFromServer`` / reader sync）。
      本参数由各分支算好后传入，``_contract_item`` 只做原样落键。
    """
    return {
        "id": vocab_id,
        "hw": hw,
        "pos": pos,
        "gender": gender,
        "plural": plural,
        "de": de,
        "zh": zh,
        "ipa": ipa,
        "example_zh": example_zh,
        "core": core,
        "cefr": cefr,
        "letter": letter,
    }


def _contract_from_a1_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """A1 内部行（S1 起 12 键：新增 letter）→ 契约条目。

    gender/plural 由 ``_a1_workbench_row``（S7）从 ``hw`` 归一化后 join
    ``lexicon.A1_LEMMA_META``（源 = 主干 LEXICON）**直取**（命中即用；未命中 → None/""），
    此处原样透传（不再硬编码空值）。
    ipa / example_zh 由 ``_a1_workbench_row``（S3）取自 seed 的 ``ipa`` / ``ex[0].zh``
    （682/682 全覆盖），此处原样透传。
    letter 由 ``_a1_workbench_row``（S1，ADR-0014 §6-S1）取自 seed 原值（缺失空串），
    此处原样透传——**绝不在此派生**（派生会漂移那 10 条）。
    """
    return _contract_item(
        vocab_id=row["id"],
        hw=row["hw"],
        pos=row["pos"],
        gender=row["gender"],
        plural=row["plural"],
        de=row["de"],
        zh=row["zh"],
        ipa=row["ipa"],
        example_zh=row["example_zh"],
        core=row["core"],
        cefr=row["cefr"],
        letter=row["letter"],
    )


def _contract_from_core_entry(lemma: str, val: Tuple[Any, ...]) -> Dict[str, Any]:
    """CORE_VOCAB_DB 5 元组存储视图 → 契约条目（A2/通用等级/官方视图共用）。

    富字段（``de`` 德语例句 / ``ipa`` 音标 / ``example_zh`` 例句中文）取自主干富字段
    side-car ``lexicon.rich_of(lemma)``（ADR-0013 §5-5 单入口）；未登记 lemma 一律
    显式空串，**禁止编造 / 静默降级**（ADR-0013 §5-3）。
    """
    lvl = val[0].upper()
    pos = val[1] or ""
    gender = val[2] if len(val) > 2 and val[2] != "None" else None
    plural = val[3] if len(val) > 3 and val[3] != "None" else ""
    zh = val[4] if len(val) > 4 else ""

    # 惰性导入富字段 side-car：与既有 `from delector.core.lexicon import ...` 同风格，
    # 避免模块级循环 / 重依赖（导入期零副作用，红线 9）。
    from delector.core.lexicon import rich_of

    rich = rich_of(lemma)
    de = (rich or {}).get("example_de", "") or ""
    ipa = (rich or {}).get("ipa", "") or ""
    example_zh = (rich or {}).get("example_zh", "") or ""

    hw = format_vocab_headword(lemma, pos, gender)
    # letter（S1，ADR-0014 §6-S1）：非 A1 分支取「与前端现行派生逐字一致」的首字母大写。
    # 依据：前端 syncB1CardsFromServer / reader sync 现行写法 = ``(rw.hw && rw.hw[0] ?
    # rw.hw[0] : "?").toUpperCase()``（取 hw 首字母大写）；非 A1 的 hw 恒非空
    # （format_vocab_headword 对非空 lemma 恒返回非空），故 (hw or " ")[0] 恒等于 hw[0]。
    return _contract_item(
        vocab_id=f"{lvl.lower()}-{lemma.lower()}",
        hw=hw,
        pos=pos,
        gender=gender,
        plural=plural,
        de=de,
        zh=zh,
        ipa=ipa,
        example_zh=example_zh,
        core=True,
        cefr=lvl,
        letter=(hw or " ")[0].upper(),
    )


def _load_a2_vocab_words() -> List[Dict[str, Any]]:
    """加载并缓存 A2 词库（取 core_dict 的 A2 存储视图，经同一映射函数产出契约条目）。

    A2 专用分支已并入通用路径：本函数只剩「过滤 A2 视图 + 缓存」，字段拼装与
    通用等级分支共用 ``_contract_from_core_entry``。core_dict 是包内必然存在的
    第 1 个数据模块，缺失 = 打包损坏 —— ImportError 直接炸，绝不静默回退（红线 2）。
    """
    global _A2_VOCAB_CACHE
    if _A2_VOCAB_CACHE is not None:
        return _A2_VOCAB_CACHE

    from delector.core.lexicon import LEXICON as CORE_VOCAB_DB

    words = [
        _contract_from_core_entry(lemma, val)
        for lemma, val in CORE_VOCAB_DB.items()
        if val[0].upper() == "A2"
    ]

    _A2_VOCAB_CACHE = words
    return words


# ── reader 精读生词富字段回填（ADR-0013 §5-3：未命中显式空值，禁止编造）──────────
#
# 查表键必须归一的原因（实测）：主干 ``RICH``（2722 键）与 ``LEXICON`` 的键 **100%
# 全小写** —— ``rich_of("Zustand")`` 不命中、``rich_of("zustand")`` 命中。而写卡方
# 传入的 ``lemma`` 可能是首字母大写、甚至带冠词的形式（如 ``a1_hoeren.js`` 只去冠词
# 未小写），直接拿原始值查表会**大面积静默漏命中**，生词卡照样是裸的。
_READER_ARTICLE_RE = re.compile(
    r"^(?:der|die|das|ein|eine|einen|einem|einer|eines|den|dem|des)\s+",
    re.IGNORECASE,
)


def _reader_lemma_key(word: str, lemma: str) -> str:
    """reader 卡片 → 富字段查表键：去前导冠词 + 小写。

    取值顺序：``lemma`` 优先（屈折形→lemma 在写入侧已归一，见 routes/main.py 落库
    INSERT），``lemma`` 为空才退回 ``word``（老数据可能只填了 word）；两者皆空返回
    ``""``，调用方据此直接走「全空值」分支。
    """
    for raw in (lemma, word):
        if not raw:
            continue
        stripped = str(raw).strip()
        if not stripped:
            continue
        return _READER_ARTICLE_RE.sub("", stripped).lower()
    return ""


def _reader_rich_fields(word: str, lemma: str) -> Dict[str, Any]:
    """reader 卡片的富字段（音标 / 例句 / 性数）；**未命中一律显式空值，绝不编造**。

    返回 ``{"ipa", "de", "example_zh", "gender", "plural"}``：
    - ``ipa`` / ``de``(=``example_de``) / ``example_zh`` ← ``lexicon.rich_of``；
    - ``gender`` / ``plural`` ← ``lexicon.a1_lemma_meta_of``（源 = 主干 LEXICON
      4762 条全量，覆盖非 A1 等级；动词天然 ``gender=None``）。
    - 两者都未命中 → 走不规则动词兜底：生词常以**屈折形**入库（``ging`` / ``war`` /
      ``hatte``），用双向 ``lookup_irregular_verb`` 取不定式再查一次；仍不命中则全空
      （ADR-0013 §5-3 红线：禁止编造 / 静默降级）。

    惰性 import 放在函数内：保持模块导入期零重依赖（红线 9）。
    """
    empty: Dict[str, Any] = {"ipa": "", "de": "", "example_zh": "", "gender": None, "plural": ""}
    key = _reader_lemma_key(word, lemma)
    if not key:
        return empty

    from delector.core import lexicon
    from delector.nlp_engine.linguistics import lookup_irregular_verb

    if lexicon.rich_of(key) is None and lexicon.a1_lemma_meta_of(key) is None:
        trio = lookup_irregular_verb(key)
        if trio is not None:
            key = trio.infinitiv.strip().lower()

    rich = lexicon.rich_of(key) or {}
    meta = lexicon.a1_lemma_meta_of(key) or {}
    return {
        "ipa": rich.get("ipa") or "",
        "de": rich.get("example_de") or "",
        "example_zh": rich.get("example_zh") or "",
        "gender": meta.get("gender"),
        "plural": meta.get("plural") or "",
    }


def get_vocab_by_cefr(
    cefr: str = "A1",
    scope: str = "core",
    db_path: Optional[str] = None,
    sources: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """按 CEFR 等级与核心范围获取词汇（供工作台与外部组件拉取）。

    ``sources`` 语义（ADR-0012，纯增量）：
    - ``None``（默认）→ **完全走既有分支**，输出逐字不变（A1 workbench /
      A2 core_dict / B1 core_dict / ALL / reader）。
    - 含 ``"official"`` → 官方原样视图 ``lexicon.official_level(cefr)``，逐条经
      既有 ``_contract_from_core_entry`` 产出 11 字段契约。官方视图是「该级全量」，
      故 ``scope``（core/all/reader）只做合法性校验、不影响条数。
    - 非 ``None`` 但不含 ``"official"``（未知来源名）→ **降级为 ``None`` 默认视图**
      （绝不静默返回空表）：sources 是「官方源」开关，无法识别的来源名一律退回
      既有默认分支，保证默认行为与调用方预期不被静默破坏。
    """
    cefr_norm = (cefr or "A1").strip().upper()
    scope_norm = (scope or "core").strip().lower()

    if scope_norm not in ("core", "all", "reader"):
        raise ValueError(f"Invalid scope: {scope}. Must be 'core', 'all', or 'reader'")

    if sources is not None and "official" in set(sources):
        # 惰性导入：lexicon 只依赖 data 分片常量，导入期零重依赖（红线 9）。
        from delector.core import lexicon

        words = [
            _contract_from_core_entry(lemma, val) for lemma, val in lexicon.official_level(cefr_norm).items()
        ]
        return {
            "cefr": cefr_norm,
            "scope": scope_norm,
            "total": len(words),
            "words": words,
        }

    if scope_norm == "reader":
        target_path = get_db_path(db_path)
        with db_conn(target_path) as conn:
            rows = conn.execute("SELECT * FROM vocab_cards ORDER BY id ASC").fetchall()
        words = []
        for r in rows:
            hw = r["word"]
            # reader 卡片的富字段来自主干 LEXICON（经 ``_reader_rich_fields`` 归一查表，
            # 含不规则动词屈折形兜底）；未命中一律显式空值（ADR-0013 §5-3：禁止编造）。
            # 经 ``_contract_item`` 统一产出同一 12 字段集（ADR-0011 决策 2 / ADR-0013 §4-1 /
            # ADR-0014 §6-S1），保证各产出点字段集一致。
            # ``de`` 语义：有原句时保留生词所在**原句**（最贴合用户记忆的语境锚点），
            # 此时**不补** example_zh —— 那是官方例句的中文，配原句会文不对题；
            # 无原句才退回富字段官方例句 + 其中文对照。
            # letter 口径 = 与前端 ``syncReaderCardsFromServer`` 现行派生逐字一致：
            # ``(rw.hw && rw.hw[0] ? rw.hw[0] : "?").toUpperCase()``（hw = 卡片 word 字段）。
            rich = _reader_rich_fields(hw, r["lemma"] or "")
            ctx = r["sentence_context"] or ""
            if ctx:
                de_val, ex_zh_val = ctx, ""
            else:
                de_val, ex_zh_val = rich["de"], rich["example_zh"]
            words.append(
                _contract_item(
                    vocab_id=f"card-{r['id']}",
                    hw=hw,
                    pos=r["pos"] or "",
                    gender=rich["gender"],
                    plural=rich["plural"],
                    de=de_val,
                    zh=r["definition_zh"] or "",
                    ipa=rich["ipa"],
                    example_zh=ex_zh_val,
                    core=False,
                    cefr=r["cefr_level"] or "A1",
                    letter=(hw or " ")[0].upper(),
                )
            )
        return {
            "cefr": cefr_norm,
            "scope": scope_norm,
            "total": len(words),
            "words": words,
        }

    if cefr_norm == "A1":
        a1_words = _load_a1_workbench_words()
        filtered = [w for w in a1_words if w["core"]] if scope_norm == "core" else a1_words
        words = [_contract_from_a1_row(w) for w in filtered]
    else:
        # A2 并入通用路径（经 _load_a2_vocab_words 薄函数 + 缓存）；其余级别读 core_dict
        from delector.core.lexicon import LEXICON as CORE_VOCAB_DB

        if cefr_norm == "A2":
            words = _load_a2_vocab_words()
        elif cefr_norm == "ALL":
            a1_words = _load_a1_workbench_words()
            a1_view = [w for w in a1_words if w["core"]] if scope_norm == "core" else a1_words
            words = [_contract_from_a1_row(w) for w in a1_view]
            words.extend(_load_a2_vocab_words())
            words.extend(
                _contract_from_core_entry(lemma, val)
                for lemma, val in CORE_VOCAB_DB.items()
                if val[0].upper() not in ("A1", "A2")
            )
        else:
            words = [
                _contract_from_core_entry(lemma, val)
                for lemma, val in CORE_VOCAB_DB.items()
                if val[0].upper() == cefr_norm
            ]

    return {
        "cefr": cefr_norm,
        "scope": scope_norm,
        "total": len(words),
        "words": words,
    }
