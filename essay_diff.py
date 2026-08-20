"""
DeLector - Sentence-level Diff & Merge Engine for Writing Desk (v3.12.0)
100% pure Python stdlib (difflib) + syntax_tree.split_sentences_pure_python.
"""
import difflib
from typing import Any, Dict, List

from syntax_tree import split_sentences_pure_python


def split_sentences(text: str) -> List[str]:
    """Split text into sentences, preserving sentence-final punctuation."""
    if not text or not text.strip():
        return []
    return split_sentences_pure_python(text)


def join_sentences(sents: List[str]) -> str:
    """Join sentences with single spaces, skipping empty elements."""
    if not sents:
        return ""
    return " ".join(s.strip() for s in sents if s and s.strip())


def diff_sentences(original: str, corrected: str) -> List[Dict[str, Any]]:
    """Compute sentence-level diff hunks between original and corrected text.

    Uses SequenceMatcher to find sentence alignment. Non-equal segments
    are grouped into hunks with default accepted=True.
    """
    sents_orig = split_sentences(original)
    sents_corr = split_sentences(corrected)
    matcher = difflib.SequenceMatcher(None, sents_orig, sents_corr)
    hunks: List[Dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            hunks.append({
                "old": sents_orig[i1:i2],
                "new": sents_corr[j1:j2],
                "accepted": True,
            })
    return hunks


def merge_sentences(original: str, corrected: str, accepted: List[bool]) -> str:
    """Merge original and corrected text based on per-hunk acceptance boolean list."""
    sents_orig = split_sentences(original)
    sents_corr = split_sentences(corrected)
    matcher = difflib.SequenceMatcher(None, sents_orig, sents_corr)
    out: List[str] = []
    h_idx = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            out.extend(sents_orig[i1:i2])
        else:
            is_acc = accepted[h_idx] if h_idx < len(accepted) else True
            if is_acc:
                out.extend(sents_corr[j1:j2])
            else:
                out.extend(sents_orig[i1:i2])
            h_idx += 1
    return join_sentences(out)
