"""Scope-note vs adjudicate classification — shared by construction surface + Battalion guard.

Describe-vs-adjudicate property detection (not node-ID keyed). See
``design [new]/scope-note-guard-generality-check-handoff.md``.
"""

from __future__ import annotations

import re

# Descriptive scope-note language (construction surface + guard share this).
DESCRIBE_MARKERS = re.compile(
    r"\b(this page does not|does not offer|not a general|scope note|"
    r"does not provide a mechanism|not goodwill|describes only|"
    r"routing only)\b",
    re.I,
)

# Adjudicative deny / procedure — if present, node is NOT a pure scope-note.
ADJUDICATE_DENY_MARKERS = re.compile(
    r"\b(cannot return|non-returnable|must be cancelled|no published policy|"
    r"cannot be changed|within \d+ days|full refund|not change of mind|"
    r"will not price-match|no general competitor)\b",
    re.I,
)

# Intrinsic / discretionary ask shapes (broader than GAP3 wording).
INTRINSIC_ASK_MARKERS = re.compile(
    r"\b(goodwill|voucher.*inconvenience|compensation.*(?:wait|inconvenience|late)|"
    r"goodwill credit|discretionary compensation|gesture of goodwill|"
    r"car.?park.*wait|wait.*inconvenience)\b",
    re.I,
)


def node_text_blob(node: dict) -> str:
    return f"{node.get('label', '')} {node.get('text_content', '')}"


def is_scope_note_node(node: dict) -> bool:
    """Node describes scope without adjudicating the asked discretionary predicate."""
    blob = node_text_blob(node)
    if not DESCRIBE_MARKERS.search(blob):
        return False
    if ADJUDICATE_DENY_MARKERS.search(blob):
        return False
    return True


def is_intrinsic_discretionary_ask(query_text: str) -> bool:
    return bool(INTRINSIC_ASK_MARKERS.search(query_text or ""))


def infer_intrinsic_predicate(query_text: str) -> str:
    """Name the ungoverned discretionary predicate from the ask (not GAP3-hardcoded)."""
    q = (query_text or "").lower()
    if "whoosh" in q and ("late" in q or "compensation" in q or "goodwill" in q):
        return "goodwill compensation or credit for a late-but-within-window delivery"
    if ("click" in q and "collect" in q) or "car park" in q or "car-park" in q:
        return "goodwill compensation for collection wait inconvenience"
    if "goodwill" in q:
        return "goodwill or discretionary compensation"
    return "discretionary remedy not governed by published policy"


def scope_note_guard_applies(
    governance: dict | None,
    query_text: str,
    node_records: list[dict] | None,
) -> tuple[bool, str]:
    """Return (would_fire, reason). Property-keyed — no node IDs."""
    if governance is None:
        return False, "no_governance"
    if governance.get("governance_verdict") != "GOVERNED":
        return False, "not_governed"
    if governance.get("ungoverned_predicate"):
        return False, "named_predicate"
    if not is_intrinsic_discretionary_ask(query_text):
        return False, "not_intrinsic_ask"
    scope_nodes = [n for n in (node_records or []) if is_scope_note_node(n)]
    if not scope_nodes:
        return False, "no_scope_note_in_packet"
    return True, f"scope_note_nodes={len(scope_nodes)}"


def apply_scope_note_guard(
    governance: dict | None,
    query_text: str,
    node_records: list[dict] | None,
) -> tuple[dict | None, bool]:
    """Apply guard; return (governance, fired)."""
    fires, _ = scope_note_guard_applies(governance, query_text, node_records)
    if not fires or governance is None:
        return governance, False
    return {
        "governance_verdict": "UNGOVERNED",
        "ungoverned_predicate": infer_intrinsic_predicate(query_text),
    }, True


def enrich_node_records(node_records: list[dict] | None, conn) -> list[dict]:
    """Load ``text_content`` from graph when packet carries labels only (principled classification)."""
    if not node_records:
        return []
    if conn is None:
        return [dict(n) for n in node_records]
    out: list[dict] = []
    for n in node_records:
        rec = dict(n)
        if rec.get("text_content"):
            out.append(rec)
            continue
        nid = rec.get("id")
        if not nid:
            out.append(rec)
            continue
        try:
            row = conn.execute(
                "MATCH (c:Concept {id: $id}) RETURN c.label, c.text_content",
                {"id": nid},
            ).get_next()
            if row:
                rec.setdefault("label", row[0] or "")
                rec["text_content"] = row[1] or ""
        except Exception:
            pass
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Declared-exclusion guard (general, corpus-driven) — post nonce live_v6.
#
# A rule node may declare its own limits with a machine-readable marker:
#     DOES NOT GOVERN: grant vs separated downstream use (relational)
# When a GOVERNED verdict arrives for a question that matches an exclusion
# declared IN THE RETRIEVED NODES THEMSELVES, the engine demotes to
# UNGOVERNED with the declared predicate verbatim. Asymmetric by design:
# only GOVERNED is ever demoted — the constitution enforcing its own stated
# boundaries deterministically, in the harm-safe direction.
# ---------------------------------------------------------------------------

EXCLUSION_MARKER = re.compile(
    r"(?:DOES NOT GOVERN|DOES NOT ADJUDICATE|EXCLUDES|OUT OF SCOPE)\s*:\s*([^\n.;]+)",
    re.I,
)

_EXCLUSION_STOPWORDS = frozenset(
    "the a an of vs v and or for to in on is are be been was were this that "
    "than it its with as by not no case cases".split()
)


def declared_exclusions(node_records: list[dict] | None) -> list[tuple[str, str]]:
    """(excluded-predicate phrase, source node label) pairs declared in node text."""
    out: list[tuple[str, str]] = []
    for node in node_records or []:
        blob = node_text_blob(node)
        for m in EXCLUSION_MARKER.finditer(blob):
            phrase = m.group(1).strip()
            if phrase:
                out.append((phrase, str(node.get("label") or node.get("id") or "")))
    return out


def _content_tokens(text: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-z0-9\-]+", (text or "").lower())
        if t not in _EXCLUSION_STOPWORDS and len(t) > 2
    }


def exclusion_matches_query(phrase: str, query_text: str) -> bool:
    """Conservative overlap: ≥2 distinct content tokens of the declared phrase
    appear in the query AND they cover ≥ half the phrase's content tokens."""
    p, q = _content_tokens(phrase), _content_tokens(query_text)
    if not p:
        return False
    hits = p & q
    return len(hits) >= 2 and len(hits) / len(p) >= 0.5


def declared_exclusion_guard(
    governance: dict | None,
    query_text: str,
    node_records: list[dict] | None,
) -> tuple[bool, str, str]:
    """(applies, declared_predicate, source_label). Only demotes GOVERNED."""
    if not governance or str(governance.get("governance_verdict", "")).upper() != "GOVERNED":
        return False, "", ""
    for phrase, source in declared_exclusions(node_records):
        if exclusion_matches_query(phrase, query_text):
            return True, phrase, source
    return False, "", ""
