"""Deterministic gap-type corrections.

The Company / Planner LLMs reliably detect *that* a gap exists but
frequently mis-type it. Typed_gap benchmark evidence:

* Queries that name two known entities and an explicit SST edge type
  come back as ``missing_concept`` instead of ``missing_relationship``.
* Queries asking for scalar/temporal attributes the graph lacks as
  EXPRESSES edges come back as ``missing_concept`` instead of
  ``schema_gap``.
* Queries that reference a proper-noun absent from every packet label
  sometimes come back with no gap at all (silent confabulation).

This module post-processes a list of gap dicts and corrects only the
obvious cases — where the signal from the EvidencePacket + query tokens
is unambiguous. Cases where the LLM could plausibly be right are left
untouched.

Applied uniformly across all three pipelines (Pipeline A, Pipeline B,
full Squad/Company) so gap-type shape is consistent regardless of
route.
"""

from __future__ import annotations

import re
from typing import Callable, Iterable

_SCALAR_ATTR_TOKENS: tuple[str, ...] = (
    "unix epoch",
    "signing date",
    "exact date",
    "timestamp",
    "milliseconds",
    "millisecond",
    "nanosecond",
    "lat/long",
    "latitude",
    "longitude",
    "file size in bytes",
    "bytes",
    "percentage",
    "decimal",
    "floating point",
)
_SST_EDGE_TOKENS: tuple[str, ...] = ("leadsto", "contains", "expresses", "nearto")


def _gap_type(g: dict) -> str:
    return str(g.get("gap_type") or g.get("type") or "").lower()


def _set_type(g: dict, new_type: str) -> None:
    g["gap_type"] = new_type
    g["type"] = new_type


def apply_gap_type_hints(
    gaps: list[dict],
    query: str,
    *,
    node_records: Iterable[dict] | None = None,
    edge_records: Iterable[dict] | None = None,
    known_context: str = "",
    token_in_graph: Callable[[str], bool] | None = None,
) -> list[dict]:
    """Return a corrected copy of ``gaps`` using packet-derived signals.

    Mutates entries in place (the caller is expected to own the list).
    ``node_records`` / ``edge_records`` default to empty iterables when
    the packet view is unavailable; in that case only the
    confabulation-on-unknown-entity heuristic runs.

    ``token_in_graph`` answers "does the graph know this word at all". Without
    it the last signal sees only the packet, and a gap is a claim about the
    GRAPH — telling the difference between those two is the product's entire
    thesis, so making the claim from packet evidence alone is the one mistake
    this engine cannot afford to make in its own output.
    """
    if not query:
        return gaps

    node_list = list(node_records or [])
    edge_list = list(edge_records or [])

    labels: dict[str, str] = {}
    for n in node_list:
        lbl = str(n.get("label") or "").strip().lower()
        if lbl:
            labels[lbl] = str(n.get("id") or "")
    def edge_type(edge: dict) -> str:
        return str(
            edge.get("edge_type")
            or edge.get("sst_type")
            or edge.get("type")
            or ""
        ).strip().lower()

    edge_types = {edge_type(edge) for edge in edge_list}

    ql = query.lower()

    # --- Signal 1: schema_gap ------------------------------------------------
    scalar_hits = [tok for tok in _SCALAR_ATTR_TOKENS if tok in ql]
    has_expresses = "expresses" in edge_types
    if scalar_hits and not has_expresses:
        if gaps:
            for g in gaps:
                if _gap_type(g) in ("missing_concept", "missing_relationship"):
                    _set_type(g, "schema_gap")
                    g["actionable_suggestion"] = (
                        f"Graph lacks EXPRESSES attribute edges needed to answer "
                        f"questions about {scalar_hits[0]}."
                    )
        else:
            gaps.append({
                "gap_type": "schema_gap",
                "type": "schema_gap",
                "specific_node_or_concept": scalar_hits[0],
                "actionable_suggestion": (
                    f"Graph lacks EXPRESSES attribute edges needed to answer "
                    f"questions about {scalar_hits[0]}."
                ),
            })

    # --- Signal 2: missing_relationship --------------------------------------
    # An explicit SST edge-type word in the query ("LEADSTO edge between X and Y")
    # is near-certain evidence that the user is asking about a relationship,
    # not an entity. Extract two capitalised proper-noun-like tokens as
    # candidate endpoints (fall back to any in-packet labels that appear).
    edge_token_hits = [t for t in _SST_EDGE_TOKENS if re.search(rf"\b{t}\b", ql)]
    mentioned_labels = [lbl for lbl in labels if len(lbl) >= 3 and lbl in ql]
    proper_nouns: list[str] = []
    if edge_token_hits:
        _STOPWORDS = {
            "which", "what", "when", "where", "who", "why", "how",
            "the", "this", "that", "those", "these",
            *(t.lower() for t in _SST_EDGE_TOKENS),
        }
        for tok in re.findall(r"\b([A-Z][A-Za-z0-9_\-]{2,})\b", query):
            if tok.lower() not in _STOPWORDS:
                proper_nouns.append(tok)
    endpoints = mentioned_labels or proper_nouns
    mentioned_ids = {
        labels[label]
        for label in mentioned_labels
        if labels.get(label)
    }
    requested_edge_present = any(
        edge_type(edge) in edge_token_hits
        and str(edge.get("source_id") or edge.get("source") or "") in mentioned_ids
        and str(edge.get("target_id") or edge.get("target") or "") in mentioned_ids
        for edge in edge_list
    )
    if (edge_token_hits or len(mentioned_labels) >= 2) and endpoints:
        for g in gaps:
            if (
                _gap_type(g) == "missing_concept"
                and not requested_edge_present
            ):
                _set_type(g, "missing_relationship")
                g["specific_node_or_concept"] = endpoints[0].lower()
                edge_word = edge_token_hits[0].upper() if edge_token_hits else "direct"
                g["actionable_suggestion"] = (
                    f"The query asks about a {edge_word} edge, not a missing concept. "
                    f"Author the missing relationship between the named endpoints."
                )

    # --- Signal 3: unknown-entity confabulation ------------------------------
    _CAPS_STOPWORDS = {
        "does", "what", "when", "where", "which", "who", "why", "how",
        "can", "could", "should", "would", "may", "might", "must",
        "the", "this", "that", "those", "these", "a", "an",
        "is", "are", "was", "were", "be", "been", "being",
        "i", "we", "you", "they", "he", "she", "it",
        "return", "give", "list", "show", "find", "compute", "tell",
        "trace", "connect", "describe", "explain",
        # The SST edge types. Signal 2's list had them and this one did not, so
        # "What EXPRESSES edge connects Gandalf to the One Ring?" produced
        # "Add a node for 'EXPRESSES'" — advice to create a node named after an
        # edge type, which cannot be acted on. Two lists that had to agree and
        # did not; there is now one source for the edge vocabulary.
        *(t.lower() for t in _SST_EDGE_TOKENS),
    }
    # An edge question that produced no gap at all is a missing *relationship*,
    # not an unknown entity. Signal 2 only re-types gaps that already exist, so
    # when the packet yielded none this fell through to the confabulation signal
    # below and guessed at a concept. The question already says what is missing:
    # an edge of the named type between the named endpoints.
    if (
        not gaps
        and edge_token_hits
        and len(mentioned_ids) >= 2
        and not requested_edge_present
    ):
        gaps.append({
            "gap_type": "missing_relationship",
            "type": "missing_relationship",
            "specific_node_or_concept": endpoints[0].lower(),
            "actionable_suggestion": (
                f"The query asks for a {edge_token_hits[0].upper()} edge between "
                f"the named endpoints and the packet holds none. Author that "
                f"relationship, or confirm it does not exist."
            ),
        })

    if not gaps:
        caps = re.findall(r"\b([A-Z][A-Za-z0-9_\-]{3,})\b", query)
        packet_text = " ".join(labels.keys())
        known_text = f"{packet_text} {known_context}".casefold()
        for token in caps:
            if token.lower() in _CAPS_STOPWORDS:
                continue
            # Absent from the packet is not absent from the graph. Measured on
            # the NIST SSDF held-out set: two of three queries were told to
            # "Add a node for 'NIST'" and "for 'SSDF'" while `nist_ssdf_1_1`
            # ("NIST SSDF 1.1") sat in the graph, merely unretrieved. Reporting
            # a retrieval miss as a corpus gap sends an operator to author a
            # node they already have.
            if token.lower() not in known_text and token_in_graph is not None:
                try:
                    known_to_graph = token_in_graph(token)
                except Exception:
                    # Fail open, deliberately: if the check cannot answer, the
                    # hinter must not assert absence. A missing gap is a smaller
                    # harm than a fabricated one, and the caller's own guard is
                    # not something this function should rely on.
                    known_to_graph = True
                if known_to_graph:
                    continue
            if token.lower() not in known_text:
                gaps.append({
                    "gap_type": "missing_concept",
                    "type": "missing_concept",
                    "specific_node_or_concept": token.lower(),
                    "actionable_suggestion": (
                        f"Add a node for '{token}' so queries referencing it can "
                        f"ground against explicit evidence."
                    ),
                })
                break

    return gaps
