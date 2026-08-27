"""Component-applicability gate — rule→component boundaries from the constitution graph.

Reads LEADSTO targets for a rule node; if the change's component is explicitly
scoped out, returns honest UNGOVERNED before Battalion/semantic adjudication.

Handoff: design [new]/component-applicability-gate-handoff.md
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

_COMPONENT_CACHE: dict[int, list[tuple[str, str, str]]] = {}


@dataclass(frozen=True)
class ApplicabilityResult:
    gated: bool
    predicate: str = ""
    grounding: str = ""
    rule_id: str = ""
    change_component: str | None = None
    governed_components: tuple[str, ...] = ()
    ambiguous: bool = False


def _conn_key(conn: Any) -> int:
    return id(conn)


def _filename_from_label(snippet_label: str, target_file: str | None) -> str | None:
    if target_file:
        from pathlib import Path

        return Path(target_file).name
    label = (snippet_label or "").strip()
    if not label:
        return None
    base = label.split(":", 1)[0].strip()
    if base.endswith(".py") or "/" in base or "\\" in base:
        from pathlib import Path

        return Path(base).name
    return None


def _load_component_registry(conn: Any) -> list[tuple[str, str, str]]:
    """All LEADSTO targets (id, label, semantic_anchor) — handbook component nodes."""
    key = _conn_key(conn)
    if key in _COMPONENT_CACHE:
        return _COMPONENT_CACHE[key]
    rows = list(
        conn.execute(
            "MATCH (r:Concept)-[:LEADSTO]->(c:Concept) "
            "RETURN DISTINCT c.id, c.label, c.semantic_anchor"
        )
    )
    registry = [(str(r[0]), str(r[1] or ""), str(r[2] or "")) for r in rows]
    _COMPONENT_CACHE[key] = registry
    return registry


def governed_components_for_rule(conn: Any, rule_id: str) -> list[str]:
    """LEADSTO component targets explicitly governed by this rule."""
    rows = list(
        conn.execute(
            "MATCH (r:Concept {id: $rid})-[:LEADSTO]->(c:Concept) RETURN c.id",
            parameters={"rid": rule_id},
        )
    )
    return [str(r[0]) for r in rows]


def resolve_change_component(
    conn: Any,
    *,
    snippet_label: str = "",
    target_file: str | None = None,
) -> str | None:
    """Map a file/snippet label to a handbook component id, if unambiguous."""
    filename = _filename_from_label(snippet_label, target_file)
    if not filename:
        return None
    stem = re.sub(r"\.py$", "", filename, flags=re.I).lower()
    registry = _load_component_registry(conn)
    matches: list[str] = []
    for cid, _label, anchor in registry:
        anchor_l = anchor.lower()
        if filename.lower() in anchor_l or stem in anchor_l.replace("_", ""):
            matches.append(cid)
            continue
        if stem.replace("_", "") in cid.lower().replace("_", ""):
            matches.append(cid)
    unique = list(dict.fromkeys(matches))
    if len(unique) == 1:
        return unique[0]
    return None


def evaluate_component_applicability(
    conn: Any,
    *,
    rule_id: str,
    snippet_label: str = "",
    target_file: str | None = None,
) -> ApplicabilityResult:
    """Return gated=True when the constitution explicitly scopes the rule away from this file."""
    governed = governed_components_for_rule(conn, rule_id)
    if not governed:
        return ApplicabilityResult(gated=False, rule_id=rule_id)

    change = resolve_change_component(
        conn, snippet_label=snippet_label, target_file=target_file
    )
    if change is None:
        return ApplicabilityResult(
            gated=False,
            rule_id=rule_id,
            governed_components=tuple(governed),
            ambiguous=True,
        )

    if change in governed:
        return ApplicabilityResult(
            gated=False,
            rule_id=rule_id,
            change_component=change,
            governed_components=tuple(governed),
        )

    governed_names = ", ".join(governed)
    predicate = (
        f"{rule_id} does not govern {change} — it governs {governed_names}"
    )
    grounding = (
        f"The credential governance handbook scopes {rule_id} to "
        f"{governed_names} via LEADSTO component boundaries. "
        f"The change under review maps to {change}, which is outside that scope. "
        f"No conformance adjudication applies — UNGOVERNED (rule does not govern this component)."
    )
    return ApplicabilityResult(
        gated=True,
        rule_id=rule_id,
        predicate=predicate,
        grounding=grounding,
        change_component=change,
        governed_components=tuple(governed),
    )


def applicability_verdict(result: ApplicabilityResult) -> dict[str, str]:
    """ConformanceVerdict-compatible fields for a gated result."""
    return {
        "verdict": "UNGOVERNED",
        "rule": result.rule_id,
        "predicate": result.predicate,
        "grounding": result.grounding,
        "confidence_note": "component_applicability_gate",
        "governance_status": "UNGOVERNED",
        "engine_verdict": "ILL_POSED",
    }
