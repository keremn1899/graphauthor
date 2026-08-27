from scripts.retrieval_receipt_rollup import rollup


def test_rollup_aggregates_route_form_receipt_and_view_metrics():
    records = [
        {
            "planner_route": "targeted_retrieval",
            "relational_contract": {"question_form": "lookup"},
            "packet_node_count": 20,
            "judgment_node_count": 5,
            "elapsed_ms": 100,
            "governance_verdict": "GOVERNED",
            "execution_receipt": {
                "author": "contract_lowering",
                "contingency_triggered": True,
                "resolve_miss_count": 1,
                "recovery_reasons": ["direction_retry"],
                "final_packet_node_count": 20,
                "operations": [{"tool": "get_neighbourhood"}],
                "postprocessing_operations": [
                    {"operation": "governing_query_candidates"}
                ],
            },
        },
        {
            "planner_route": "targeted_retrieval",
            "relational_contract": {},
            "packet_node_count": 4,
            "judgment_node_count": 4,
            "elapsed_ms": 300,
            "governance_verdict": "UNGOVERNED",
            "execution_receipt": {
                "author": "planner",
                "contingency_triggered": False,
                "packet_node_count": 4,
                "operations": [{"tool": "exact_node_lookup"}],
            },
        },
    ]

    report = rollup(records)

    assert report["execution_routes"] == {"exploratory": 1, "pipeline_b": 1}
    assert report["question_forms"] == {"exploratory": 1, "lookup": 1}
    assert report["receipt_coverage"]["packet_count_match_rate"] == 1.0
    assert report["receipt_coverage"]["packet_count_fields_present"] == 1
    assert report["receipt_coverage"]["round_or_final_packet_count_match_rate"] == 1.0
    assert report["contingencies"]["triggered"] == 1
    assert report["resolve_miss_count"] == 1
    assert report["tool_operations"] == {
        "exact_node_lookup": 1,
        "get_neighbourhood": 1,
    }
    assert report["packet_nodes"]["p50"] == 12.0
    assert report["judgment_nodes"]["p50"] == 4.5
    assert report["elapsed_ms"]["p95"] == 300.0
