"""
Tests for sentence-level diff and merge engine (essay_diff.py).
"""
from essay_diff import (
    split_sentences,
    join_sentences,
    diff_sentences,
    merge_sentences,
)


def test_split_and_join_preserves_punctuation():
    text = "Hallo Welt! Wie geht es dir? Ich lerne Deutsch. „Das ist super!\""
    sents = split_sentences(text)
    assert sents == [
        "Hallo Welt!",
        "Wie geht es dir?",
        "Ich lerne Deutsch.",
        "„Das ist super!\"",
    ]
    rejoined = join_sentences(sents)
    assert rejoined == "Hallo Welt! Wie geht es dir? Ich lerne Deutsch. „Das ist super!\""


def test_split_empty_and_whitespace():
    assert split_sentences("") == []
    assert split_sentences("   \n\t  ") == []
    assert join_sentences([]) == ""
    assert join_sentences(["", "   "]) == ""


def test_diff_identical_texts():
    text = "Ich wohne in Berlin. Das Wetter ist schön."
    hunks = diff_sentences(text, text)
    assert hunks == []


def test_diff_single_sentence_modified():
    orig = "Ich habe ein Hund. Er ist sehr nett."
    corr = "Ich habe einen Hund. Er ist sehr nett."
    hunks = diff_sentences(orig, corr)
    assert len(hunks) == 1
    assert hunks[0] == {
        "old": ["Ich habe ein Hund."],
        "new": ["Ich habe einen Hund."],
        "accepted": True,
    }


def test_diff_multiple_sentences_in_order():
    orig = "Satz eins falsch. Satz zwei gut. Satz drei falsch. Satz vier gut."
    corr = "Satz eins richtig. Satz zwei gut. Satz drei richtig. Satz vier gut."
    hunks = diff_sentences(orig, corr)
    assert len(hunks) == 2
    assert hunks[0] == {
        "old": ["Satz eins falsch."],
        "new": ["Satz eins richtig."],
        "accepted": True,
    }
    assert hunks[1] == {
        "old": ["Satz drei falsch."],
        "new": ["Satz drei richtig."],
        "accepted": True,
    }


def test_diff_pure_addition():
    orig = "Erster Satz."
    corr = "Erster Satz. Zweiter Satz."
    hunks = diff_sentences(orig, corr)
    assert len(hunks) == 1
    assert hunks[0] == {
        "old": [],
        "new": ["Zweiter Satz."],
        "accepted": True,
    }


def test_diff_pure_deletion():
    orig = "Erster Satz. Zweiter Satz."
    corr = "Erster Satz."
    hunks = diff_sentences(orig, corr)
    assert len(hunks) == 1
    assert hunks[0] == {
        "old": ["Zweiter Satz."],
        "new": [],
        "accepted": True,
    }


def test_diff_contiguous_multiple_sentences():
    orig = "Satz A. Satz B falsch. Satz C falsch. Satz D."
    corr = "Satz A. Satz B und C neu formuliert. Satz D."
    hunks = diff_sentences(orig, corr)
    assert len(hunks) == 1
    assert hunks[0]["old"] == ["Satz B falsch.", "Satz C falsch."]
    assert hunks[0]["new"] == ["Satz B und C neu formuliert."]


def test_merge_all_true():
    orig = "Satz 1 falsch. Satz 2 gut. Satz 3 falsch."
    corr = "Satz 1 richtig. Satz 2 gut. Satz 3 richtig."
    hunks = diff_sentences(orig, corr)
    assert len(hunks) == 2
    merged = merge_sentences(orig, corr, [True, True])
    assert merged == corr


def test_merge_all_false():
    orig = "Satz 1 falsch. Satz 2 gut. Satz 3 falsch."
    corr = "Satz 1 richtig. Satz 2 gut. Satz 3 richtig."
    hunks = diff_sentences(orig, corr)
    assert len(hunks) == 2
    merged = merge_sentences(orig, corr, [False, False])
    assert merged == orig


def test_merge_mixed_acceptance():
    orig = "Satz 1 alt. Satz 2 mitte. Satz 3 alt."
    corr = "Satz 1 neu. Satz 2 mitte. Satz 3 neu."
    # Accept hunk 0, reject hunk 1
    merged1 = merge_sentences(orig, corr, [True, False])
    assert merged1 == "Satz 1 neu. Satz 2 mitte. Satz 3 alt."

    # Reject hunk 0, accept hunk 1
    merged2 = merge_sentences(orig, corr, [False, True])
    assert merged2 == "Satz 1 alt. Satz 2 mitte. Satz 3 neu."


def test_merge_addition_and_deletion():
    # Pure addition accepted / rejected
    orig = "Satz 1."
    corr = "Satz 1. Satz 2."
    assert merge_sentences(orig, corr, [True]) == "Satz 1. Satz 2."
    assert merge_sentences(orig, corr, [False]) == "Satz 1."

    # Pure deletion accepted / rejected
    orig2 = "Satz 1. Satz 2."
    corr2 = "Satz 1."
    assert merge_sentences(orig2, corr2, [True]) == "Satz 1."
    assert merge_sentences(orig2, corr2, [False]) == "Satz 1. Satz 2."


def test_diff_consecutive_1to1_sentence_modifications():
    orig = "Satz 1 gut. Satz 2 alt. Satz 3 alt. Satz 4 alt. Satz 5 alt."
    corr = "Satz 1 gut. Satz 2 neu. Satz 3 neu. Satz 4 neu. Satz 5 neu."
    hunks = diff_sentences(orig, corr)
    assert len(hunks) == 4
    assert hunks[0]["old"] == ["Satz 2 alt."]
    assert hunks[0]["new"] == ["Satz 2 neu."]
    assert hunks[1]["old"] == ["Satz 3 alt."]
    assert hunks[1]["new"] == ["Satz 3 neu."]
    assert hunks[2]["old"] == ["Satz 4 alt."]
    assert hunks[2]["new"] == ["Satz 4 neu."]
    assert hunks[3]["old"] == ["Satz 5 alt."]
    assert hunks[3]["new"] == ["Satz 5 neu."]

    # Partial merge
    merged = merge_sentences(orig, corr, [True, False, True, False])
    assert merged == "Satz 1 gut. Satz 2 neu. Satz 3 alt. Satz 4 neu. Satz 5 alt."

