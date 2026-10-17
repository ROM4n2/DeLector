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
    format_text_report,
    load_records,
    main,
    report_to_dict,
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


def test_load_records_json_and_jsonl(tmp_path: Path) -> None:
    """Verifies load_records correctly handles .json arrays, .json objects, and .jsonl lines."""
    # 1. JSON array
    json_arr_path = tmp_path / "records_array.json"
    json_arr_path.write_text(json.dumps([{"case_id": "c1"}, {"case_id": "c2"}]), encoding="utf-8")
    loaded_arr = load_records(json_arr_path)
    assert len(loaded_arr) == 2
    assert loaded_arr[0]["case_id"] == "c1"

    # 2. JSON object with "records" field
    json_obj_path = tmp_path / "records_obj.json"
    json_obj_path.write_text(json.dumps({"records": [{"case_id": "c3"}]}), encoding="utf-8")
    loaded_obj = load_records(json_obj_path)
    assert len(loaded_obj) == 1
    assert loaded_obj[0]["case_id"] == "c3"

    # 3. JSONL file
    jsonl_path = tmp_path / "records.jsonl"
    jsonl_path.write_text('{"case_id": "c4"}\n\n{"case_id": "c5"}\n', encoding="utf-8")
    loaded_jsonl = load_records(jsonl_path)
    assert len(loaded_jsonl) == 2
    assert loaded_jsonl[1]["case_id"] == "c5"

    # 4. Missing file
    with pytest.raises(FileNotFoundError):
        load_records(tmp_path / "nonexistent.json")

    # 5. Invalid JSON
    corrupt_path = tmp_path / "corrupt.json"
    corrupt_path.write_text("{bad json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_records(corrupt_path)

    # 6. Unsupported JSON structure
    unsupported_path = tmp_path / "unsupported.json"
    unsupported_path.write_text(json.dumps({"other": 123}), encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported record format"):
        load_records(unsupported_path)


def test_report_to_dict_schema() -> None:
    """Verifies report_to_dict produces expected nested dictionary structure."""
    records = _load_fixture_records()
    t_rep = analyze_token_ratios(records)
    d_rep = analyze_turn_distribution(records)
    g_rep = analyze_by_genre(records)

    data = report_to_dict(t_rep, d_rep, g_rep)
    assert isinstance(data, dict)
    assert "token_ratios" in data
    assert "turn_distribution" in data
    assert "by_genre" in data

    assert data["token_ratios"]["sample_count"] == 10
    assert data["turn_distribution"]["total_runs"] == 10
    assert set(data["by_genre"].keys()) == {"letter", "prose"}


def test_format_text_report_sections() -> None:
    """Verifies format_text_report includes all required headers and statistics."""
    records = _load_fixture_records()
    t_rep = analyze_token_ratios(records, chars_per_token_estimate=3.0)
    d_rep = analyze_turn_distribution(records)
    g_rep = analyze_by_genre(records)

    text = format_text_report(t_rep, d_rep, g_rep, chars_per_token_estimate=3.0)
    assert "=== Token & Turn Distribution Backtest ===" in text
    assert "Token Ratio Analysis:" in text
    assert "Samples: 10" in text
    assert "Prompt Chars / Tokens: 13200 / 4000" in text
    assert "Completion Chars / Tokens: 2106 / 600" in text
    assert "Completion p50 / p95: 3.500 / 3.910" in text
    assert "Conservative Bound Coverage: 100.0%" in text
    assert "Recommended Estimate Factor: 3.100" in text

    assert "Turn Distribution Analysis:" in text
    assert "Total Runs: 10" in text
    assert "Round 1: 5 (50.0%)" in text
    assert "Round 2: 4 (40.0%)" in text
    assert "Round 3: 1 (10.0%)" in text
    assert "Mean / Median Rounds: 1.60 / 1.50" in text
    assert "Convergence Rate: 80.0% (8/10)" in text
    assert "ok: 8" in text

    assert "By Genre:" in text
    assert "[letter]" in text
    assert "[prose]" in text


def test_cli_main_text_output_fixture(capsys: pytest.CaptureFixture[str]) -> None:
    """Verifies default CLI execution prints human-readable text report and exits 0."""
    rc = main(["--from-records", str(_FIXTURE_PATH)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "=== Token & Turn Distribution Backtest ===" in out
    assert "Samples: 10" in out
    assert "Total Runs: 10" in out
    assert "[letter]" in out
    assert "[prose]" in out


def test_cli_main_json_output_fixture(capsys: pytest.CaptureFixture[str]) -> None:
    """Verifies CLI execution with --json outputs valid JSON matching contract and exits 0."""
    rc = main(["--from-records", str(_FIXTURE_PATH), "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["token_ratios"]["sample_count"] == 10
    assert data["turn_distribution"]["total_runs"] == 10
    assert "letter" in data["by_genre"]
    assert "prose" in data["by_genre"]


def test_cli_main_output_to_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verifies --output writes report to file for both text and JSON modes."""
    # Text mode with --output
    text_out = tmp_path / "sub_dir" / "report.txt"
    rc_text = main(["--from-records", str(_FIXTURE_PATH), "--output", str(text_out)])
    assert rc_text == 0
    assert text_out.is_file()
    assert "=== Token & Turn Distribution Backtest ===" in text_out.read_text(encoding="utf-8")

    # JSON mode with --output
    json_out = tmp_path / "report.json"
    rc_json = main(["--from-records", str(_FIXTURE_PATH), "--json", "--output", str(json_out)])
    assert rc_json == 0
    assert json_out.is_file()
    data = json.loads(json_out.read_text(encoding="utf-8"))
    assert data["token_ratios"]["sample_count"] == 10


def test_cli_main_custom_chars_per_token_estimate(capsys: pytest.CaptureFixture[str]) -> None:
    """Verifies custom --chars-per-token-estimate alters token ratio calculation."""
    rc = main(["--from-records", str(_FIXTURE_PATH), "--chars-per-token-estimate", "4.0", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["token_ratios"]["conservative_bound_coverage"] < 1.0


def test_cli_main_missing_file_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    """Verifies missing file exits 2 with human-readable error on stderr."""
    rc = main(["--from-records", "nonexistent_file_path_xyz.json"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "file missing" in err.lower() or "not found" in err.lower()


def test_cli_main_missing_arguments_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    """Verifies missing required arguments exits 2 with human-readable error."""
    rc = main([])
    assert rc == 2
    err = capsys.readouterr().err
    assert "required" in err.lower() or "error" in err.lower()


def test_cli_main_invalid_estimate_factor_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    """Verifies non-positive estimate factor exits 2."""
    rc = main(["--from-records", str(_FIXTURE_PATH), "--chars-per-token-estimate", "-1.0"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "positive" in err.lower() or "error" in err.lower()


def test_cli_main_corrupt_json_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verifies corrupt JSON file exits 1 with human-readable error on stderr."""
    corrupt_file = tmp_path / "corrupt.json"
    corrupt_file.write_text("{bad: json:", encoding="utf-8")
    rc = main(["--from-records", str(corrupt_file)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "corrupt" in err.lower() or "invalid" in err.lower()


def test_cli_main_unsupported_structure_exits_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verifies unsupported JSON structure exits 1 with human-readable error on stderr."""
    bad_file = tmp_path / "bad_structure.json"
    bad_file.write_text(json.dumps({"unknown_key": [1, 2, 3]}), encoding="utf-8")
    rc = main(["--from-records", str(bad_file)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "unsupported" in err.lower() or "corrupt" in err.lower() or "invalid" in err.lower()
