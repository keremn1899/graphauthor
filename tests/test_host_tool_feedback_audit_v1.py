from __future__ import annotations

from benchmarks.host_retrieval.host_tool_feedback_audit_v1 import audit


def test_feedback_audit_separates_schema_exception_and_result_channels(tmp_path):
    report = audit(tmp_path)
    assert report["model_calls"] == 0
    assert report["public_mcp_schema_checks"] == {
        "expand_edge_type_enum": ["leadsto", "contains", "expresses", "nearto"],
        "expand_direction_enum": ["outgoing", "incoming", "both"],
        "expand_depth_bounds": {"minimum": 1, "maximum": 3},
        # Raised from 6 to 64 on 2026-08-25. Six made a real answer
        # unreachable rather than expensive -- a causal chain thirty hops long
        # could not be walked at all -- and it was not buying safety: every
        # walk behind this verb is BFS with a visited set. This line is the
        # audit's record that the public bound changed deliberately.
        "path_hop_bounds": {"minimum": 1, "maximum": 64},
        "search_mode_enum": ["lexical", "semantic"],
        "search_limit_bounds": {"minimum": 1, "maximum": 25},
    }
    rows = {row["case_id"]: row for row in report["rows"]}
    assert rows["ordinary_exact_miss"]["outcome"] == "EXACT_MISS"
    assert rows["ordinary_label_in_edge_type"]["channel"] == "python_exception"

    correction = rows["feedback_label_in_edge_type"]
    assert correction["outcome"] == "INVALID_ARGUMENT"
    assert correction["error"]["matched_edge_labels"] == {
        "registers_hooks_on": ["leadsto"]
    }
    assert rows["feedback_unknown_edge_type"]["error"]["matched_edge_labels"] == {}
    assert rows["feedback_label_in_path_type"]["error"]["matched_edge_labels"] == {
        "registers_hooks_on": ["leadsto"]
    }

    assert rows["ordinary_unknown_expand_id"]["outcome"] == "EMPTY"
    # This is the feedback gap the audit is intended to preserve: lookup records
    # an exact resolution miss, while expand currently reports only an empty
    # neighbourhood for an unknown seed ID.
    assert rows["ordinary_unknown_expand_id"]["receipt"]["resolve_miss_count"] == 0
    assert rows["ordinary_unknown_expand_id"]["receipt"]["empty_variables"] == [
        "neighbourhood"
    ]
    assert rows["ordinary_stale_graph"]["outcome"] == "STALE_GRAPH"
    assert rows["regional_unknown_region"]["outcome"] == "UNKNOWN_REGION"
    assert rows["regional_invalid_page_limit"]["channel"] == "python_exception"

    wire = {row["case_id"]: row for row in report["mcp_wire_rows"]}
    assert report["summary"]["mcp_wire_case_count"] == 4
    assert report["summary"]["mcp_tool_errors"] == 3
    assert wire["mcp_label_in_edge_type"]["channel"] == "mcp_tool_error"
    assert "is not one of" in wire["mcp_label_in_edge_type"]["message"]
    assert wire["mcp_depth_above_bound"]["channel"] == "mcp_tool_error"
    assert wire["mcp_invalid_search_mode"]["channel"] == "mcp_tool_error"
    assert wire["mcp_unknown_expand_id"]["channel"] == "mcp_result"
    assert wire["mcp_unknown_expand_id"]["outcome"] == "EMPTY"
    assert wire["mcp_unknown_expand_id"]["receipt"]["resolve_miss_count"] == 0
