"""build_prep_matrix() 的纯函数契约。

核心不变量：
1. 总数守恒 —— 所有组内 entry 数之和 == PREP_COLLOCATIONS 展开的搭配总数。
   反转索引最常见的 bug 就是丢词条或双计（一个 lemma 有多个介词时）。
2. 抽样归属 —— 每个采样搭配都能通过 (praeposition, kasus) 定位到，
   且 lemma 与中文义原样保留。
3. 排序契约 —— 同组内 lemma 字母序。组间顺序属呈现策略，由 server 层负责，
   这里不断言（避免两层各有一套真相）。
"""
from linguistics import build_prep_matrix, build_prep_matrix_core, PREP_COLLOCATIONS


def test_matrix_total_conservation():
    matrix = build_prep_matrix()
    total_in_matrix = sum(
        len(entries)
        for by_case in matrix.values()
        for entries in by_case.values()
    )
    total_in_dict = sum(len(rows) for rows in PREP_COLLOCATIONS.values())
    assert total_in_matrix == total_in_dict > 0


def test_sample_collocation_is_findable():
    # bestehen 有三条：auf Dat 坚持 / aus Dat 由…组成 / in Dat 在于。
    # 它们必须分别出现在 matrix["auf"]["Dat"] 等 group 里，且字段原样。
    matrix = build_prep_matrix()
    auf_dat = {(e["lemma"], e["bedeutung_zh"]) for e in matrix.get("auf", {}).get("Dat", [])}
    assert ("bestehen", "坚持") in auf_dat
    aus_dat = {e["lemma"] for e in matrix.get("aus", {}).get("Dat", [])}
    assert "bestehen" in aus_dat


def test_entry_fields_complete():
    """字段集合用 == 而不是 >=：等号同时钉住「这一层不注入 cefr」的分层契约
    （CEFR 由 server 层加，见 linguistics.build_prep_matrix 的 docstring），
    >= 的写法对多出来的字段一律放行，等于没有约束。

    不 break：691 次 dict 比较是微秒级，抽一条只覆盖 25/691，
    「除了每桶第一条以外全都缺 beispiel」这种变异照样能溜过去。
    """
    matrix = build_prep_matrix()
    for by_case in matrix.values():
        for entries in by_case.values():
            for e in entries:
                assert set(e) == {"lemma", "reflexive", "bedeutung_zh", "beispiel"}
                assert isinstance(e["reflexive"], bool)
                assert e["bedeutung_zh"].strip() and e["beispiel"].strip()


def test_reflexive_flag_matches_dataset_marker():
    """reflexive 决定词头渲成 "sich freuen" 还是 "freuen"，也决定入卡的 word。

    只断言「键存在」抓不住它：把整列写死成 False 或把判定换成
    `bedeutung.startswith("(sich)")`，其余六条测试全绿。后者尤其危险 ——
    93 个反身条目里 81 个的 (sich) 恰好在开头，12 个不在
    （abgeben「与…打交道(sich)」、einschalten「介入 (sich)」…），
    换成 startswith 只静默错这 12 条。
    """
    matrix = build_prep_matrix()
    flagged = sum(e["reflexive"] for by_case in matrix.values()
                  for es in by_case.values() for e in es)
    expected = sum(1 for rows in PREP_COLLOCATIONS.values()
                   for r in rows if "(sich)" in r[2])
    assert flagged == expected > 0, f"reflexive 标记数 {flagged} != 数据集 (sich) 数 {expected}"
    # 位置钉子：标记不在句首的那一类必须也认出来
    tail_marked = build_prep_matrix_core({"einschalten": (("in", "Akk", "介入 (sich)", "x"),)})
    assert tail_marked["in"]["Akk"][0]["reflexive"] is True
    plain = build_prep_matrix_core({"warten": (("auf", "Akk", "等待", "x"),)})
    assert plain["auf"]["Akk"][0]["reflexive"] is False


def test_lemmas_sorted_inside_each_bucket():
    """数据集自身的顺序棘轮，**不是**排序实现的契约。

    prep_dict.py 的键本来就是 lemma 升序，所以删掉 build_prep_matrix_core 里的
    sort 这条也照样绿（已实测）。排序契约由 test_core_sorts_unsorted_input 扛；
    这条留着的价值只有一个：将来生成流水线改成别的键序时它会红，提醒
    「组内有序」这件事不再是白送的。
    """
    matrix = build_prep_matrix()
    for by_case in matrix.values():
        for entries in by_case.values():
            lemmas = [e["lemma"] for e in entries]
            assert lemmas == sorted(lemmas)


def test_core_sorts_unsorted_input():
    """喂乱序输入才能真正钉住排序契约。

    prep_dict.py 由 tools/build_prep.py 生成时键就已按 lemma 升序，于是
    build_prep_matrix() 的桶天然有序 —— 上一个测试删掉 sort 也照样绿。
    只有走内核喂一份乱序表，才抽到了会出错的那条路径。
    """
    unsorted = {
        "zweifeln": (("an", "Dat", "怀疑", "Er zweifelt an der Aussage."),),
        "arbeiten": (("an", "Dat", "从事", "Sie arbeitet an dem Projekt."),),
        "leiden": (("an", "Dat", "患…病", "Er leidet an Diabetes."),),
    }
    lemmas = [e["lemma"] for e in build_prep_matrix_core(unsorted)["an"]["Dat"]]
    assert lemmas == ["arbeiten", "leiden", "zweifeln"], f"组内未按 lemma 排序：{lemmas}"


def test_counts_ratchet_never_shrinks():
    """棘轮：词库只许增长不许缩水。缩水说明生成流水线或合并出了事故。"""
    matrix = build_prep_matrix()
    n_lemmas = len({e["lemma"] for by_case in matrix.values() for es in by_case.values() for e in es})
    n_pairs = sum(len(es) for by_case in matrix.values() for es in by_case.values())
    assert n_lemmas >= 552, f"lemma 数缩水：{n_lemmas} < 552"
    assert n_pairs >= 691, f"搭配数缩水：{n_pairs} < 691"


def test_empty_dataset_degrades_to_empty_matrix():
    """prep_dict 缺失时 PREP_COLLOCATIONS 是 {} —— 内核必须返回空结构而非抛异常。"""
    assert build_prep_matrix_core({}) == {}


# ── 前端静态契约 ──────────────────────────────────────────────────────────────
from pathlib import Path

_ROOT = Path(__file__).parent
_INDEX = (_ROOT / "static" / "index.html").read_text(encoding="utf-8")
_CARDS = (_ROOT / "static" / "js" / "cards.js").read_text(encoding="utf-8")


def test_segment_button_exists_and_wired():
    seg_html = _INDEX.split('class="cards-seg-bar"')[1].split("</div>")[0]
    assert 'id="seg-prep"' in seg_html
    assert "setCardSegment('prep')" in seg_html


def test_cards_js_has_lazy_fetch_and_local_filter():
    assert "/api/prep/matrix" in _CARDS, "cards.js 必须调用新端点"
    assert "_prepMatrixCache" in _CARDS, "必须有模块级缓存变量（懒加载一次）"
    assert "/api/cards/vocab" in _CARDS, "行内入卡必须打到既有 vocab 端点"


def test_cards_js_reuses_save_payload_shape():
    """入卡 payload 必须与 VocabCardReq 逐字段对齐。

    断言范围切到 savePrepCardFromMatrix 函数体内：`definition_zh`/`sentence_context`
    在 cards.js 的渲染函数里到处都是（deck/memo/quiz 都读这两个字段），
    对整份文件断言等于永远为真——删掉 payload 里的 definition_zh 也照样绿，
    变异验证 M4 就是这么活下来的。
    """
    body = _CARDS.split("export async function savePrepCardFromMatrix")[1]
    for field in ("article_id", "word", "lemma", "pos", "gender",
                  "cefr_level", "definition_zh", "sentence_context"):
        assert f"{field}:" in body, f"payload 缺字段 {field}（VocabCardReq 要求）"
    # 反身标记只在词头渲染一次，释义里的 (sich) 要摘掉
    assert "(sich)" in _CARDS


def test_prep_segment_included_in_segment_switcher():
    """setCardSegment 的 active-class 循环 hardcode 了段 id 数组 —— 漏了 'prep'
    的话按钮点得动但高亮不跟着走，是最容易漏的一处。"""
    assert "'prep'" in _CARDS.split("export function setCardSegment")[1][:400]
