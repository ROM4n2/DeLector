"""CI pytest 分片计划：workflow 与守卫测试共用的唯一事实来源。

为什么是显式文件列表，而不是 glob + `--ignore`：
  `pytest -q tests/test_[a-c]*.py --ignore=...` 在 bash 里会先把 glob 展开成
  **显式文件路径**，而 pytest 的 `--ignore` 只作用于目录递归、对显式传入的文件
  **无效**。实测（2026-11-04，run 41793803081）unit-1 因此多跑了 113 个本应属于
  cost/integration 的用例：日志 721 passed，而按意图应为 608。也就是说旧分片
  既重复执行又没真正互斥。这里改成显式清单，由 `tests/test_ci_hardening_governance.py`
  钉住「全部用例恰好出现一次」。

分片按本机 `pytest --durations=0` 实测时长配平（2026-11-04，见
`tools/ci_shard_weights.json`）；unit-2 额外承担 6 个 Ruff/mypy 步骤（CI 约 14s），
故其 pytest 负载刻意低于其它三个分片。新增/删除测试文件或调整分片后，
请重跑 `tests/test_ci_hardening_governance.py` 的分区与配平守卫。
"""

from __future__ import annotations

import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# 每个分片的测试文件清单（相对仓库根，全部用 POSIX 分隔符）。
SHARDS: dict[str, tuple[str, ...]] = {
    "unit-1": (
        "tests/test_a1_noun_meta.py",
        "tests/test_a1_rich_convergence_t1.py",
        "tests/test_a1_seed_errors_data.py",
        "tests/test_a1_verb_case_data.py",
        "tests/test_a1_workbench_source.py",
        "tests/test_a2_vocab_data.py",
        "tests/test_ai_endpoints_localhost_gate.py",
        "tests/test_ai_polish_loop.py",
        "tests/test_android_packaging.py",
        "tests/test_android_splash_commit.py",
        "tests/test_android_startup_readiness_policy.py",
        "tests/test_android_ttfd_instrumentation.py",
        "tests/test_android_webview_policy.py",
        "tests/test_app_version_source.py",
        "tests/test_article_store_probe.py",
        "tests/test_articles_list_contract.py",
        "tests/test_assets_manifest.py",
        "tests/test_audit_hardening.py",
        "tests/test_audit_official_vocab.py",
        "tests/test_audit_regressions.py",
        "tests/test_backend_package_layout.py",
        "tests/test_bench_judge_rater.py",
        "tests/test_bench_token_distribution.py",
        "tests/test_c9_reason_alignment.py",
        "tests/test_cards_catalog_tag_probe.py",
        "tests/test_cards_count_probe.py",
        "tests/test_cards_deck_tap_probe.py",
        "tests/test_cards_quiz_choice_probe.py",
        "tests/test_cards_state_split.py",
        "tests/test_cards_wb_source_probe.py",
        "tests/test_cards_workbench_no_review_probe.py",
        "tests/test_check_css_sync.py",
        "tests/test_check_index_html_sync.py",
        "tests/test_check_layer_invariants.py",
        "tests/test_check_mock_drift.py",
        "tests/test_check_silent_degradation.py",
        "tests/test_ci_hardening_android.py",
        "tests/test_ci_hardening_backup_restore.py",
        "tests/test_ci_hardening_core.py",
        "tests/test_ci_hardening_governance.py",
        "tests/test_ci_hardening_infra.py",
        "tests/test_ci_hardening_test_hygiene.py",
        "tests/test_ci_hardening_workflow_wiring.py",
        "tests/test_ci_heartbeat.py",
        "tests/test_companion_agent_loop.py",
        "tests/test_companion_api_contract.py",
        "tests/test_companion_bubble_resume_probe.py",
        "tests/test_companion_context_probe.py",
        "tests/test_companion_db.py",
        "tests/test_companion_domain_tools.py",
        "tests/test_companion_provider_integration.py",
        "tests/test_companion_routes.py",
        "tests/test_companion_services.py",
        "tests/test_core_database_public_surface.py",
        "tests/test_core_dict_ext.py",
        "tests/test_corpus.py",
        "tests/test_encounter_i1_consistency.py",
        "tests/test_server_android_fallback.py",
    ),
    "unit-2": (
        "tests/test_data_dir_migration_gate.py",
        "tests/test_db_cleanup_helper.py",
        "tests/test_desktop_bootstrap.py",
        "tests/test_desktop_data_dir_bootstrap.py",
        "tests/test_desktop_early_static.py",
        "tests/test_desktop_port_guard.py",
        "tests/test_desktop_shell.py",
        "tests/test_desktop_startup_guards.py",
        "tests/test_desktop_tray_exit.py",
        "tests/test_desktop_window_lifecycle.py",
        "tests/test_dict_pipeline.py",
        "tests/test_docs_layout_gate.py",
        "tests/test_edge_tts_mini.py",
        "tests/test_enc_coverage_degraded_probe.py",
        "tests/test_enc_degraded_concurrency_probe.py",
        "tests/test_enc_i1_probe.py",
        "tests/test_enc_known_lemmas_dedupe_probe.py",
        "tests/test_enc_known_same_source_probe.py",
        "tests/test_enc_open_race_probe.py",
        "tests/test_enc_popover_clamp_probe.py",
        "tests/test_enc_read_probe.py",
        "tests/test_encounter_addcard.py",
        "tests/test_encounter_annotate.py",
        "tests/test_encounter_deck_bridge.py",
        "tests/test_encounter_index.py",
        "tests/test_encounter_journey_e2e.py",
        "tests/test_encounter_journey_probe.py",
        "tests/test_encounter_pull.py",
        "tests/test_encounter_pull_ui_probes.py",
        "tests/test_encounter_routes.py",
        "tests/test_encounter_seed.py",
        "tests/test_encounter_store.py",
        "tests/test_encounter_ui_probes.py",
        "tests/test_essay_diff.py",
        "tests/test_exam_catalog.py",
        "tests/test_exam_domain.py",
        "tests/test_exam_trials.py",
        "tests/test_first_screen_from_log.py",
        "tests/test_frontend_api_contract.py",
        "tests/test_frontend_guards.py",
        "tests/test_frontend_module_graph.py",
        "tests/test_frontend_port_guard.py",
        "tests/test_frontend_security.py",
        "tests/test_german_workbench.py",
        "tests/test_get_endpoints_with_writes.py",
        "tests/test_get_setting_observability.py",
        "tests/test_go_agent_supervisor.py",
        "tests/test_goethe_a1.py",
        "tests/test_goethe_a1_hoeren.py",
        "tests/test_goethe_a1_lesen.py",
        "tests/test_goethe_a1_writing.py",
        "tests/test_grammatik_radar.py",
        "tests/test_server_ai_polish.py",
    ),
    "unit-3": (
        "tests/test_hard_sentences_probe.py",
        "tests/test_import_root_modules.py",
        "tests/test_index_dom_probe.py",
        "tests/test_instance_lock.py",
        "tests/test_judge_fp_bench.py",
        "tests/test_lazy_migration_singleflight.py",
        "tests/test_lexicon_priority.py",
        "tests/test_lexicon_rich.py",
        "tests/test_lexicon_single_entry.py",
        "tests/test_listen_api.py",
        "tests/test_listen_engine.py",
        "tests/test_listen_lab_probe.py",
        "tests/test_llm_client.py",
        "tests/test_localhost_guard.py",
        "tests/test_long_read_cost.py",
        "tests/test_motion_count_probe.py",
        "tests/test_nlp_lazy_load.py",
        "tests/test_nlp_model_sm_only.py",
        "tests/test_nlp_prewarm.py",
        "tests/test_noun_case_resolution.py",
        "tests/test_official_vocab.py",
        "tests/test_official_vocab_rich.py",
        "tests/test_player_tray_probe.py",
        "tests/test_polish_tools.py",
        "tests/test_prep_matrix.py",
        "tests/test_preset_processed_data.py",
        "tests/test_probe_json_contract.py",
        "tests/test_probe_wiring_guard.py",
        "tests/test_processed_json_migration.py",
        "tests/test_profile_layers.py",
        "tests/test_pwa_manifest.py",
        "tests/test_pwa_update_notice.py",
        "tests/test_query_plans.py",
        "tests/test_rank_sentences_cost.py",
        "tests/test_reader_api_split.py",
        "tests/test_reader_continuous_flow.py",
        "tests/test_reader_layer_split.py",
        "tests/test_reader_syntax_sync.py",
        "tests/test_release_docs_gate.py",
        "tests/test_start_lifecycle.py",
    ),
    "unit-4": (
        "tests/test_save_wb_state_cost.py",
        "tests/test_search_api.py",
        "tests/test_search_service.py",
        "tests/test_search_ui.py",
        "tests/test_server_backup_restore.py",
        "tests/test_server_cards_vocab.py",
        "tests/test_server_health.py",
        "tests/test_server_lan.py",
        "tests/test_server_packaging.py",
        "tests/test_server_prep.py",
        "tests/test_server_progress_quiz.py",
        "tests/test_server_wb_sync_rtc.py",
        "tests/test_silent_degradation_incidents.py",
        "tests/test_source_hygiene.py",
        "tests/test_spacy_unit_cost.py",
        "tests/test_start.py",
        "tests/test_start_agent_integration.py",
        "tests/test_start_banner_encoding.py",
        "tests/test_static_cache_fingerprint.py",
        "tests/test_syntax_score.py",
        "tests/test_syntax_tree.py",
        "tests/test_test_isolation.py",
        "tests/test_tools.py",
        "tests/test_tools_distill.py",
        "tests/test_unified_pool_e2e.py",
        "tests/test_update_check_endpoint.py",
        "tests/test_update_chip_ui.py",
        "tests/test_verify_windows_portable.py",
        "tests/test_visual_gates.py",
        "tests/test_vocab_contract_uniform.py",
        "tests/test_vocab_identity_upsert.py",
        "tests/test_vocab_pool_projection.py",
        "tests/test_vocab_save_feedback_probe.py",
        "tests/test_vocab_sources.py",
        "tests/test_vocab_stats.py",
        "tests/test_wb_auth_convergence.py",
        "tests/test_wb_pair_persist_probe.py",
        "tests/test_wb_rate_probe.py",
        "tests/test_wb_rtc_probes.py",
        "tests/test_wb_source.py",
        "tests/test_wordcard_ledger.py",
        "tests/test_workbench_gates.py",
        "tests/test_workbench_tokens.py",
        "tests/test_writer_mobile.py",
        "tests/test_writing_rules.py",
    ),
    "integration-heavy": (
        "tests/test_bench_judge_gaming.py",
        "tests/test_frontend_layers.py",
        "tests/test_server.py",
        "tests/test_server_settings_security.py",
        "tests/test_syntax_hard_api.py",
    ),
    "cost-guards": (
        "tests/test_articles_list_cost.py",
        "tests/test_cards_endpoint_cost.py",
    ),
    # TODO-CI-04：cold_start 是 cost 三文件里最慢的一个（本机 49.6s、CI 约 1/3 的 pytest
    # 时间），单独放一个 runner 可把 cost pytest 从 83s 压到约 45–50s。两个分片各自只含
    # cost 文件（无 xdist、不与普通测试共享进程），计时断言语义不变；并集由
    # tests/test_ci_hardening_governance.py 钉住必须恰好覆盖三个 cost 文件。
    "cost-cold-start": (
        "tests/test_cold_start_cost.py",
    ),
}


def resolve_shard(shard: str) -> list[str]:
    """返回分片清单；列出的文件缺失时立即失败（防止静默少跑）。"""
    files = SHARDS[shard]
    for relative in files:
        if not (REPO_ROOT / relative).is_file():
            raise SystemExit(f"分片 {shard} 列出的测试文件不存在：{relative}")
    return list(files)


def main() -> None:
    parser = argparse.ArgumentParser(description="打印某个 CI 分片的 pytest 文件清单")
    parser.add_argument("shard", choices=sorted(SHARDS))
    args = parser.parse_args()
    print(" ".join(resolve_shard(args.shard)))


if __name__ == "__main__":
    main()
