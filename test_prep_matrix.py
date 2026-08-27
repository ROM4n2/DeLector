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
    matrix = build_prep_matrix()
    for by_case in matrix.values():
        for entries in by_case.values():
            for e in entries:
                assert set(e) >= {"lemma", "reflexive", "bedeutung_zh", "beispiel"}
                break  # 每组抽一条就够


def test_lemmas_sorted_inside_each_bucket():
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
