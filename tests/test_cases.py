"""Cases: the semantic half, and the ways a case file can lie.

Most of these are about refusing malformed cases at load. A case that parses
but checks nothing reports a pass, and a green report nobody can trust is
worse than no report — which is not a hypothetical here: six acceptance
predicates passed a graph of nonsense before anyone checked whether they
could fail.
"""

from __future__ import annotations

import pytest

from mcp_server.cases import Case, CaseError, check_cases, load_cases

ENCODING = {
    "concepts": [
        {"id": "character:gunnlaug", "kind": "character", "label": "Gunnlaug"},
        {"id": "character:helga", "kind": "character", "label": "Helga"},
        {"id": "character:althing", "kind": "character", "label": "Althing"},
        {"id": "character:william-morris", "kind": "character",
         "label": "William Morris"},
        {"id": "place:iceland", "kind": "place", "label": "Iceland"},
        {"id": "event:and-men-rode-home", "kind": "event",
         "label": "And men rode home from the Althing"},
    ],
    "edges": [
        {"source_id": "character:gunnlaug", "predicate": "allied_with",
         "target_id": "character:helga"},
        {"source_id": "character:helga", "predicate": "allied_with",
         "target_id": "place:iceland"},
    ],
}


def _write(tmp_path, text: str):
    path = tmp_path / "cases.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _run(*cases) -> dict:
    return check_cases(list(cases), ENCODING)


def test_a_mistyped_node_is_caught_by_kind():
    report = _run(Case(claim="node_kind", label="Althing", must_be="place",
                       because="the assembly is a place"))
    assert report["outcome"] == "CASES_FAILED"
    assert "not 'place'" in report["reports"][0]["examples"][0]


def test_an_absent_node_is_reported_differently_from_a_mistyped_one():
    """Two different repairs: retype it, or find out why it was never built."""
    report = _run(Case(claim="node_kind", label="Nobody", must_be="character",
                       because="a sanity check"))
    assert "no node labelled" in report["reports"][0]["examples"][0]


def test_a_node_that_should_not_exist_is_caught_by_pattern():
    report = _run(Case(claim="node_absent",
                       label_matching="^(William Morris|Eirikr Magnusson)$",
                       because="translators are not characters"))
    assert report["reports"][0]["failures"] == 1


def test_label_shape_scopes_to_one_kind():
    """The conjunction rule is about events; characters may be named anything."""
    report = _run(Case(claim="label_shape", kind="event",
                       must_not_match=r"^(And|But)\b",
                       because="an event label is a name, not a sentence"))
    assert report["reports"][0]["failures"] == 1

    unscoped = _run(Case(claim="label_shape", must_not_match=r"^Iceland$",
                         because="scoping check"))
    assert unscoped["reports"][0]["failures"] == 1


def test_connectivity_walks_edges_in_both_directions():
    """`allied_with` is symmetric, and a two-hop path is still a path."""
    close = _run(Case(claim="connected_within", label="Gunnlaug", to="Iceland",
                      within=2, because="reachable in two"))
    assert close["outcome"] == "CASES_PASS"

    far = _run(Case(claim="connected_within", label="Gunnlaug", to="Iceland",
                    within=1, because="not reachable in one"))
    assert far["outcome"] == "CASES_FAILED"


def test_an_empty_case_file_is_unchecked_not_a_pass():
    """A corpus nobody has made a claim about has not been judged."""
    assert check_cases([], ENCODING)["outcome"] == "UNCHECKED"


def test_a_case_with_no_claim_field_is_refused(tmp_path):
    path = _write(tmp_path, "cases:\n  - label: Gunnlaug\n    because: x\n")
    with pytest.raises(CaseError, match="not one of"):
        load_cases(path)


def test_a_case_missing_its_required_field_is_refused(tmp_path):
    """`node_kind` without `must_be` would check nothing and report a pass."""
    path = _write(tmp_path,
                  "cases:\n  - claim: node_kind\n    label: X\n    because: y\n")
    with pytest.raises(CaseError, match="needs one of"):
        load_cases(path)


def test_a_case_without_a_rationale_is_refused(tmp_path):
    """A check whose point nobody remembers gets deleted rather than fixed."""
    path = _write(tmp_path, "cases:\n  - claim: node_present\n    label: X\n")
    with pytest.raises(CaseError, match="because"):
        load_cases(path)


def test_a_typo_in_a_field_name_is_refused_rather_than_ignored(tmp_path):
    """`must_be_kind` silently ignored would leave `node_kind` checking nothing."""
    path = _write(tmp_path, "cases:\n  - claim: node_kind\n    label: X\n"
                            "    must_be_kind: place\n    because: y\n")
    with pytest.raises(CaseError, match="unknown field"):
        load_cases(path)




def test_a_node_can_be_named_by_pattern_when_its_label_is_unstable():
    """Labels lifted from a source are not stable enough to key on exactly.

    Measured: a paper node's label was its title, plus the IEEE acceptance
    footnote, plus a truncating ellipsis. A case written against the real
    title reported "endpoint absent" for a node that was right there — a false
    failure, which is the one thing a case set must not produce.
    """
    encoding = {
        "concepts": [
            {"id": "paper:coma", "kind": "paper",
             "label": "COMA: A Compositional Misleading Attack Class Thanks: "
                      "Accepted at the IEEE Conference on…"},
            {"id": "paper:trustrag", "kind": "paper", "label": "TrustRAG"},
        ],
        "edges": [{"source_id": "paper:trustrag", "predicate": "cites",
                   "target_id": "paper:coma"}],
    }
    exact = check_cases([Case(claim="node_present",
                              label="COMA: A Compositional Misleading Attack Class",
                              because="the real title")], encoding)
    assert exact["outcome"] == "CASES_FAILED"

    by_pattern = check_cases([Case(claim="node_present", label_matching="^COMA",
                                   because="stable prefix")], encoding)
    assert by_pattern["outcome"] == "CASES_PASS"

    joined = check_cases([Case(claim="connected_within",
                               label_matching="^TrustRAG", to_matching="^COMA",
                               within=1, because="they cite each other")], encoding)
    assert joined["outcome"] == "CASES_PASS"


def _every_case_can_fail(path: str, graphs: list[dict], minimum: int) -> None:
    """Each shipped case must fail on at least one of `graphs`.

    A case that passes everything is indistinguishable from a case that checks
    nothing. This is the cheapest place to find that out, and it has already
    caught three cases in one set and three in another.
    """
    cases = load_cases(path)
    assert len(cases) >= minimum, path

    failed = set()
    for graph in graphs:
        for report in check_cases(cases, graph)["reports"]:
            if not report["ok"]:
                failed.add(report["describes"])

    never = [c.describe() for c in cases if c.describe() not in failed]
    assert not never, f"{path}: these never failed, so nothing shows they can: {never}"




# --- edge-level claims -------------------------------------------------
#
# Everything above claims something about nodes, which left a format's most
# valuable predicate uncheckable. `contradicts` scored precision 0 of 4 on a
# corpus containing three real disputes, and no case could say so: the defect
# was in no node, and every structural check passed.

def _research_graph(*extra_edges) -> dict:
    """Two papers, one citing the other, one claim each."""
    def node(node_id, kind, label):
        return {"id": node_id, "kind": kind, "label": label,
                "text_content": label, "semantic_anchor": label,
                "source_unit_ids": ["u:1"]}

    def edge(source, predicate, target):
        return {"source_id": source, "predicate": predicate,
                "target_id": target, "source_unit_ids": ["u:1"]}

    return {
        "concepts": [
            node("paper:das", "paper", "DAS"),
            node("paper:illusion", "paper", "Interpretability Illusion"),
            node("paper:unrelated", "paper", "A Comment On Something Else"),
            node("claim:alignment", "claim", "We find a perfect alignment"),
            node("claim:misleading", "claim", "That metric is misleading"),
            node("claim:elsewhere", "claim", "Their model is a weak approximation"),
        ],
        "edges": [
            edge("paper:das", "asserts", "claim:alignment"),
            edge("paper:illusion", "asserts", "claim:misleading"),
            edge("paper:unrelated", "asserts", "claim:elsewhere"),
            edge("paper:illusion", "cites", "paper:das"),
            *extra_edges,
        ],
    }


def _contradicts(source, target):
    return {"source_id": source, "predicate": "contradicts",
            "target_id": target, "source_unit_ids": ["u:1"]}


BACKED_BY = Case(claim="edge_backed_by", predicate="contradicts",
                 using=["asserts", "cites"], within=3)


def test_a_disagreement_between_papers_that_cite_each_other_passes():
    graph = _research_graph(_contradicts("claim:misleading", "claim:alignment"))
    assert check_cases([BACKED_BY], graph)["outcome"] == "CASES_PASS"


def test_a_disagreement_between_papers_with_no_citation_fails():
    """The measured defect, in miniature.

    Two claims that share vocabulary, from papers that have never read each
    other. Shared topic says they are *about* similar things, which is not the
    same as one bearing on the other.
    """
    graph = _research_graph(_contradicts("claim:alignment", "claim:elsewhere"))
    report = check_cases([BACKED_BY], graph)
    assert report["outcome"] == "CASES_FAILED"
    assert "no backing path" in report["reports"][0]["examples"][0]


def test_the_backing_walk_may_not_wander_through_other_predicates():
    """`using` is a restriction, not a hint.

    Both claims hang off `about` the same topic, which connects them in three
    hops. If the walk were unrestricted that would satisfy the case, and the
    case would be satisfied by the very thing it exists to reject.
    """
    graph = _research_graph(
        _contradicts("claim:alignment", "claim:elsewhere"),
        {"source_id": "claim:alignment", "predicate": "about",
         "target_id": "topic:causal", "source_unit_ids": ["u:1"]},
        {"source_id": "claim:elsewhere", "predicate": "about",
         "target_id": "topic:causal", "source_unit_ids": ["u:1"]},
    )
    assert check_cases([BACKED_BY], graph)["outcome"] == "CASES_FAILED"


def test_no_edges_of_that_predicate_is_not_a_failure():
    """`edge_backed_by` claims nothing about how many edges there are.

    A graph with no disagreements is not a graph with badly-backed ones, and
    conflating the two would make this case unusable on any corpus that
    legitimately has none. Counting is what `edges_per_predicate` is for.
    """
    assert check_cases([BACKED_BY], _research_graph())["outcome"] == "CASES_PASS"


def test_edges_per_predicate_counts_them():
    graph = _research_graph(_contradicts("claim:misleading", "claim:alignment"))
    at_least_one = Case(claim="edges_per_predicate", predicate="contradicts",
                        min=1)
    assert check_cases([at_least_one], graph)["outcome"] == "CASES_PASS"
    assert check_cases([at_least_one], _research_graph())["outcome"] == "CASES_FAILED"


def test_an_edge_claim_missing_its_predicate_is_refused_at_load(tmp_path):
    path = tmp_path / "cases.yaml"
    path.write_text(
        "cases:\n  - claim: edges_per_predicate\n    min: 1\n"
        "    because: nothing names the predicate\n",
        encoding="utf-8")
    with pytest.raises(CaseError):
        load_cases(path)
