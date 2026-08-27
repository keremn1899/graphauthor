"""Unit tests for the corpus generator's pure helpers (no LLM needed)."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.gen_queries import CLASS_TEMPLATES, _build_case, promote


_SUMMARY = {
    "nodes": [
        {"id": "char_frodo", "label": "Frodo"},
        {"id": "item_ring", "label": "One Ring"},
    ],
    "edges": [
        {
            "source_id": "char_frodo",
            "target_id": "item_ring",
            "edge_type": "expresses",
            "edge_label": "is_bearer_of",
        }
    ],
    "landmarks": [],
    "metanodes": [],
    "structural_roles": {},
}


def test_class_templates_cover_v6_taxonomy() -> None:
    from models import V6_QUERY_CLASS

    expected = set(V6_QUERY_CLASS.__args__) - {"unknown"}
    assert expected.issubset(CLASS_TEMPLATES.keys()), (
        f"generator missing templates for: {sorted(expected - set(CLASS_TEMPLATES))}"
    )


def test_build_case_clamps_unknown_node_ids() -> None:
    raw = {
        "query": "What expresses what?",
        "required_edge_types": ["expresses", "contains"],  # contains not in summary
        "required_node_ids_any": ["char_frodo", "fake_id"],  # fake_id not in summary
    }
    case = _build_case("lotr", "enumeration", raw, _SUMMARY, 0, "20260101T000000Z")
    assert case["ground_truth"]["required_edge_types"] == ["expresses"]
    assert case["ground_truth"]["required_node_ids_any"] == ["char_frodo"]


def test_build_case_meta_gap_has_required_gap_type() -> None:
    raw = {"query": "Where is the economy?", "notes": "absent_concept"}
    case = _build_case("lotr", "meta_gap", raw, _SUMMARY, 0, "20260101T000000Z")
    assert case["ground_truth"]["answerable"] is False
    assert case["ground_truth"]["expected_gap_types_required"] == ["missing_concept"]
    assert "EXHAUSTED" in case["ground_truth"]["expected_verdict"]


def test_promote_appends_to_seed_file(tmp_path: Path, monkeypatch) -> None:
    # Temporarily redirect CORPUS_DIR inside the promote() function.
    import scripts.gen_queries as gq

    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "lotr.yaml").write_text(
        yaml.safe_dump([{"id": "existing_one", "query": "q", "seed": "lotr"}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(gq, "CORPUS_DIR", corpus_dir)

    proposal_path = tmp_path / "proposal.yaml"
    proposal_case = {
        "id": "proposed_one",
        "query": "What expresses what?",
        "seed": "lotr",
        "query_class": "enumeration",
        "ground_truth": {"answerable": True},
    }
    proposal_path.write_text(yaml.safe_dump([proposal_case]), encoding="utf-8")

    promote(proposal_path)
    combined = yaml.safe_load((corpus_dir / "lotr.yaml").read_text(encoding="utf-8"))
    ids = {c["id"] for c in combined}
    assert ids == {"existing_one", "proposed_one"}


def test_promote_skips_duplicates(tmp_path: Path, monkeypatch) -> None:
    import scripts.gen_queries as gq

    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    (corpus_dir / "lotr.yaml").write_text(
        yaml.safe_dump([{"id": "dup_id", "query": "q", "seed": "lotr"}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(gq, "CORPUS_DIR", corpus_dir)

    proposal_path = tmp_path / "proposal.yaml"
    proposal_path.write_text(
        yaml.safe_dump(
            [
                {
                    "id": "dup_id",
                    "query": "q2",
                    "seed": "lotr",
                    "query_class": "enumeration",
                }
            ]
        ),
        encoding="utf-8",
    )
    promote(proposal_path)
    combined = yaml.safe_load((corpus_dir / "lotr.yaml").read_text(encoding="utf-8"))
    assert len(combined) == 1
