"""Automatic distractor gate — multi-cycle methodology, built-in."""

from __future__ import annotations

from collections import Counter

from write_path.models import DistractorFinding


def verdict_rates(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0, "GOVERNED": 0.0, "UNGOVERNED": 0.0, "ABSENT": 0.0, "distribution": {}}
    n = len(rows)
    d = Counter(str(r.get("governance_verdict", "?")).upper() for r in rows)
    return {
        "n": n,
        "GOVERNED": d.get("GOVERNED", 0) / n,
        "UNGOVERNED": d.get("UNGOVERNED", 0) / n,
        "ABSENT": d.get("ABSENT", 0) / n,
        "distribution": dict(d),
    }


def movement(before: dict, after: dict) -> dict:
    return {
        "gov_delta": after.get("GOVERNED", 0) - before.get("GOVERNED", 0),
        "ungov_delta": after.get("UNGOVERNED", 0) - before.get("UNGOVERNED", 0),
        "absent_delta": after.get("ABSENT", 0) - before.get("ABSENT", 0),
    }


def check_distractors(
    baseline: dict[str, dict],
    post_rows: dict[str, list[dict]],
    *,
    encoded_gap_ids: list[str],
    gap_anchor_ids: tuple[str, ...],
    flaky_anchor_ids: tuple[str, ...],
    intentional_closure_ids: tuple[str, ...],
    intrinsic_ids: tuple[str, ...],
) -> tuple[bool, list[DistractorFinding]]:
    """Return (clean, findings). False-GOVERNED or anchor regression → not clean."""
    findings: list[DistractorFinding] = []

    for qid, rows in post_rows.items():
        if not rows:
            continue
        br = baseline.get(qid, {})
        ar = verdict_rates(rows)
        mov = movement(br, ar)
        gov_delta = mov["gov_delta"]
        ungov_delta = mov["ungov_delta"]
        before_ungov = br.get("UNGOVERNED", 0)

        if qid in encoded_gap_ids:
            continue
        if qid in gap_anchor_ids and gov_delta > 0:
            findings.append(DistractorFinding(
                query_id=qid, kind="intrinsic_gap_governed", **mov,
            ))
        elif qid in flaky_anchor_ids:
            if abs(ungov_delta) > 0.15:
                findings.append(DistractorFinding(
                    query_id=qid,
                    kind="flaky_anchor_ungov_shift",
                    flaky_only=True,
                    **mov,
                ))
        elif before_ungov >= 0.5 and gov_delta >= 0.2 and ungov_delta <= -0.2:
            findings.append(DistractorFinding(
                query_id=qid, kind="movement_toward_governed", **mov,
            ))
        elif qid not in intrinsic_ids and qid not in intentional_closure_ids:
            if br.get("GOVERNED", 0) >= 0.8 and ar.get("GOVERNED", 0) < 0.7:
                findings.append(DistractorFinding(
                    query_id=qid, kind="governed_anchor_dropped", **mov,
                ))

    # Coverage pass: a pinned/baselined query that produced NO post rows is a
    # gate hole, not a pass — an encode that makes an anchor crash (rather than
    # flip) must block. Flaky anchors stay advisory; the encoded gap itself is
    # exercised by check_closure, not here.
    monitored = (
        set(baseline)
        | set(gap_anchor_ids)
        | set(flaky_anchor_ids)
        | set(intrinsic_ids)
    )
    for qid in sorted(monitored):
        if qid in encoded_gap_ids or qid in intentional_closure_ids:
            continue
        if not post_rows.get(qid):
            findings.append(DistractorFinding(
                query_id=qid,
                kind="anchor_unanswerable",
                flaky_only=qid in flaky_anchor_ids,
            ))

    blocking = [f for f in findings if not f.flaky_only]
    return len(blocking) == 0, findings


def check_closure(
    gap_id: str,
    rows: list[dict],
    *,
    policy_id: str,
    also_valid: list[str] | None = None,
    wrong_adjacent: list[str] | None = None,
    policy_in_grounding,
    adjacent_only,
    min_gov_rate: float = 0.7,
) -> dict:
    """Right-reason closure check for the encoded gap."""
    rates = verdict_rates(rows)
    n = rates["n"]
    gov_n = rates.get("distribution", {}).get("GOVERNED", 0)
    also = also_valid or []
    wrong = wrong_adjacent or []
    right_reason = sum(
        1 for r in rows
        if r.get("governance_verdict") == "GOVERNED"
        and policy_in_grounding(r, policy_id, also)
    )
    adjacent = [
        r for r in rows
        if adjacent_only(r, wrong, policy_id, also)
    ]
    closes = (
        n > 0
        and gov_n >= max(1, n * min_gov_rate)
        and right_reason >= max(1, gov_n * min_gov_rate)
        and not adjacent
    )
    return {
        "n": n,
        "governed": gov_n,
        "right_reason": right_reason,
        "closes_cleanly": closes,
        "adjacent_mistaken": len(adjacent),
    }
