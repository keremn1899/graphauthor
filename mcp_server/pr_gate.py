"""Graph-native PR gate (backlog B12) + conformance receipts (B9).

Backend only — the engine a CI/GitHub check would call, not the packaging. A
diff is decomposed per file, each changed file is checked against the rules that
APPLY to its component (the zero-LLM applicability gate keeps out-of-scope pairs
free), and the results aggregate into one PR verdict plus receipts.

Founder decisions (this session):

- **Fail only on VIOLATES.** UNGOVERNED and INSUFFICIENT_EVIDENCE never fail the
  check — a gate that fails on absence is unusable noise. UNGOVERNED changes
  surface as *gaps* (dispositionable via B8 materiality); INSUFFICIENT surfaces
  as *needs_attention*. This is the usability crux, tested directly.
- **Receipts bind to `(diff_hash, graph_version)`.** A green result provably
  means "this diff conformed to this graph revision"; change either and the
  receipt auto-invalidates. `graph_changed` staleness is the lightweight
  anti-rationalization signal — governance moved under previously-checked code.
- **Applicability is free; adjudication is filtered.** Conformance (the model
  call) runs only on applicable (rule, file) pairs.

The conformance and applicability functions are injected so the gate is provable
deterministically; `pr_gate_live` wires the engine's real `check_conformance`.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Callable

# ruling-space verdicts we bucket
_VIOLATES = "VIOLATES"
_CONFORMS = "CONFORMS"
_UNGOVERNED = "UNGOVERNED"
_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"


def diff_hash(diff_text: str) -> str:
    return hashlib.sha1(diff_text.encode("utf-8", "replace")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# decomposition (B12: multi-file, multi-hunk)
# ---------------------------------------------------------------------------

def decompose_diff(diff_text: str) -> list[dict[str, Any]]:
    """Parse a unified diff into per-file changes. Each entry:
    {path, added_text, added, removed, hunks}. Deletions (path → /dev/null) are
    dropped — there is no artifact to check."""
    files: list[dict] = []
    cur: dict | None = None

    def _flush():
        nonlocal cur
        if cur and cur["path"]:
            cur["added_text"] = "\n".join(cur["added"])
            files.append(cur)
        cur = None

    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            _flush()
            cur = {"path": "", "added": [], "removed": [], "hunks": 0}
        elif line.startswith("+++ "):
            path = line[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            if cur is None:
                cur = {"path": "", "added": [], "removed": [], "hunks": 0}
            cur["path"] = "" if path == "/dev/null" else path
        elif line.startswith("--- "):
            continue
        elif line.startswith("@@"):
            if cur is not None:
                cur["hunks"] += 1
        elif line.startswith("+") and not line.startswith("+++"):
            if cur is not None:
                cur["added"].append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            if cur is not None:
                cur["removed"].append(line[1:])
    _flush()
    return files


# ---------------------------------------------------------------------------
# receipts (B9)
# ---------------------------------------------------------------------------

def make_receipt(*, rule_id: str, artifact_path: str, verdict: str,
                 dhash: str, graph_version: str) -> dict[str, Any]:
    return {"rule_id": rule_id, "artifact_path": artifact_path, "verdict": verdict,
            "diff_hash": dhash, "graph_version": graph_version,
            "issued_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def receipt_status(receipt: dict, *, current_diff_hash: str,
                   current_graph_version: str) -> dict[str, Any]:
    """A receipt is valid only while BOTH the diff and the graph revision are
    unchanged. `graph_changed` is the anti-rationalization signal: governance
    moved under a previously-checked diff, so the receipt must not be trusted."""
    diff_changed = receipt["diff_hash"] != current_diff_hash
    graph_changed = receipt["graph_version"] != current_graph_version
    if not diff_changed and not graph_changed:
        return {"valid": True, "stale_reason": ""}
    reason = ("both_changed" if diff_changed and graph_changed
              else "graph_changed" if graph_changed else "diff_changed")
    return {"valid": False, "stale_reason": reason}


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------

def _rationalizations(receipts: list[dict], prior_receipts: list[dict] | None,
                      dhash: str, graph_version: str) -> list[dict]:
    """B9 two-checkpoint: detect governance bent to bless UNCHANGED code. A prior
    receipt for the SAME diff (same code) that was VIOLATES/UNGOVERNED under an
    OLDER graph and now CONFORMS means the graph moved to pass it — a possible
    rationalization. Carries full context for the operator's decision."""
    if not prior_receipts:
        return []
    prior_by = {(r["rule_id"], r["artifact_path"]): r for r in prior_receipts}
    out: list[dict] = []
    for rec in receipts:
        p = prior_by.get((rec["rule_id"], rec["artifact_path"]))
        if (p and p["diff_hash"] == dhash and p["graph_version"] != graph_version
                and p["verdict"] in (_VIOLATES, _UNGOVERNED) and rec["verdict"] == _CONFORMS):
            out.append({
                "rule_id": rec["rule_id"], "artifact_path": rec["artifact_path"],
                "prior_verdict": p["verdict"], "prior_graph_version": p["graph_version"],
                "current_verdict": rec["verdict"], "current_graph_version": graph_version,
                "diff_hash": dhash,
                "note": "unchanged code passed only after a graph change — inspect the "
                        "governance delta (history diff of the two versions) before trusting; "
                        "acknowledge with a reason if the change is legitimate",
            })
    return out


def run_pr_gate(diff_text: str, rules: list[str], *,
                conformance_fn: Callable[[str, str, str], str | dict[str, Any]],
                applicability_fn: Callable[[str, str], bool] | None = None,
                graph_version: str = "", store_path=None,
                prior_receipts: list[dict] | None = None) -> dict[str, Any]:
    """Evaluate a diff against the rules. `conformance_fn(rule_id, artifact,
    path) -> verdict` runs only on applicable pairs; `applicability_fn(rule_id,
    path) -> bool` (optional) pre-filters for free. FAIL iff any VIOLATES.

    `prior_receipts` (from an earlier run of the same diff) enables the B9
    two-checkpoint check: a PASS reached only because the graph changed under
    unchanged code is flagged and marked untrusted until acknowledged."""
    dhash = diff_hash(diff_text)
    files = decompose_diff(diff_text)
    blocking: list[dict] = []
    gaps: list[dict] = []
    needs_attention: list[dict] = []
    conforming: list[dict] = []
    receipts: list[dict] = []

    for f in files:
        path = f["path"]
        candidates = [r for r in rules if applicability_fn(r, path)] if applicability_fn else list(rules)
        if not candidates:
            # nothing governs this change — a gap, never a failure (dispositionable via B8)
            gaps.append({"artifact_path": path, "verdict": _UNGOVERNED,
                         "gap_id": f"component_governance:{path}",
                         "reason": "no rule applies to this component"})
            continue
        for rid in candidates:
            raw = conformance_fn(rid, f["added_text"], path)
            if isinstance(raw, dict):
                verdict = str(
                    raw.get("verdict") or raw.get("corpus_ruling")
                    or raw.get("kind") or raw.get("status") or ""
                ).split(".")[-1].upper()
                predicate = str(
                    raw.get("ungoverned_predicate") or raw.get("predicate") or ""
                ).strip()
            else:
                verdict = str(raw or "").split(".")[-1].upper()
                predicate = ""
            rec = make_receipt(rule_id=rid, artifact_path=path, verdict=verdict,
                               dhash=dhash, graph_version=graph_version)
            receipts.append(rec)
            if verdict == _VIOLATES:
                blocking.append(rec)
            elif verdict == _CONFORMS:
                conforming.append(rec)
            elif verdict == _INSUFFICIENT:
                needs_attention.append(rec)
            else:  # UNGOVERNED (applicable but unruled) — a gap, not a failure
                gaps.append({
                    **rec,
                    "gap_id": predicate or f"{rid}@{path}",
                })

    rationalizations = _rationalizations(receipts, prior_receipts, dhash, graph_version)
    return {
        "verdict": "FAIL" if blocking else "PASS",   # D3: only VIOLATES fails
        "trusted": not rationalizations,             # B9: untrusted until rationalizations acked
        "diff_hash": dhash,
        "graph_version": graph_version,
        "file_count": len(files),
        "blocking": blocking,
        "gaps": gaps,
        "needs_attention": needs_attention,
        "conforming": conforming,
        "rationalizations": rationalizations,
        "receipts": receipts,
    }


def acknowledge_rationalization(store_path, *, rule_id: str, artifact_path: str,
                                actor: str, reasoning: str) -> dict[str, Any]:
    """Flag + require acknowledgment (never a silent bless): an operator accepts
    a flagged rationalization with a REASON (the context that justifies the
    graph change). The gate never acknowledges its own flag."""
    if actor.strip().lower().startswith(("engine", "system", "gate")):
        return {"error": "a rationalization is acknowledged by a human, never by the gate"}
    if not reasoning.strip():
        return {"error": "acknowledgment requires a reason: why is the graph change legitimate, "
                "not a rationalization of already-written code?"}
    return {"acknowledged": True, "rule_id": rule_id, "artifact_path": artifact_path,
            "actor": actor, "reasoning": reasoning}


def pr_gate_live(surface, diff_text: str, *, store_path=None,
                 prior_receipts: list[dict] | None = None) -> dict[str, Any]:
    """Convenience wiring over the real engine (best-effort, not part of the
    deterministic battery): enumerate rule-shaped nodes and call the surface's
    check_conformance — its zero-LLM applicability gate makes out-of-scope pairs
    free, so no separate applicability_fn is needed.

    ``store_path`` / ``prior_receipts`` are forwarded to ``run_pr_gate`` so CI
    packaging can persist receipts and run the B9 two-checkpoint check.
    """
    import re

    from mcp_server.crossing import _all_nodes, _connect

    conn = _connect(surface._db_path)
    try:
        nodes = _all_nodes(conn)
    finally:
        conn.close()
    rule_hint = re.compile(r"\bADJUDICATES\b|\bMUST\b|\brule\b|\bpolicy\b", re.I)
    rules = [
        nid
        for nid, node in nodes.items()
        if not node.get("is_metanode")
        and rule_hint.search(f"{node.get('label', '')} {node.get('text_content', '')}")
    ]

    def _conf(rule_id: str, artifact: str, path: str) -> dict[str, Any]:
        # Gate fail policy uses corpus_ruling when coexist is present (whole-graph
        # question). Fall back to top-line kind / legacy fields.
        out = surface.check_conformance(rule_id=rule_id, artifact=artifact, artifact_path=path)
        for key in ("corpus_ruling", "kind", "verdict", "status"):
            val = out.get(key)
            if val:
                return {**out, "verdict": str(val).split(".")[-1].upper()}
        return {**out, "verdict": _UNGOVERNED}

    gv = surface._base().get("graph_version", "")
    return run_pr_gate(
        diff_text, rules, conformance_fn=_conf, graph_version=gv,
        store_path=store_path, prior_receipts=prior_receipts,
    )
