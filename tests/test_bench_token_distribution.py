# -*- coding: utf-8 -*-
"""Unit tests for Token distribution & chars-per-token backtest analyzer.

Tests adhere to Task 2 specification:
- Pure statistical calculation on execution records
- Robust handling of missing fields, 0 tokens, and empty record sets
- Conservative bound coverage and recommended estimate factor calculations
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_TOOLS_DIR = _ROOT / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from bench_token_distribution import (  # noqa: E402
    TokenRatioReport,
    TurnDistributionReport,
    analyze_by_genre,
    analyze_token_ratios,
    analyze_turn_distribution,
)

_FIXTURE_PATH = _ROOT / "tests" / "fixtures" / "token_backtest_sample.json"


def _load_fixture_records() -> list[dict[str, Any]]:
    with open(_FIXTURE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list)
    return data


def test_analyze_token_ratios_fixture_sample() -> None:
    """Verifies statistical outputs on the 10-record German A1 backtest fixture."""
    records = _load_fixture_records()
    report = analyze_token_ratios(records, chars_per_token_estimate=3.0)

    assert isinstance(report, TokenRatioReport)
    assert report.sample_count == 10

    # Totals
    assert report.prompt_chars_total == 13200
    assert report.prompt_tokens_total == 4000
    assert report.completion_chars_total == 2106
    assert report.completion_tokens_total == 600

    # Means
    assert report.prompt_chars_per_token_mean == pytest.approx(3.300, abs=1e-3)
    assert report.completion_chars_per_token_mean == pytest.approx(3.510, abs=1e-3)

    # Quantiles (p50 and p95 of completion chars-per-token)
    assert report.completion_chars_per_token_p50 == pytest.approx(3.500, abs=1e-3)
    assert report.completion_chars_per_token_p95 == pytest.approx(3.910, abs=1e-3)

    # Conservative bound coverage (at estimate factor 3.0, all 10 are covered)
    assert report.conservative_bound_coverage == pytest.approx(1.0, abs=1e-3)

    # Recommended estimate factor equals min(completion_chars / completion_tokens)
    assert report.recommended_estimate_factor == pytest.approx(3.100, abs=1e-3)


def test_analyze_token_ratios_custom_chars_per_token_estimate() -> None:
    """Higher chars_per_token_estimate (e.g. 4.0) produces smaller estimated token bounds."""
    records = _load_fixture_records()
    report = analyze_token_ratios(records, chars_per_token_estimate=4.0)

    # At 4.0, estimated tokens = ceil(chars / 4.0) will be lower than completion_tokens
    # for samples with ratio < 4.0, so coverage drops significantly below 1.0.
    assert report.conservative_bound_coverage < 1.0


def test_analyze_token_ratios_conservative_coverage_partial() -> None:
    """Verifies conservative coverage calculation when only a subset is covered."""
    # Record 1: completion_chars=180, comp_tokens=50 -> ceil(180/3.0) = 60 >= 50 (covered)
    # Record 2: completion_chars=120, comp_tokens=50 -> ceil(120/3.0) = 40 < 50 (not covered)
    records = [
        {"prompt_tokens": 100, "completion_tokens": 50, "prompt_chars": 300, "completion_chars": 180},
        {"prompt_tokens": 100, "completion_tokens": 50, "prompt_chars": 300, "completion_chars": 120},
    ]
    report = analyze_token_ratios(records, chars_per_token_estimate=3.0)
    assert report.sample_count == 2
    assert report.conservative_bound_coverage == pytest.approx(0.5, abs=1e-3)
    # min ratio is 120 / 50 = 2.40
    assert report.recommended_estimate_factor == pytest.approx(2.400, abs=1e-3)


def test_analyze_token_ratios_fallback_extraction() -> None:
    """Verifies graceful fallback to prompt_text and final_text when char counts absent."""
    records = [
        {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "prompt_text": "A" * 300,
            "final_text": "B" * 150,
        }
    ]
    report = analyze_token_ratios(records, chars_per_token_estimate=3.0)
    assert report.sample_count == 1
    assert report.prompt_chars_total == 300
    assert report.completion_chars_total == 150
    assert report.prompt_chars_per_token_mean == pytest.approx(3.0, abs=1e-3)
    assert report.completion_chars_per_token_mean == pytest.approx(3.0, abs=1e-3)
    assert report.completion_chars_per_token_p50 == pytest.approx(3.0, abs=1e-3)
    assert report.completion_chars_per_token_p95 == pytest.approx(3.0, abs=1e-3)
    assert report.conservative_bound_coverage == pytest.approx(1.0, abs=1e-3)
    assert report.recommended_estimate_factor == pytest.approx(3.0, abs=1e-3)


def test_analyze_token_ratios_fallback_from_estimated_tokens() -> None:
    """Verifies fallback when completion_chars and final_text are absent but estimated_completion_tokens is present."""
    records = [
        {
            "prompt_tokens": 50,
            "completion_tokens": 20,
            "estimated_completion_tokens": 30,
        }
    ]
    report = analyze_token_ratios(records, chars_per_token_estimate=3.0)
    assert report.sample_count == 1
    # Fallback completion_chars = ceil(30 * 3.0) = 90
    assert report.completion_chars_total == 90
    assert report.completion_tokens_total == 20
    assert report.conservative_bound_coverage == pytest.approx(1.0, abs=1e-3)


def test_analyze_token_ratios_empty_records() -> None:
    """Verifies that an empty record list yields zero-filled report with zero division protection."""
    report = analyze_token_ratios([])
    assert report.sample_count == 0
    assert report.prompt_chars_total == 0
    assert report.prompt_tokens_total == 0
    assert report.prompt_chars_per_token_mean == 0.0
    assert report.completion_chars_total == 0
    assert report.completion_tokens_total == 0
    assert report.completion_chars_per_token_mean == 0.0
    assert report.completion_chars_per_token_p50 == 0.0
    assert report.completion_chars_per_token_p95 == 0.0
    assert report.conservative_bound_coverage == 0.0
    assert report.recommended_estimate_factor == 0.0


def test_analyze_token_ratios_zero_tokens_and_missing_fields() -> None:
    """Verifies defense against records having 0 tokens or missing keys."""
    records: list[dict[str, Any]] = [
        {},
        {"prompt_tokens": 0, "completion_tokens": 0, "prompt_chars": 100, "completion_chars": 50},
        {"prompt_tokens": "invalid", "completion_tokens": None},
    ]
    report = analyze_token_ratios(records)
    assert report.sample_count == 3
    assert report.prompt_tokens_total == 0
    assert report.completion_tokens_total == 0
    assert report.prompt_chars_per_token_mean == 0.0
    assert report.completion_chars_per_token_mean == 0.0
    assert report.completion_chars_per_token_p50 == 0.0
    assert report.completion_chars_per_token_p95 == 0.0
    assert report.conservative_bound_coverage == 0.0
    assert report.recommended_estimate_factor == 0.0


def test_token_ratio_report_immutability() -> None:
    """Verifies TokenRatioReport is a frozen dataclass."""
    report = analyze_token_ratios([])
    with pytest.raises(Exception):  # FrozenInstanceError
        setattr(report, "sample_count", 5)


def test_analyze_turn_distribution_fixture_sample() -> None:
    """Verifies turn distribution statistics on the 10-record fixture."""
    records = _load_fixture_records()
    report = analyze_turn_distribution(records)

    assert isinstance(report, TurnDistributionReport)
    assert report.total_runs == 10
    assert report.round_counts == {1: 5, 2: 4, 3: 1}
    assert report.round_percentages == {1: 0.5, 2: 0.4, 3: 0.1}

    # Mean & Median rounds
    assert report.mean_rounds == pytest.approx(1.600, abs=1e-3)
    assert report.median_rounds == pytest.approx(1.500, abs=1e-3)

    # Convergence
    assert report.converged_count == 8
    assert report.converged_rate == pytest.approx(0.800, abs=1e-3)

    # Reasons breakdown
    assert report.reasons == {"ok": 8, "turn_limit": 1, "no_improvement": 1}

    # Per-round metrics (sum of rounds = 16, sum of tokens = 4600, sum of elapsed = 53.75)
    assert report.tokens_per_round_mean == pytest.approx(4600.0 / 16.0, abs=1e-3)
    assert report.elapsed_per_round_mean == pytest.approx(53.75 / 16.0, abs=1e-3)


def test_analyze_by_genre_partitions_letter_and_prose() -> None:
    """Verifies analyze_by_genre splits records into letter and prose subgroups correctly."""
    records = _load_fixture_records()
    by_genre = analyze_by_genre(records)

    assert set(by_genre.keys()) == {"letter", "prose"}

    letter_rep = by_genre["letter"]
    assert letter_rep.total_runs == 5
    assert letter_rep.round_counts == {1: 2, 2: 2, 3: 1}
    assert letter_rep.round_percentages == {1: 0.4, 2: 0.4, 3: 0.2}
    assert letter_rep.mean_rounds == pytest.approx(1.800, abs=1e-3)
    assert letter_rep.median_rounds == pytest.approx(2.000, abs=1e-3)
    assert letter_rep.converged_count == 4
    assert letter_rep.converged_rate == pytest.approx(0.800, abs=1e-3)
    assert letter_rep.reasons == {"ok": 4, "turn_limit": 1}
    assert letter_rep.tokens_per_round_mean == pytest.approx(2300.0 / 9.0, abs=1e-3)
    assert letter_rep.elapsed_per_round_mean == pytest.approx(30.02 / 9.0, abs=1e-3)

    prose_rep = by_genre["prose"]
    assert prose_rep.total_runs == 5
    assert prose_rep.round_counts == {1: 3, 2: 2}
    assert prose_rep.round_percentages == {1: 0.6, 2: 0.4}
    assert prose_rep.mean_rounds == pytest.approx(1.400, abs=1e-3)
    assert prose_rep.median_rounds == pytest.approx(1.000, abs=1e-3)
    assert prose_rep.converged_count == 4
    assert prose_rep.converged_rate == pytest.approx(0.800, abs=1e-3)
    assert prose_rep.reasons == {"ok": 4, "no_improvement": 1}
    assert prose_rep.tokens_per_round_mean == pytest.approx(2300.0 / 7.0, abs=1e-3)
    assert prose_rep.elapsed_per_round_mean == pytest.approx(23.73 / 7.0, abs=1e-3)


def test_analyze_by_genre_explicit_text_type_and_unknown() -> None:
    """Verifies explicit text_type takes precedence over case_id and handles unknowns."""
    records = [
        {"case_id": "letter_01", "text_type": "dialogue", "rounds": 1, "converged": True},
        {"case_id": "unknown_topic_99", "rounds": 2, "converged": False, "reason": "no_improvement"},
    ]
    by_genre = analyze_by_genre(records)
    assert set(by_genre.keys()) == {"dialogue", "unknown"}
    assert by_genre["dialogue"].total_runs == 1
    assert by_genre["unknown"].total_runs == 1


def test_analyze_turn_distribution_empty_records() -> None:
    """Verifies that an empty record set produces zeroed TurnDistributionReport."""
    rep = analyze_turn_distribution([])
    assert rep.total_runs == 0
    assert rep.round_counts == {}
    assert rep.round_percentages == {}
    assert rep.mean_rounds == 0.0
    assert rep.median_rounds == 0.0
    assert rep.converged_count == 0
    assert rep.converged_rate == 0.0
    assert rep.reasons == {}
    assert rep.tokens_per_round_mean == 0.0
    assert rep.elapsed_per_round_mean == 0.0

    assert analyze_by_genre([]) == {}


def test_analyze_turn_distribution_malformed_and_edge_records() -> None:
    """Verifies robust handling of malformed records, <=0 rounds, missing keys, and invalid types."""
    records = [
        {},  # rounds defaults to 1, tokens defaults to 0, elapsed to 0.0, converged False, reason unknown
        {"rounds": 0, "tokens_used": -50, "elapsed_s": -1.0, "reason": None, "converged": 0},
        {"rounds": -3, "tokens_used": None, "completion_tokens": 150, "elapsed_s": "invalid", "reason": ""},
        {"rounds": "invalid", "tokens_used": "bad", "elapsed_s": float("nan"), "converged": True, "reason": "custom"},
    ]
    rep = analyze_turn_distribution(records)
    assert rep.total_runs == 4
    # All 4 fall back to rounds=1
    assert rep.round_counts == {1: 4}
    assert rep.round_percentages == {1: 1.0}
    assert rep.mean_rounds == 1.0
    assert rep.median_rounds == 1.0
    assert rep.converged_count == 1
    assert rep.converged_rate == 0.25
    assert rep.reasons == {"unknown": 3, "custom": 1}
    # Tokens: record 0 -> 0, record 1 -> 0, record 2 -> 150 (from completion_tokens), record 3 -> 0 = 150
    assert rep.tokens_per_round_mean == pytest.approx(150.0 / 4.0, abs=1e-3)
    # Elapsed: all 0.0 -> sum 0.0
    assert rep.elapsed_per_round_mean == 0.0


def test_turn_distribution_report_immutability() -> None:
    """Verifies TurnDistributionReport is a frozen dataclass."""
    rep = analyze_turn_distribution([])
    with pytest.raises(Exception):
        setattr(rep, "total_runs", 10)
