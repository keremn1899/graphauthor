"""Structural scoped adjudication — one rule node text vs artifact (no retrieval).

Escalation from FINDINGS_SCOPING.md: prompt-level "judge only rule X" failed because
retrieval still fed neighbouring obligations. Scope by construction:

    scoped_ruling(X, artifact) := adjudicate(artifact, context = text_content(X) ONLY)

Umbrella / delegating rules that omit obligations from their own text will
under-scope — that is a grain signal, not a soft-instruction failure.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from conformance_verdict import ConformanceKind, ConformanceVerdict

SCOPED_SYSTEM = """You are a strict conformance judge for ONE rule only.

You receive:
- RULE NODE TEXT — the complete text of a single governance rule node
- ARTIFACT — code or content under judgment

Decide whether the artifact conforms to obligations stated IN THAT RULE TEXT.
- If every obligation in the rule text is satisfied → CONFORMS
- If any obligation in the rule text is breached → VIOLATES
- If the rule text clearly does not govern this artifact at all → UNGOVERNED
- If the rule text is too thin or ambiguous to decide → INSUFFICIENT_EVIDENCE

CRITICAL — narrow reading:
- Do not invent, recall, or apply any other rule, licence section, or policy.
- Do not treat a *related-sounding* practice as the same obligation. Example:
  shipping a NOTICE file is NOT the same obligation as retaining copyright
  headers in source files, unless THIS rule text explicitly requires both.
- A breach of some other rule that is NOT written in the provided rule text
  must NOT produce VIOLATES — answer CONFORMS if this rule's own obligations
  are met.
- Quote or paraphrase the exact clause you rely on in grounding.

Return JSON only:
{"verdict": "CONFORMS"|"VIOLATES"|"UNGOVERNED"|"INSUFFICIENT_EVIDENCE",
 "grounding": "one short paragraph citing the rule text"}
"""


def structural_scoped_enabled() -> bool:
    """Default ON. Set SST_SCOPED_STRUCTURAL=0 to fall back to soft prompt scope."""
    raw = (os.environ.get("SST_SCOPED_STRUCTURAL") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def resolve_rule_node(db_path: Path | str, rule_id: str) -> dict[str, Any] | None:
    """Match Concept by id (exact) or label (case-insensitive / contains)."""
    from mcp_server.crossing import _all_nodes, _connect

    rid = str(rule_id or "").strip()
    if not rid:
        return None
    conn = _connect(db_path)
    try:
        nodes = _all_nodes(conn)
    finally:
        conn.close()

    if rid in nodes:
        n = dict(nodes[rid])
        n["id"] = rid
        return n

    rid_l = rid.lower()
    # exact label
    for nid, n in nodes.items():
        if str(n.get("label") or "").strip().lower() == rid_l:
            out = dict(n)
            out["id"] = nid
            return out
    # label contains / id contains (Apache probes pass labels)
    for nid, n in nodes.items():
        lab = str(n.get("label") or "")
        if rid_l in lab.lower() or rid_l in nid.lower():
            out = dict(n)
            out["id"] = nid
            return out
    return None


def adjudicate_rule_text_only(
    *,
    rule_id: str,
    rule_text: str,
    rule_label: str,
    artifact: str,
    artifact_path: str | None = None,
    model: str | None = None,
) -> ConformanceVerdict:
    """LLM judge over rule text + artifact only — no graph retrieval."""
    from mcp_server.json_model import invoke_json_model

    path_line = f"\nARTIFACT PATH: {artifact_path}" if artifact_path else ""
    user = (
        f"RULE ID: {rule_id}\n"
        f"RULE LABEL: {rule_label}\n"
        f"RULE NODE TEXT:\n{rule_text.strip()}\n"
        f"{path_line}\n"
        f"ARTIFACT UNDER JUDGMENT:\n{artifact.strip()}\n"
    )
    try:
        data = invoke_json_model(
            SCOPED_SYSTEM, user, tier="heavy", model=model, max_tokens=1024,
        )
    except Exception as exc:  # noqa: BLE001
        return ConformanceVerdict(
            verdict=ConformanceKind.INSUFFICIENT_EVIDENCE,
            rule=rule_id,
            grounding=f"scoped structural adjudicate failed: {exc}",
            engine_degraded=True,
            degradation_flags=[f"engine_fault:scoped_structural:{type(exc).__name__}"],
        )

    raw = str(data.get("verdict") or data.get("kind") or "").strip().upper()
    try:
        kind = ConformanceKind(raw)
    except ValueError:
        kind = ConformanceKind.INSUFFICIENT_EVIDENCE
    return ConformanceVerdict(
        verdict=kind,
        rule=rule_id,
        grounding=str(data.get("grounding") or "")[:2000],
        engine_verdict="SCOPED_STRUCTURAL",
        planner_route="scoped_single_node",
    )


def scoped_ruling_for_db(
    db_path: Path | str,
    *,
    rule_id: str,
    artifact: str,
    artifact_path: str | None = None,
    model: str | None = None,
) -> ConformanceVerdict:
    node = resolve_rule_node(db_path, rule_id)
    if node is None:
        return ConformanceVerdict(
            verdict=ConformanceKind.INSUFFICIENT_EVIDENCE,
            rule=rule_id,
            grounding=f"no rule node matched rule_id={rule_id!r}",
            engine_verdict="SCOPED_NO_NODE",
            planner_route="scoped_single_node",
        )
    text = str(node.get("text_content") or "").strip()
    if not text:
        return ConformanceVerdict(
            verdict=ConformanceKind.INSUFFICIENT_EVIDENCE,
            rule=rule_id,
            grounding="matched rule node has empty text_content",
            engine_verdict="SCOPED_EMPTY_RULE",
            planner_route="scoped_single_node",
        )
    return adjudicate_rule_text_only(
        rule_id=rule_id,
        rule_text=text,
        rule_label=str(node.get("label") or rule_id),
        artifact=artifact,
        artifact_path=artifact_path,
        model=model,
    )
