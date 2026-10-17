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


@dataclass(frozen=True)
class TurnDistributionReport:
    """Statistical summary of multi-turn agent iterations and termination reasons."""

    total_runs: int
    round_counts: dict[int, int]          # {1: count, 2: count, ...}
    round_percentages: dict[int, float]   # {1: fraction, 2: fraction, ...} (0.0 to 1.0)
    mean_rounds: float
    median_rounds: float
    converged_count: int
    converged_rate: float                 # 0.0 to 1.0
    reasons: dict[str, int]               # {"ok": count, "no_improvement": count, ...}
    tokens_per_round_mean: float
    elapsed_per_round_mean: float


def _safe_int(val: Any, default: int = 0) -> int:
    """Defensively parse an integer without crashing on None, bool, or malformed data."""
    if val is None or isinstance(val, bool):
        return default
    try:
        n = int(val)
        return n if n >= 0 else default
    except (ValueError, TypeError):
        return default


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Defensively parse a float without crashing on None, bool, or malformed data."""
    if val is None or isinstance(val, bool):
        return default
    try:
        f = float(val)
        return f if f >= 0.0 and not math.isnan(f) and not math.isinf(f) else default
    except (ValueError, TypeError):
        return default


def _extract_genre(record: dict[str, Any]) -> str:
    """Extract genre from text_type or infer from case_id."""
    tt = record.get("text_type")
    if tt is not None and str(tt).strip():
        return str(tt).strip()
    cid = str(record.get("case_id", "")).strip().lower()
    if cid.startswith("letter"):
        return "letter"
    if cid.startswith("prose"):
        return "prose"
    return "unknown"


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


def analyze_turn_distribution(
    records: Sequence[dict[str, Any]],
) -> TurnDistributionReport:
    """Pure statistical analysis of turn iterations, convergence, and termination reasons.

    Zero division protected: returns zero-filled TurnDistributionReport when records is empty.
    """
    if not records:
        return TurnDistributionReport(
            total_runs=0,
            round_counts={},
            round_percentages={},
            mean_rounds=0.0,
            median_rounds=0.0,
            converged_count=0,
            converged_rate=0.0,
            reasons={},
            tokens_per_round_mean=0.0,
            elapsed_per_round_mean=0.0,
        )

    round_counts_map: dict[int, int] = {}
    reasons_map: dict[str, int] = {}
    rounds_list: list[int] = []
    tokens_list: list[int] = []
    elapsed_list: list[float] = []
    converged_count = 0

    for r in records:
        raw_rounds = _safe_int(r.get("rounds"), 1)
        rnd = raw_rounds if raw_rounds > 0 else 1
        rounds_list.append(rnd)
        round_counts_map[rnd] = round_counts_map.get(rnd, 0) + 1

        is_converged = bool(r.get("converged", False))
        if is_converged:
            converged_count += 1

        raw_reason = r.get("reason")
        reason = str(raw_reason).strip() if raw_reason is not None and str(raw_reason).strip() else "unknown"
        reasons_map[reason] = reasons_map.get(reason, 0) + 1

        tok_val = r.get("tokens_used")
        if tok_val is None:
            tok_val = r.get("completion_tokens", 0)
        tokens_list.append(_safe_int(tok_val, 0))

        elapsed_list.append(_safe_float(r.get("elapsed_s", 0.0), 0.0))

    total_runs = len(records)
    sorted_rounds = sorted(round_counts_map.keys())
    round_counts = {k: round_counts_map[k] for k in sorted_rounds}
    round_percentages = {k: round_counts_map[k] / total_runs for k in sorted_rounds}

    mean_rounds = sum(rounds_list) / total_runs
    median_rounds = float(statistics.median(rounds_list))
    converged_rate = converged_count / total_runs
    reasons = {k: reasons_map[k] for k in sorted(reasons_map.keys())}

    total_rounds = sum(rounds_list)
    tokens_per_round_mean = sum(tokens_list) / total_rounds if total_rounds > 0 else 0.0
    elapsed_per_round_mean = sum(elapsed_list) / total_rounds if total_rounds > 0 else 0.0

    return TurnDistributionReport(
        total_runs=total_runs,
        round_counts=round_counts,
        round_percentages=round_percentages,
        mean_rounds=mean_rounds,
        median_rounds=median_rounds,
        converged_count=converged_count,
        converged_rate=converged_rate,
        reasons=reasons,
        tokens_per_round_mean=tokens_per_round_mean,
        elapsed_per_round_mean=elapsed_per_round_mean,
    )


def analyze_by_genre(
    records: Sequence[dict[str, Any]],
) -> dict[str, TurnDistributionReport]:
    """Group execution records by genre (e.g. 'letter', 'prose') and analyze each subset."""
    if not records:
        return {}

    groups: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        genre = _extract_genre(r)
        groups.setdefault(genre, []).append(r)

    return {
        genre: analyze_turn_distribution(genre_records)
        for genre, genre_records in sorted(groups.items())
    }


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
