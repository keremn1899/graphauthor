"""Write-path machinery unit tests (Stages 1–2 free; distractor gate synthetic)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from write_path.config import RecurrenceConfig
from write_path.curation import CurationWorkflow
from write_path.distractor import check_distractors
from write_path.models import EscalationRecord, GapHintClass, PrimarySource
from write_path.recurrence import analyze_recurrence, records_from_capture_rows


def _synthetic_records():
    return records_from_capture_rows([
        {"governance_verdict": "UNGOVERNED", "ungoverned_predicate": "price match / competitor price adjustment", "query_id": "GAP1"},
        {"governance_verdict": "UNGOVERNED", "ungoverned_predicate": "price match / competitor price adjustment", "query_id": "GAP1"},
        {"governance_verdict": "UNGOVERNED", "ungoverned_predicate": "price match / competitor price adjustment", "query_id": "GAP1"},
        {"governance_verdict": "UNGOVERNED", "ungoverned_predicate": "changing delivery address for an order in transit", "query_id": "GAP2"},
        {"governance_verdict": "UNGOVERNED", "ungoverned_predicate": "changing delivery address for an order in transit", "query_id": "GAP2"},
        {"governance_verdict": "UNGOVERNED", "ungoverned_predicate": "changing delivery address for an order in transit", "query_id": "GAP2"},
        {"governance_verdict": "UNGOVERNED", "ungoverned_predicate": "goodwill compensation for late delivery", "query_id": "GAP3"},
        {"governance_verdict": "UNGOVERNED", "ungoverned_predicate": "goodwill compensation for late delivery", "query_id": "GAP3"},
        {"governance_verdict": "UNGOVERNED", "ungoverned_predicate": "goodwill compensation for late delivery", "query_id": "GAP3"},
        {"governance_verdict": "UNGOVERNED", "ungoverned_predicate": "goodwill compensation for late delivery", "query_id": "GAP3"},
    ])


def test_recurrence_surfaces_legislatable_not_intrinsic():
    analysis = analyze_recurrence(_synthetic_records(), config=RecurrenceConfig(min_occurrences=3))
    cand_samples = {c.sample_predicate for c in analysis.candidates}
    assert any("price match" in p for p in cand_samples)
    assert any("delivery address" in p for p in cand_samples)
    assert not any("goodwill" in c.sample_predicate for c in analysis.candidates)
    assert any("goodwill" in r.sample_predicate for r in analysis.recurring_intrinsic)


def test_recurrence_on_disk_captures_if_present():
    cap = Path(__file__).resolve().parents[1] / "examples/tesco-returns/results/legislatable_intrinsic/full/captures.json"
    if not cap.exists():
        pytest.skip("legislatable_intrinsic captures not on disk")
    rows = json.loads(cap.read_text())
    analysis = analyze_recurrence(
        records_from_capture_rows(rows),
        config=RecurrenceConfig(min_occurrences=3),
    )
    assert analysis.candidates
    assert analysis.recurring_intrinsic
    assert not any("goodwill" in c.sample_predicate for c in analysis.candidates)


def test_workflow_confirm_routes_to_encode_reject_exits():
    analysis = analyze_recurrence(_synthetic_records(), config=RecurrenceConfig(min_occurrences=3))
    wf = CurationWorkflow(analysis)
    cand = next(c for c in wf.list_candidates() if "price match" in c.sample_predicate)
    confirmed = wf.confirm(
        cand.candidate_id,
        gap_id="GAP1",
        primary_source=PrimarySource(
            policy_id="t31_no_general_competitor_price_match",
            source_url="https://example.com",
            source_note="human supplied",
        ),
    )
    assert confirmed.gap_id == "GAP1"
    assert wf.status(cand.candidate_id).value == "CONFIRMED"
    assert len(wf.list_candidates()) == len(analysis.candidates) - 1

    intrinsic = next(r for r in analysis.recurring_intrinsic if "goodwill" in r.sample_predicate)
    assert intrinsic.b_hint == GapHintClass.INTRINSIC


def test_distractor_gate_catches_intrinsic_false_governed():
    baseline = {
        "GAP3": {"GOVERNED": 0.0, "UNGOVERNED": 1.0, "ABSENT": 0.0},
        "G1": {"GOVERNED": 1.0, "UNGOVERNED": 0.0, "ABSENT": 0.0},
    }
    post = {
        "GAP3": [{"governance_verdict": "GOVERNED"}] * 5,
        "G1": [{"governance_verdict": "GOVERNED"}] * 5,
    }
    clean, findings = check_distractors(
        baseline,
        post,
        encoded_gap_ids=["GAP1"],
        gap_anchor_ids=("GAP3", "ADJ2"),
        flaky_anchor_ids=("ADJ1",),
        intentional_closure_ids=("GAP1", "GAP2", "LEG-PERISH"),
        intrinsic_ids=("GAP3", "ADJ2"),
    )
    assert not clean
    assert any(f.kind == "intrinsic_gap_governed" for f in findings)


def test_distractor_gate_flaky_shift_does_not_block():
    baseline = {
        "ADJ1": {"GOVERNED": 0.333, "UNGOVERNED": 0.667, "ABSENT": 0.0},
    }
    post = {
        "ADJ1": [{"governance_verdict": "GOVERNED"}] * 3,
        # Blocking pins must be re-measured post-encode: an unmeasured pin is
        # now an anchor_unanswerable finding, not a silent pass.
        "GAP3": [{"governance_verdict": "UNGOVERNED"}] * 3,
        "ADJ2": [{"governance_verdict": "UNGOVERNED"}] * 3,
    }
    clean, findings = check_distractors(
        baseline,
        post,
        encoded_gap_ids=["GAP1"],
        gap_anchor_ids=("GAP3", "ADJ2"),
        flaky_anchor_ids=("ADJ1",),
        intentional_closure_ids=("GAP1", "GAP2", "LEG-PERISH"),
        intrinsic_ids=("GAP3", "ADJ2"),
    )
    assert clean
    assert any(f.kind == "flaky_anchor_ungov_shift" and f.flaky_only for f in findings)


def test_distractor_gate_clean_when_anchors_stable():
    baseline = {
        "GAP3": {"GOVERNED": 0.0, "UNGOVERNED": 1.0, "ABSENT": 0.0},
        "G1": {"GOVERNED": 1.0, "UNGOVERNED": 0.0, "ABSENT": 0.0},
        "ADJ2": {"GOVERNED": 0.0, "UNGOVERNED": 1.0, "ABSENT": 0.0},
        "ADJ1": {"GOVERNED": 0.333, "UNGOVERNED": 0.667, "ABSENT": 0.0},
    }
    post = {
        "GAP3": [{"governance_verdict": "UNGOVERNED"}] * 5,
        "G1": [{"governance_verdict": "GOVERNED"}] * 5,
        "GAP1": [{"governance_verdict": "GOVERNED"}] * 8 + [{"governance_verdict": "ABSENT"}] * 2,
        # All declared pins are re-measured: unmeasured pins now surface as
        # anchor_unanswerable rather than passing silently.
        "ADJ2": [{"governance_verdict": "UNGOVERNED"}] * 5,
        "ADJ1": [{"governance_verdict": "GOVERNED"}] * 1 + [{"governance_verdict": "UNGOVERNED"}] * 2,
    }
    clean, findings = check_distractors(
        baseline,
        post,
        encoded_gap_ids=["GAP1"],
        gap_anchor_ids=("GAP3", "ADJ2"),
        flaky_anchor_ids=("ADJ1",),
        intentional_closure_ids=("GAP1", "GAP2", "LEG-PERISH"),
        intrinsic_ids=("GAP3", "ADJ2"),
    )
    assert clean
    assert not findings
