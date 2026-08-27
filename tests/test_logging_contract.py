"""Logging contract tests for structured SST event traces."""

from __future__ import annotations

from reporting import parse_sst_log_lines


def test_parse_sst_log_lines_extracts_fields():
    log_text = "\n".join(
        [
            "planner_initial_exit | elapsed_ms=12 | query_id='q1'",
            "backend_execute_exit | elapsed_ms=20 | candidate_set_size=7",
        ]
    )
    events = parse_sst_log_lines(log_text)
    assert len(events) == 2
    assert events[0]["event"] == "planner_initial_exit"
    assert events[0]["fields"]["query_id"] == "q1"
    assert events[1]["fields"]["candidate_set_size"] == "7"


def test_logging_stage_order_contract():
    log_text = "\n".join(
        [
            "planner_initial_exit | elapsed_ms=10",
            "backend_execute_exit | elapsed_ms=20",
            "company_evaluate_exit | elapsed_ms=30",
            "planner_confirm_exit | elapsed_ms=40 | verdict='CONFIRMED'",
            "battalion_synthesize_exit | elapsed_ms=50",
        ]
    )
    events = [e["event"] for e in parse_sst_log_lines(log_text)]
    expected = [
        "planner_initial_exit",
        "backend_execute_exit",
        "company_evaluate_exit",
        "planner_confirm_exit",
        "battalion_synthesize_exit",
    ]
    assert events == expected


def test_logging_required_fields_contract():
    event = parse_sst_log_lines("planner_confirm_exit | elapsed_ms=33 | verdict='EXHAUSTED'")[0]
    assert "elapsed_ms" in event["fields"]
    assert "verdict" in event["fields"]


def test_backend_execute_logging_required_fields_contract():
    event = parse_sst_log_lines(
        "backend_execute_exit | elapsed_ms=20 | tools_executed=2 | candidate_set_size=4 | "
        "frontier_clusters_count=1 | contingency_triggered=False"
    )[0]
    fields = event["fields"]
    assert fields["tools_executed"] == "2"
    assert fields["candidate_set_size"] == "4"
    assert fields["frontier_clusters_count"] == "1"
    assert fields["contingency_triggered"] == "False"


def test_backend_execute_seed_miss_fields_contract():
    """backend_execute_exit must carry seed_miss bool and per_strategy_counts dict."""
    event = parse_sst_log_lines(
        "backend_execute_exit | elapsed_ms=3.1 | tools_executed=2 | candidate_set_size=0 | "
        "frontier_clusters_count=0 | contingency_triggered=False | seed_miss=True | "
        "per_strategy_counts={'seeds_a': 0, 'neighbourhood': 0}"
    )[0]
    fields = event["fields"]
    assert fields["seed_miss"] == "True"
    assert "per_strategy_counts" in fields


def test_squad_cluster_exit_excluded_fields_contract():
    """squad_cluster_exit must carry excluded_count and worth_continuing."""
    event = parse_sst_log_lines(
        "squad_cluster_exit | cluster_id='cluster_1' | elapsed_ms=1.2 | iterations_used=4 | "
        "termination_status='BUDGET_EXHAUSTED' | included_count=8 | excluded_count=3 | worth_continuing=True"
    )[0]
    fields = event["fields"]
    assert fields["excluded_count"] == "3"
    assert fields["worth_continuing"] == "True"


def test_company_evaluate_exit_pruned_fields_contract():
    """company_evaluate_exit must carry pruned_trail_ids list and cross_cluster_signals_count."""
    event = parse_sst_log_lines(
        "company_evaluate_exit | elapsed_ms=5.0 | hypothesis_status='partial' | confidence='medium' | "
        "primary_trails_count=2 | supporting_trails_count=1 | pruned_trail_ids_count=1 | "
        "pruned_trail_ids=['trail_3'] | cross_cluster_signals_count=0 | gaps_count=2 | recovery_spec_type='none'"
    )[0]
    fields = event["fields"]
    assert "pruned_trail_ids" in fields
    assert fields["cross_cluster_signals_count"] == "0"


def test_planner_initial_exit_strategy_a_concepts_contract():
    """planner_initial_exit must carry strategy_a_concepts list."""
    event = parse_sst_log_lines(
        "planner_initial_exit | elapsed_ms=2100.0 | query_type='semantic' | structural_intent='null' | "
        "strategy_a_count=3 | strategy_a_concepts=['checkout', 'timeout', 'database'] | "
        "strategy_b_count=2 | steps_count=2"
    )[0]
    fields = event["fields"]
    assert "strategy_a_concepts" in fields
    assert fields["strategy_a_count"] == "3"


def test_battalion_synthesize_payload_fields_contract():
    """battalion_synthesize_exit must carry payloads_requested and payloads_fetched."""
    event = parse_sst_log_lines(
        "battalion_synthesize_exit | elapsed_ms=4200.0 | final_answer_chars=1800 | "
        "provenance_count=3 | gaps_count=1 | payloads_requested=5 | payloads_fetched=5"
    )[0]
    fields = event["fields"]
    assert fields["payloads_requested"] == "5"
    assert fields["payloads_fetched"] == "5"
