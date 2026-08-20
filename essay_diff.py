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


def _decompose_opcodes(sents_orig: List[str], sents_corr: List[str]):
    """Walk difflib opcodes, decomposing 1-to-1 sentence replacements and additions/deletions into individual hunks."""
    matcher = difflib.SequenceMatcher(None, sents_orig, sents_corr)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            yield "equal", sents_orig[i1:i2], sents_corr[j1:j2]
        elif tag == "replace":
            old_sents = sents_orig[i1:i2]
            new_sents = sents_corr[j1:j2]
            n_old = len(old_sents)
            n_new = len(new_sents)
            if n_old == n_new:
                for k in range(n_old):
                    yield "replace", [old_sents[k]], [new_sents[k]]
            else:
                min_len = min(n_old, n_new)
                if min_len <= 1:
                    yield "replace", old_sents, new_sents
                else:
                    for k in range(min_len - 1):
                        yield "replace", [old_sents[k]], [new_sents[k]]
                    yield "replace", old_sents[min_len - 1:], new_sents[min_len - 1:]
        elif tag == "insert":
            for s in sents_corr[j1:j2]:
                yield "insert", [], [s]
        elif tag == "delete":
            for s in sents_orig[i1:i2]:
                yield "delete", [s], []


def diff_sentences(original: str, corrected: str) -> List[Dict[str, Any]]:
    """Compute sentence-level diff hunks between original and corrected text.

    Uses SequenceMatcher to find sentence alignment. Non-equal segments
    are decomposed into sentence-level hunks with default accepted=True.
    """
    sents_orig = split_sentences(original)
    sents_corr = split_sentences(corrected)
    hunks: List[Dict[str, Any]] = []
    for tag, old_chunk, new_chunk in _decompose_opcodes(sents_orig, sents_corr):
        if tag != "equal":
            hunks.append({
                "old": old_chunk,
                "new": new_chunk,
                "accepted": True,
            })
    return hunks


def merge_sentences(original: str, corrected: str, accepted: List[bool]) -> str:
    """Merge original and corrected text based on per-hunk acceptance boolean list."""
    sents_orig = split_sentences(original)
    sents_corr = split_sentences(corrected)
    out: List[str] = []
    h_idx = 0
    for tag, old_chunk, new_chunk in _decompose_opcodes(sents_orig, sents_corr):
        if tag == "equal":
            out.extend(old_chunk)
        else:
            is_acc = accepted[h_idx] if h_idx < len(accepted) else True
            if is_acc:
                out.extend(new_chunk)
            else:
                out.extend(old_chunk)
            h_idx += 1
    return join_sentences(out)

