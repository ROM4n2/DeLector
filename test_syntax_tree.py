"""
Unit Tests for DeLector v3.5.0 German Syntax Tree & Topological Field Engine (syntax_tree.py)
"""
from syntax_tree import (
    analyze_sentence_topology,
    build_clause_tree,
    analyze_syntax_tree,
    get_spacy_nlp,
)


def test_spacy_nlp_loader():
    nlp = get_spacy_nlp()
    assert nlp is not None
    doc = nlp("Das ist ein Test.")
    assert len(doc) > 0


def test_analyze_sentence_topology_v2_compound():
    sent = "Er hat gestern das spannende Buch mit großer Freude gelesen."
    res = analyze_sentence_topology(sent)

    # 1. Check top-level 5 field dictionary keys
    assert "vorfeld" in res
    assert "linke_klammer" in res
    assert "mittelfeld" in res
    assert "rechte_klammer" in res
    assert "nachfeld" in res

    # 2. Check token contents
    vf_texts = [t["text"] for t in res["vorfeld"]]
    lk_texts = [t["text"] for t in res["linke_klammer"]]
    mf_texts = [t["text"] for t in res["mittelfeld"]]
    rk_texts = [t["text"] for t in res["rechte_klammer"]]

    assert "Er" in vf_texts
    assert "hat" in lk_texts
    assert "gestern" in mf_texts
    assert "Buch" in mf_texts
    assert "gelesen" in rk_texts

    # 3. Check field_texts summary
    ft = res["field_texts"]
    assert ft["vorfeld"] == "Er"
    assert ft["linke_klammer"] == "hat"
    assert "gelesen" in ft["rechte_klammer"]
    assert res["sentence_type"] == "V2"


def test_analyze_sentence_topology_v1_separable_particle():
    sent = "Kommst du morgen zur Party mit?"
    res = analyze_sentence_topology(sent)

    assert res["sentence_type"] == "V1"
    assert len(res["vorfeld"]) == 0
    lk_texts = [t["text"] for t in res["linke_klammer"]]
    rk_texts = [t["text"] for t in res["rechte_klammer"]]

    assert "Kommst" in lk_texts
    assert "mit" in rk_texts
    assert res["field_texts"]["linke_klammer"] == "Kommst"
    assert res["field_texts"]["rechte_klammer"] == "mit"


def test_analyze_sentence_topology_v1_imperative():
    sent = "Lies bitte diesen deutschen Text aufmerksam durch!"
    res = analyze_sentence_topology(sent)

    assert res["sentence_type"] == "V1"
    assert len(res["vorfeld"]) == 0
    assert "Lies" in res["field_texts"]["linke_klammer"]
    assert "durch" in res["field_texts"]["rechte_klammer"]


def test_analyze_sentence_topology_preposed_subclause():
    sent = "Weil das Wetter heute sehr schön ist, geht Maria im Park spazieren."
    res = analyze_sentence_topology(sent)

    assert res["sentence_type"] == "V2"
    assert "Weil das Wetter heute sehr schön ist" in res["field_texts"]["vorfeld"]
    assert res["field_texts"]["linke_klammer"] == "geht"
    assert "Maria" in res["field_texts"]["mittelfeld"]
    assert "spazieren" in res["field_texts"]["rechte_klammer"]


def test_analyze_sentence_topology_passive_modal():
    sent = "Die Arbeit muss bis morgen früh erledigt werden."
    res = analyze_sentence_topology(sent)

    vf_texts = [t["text"] for t in res["vorfeld"]]
    assert "Arbeit" in vf_texts
    assert res["field_texts"]["linke_klammer"] == "muss"
    assert "erledigt" in res["field_texts"]["rechte_klammer"]
    assert "Passiv" in res["bracket_structure"] or "Modalverb" in res["bracket_structure"]


def test_analyze_sentence_topology_extraposed_nachfeld():
    sent = "Er hat gestern das Buch gelesen, das Maria ihm empfohlen hatte."
    res = analyze_sentence_topology(sent)

    assert res["field_texts"]["vorfeld"] == "Er"
    assert res["field_texts"]["linke_klammer"] == "hat"
    assert "gelesen" in res["field_texts"]["rechte_klammer"]
    assert "das Maria ihm empfohlen hatte" in res["field_texts"]["nachfeld"]


def test_build_clause_tree_konjunktionalsatz_kausal_and_konzessiv():
    sent = "Obwohl er krank war, ist er zur Arbeit gegangen, weil er ein wichtiges Projekt abschließen musste."
    tree = build_clause_tree(sent)

    assert tree["type"] == "hauptsatz"
    assert "ist" in tree["finite_verb"] or tree["finite_verb"] == "ist"
    assert len(tree["children"]) >= 2

    child_types = [c["type"] for c in tree["children"]]
    child_subtypes = [c["subtype"] for c in tree["children"]]
    child_conns = [c["connector"].lower() for c in tree["children"]]

    assert "konjunktionalsatz" in child_types
    assert "konzessiv" in child_subtypes or "obwohl" in child_conns
    assert "kausal" in child_subtypes or "weil" in child_conns


def test_build_clause_tree_relativsatz_and_infinitivgruppe():
    sent = "Der Student, dessen Vater Professor ist, liest ein Buch, um die Prüfung zu bestehen."
    tree = build_clause_tree(sent)

    assert tree["type"] == "hauptsatz"
    assert "liest" in tree["finite_verb"]

    types = [c["type"] for c in tree["children"]]
    assert "relativsatz" in types
    assert "infinitivgruppe" in types

    rel_node = next(c for c in tree["children"] if c["type"] == "relativsatz")
    assert "dessen" in rel_node["connector"]
    assert "ist" in rel_node["finite_verb"]

    inf_node = next(c for c in tree["children"] if c["type"] == "infinitivgruppe")
    assert inf_node["connector"] == "um"
    assert "bestehen" in inf_node["finite_verb"]
    assert "um...zu" in inf_node["label"]


def test_build_clause_tree_passiv_and_konjunktiv_features():
    # 1. Vorgangspassiv
    p_sent = "Das neue Gesetz wurde gestern vom Bundestag mit großer Mehrheit beschlossen."
    p_tree = build_clause_tree(p_sent)
    assert p_tree["features"]["is_passive"] is True
    assert "Passiv" in p_tree["bracket_structure"]

    # 2. Zustandspassiv
    z_sent = "Die Tür ist seit gestern geschlossen."
    z_tree = build_clause_tree(z_sent)
    assert z_tree["features"]["is_passive"] is True
    assert z_tree["features"]["voice"] == "Zustandspassiv"

    # 3. Konjunktiv II
    k_sent = "Wenn ich Zeit gehabt hätte, wäre ich gerne nach Deutschland gereist."
    k_tree = build_clause_tree(k_sent)
    assert k_tree["features"]["is_subjunctive"] is True
    assert k_tree["features"]["mood"] == "Konjunktiv II"


def test_build_clause_tree_nested_clauses_hierarchy():
    sent = "Er weiß genau, dass Maria glaubt, dass Deutsch eine schöne Sprache ist."
    tree = build_clause_tree(sent)

    assert tree["type"] == "hauptsatz"
    assert len(tree["children"]) >= 1

    level2 = tree["children"][0]
    assert level2["type"] == "konjunktionalsatz"
    assert level2["connector"].lower() == "dass"

    # Check 3rd level nested subclause
    assert len(level2["children"]) >= 1
    level3 = level2["children"][0]
    assert level3["type"] == "konjunktionalsatz"
    assert level3["connector"].lower() == "dass"
    assert "ist" in level3["finite_verb"]


def test_build_clause_tree_infinitivgruppe_varieties():
    # ohne...zu
    s1 = "Er ging aus dem Raum, ohne ein einziges Wort zu sagen."
    t1 = build_clause_tree(s1)
    assert len(t1["children"]) == 1
    assert t1["children"][0]["type"] == "infinitivgruppe"
    assert t1["children"][0]["connector"] == "ohne"

    # anstatt...zu
    s2 = "Er spielte Computerspiele, anstatt fleißig Deutsch zu lernen."
    t2 = build_clause_tree(s2)
    assert len(t2["children"]) == 1
    assert t2["children"][0]["type"] == "infinitivgruppe"
    assert t2["children"][0]["connector"] == "anstatt"

    # general zu + Infinitiv
    s3 = "Er versucht, das schwere Problem zu lösen."
    t3 = build_clause_tree(s3)
    assert len(t3["children"]) == 1
    assert t3["children"][0]["type"] == "infinitivgruppe"
    assert "lösen" in t3["children"][0]["finite_verb"]


def test_build_clause_tree_indirect_question():
    sent = "Er fragte mich, wann der Zug nach Hamburg abfährt."
    tree = build_clause_tree(sent)
    assert len(tree["children"]) >= 1
    sub = tree["children"][0]
    assert sub["type"] == "konjunktionalsatz"
    assert sub["connector"] == "wann"


def test_analyze_syntax_tree_full_text():
    text = "Er lernt fleißig Deutsch. Weil er in München studieren will, besucht er einen Intensivkurs."
    res = analyze_syntax_tree(text)

    assert res["version"] == "3.5.0"
    assert res["sentence_count"] == 2
    assert len(res["sentences"]) == 2

    s1 = res["sentences"][0]
    assert s1["sentence_id"] == 0
    assert "clause_tree" in s1
    assert "topology" in s1
    assert s1["topology"]["field_texts"]["vorfeld"] == "Er"

    s2 = res["sentences"][1]
    assert s2["sentence_id"] == 1
    assert len(s2["clause_tree"]["children"]) >= 1


def test_empty_and_edge_inputs():
    res_empty = analyze_sentence_topology("")
    assert res_empty["vorfeld"] == []
    assert res_empty["linke_klammer"] == []

    tree_empty = build_clause_tree("")
    assert tree_empty == {}

    text_empty = analyze_syntax_tree("")
    assert text_empty["sentence_count"] == 0
