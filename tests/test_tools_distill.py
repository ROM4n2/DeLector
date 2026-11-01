# -*- coding: utf-8 -*-
"""Tests for high-SNR NLP analysis distillation projection (Task 1).

Validates distill_analysis_for_agent contract:
- Strips heavy AST and spacy internal pointers (tag, dep, head_id, is_space, is_punct).
- Preserves 5-field sentence topology as clean strings.
- Retains token linguistic morphology (text, lemma, pos, case, gender, number, cefr_level).
- Achieves high-ratio compression (>85%) suitable for LLM agent context.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

from delector.nlp_engine.processor import process_german_text
from delector.tools import analyze
from delector.tools.analyze import distill_analysis_for_agent

SAMPLE_TEXT: str = "Am Samstag soll es in zahlreichen Städten Deutschlands zu Protesten kommen."
EXPECTED_TOPOLOGY_KEYS: set[str] = {
    "vorfeld",
    "linke_klammer",
    "mittelfeld",
    "rechte_klammer",
    "nachfeld",
    "sentence_type",
    "bracket_structure",
}
EXPECTED_TOKEN_KEYS: set[str] = {
    "text",
    "lemma",
    "pos",
    "case",
    "gender",
    "number",
    "cefr_level",
}
FORBIDDEN_SPACY_POINTERS: set[str] = {
    "head_id",
    "head_text",
    "dep",
    "tag",
    "is_space",
    "is_punct",
    "person",
    "tense",
    "mood",
    "verb_form",
}


def test_distill_analysis_for_agent_contract() -> None:
    raw_res: Dict[str, Any] = process_german_text(SAMPLE_TEXT)
    raw_json: str = json.dumps(raw_res, ensure_ascii=False)
    assert len(raw_json) in (13576, 13500), f"Expected raw size 13576 or 13500, got {len(raw_json)}"

    distilled: Dict[str, Any] = distill_analysis_for_agent(raw_res)

    assert "sentences" in distilled
    sentences: List[Dict[str, Any]] = distilled["sentences"]
    assert isinstance(sentences, list)
    assert len(sentences) == 1

    sent: Dict[str, Any] = sentences[0]
    assert isinstance(sent["id"], str)
    assert sent["text"] == SAMPLE_TEXT

    # Topology assertions
    topology: Dict[str, Any] = sent["topology"]
    assert set(topology.keys()) == EXPECTED_TOPOLOGY_KEYS
    for key in EXPECTED_TOPOLOGY_KEYS:
        assert isinstance(topology[key], str), f"Field {key} must be a clean string"

    assert topology["vorfeld"] == "Am Samstag"
    assert topology["linke_klammer"] == "soll"
    assert topology["mittelfeld"] == "es in zahlreichen Städten Deutschlands zu Protesten"
    assert topology["rechte_klammer"] == "kommen"
    assert topology["sentence_type"] == "V2"
    assert bool(topology["bracket_structure"])

    # Token assertions
    tokens: List[Dict[str, Any]] = sent["tokens"]
    assert isinstance(tokens, list)
    assert len(tokens) >= 11

    for tok in tokens:
        assert set(tok.keys()) == EXPECTED_TOKEN_KEYS
        for ptr in FORBIDDEN_SPACY_POINTERS:
            assert ptr not in tok, f"Raw pointer {ptr} must not leak into distilled token"

    # Verify linguistic morphology retention on known tokens
    tok_map: Dict[str, Dict[str, Any]] = {tok["text"]: tok for tok in tokens}
    assert "Samstag" in tok_map
    assert tok_map["Samstag"]["pos"] == "NOUN"
    assert tok_map["Samstag"]["case"] == "Dat"
    assert tok_map["Samstag"]["gender"] == "Masc"
    assert tok_map["Samstag"]["number"] == "Sing"
    assert tok_map["Samstag"]["cefr_level"] == "A1"

    assert "kommen" in tok_map
    assert tok_map["kommen"]["pos"] == "VERB"
    assert tok_map["kommen"]["lemma"] == "kommen"
    assert tok_map["kommen"]["cefr_level"] == "A1"

    # Distillation compression checks
    distilled_json: str = json.dumps(distilled, ensure_ascii=False)
    assert len(json.dumps(topology, ensure_ascii=False)) < 800
    assert len(distilled_json) < 2200
    assert len(distilled_json) < len(raw_json) * 0.20


def test_analyze_run_returns_distilled_by_default() -> None:
    result: Any = asyncio.run(analyze.run({"text": SAMPLE_TEXT}))
    assert isinstance(result, dict)
    assert "sentences" in result
    sentences: List[Dict[str, Any]] = result["sentences"]
    assert len(sentences) == 1

    sent: Dict[str, Any] = sentences[0]
    assert isinstance(sent["id"], str)
    assert set(sent["topology"].keys()) == EXPECTED_TOPOLOGY_KEYS
    assert isinstance(sent["tokens"], list)
    for tok in sent["tokens"]:
        assert set(tok.keys()) == EXPECTED_TOKEN_KEYS
        for ptr in FORBIDDEN_SPACY_POINTERS:
            assert ptr not in tok


def test_distill_analysis_pure_python_fallback() -> None:
    pure_fallback: Dict[str, Any] = {
        "version": 2,
        "sentence_count": 1,
        "sentences": [
            {
                "id": 0,
                "text": "Hallo Welt.",
                "tokens": [
                    {
                        "id": 0,
                        "text": "Hallo",
                        "lemma": "hallo",
                        "pos": "INTJ",
                        "gender": "",
                        "case": "",
                        "cefr_level": "A1",
                        "is_punct": False,
                        "is_space": False,
                    },
                    {
                        "id": 1,
                        "text": "Welt",
                        "lemma": "Welt",
                        "pos": "NOUN",
                        "gender": "Fem",
                        "case": "",
                        "cefr_level": "A1",
                        "is_punct": False,
                        "is_space": False,
                    },
                ],
                "topology": {
                    "vorfeld": [],
                    "linke_klammer": [],
                    "mittelfeld": ["Hallo", "Welt"],
                    "rechte_klammer": [],
                    "nachfeld": [],
                },
            }
        ],
    }
    distilled: Dict[str, Any] = distill_analysis_for_agent(pure_fallback)
    assert "sentences" in distilled
    sent: Dict[str, Any] = distilled["sentences"][0]
    assert sent["id"] == "0"
    assert sent["text"] == "Hallo Welt."
    assert sent["topology"]["mittelfeld"] == "Hallo Welt"
    assert len(sent["tokens"]) == 2
    for tok in sent["tokens"]:
        assert set(tok.keys()) == EXPECTED_TOKEN_KEYS
