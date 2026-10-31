# -*- coding: utf-8 -*-
"""Domain-native tool: query_dictionary.

Queries lemma definition and preposition collocations:
- Queries delector.core.linguistics.lookup_lemma(lemma) if available (falling back to
  delector.nlp_engine.linguistics or delector.core.lexicon.lookup_core_vocab).
- Queries delector.core.prep_dict.lookup_prep_collocations(lemma) if available (falling back to
  delector.nlp_engine.linguistics.lookup_prep_collocations).
- Returns: {"status": "ok", "lemma": lemma, "definitions_zh": list, "collocations": list}
"""

from __future__ import annotations

import importlib
import re
import sys
from typing import Any, Callable, Dict, List, Optional, cast

# Module-level hooks for testing or explicit customization
lookup_lemma: Optional[Callable[[str], Any]] = None
lookup_prep_collocations: Optional[Callable[[str], Any]] = None


def _resolve_lookup_lemma() -> Optional[Callable[[str], Any]]:
    """Resolve lemma lookup function with fallback ladder."""
    if lookup_lemma is not None:
        return lookup_lemma

    # 1. delector.core.linguistics (if registered or importable)
    if "delector.core.linguistics" in sys.modules:
        mod = sys.modules["delector.core.linguistics"]
        fn = getattr(mod, "lookup_lemma", None)
        if callable(fn):
            return cast(Callable[[str], Any], fn)

    try:
        core_ling = importlib.import_module("delector.core.linguistics")
        fn = getattr(core_ling, "lookup_lemma", None)
        if callable(fn):
            return cast(Callable[[str], Any], fn)
    except (ImportError, AttributeError):
        pass

    # 2. delector.nlp_engine.linguistics
    if "delector.nlp_engine.linguistics" in sys.modules:
        mod = sys.modules["delector.nlp_engine.linguistics"]
        fn = getattr(mod, "lookup_lemma", None)
        if callable(fn):
            return cast(Callable[[str], Any], fn)

    try:
        nlp_ling = importlib.import_module("delector.nlp_engine.linguistics")
        fn = getattr(nlp_ling, "lookup_lemma", None)
        if callable(fn):
            return cast(Callable[[str], Any], fn)
    except (ImportError, AttributeError):
        pass

    # 3. Fallback: core lexicon lookup_core_vocab
    try:
        from delector.core.lexicon import lookup_core_vocab

        return cast(Callable[[str], Any], lookup_core_vocab)
    except ImportError:
        pass

    return None


def _resolve_lookup_prep_collocations() -> Optional[Callable[[str], Any]]:
    """Resolve preposition collocations lookup function with fallback ladder."""
    if lookup_prep_collocations is not None:
        return lookup_prep_collocations

    # 1. delector.core.prep_dict (if registered or importable)
    if "delector.core.prep_dict" in sys.modules:
        mod = sys.modules["delector.core.prep_dict"]
        fn = getattr(mod, "lookup_prep_collocations", None)
        if callable(fn):
            return cast(Callable[[str], Any], fn)

    try:
        core_prep = importlib.import_module("delector.core.prep_dict")
        fn = getattr(core_prep, "lookup_prep_collocations", None)
        if callable(fn):
            return cast(Callable[[str], Any], fn)
    except (ImportError, AttributeError):
        pass

    # 2. Fallback: delector.nlp_engine.linguistics.lookup_prep_collocations
    if "delector.nlp_engine.linguistics" in sys.modules:
        mod = sys.modules["delector.nlp_engine.linguistics"]
        fn = getattr(mod, "lookup_prep_collocations", None)
        if callable(fn):
            return cast(Callable[[str], Any], fn)

    try:
        nlp_prep = importlib.import_module("delector.nlp_engine.linguistics")
        fn = getattr(nlp_prep, "lookup_prep_collocations", None)
        if callable(fn):
            return cast(Callable[[str], Any], fn)
    except (ImportError, AttributeError):
        pass

    return None


def _split_definitions(val: Any) -> List[str]:
    """Parse definitions into a list of strings."""
    if not val:
        return []
    if isinstance(val, list):
        out: List[str] = []
        for item in val:
            out.extend(_split_definitions(item))
        return out
    if isinstance(val, str):
        parts = [p.strip() for p in re.split(r"[,，；;、/]+", val) if p.strip()]
        return parts if parts else [val.strip()]
    return [str(val)]


def _extract_definitions_zh(result: Any) -> List[str]:
    """Extract definitions_zh list from arbitrary lookup result."""
    if result is None:
        return []
    if isinstance(result, list):
        return _split_definitions(result)
    if isinstance(result, str):
        return _split_definitions(result)
    if isinstance(result, dict):
        for key in ("definitions_zh", "definition_zh", "def_zh", "definitions", "bedeutung_zh"):
            if key in result and result[key]:
                return _split_definitions(result[key])
    return []


def query_dictionary(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Query lemma definition and collocations.

    Payload:
        lemma: str (required)
    Returns:
        {"status": "ok", "lemma": lemma, "definitions_zh": list, "collocations": list}
        or {"status": "error", "message": "lemma is required"}
    """
    if not isinstance(payload, dict):
        return {"status": "error", "message": "lemma is required"}

    raw_lemma = payload.get("lemma")
    if raw_lemma is None:
        return {"status": "error", "message": "lemma is required"}

    lemma = str(raw_lemma).strip()
    if not lemma:
        return {"status": "error", "message": "lemma is required"}

    # 1. Lookup definitions
    definitions_zh: List[str] = []
    lemma_fn = _resolve_lookup_lemma()
    if lemma_fn is not None:
        try:
            res = lemma_fn(lemma)
            if res is None and lemma.lower() != lemma:
                res = lemma_fn(lemma.lower())
            definitions_zh = _extract_definitions_zh(res)
        except Exception:
            definitions_zh = []

    # 2. Lookup collocations
    collocations: List[Dict[str, Any]] = []
    prep_fn = _resolve_lookup_prep_collocations()
    if prep_fn is not None:
        try:
            prep_res = prep_fn(lemma)
            if (not prep_res) and lemma.lower() != lemma:
                prep_res = prep_fn(lemma.lower())
            if isinstance(prep_res, list):
                collocations = [item for item in prep_res if isinstance(item, dict)]
        except Exception:
            collocations = []

    return {
        "status": "ok",
        "lemma": lemma,
        "definitions_zh": definitions_zh,
        "collocations": collocations,
    }


async def run(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Async wrapper for agent tool invocation."""
    return query_dictionary(payload)
