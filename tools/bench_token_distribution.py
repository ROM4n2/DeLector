# -*- coding: utf-8 -*-
"""Token distribution & chars-per-token backtest analyzer.

Provides statistical analysis of character-to-token ratios from LLM execution
records (JSON / JSONL) to verify whether CHARS_PER_TOKEN_ESTIMATE = 3.0 holds
as a conservative safe upper bound for German A1 text correction.

Reference:
- docs/plans/2026-10-17-c3-token-and-turn-distribution-backtest.md (Task 2)
- ADR-0023 §6 Unknown B / §10.2
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


@dataclass(frozen=True)
class TokenRatioReport:
    """Statistical summary of token counts and chars-per-token ratios."""

    sample_count: int
    prompt_chars_total: int
    prompt_tokens_total: int
    prompt_chars_per_token_mean: float
    completion_chars_total: int
    completion_tokens_total: int
    completion_chars_per_token_mean: float
    completion_chars_per_token_p50: float
    completion_chars_per_token_p95: float
    conservative_bound_coverage: float  # Fraction where estimated_tokens >= completion_tokens (0.0 to 1.0)
    recommended_estimate_factor: float


def _safe_int(val: Any, default: int = 0) -> int:
    """Defensively parse an integer without crashing on None, bool, or malformed data."""
    if val is None or isinstance(val, bool):
        return default
    try:
        n = int(val)
        return n if n >= 0 else default
    except (ValueError, TypeError):
        return default


def _percentile(values: Sequence[float], p: int) -> float:
    """Compute the p-th percentile using inclusive linear interpolation.

    Consistent with bench_judge_gaming._percentile and bench_stats.
    """
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    return float(statistics.quantiles(sorted(values), n=100, method="inclusive")[p - 1])


def analyze_token_ratios(
    records: Sequence[dict[str, Any]],
    *,
    chars_per_token_estimate: float = 3.0,
) -> TokenRatioReport:
    """Pure statistical analysis of prompt and completion token ratios across records.

    Zero division protected: returns zero-filled TokenRatioReport when records is empty
    or all token counts are zero.
    """
    if not records:
        return TokenRatioReport(
            sample_count=0,
            prompt_chars_total=0,
            prompt_tokens_total=0,
            prompt_chars_per_token_mean=0.0,
            completion_chars_total=0,
            completion_tokens_total=0,
            completion_chars_per_token_mean=0.0,
            completion_chars_per_token_p50=0.0,
            completion_chars_per_token_p95=0.0,
            conservative_bound_coverage=0.0,
            recommended_estimate_factor=0.0,
        )

    prompt_chars_list: list[int] = []
    prompt_tokens_list: list[int] = []
    completion_chars_list: list[int] = []
    completion_tokens_list: list[int] = []
    estimated_tokens_list: list[int] = []

    for r in records:
        p_tokens = _safe_int(r.get("prompt_tokens"), 0)
        c_tokens = _safe_int(r.get("completion_tokens"), 0)

        # Prompt chars extraction: prompt_chars -> len(prompt_text) -> 0
        if "prompt_chars" in r and r["prompt_chars"] is not None:
            p_chars = _safe_int(r["prompt_chars"], 0)
        elif "prompt_text" in r and r["prompt_text"] is not None:
            p_chars = len(str(r["prompt_text"]))
        else:
            p_chars = 0

        # Completion chars extraction: completion_chars -> len(final_text) -> estimated fallback -> 0
        if "completion_chars" in r and r["completion_chars"] is not None:
            c_chars = _safe_int(r["completion_chars"], 0)
        elif "final_text" in r and r["final_text"] is not None:
            c_chars = len(str(r["final_text"]))
        elif "estimated_completion_tokens" in r and r["estimated_completion_tokens"] is not None:
            raw_est = _safe_int(r["estimated_completion_tokens"], 0)
            c_chars = math.ceil(raw_est * chars_per_token_estimate) if chars_per_token_estimate > 0 else 0
        else:
            c_chars = 0

        # Estimated tokens:
        # If custom chars_per_token_estimate != 3.0, always recalculate from c_chars.
        # Otherwise, honor pre-existing estimated_completion_tokens if present, else recalculate.
        if chars_per_token_estimate != 3.0:
            est_tokens = math.ceil(c_chars / chars_per_token_estimate) if chars_per_token_estimate > 0 else 0
        elif "estimated_completion_tokens" in r and r["estimated_completion_tokens"] is not None:
            est_tokens = _safe_int(r["estimated_completion_tokens"], 0)
        else:
            est_tokens = math.ceil(c_chars / chars_per_token_estimate) if chars_per_token_estimate > 0 else 0

        prompt_chars_list.append(p_chars)
        prompt_tokens_list.append(p_tokens)
        completion_chars_list.append(c_chars)
        completion_tokens_list.append(c_tokens)
        estimated_tokens_list.append(est_tokens)

    prompt_chars_total = sum(prompt_chars_list)
    prompt_tokens_total = sum(prompt_tokens_list)
    completion_chars_total = sum(completion_chars_list)
    completion_tokens_total = sum(completion_tokens_list)

    prompt_ratios = [c / t for c, t in zip(prompt_chars_list, prompt_tokens_list) if t > 0]
    completion_ratios = [c / t for c, t in zip(completion_chars_list, completion_tokens_list) if t > 0]

    prompt_chars_per_token_mean = (
        round(sum(prompt_ratios) / len(prompt_ratios), 3) if prompt_ratios else 0.0
    )
    completion_chars_per_token_mean = (
        round(sum(completion_ratios) / len(completion_ratios), 3) if completion_ratios else 0.0
    )

    completion_chars_per_token_p50 = round(_percentile(completion_ratios, 50), 3)
    completion_chars_per_token_p95 = round(_percentile(completion_ratios, 95), 3)

    # Conservative bound coverage: records with completion_tokens > 0 where est >= real
    valid_completion_pairs = [
        (est, real) for est, real in zip(estimated_tokens_list, completion_tokens_list) if real > 0
    ]
    if valid_completion_pairs:
        covered = sum(1 for est, real in valid_completion_pairs if est >= real)
        conservative_bound_coverage = round(covered / len(valid_completion_pairs), 3)
    else:
        conservative_bound_coverage = 0.0

    # Recommended estimate factor: conservative lower bound (min ratio) to guarantee ceil(chars / factor) >= tokens
    recommended_estimate_factor = round(min(completion_ratios), 3) if completion_ratios else 0.0

    return TokenRatioReport(
        sample_count=len(records),
        prompt_chars_total=prompt_chars_total,
        prompt_tokens_total=prompt_tokens_total,
        prompt_chars_per_token_mean=prompt_chars_per_token_mean,
        completion_chars_total=completion_chars_total,
        completion_tokens_total=completion_tokens_total,
        completion_chars_per_token_mean=completion_chars_per_token_mean,
        completion_chars_per_token_p50=completion_chars_per_token_p50,
        completion_chars_per_token_p95=completion_chars_per_token_p95,
        conservative_bound_coverage=conservative_bound_coverage,
        recommended_estimate_factor=recommended_estimate_factor,
    )


def load_records(path: str | Path) -> list[dict[str, Any]]:
    """Load execution records from a .json or .jsonl file."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Records file not found: {p}")

    content = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()

    if suffix == ".jsonl":
        records: list[dict[str, Any]] = []
        for line in content.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            item = json.loads(line_str)
            if isinstance(item, dict):
                records.append(item)
        return records

    data = json.loads(content)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        raw_list = data.get("records")
        if isinstance(raw_list, list):
            return [item for item in raw_list if isinstance(item, dict)]
    raise ValueError(f"Unsupported record format in JSON file: {p}")
