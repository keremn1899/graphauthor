"""Graph-side temporal ops for WHEN applicability (design: node-properties.md).

Temporal validity is an ADDITIVE, optional layer: the columns are added by
``ALTER`` (no core-DDL surgery), read DEFENSIVELY (a graph without them = every
rule timeless = today's exact behavior), and consumed by a zero-LLM conformance
gate — a rule out of its window at ``as_of`` does not govern, resolved before any
adjudication (the temporal sibling of the rule×component applicability gate).

Reads never mutate schema (the gate is read-only); only the write path
(``set_rule_window``) ensures the columns exist.
"""

from __future__ import annotations

from mcp_server.applicability import rule_applies_at

_TEMPORAL_COLS = ("effective_from", "effective_until")


def _esc(s: str) -> str:
    return str(s or "").replace("'", "''")


def ensure_temporal_columns(conn) -> None:
    """Add the optional temporal columns to Concept. ``ALTER`` is not idempotent
    in ladybug, so an 'already has property' error is the success path."""
    for col in _TEMPORAL_COLS:
        try:
            conn.execute(f"ALTER TABLE Concept ADD {col} STRING DEFAULT ''")
        except Exception as exc:
            if "already has property" not in str(exc).lower():
                raise


def read_windows(conn) -> dict[str, tuple[str, str]]:
    """{node_id: (effective_from, effective_until)} for every node. Empty dict on a
    graph with no temporal columns — backward-compatible, never raises for that."""
    try:
        rows = conn.execute(
            "MATCH (c:Concept) RETURN c.id, c.effective_from, c.effective_until")
    except Exception:
        return {}
    out: dict[str, tuple[str, str]] = {}
    for row in rows:
        r = list(row)
        out[str(r[0])] = (str(r[1] or ""), str(r[2] or ""))
    return out


def get_rule_window(conn, node_id: str) -> tuple[str, str]:
    """(effective_from, effective_until) for one node; ('', '') when the node has
    no window or the graph has no temporal columns."""
    try:
        rows = conn.execute(
            f"MATCH (c:Concept {{id:'{_esc(node_id)}'}}) "
            "RETURN c.effective_from, c.effective_until")
    except Exception:
        return ("", "")
    for row in rows:
        r = list(row)
        return (str(r[0] or ""), str(r[1] or ""))
    return ("", "")


def set_rule_window(conn, node_id: str, effective_from: str = "",
                    effective_until: str = "") -> None:
    """Set a rule's window (ensuring the columns exist first). This is the write
    path construction will call once temporal extraction is wired; usable now to
    author windows directly."""
    ensure_temporal_columns(conn)
    conn.execute(
        f"MATCH (c:Concept {{id:'{_esc(node_id)}'}}) "
        f"SET c.effective_from='{_esc(effective_from)}', "
        f"c.effective_until='{_esc(effective_until)}'")


def temporal_gate(conn, rule_id: str, as_of: str | None = None) -> tuple[bool, tuple[str, str]]:
    """Zero-LLM WHEN gate. Returns (governs_at_as_of, (from, until)). A rule with
    no window governs (today's behavior); a windowed rule governs only if ``as_of``
    is inside it. The caller (check_conformance) short-circuits to UNGOVERNED when
    this is False — before any adjudication."""
    ef, eu = get_rule_window(conn, rule_id)
    if not ef and not eu:
        return True, (ef, eu)
    return rule_applies_at(ef, eu, as_of), (ef, eu)
