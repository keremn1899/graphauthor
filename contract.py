"""Agent Contract v1 response builder.

Given a final EngineState produced by the LangGraph pipeline, build the
frozen contractual response object described in
``design [new]/agent-contract-v1.md``. This module is the engine's one
stable output surface — internal pipeline changes must not alter its
shape.

The builder is deterministic. It does not call the LLM. Every field is
derived from the engine's existing state, with structured normalisation
so agents parsing the contract see the same schema regardless of which
retrieval strategy produced the packet.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Iterable, Literal

from interaction.gap_types import (
    CONTRACT_GAP_TYPES, TRANSLATION, translate)
from pydantic import BaseModel, Field


CONTRACT_VERSION: str = "1"


# ---------------------------------------------------------------------------
# Pydantic schemas (authoritative shape for contract conformance tests)
# ---------------------------------------------------------------------------

AnswerType = Literal["yes_no", "list", "narrative", "structural"]
VerdictKind = Literal[
    "CONFIRMED",
    "ALTERNATIVE",
    "EXHAUSTED",
    "ILL_POSED",
    "UNKNOWN_TO_GRAPH",
]
RetrievalStrategy = Literal[
    "compass_derivation",
    "contract_driven",
    "exploratory",
]
ProvenanceKind = Literal["node", "edge", "path"]
ProvenanceRole = Literal["primary", "supporting", "structural"]
ProvenanceSource = Literal["deterministic", "llm"]
#: Derived from `interaction.gap_types` — there is no second list to drift.
GapType = Literal[*CONTRACT_GAP_TYPES]


class Claim(BaseModel):
    answer_type: AnswerType = "narrative"
    primary_content: str = ""
    structured_data: dict = Field(default_factory=dict)


class ProvenanceEntry(BaseModel):
    kind: ProvenanceKind
    ids: list[str] = Field(default_factory=list)
    role_in_claim: ProvenanceRole = "primary"
    text_excerpt: str = ""
    source: ProvenanceSource = "llm"
    tier: str = ""
    #: The handoff key the claim cites as `[Trail pb_edge_0]`. Node `ids` are
    #: the trail's contents; this is the name the prose uses. Empty when the
    #: entry was synthesised from packet edges rather than a named trail.
    trail_id: str = ""


class GapEntryV1(BaseModel):
    type: GapType = "missing_concept"
    specific_node_or_concept: str = ""
    context: str = ""
    actionable_suggestion: str = ""


class NextQuerySuggestion(BaseModel):
    suggested_query: str = ""
    reason: str = ""
    expected_retrieval_strategy: RetrievalStrategy = "exploratory"


class AgentResponse(BaseModel):
    contract_version: str = CONTRACT_VERSION
    graph_version: str = ""
    query: str = ""
    verdict: VerdictKind = "EXHAUSTED"
    claim: Claim | None = None
    provenance: list[ProvenanceEntry] = Field(default_factory=list)
    gaps: list[GapEntryV1] = Field(default_factory=list)
    next_query_suggestions: list[NextQuerySuggestion] = Field(default_factory=list)
    retrieval_strategy: RetrievalStrategy = "exploratory"
    degradation_flags: list[str] = Field(default_factory=list)
    engine_degraded: bool = False
    trace_id: str = ""


# ---------------------------------------------------------------------------
# Gap-type translation (internal → contract v1)
# ---------------------------------------------------------------------------

#: Kept as a name for existing importers; the mapping itself lives in
#: `interaction.gap_types`.
_INTERNAL_TO_CONTRACT_GAP: dict[str, str] = dict(TRANSLATION)



def _translate_gap_type(raw: str) -> GapType:
    return translate(raw)  # type: ignore[return-value]


def _normalise_gaps(raw_gaps: Iterable[Any], query: str) -> list[GapEntryV1]:
    out: list[GapEntryV1] = []
    for g in raw_gaps or []:
        if isinstance(g, dict):
            out.append(
                GapEntryV1(
                    type=_translate_gap_type(str(g.get("gap_type", g.get("type", "")))),
                    specific_node_or_concept=str(g.get("specific_node_or_concept", "")),
                    context=str(g.get("context", "")) or query[:200],
                    actionable_suggestion=str(g.get("actionable_suggestion", "")),
                )
            )
        elif isinstance(g, str) and g.strip():
            out.append(
                GapEntryV1(
                    type="missing_concept",
                    specific_node_or_concept=g.strip(),
                    context=query[:200],
                    actionable_suggestion="",
                )
            )
    return out


# ---------------------------------------------------------------------------
# Retrieval-strategy normalisation
# ---------------------------------------------------------------------------

def _normalise_strategy(raw: Any) -> RetrievalStrategy:
    s = (str(raw or "").strip().lower())
    if s in ("compass_derivation", "map_reader"):
        return "compass_derivation"
    if s in ("contract_driven", "targeted_retrieval", "pipeline_b"):
        return "contract_driven"
    return "exploratory"


# ---------------------------------------------------------------------------
# Verdict normalisation
# ---------------------------------------------------------------------------

_ALLOWED_VERDICTS: set[str] = {
    "CONFIRMED",
    "ALTERNATIVE",
    "EXHAUSTED",
    "ILL_POSED",
    "UNKNOWN_TO_GRAPH",
}


def _normalise_verdict(raw: Any) -> VerdictKind:
    v = str(raw or "").strip().upper()
    return v if v in _ALLOWED_VERDICTS else "EXHAUSTED"


# ---------------------------------------------------------------------------
# Provenance normalisation
# ---------------------------------------------------------------------------

def _build_provenance(
    raw_prov: Iterable[Any],
    packet: dict,
) -> list[ProvenanceEntry]:
    entries: list[ProvenanceEntry] = []
    node_excerpts: dict[str, str] = {}
    for n in packet.get("node_records") or []:
        nid = str(n.get("id", ""))
        if not nid:
            continue
        text = n.get("text_content") or n.get("text_excerpt") or n.get("anchor_preview") or ""
        if text:
            node_excerpts[nid] = str(text)[:1200]

    for p in raw_prov or []:
        if not isinstance(p, dict):
            continue
        cp = p.get("confidence_provenance") or {}
        source_raw = str(cp.get("source", "llm")).lower()
        source: ProvenanceSource = "deterministic" if source_raw == "deterministic" else "llm"
        tier = str(cp.get("tier", "") or p.get("origin", ""))
        node_ids = [str(x) for x in (p.get("node_ids") or []) if x]

        kind: ProvenanceKind = "path" if len(node_ids) > 1 else "node"
        trail_id = str(p.get("trail_id") or "").strip()
        ids = node_ids if node_ids else ([trail_id] if trail_id else [])
        text_excerpt = ""
        if ids:
            text_excerpt = node_excerpts.get(ids[0], "")
        role: ProvenanceRole = "primary"
        basis = str(cp.get("basis", "")).lower()
        if "supporting" in basis:
            role = "supporting"
        elif "evidence_packet" in trail_id.lower() or "evidencepacket" in basis.replace(" ", "").lower():
            role = "structural"

        if ids:
            entries.append(
                ProvenanceEntry(
                    kind=kind,
                    ids=ids[:50],
                    role_in_claim=role,
                    text_excerpt=text_excerpt[:800],
                    source=source,
                    tier=tier,
                    trail_id=trail_id,
                )
            )

    # If provenance is empty but packet has edges, surface a structural entry.
    if not entries and packet:
        edges = packet.get("edge_records") or []
        for e in edges[:5]:
            src = str(e.get("source_id", "")); tgt = str(e.get("target_id", ""))
            if src and tgt:
                entries.append(
                    ProvenanceEntry(
                        kind="edge",
                        ids=[src, tgt],
                        role_in_claim="structural",
                        text_excerpt="",
                        source="deterministic",
                        tier="backend",
                    )
                )
    return entries


# ---------------------------------------------------------------------------
# Claim builder
# ---------------------------------------------------------------------------

#: Headings Battalion used to print around a claim that already exists as
#: structured fields. A panel that *is* the answer does not need **Answer:**;
#: an empty **Gaps:** (None) restates `gaps: []`.
_CLAIM_SECTION = re.compile(
    r"^\s*\*\*(Answer|Provenance|Gaps|Entities):\*\*\s*",
    re.I | re.M,
)

#: A second paragraph of Title-Case labels with no sentence end — the leftover
#: of **Entities:** after the heading is stripped, or the model dumping neighbours
#: it already put on the map. Keep it when it *is* the claim (enumeration).
_BARE_NAME_LIST = re.compile(
    r"^[A-Z][\w .'/()&+-]*(?:,\s*[A-Z][\w .'/()&+-]*)+$"
)


def _drop_trailing_name_list(claim: str) -> str:
    paras = [p.strip() for p in re.split(r"\n\s*\n", claim.strip()) if p.strip()]
    if len(paras) < 2:
        return claim.strip()
    last = paras[-1]
    if _BARE_NAME_LIST.match(last) and not re.search(r"[.?!]", last):
        return "\n\n".join(paras[:-1]).strip()
    return claim.strip()


# Pre-Ask Battalion fallback. A miss is the status line, not a description of
# spreading activation. Exact match only — those words are real node names on
# the architecture graph.
_STALE_ENGINE_CLAIM = (
    "the traversal engine was unable to find sufficient evidence in the "
    "knowledge graph to answer this query. the spreading activation and "
    "squad sensing did not surface any nodes with sufficient relevance."
)


def claim_prose(final_answer: str) -> str:
    """The claim, without the presentation Battalion used to wrap it in.

    Provenance, gaps, and entity-preservation labels are structured fields
    (or already in the sentence). Callers that still receive a heading-shaped
    `final_answer` — cached transcripts, older models — go through here so the
    contract never publishes a heading for an empty list. Leftover entity
    labels are dropped, not grafted: the map already lights those nodes.
    """
    text = (final_answer or "").replace("\r\n", "\n").strip()
    if not text:
        return ""
    parts = _CLAIM_SECTION.split(text)
    claim_bits: list[str] = []
    preamble = parts[0].strip()
    if preamble:
        claim_bits.append(preamble)
    i = 1
    while i + 1 < len(parts):
        heading = parts[i].lower()
        body = parts[i + 1].strip()
        i += 2
        if heading == "answer" and body:
            claim_bits.append(body)
        # Provenance, Gaps, Entities — structured elsewhere. Do not append.
    claim = "\n\n".join(bit for bit in claim_bits if bit)
    claim = re.sub(r"\n{3,}", "\n\n", _drop_trailing_name_list(claim)).strip()
    claim = _drop_stale_engine_claim(claim)
    return claim


def _drop_stale_engine_claim(claim: str) -> str:
    """Old Battalion / Planner essays. A miss is the status line."""
    if not claim:
        return ""
    folded = " ".join(claim.lower().split())
    if folded == _STALE_ENGINE_CLAIM:
        return ""
    if folded.startswith(
        "this query is structurally unanswerable from a graph of this shape"
    ):
        return ""
    if folded.startswith("the compass_derivation strategy was selected"):
        return ""
    if folded.startswith("**retrieved nodes** (arithmetic required") or folded.startswith(
        "retrieved nodes (arithmetic required"
    ):
        return ""
    cite = re.search(
        r"\n\s*\*\*[^\n]*citation verification[^\n]*\*\*\s*",
        claim,
        re.I,
    )
    if cite:
        return claim[: cite.start()].strip()
    return claim

def _infer_answer_type(query: str, packet: dict) -> AnswerType:
    q = (query or "").strip().lower()
    if q.startswith(("is ", "does ", "can ", "are ", "did ", "do ")):
        return "yes_no"
    if q.startswith(("list ", "what nodes", "which nodes", "enumerate", "all ")):
        return "list"
    # Structural cue
    if any(k in q for k in ("central", "bridge", "terminal", "origin", "role")):
        return "structural"
    return "narrative"


def _build_claim(
    query: str,
    final_answer: str,
    verdict: VerdictKind,
    packet: dict,
    provenance: list[ProvenanceEntry],
) -> Claim | None:
    # v6 §7-Synthesis closure: a Claim is only meaningful when the engine has
    # made a real assertion. ILL_POSED and UNKNOWN_TO_GRAPH are explicit non-
    # answers — emitting a synthetic Claim for them would have Battalion
    # backfill empty structural_data from the packet (which is content the
    # engine did not, and cannot, assert against the query).
    if verdict in {"UNKNOWN_TO_GRAPH", "ILL_POSED"}:
        return None

    answer_type = _infer_answer_type(query, packet)
    structured: dict = {}
    if answer_type == "yes_no":
        text = (final_answer or "").lower()
        positive = any(tok in text for tok in ("yes", "confirmed", "the graph confirms", "directly causes", "leads to"))
        negative = any(tok in text for tok in ("no such", "not connected", "is not", "cannot"))
        answer = True if positive and not negative else False if negative else None
        structured = {
            "answer": bool(answer) if answer is not None else False,
            "confidence": "high" if verdict == "CONFIRMED" else "medium",
        }
    elif answer_type == "list":
        items: list[dict] = []
        for n in (packet.get("node_records") or [])[:20]:
            nid = str(n.get("id", ""))
            if not nid:
                continue
            items.append({
                "node_id": nid,
                "label": str(n.get("label", nid)),
                "relevance": str(n.get("origin", "")),
            })
        structured = {"items": items}
    elif answer_type == "structural":
        buckets: dict[str, list[str]] = {}
        for n in (packet.get("node_records") or []):
            nid = str(n.get("id", ""))
            roles = (n.get("structural_facts") or {}).get("roles") or n.get("roles") or []
            if not roles:
                continue
            for r in roles:
                buckets.setdefault(str(r), []).append(nid)
        structured = {
            "structural_elements": [
                {"role": role, "nodes": nodes[:20]} for role, nodes in buckets.items()
            ]
        }
    else:  # narrative
        key_concepts: list[str] = []
        for p in provenance[:10]:
            key_concepts.extend(p.ids)
        main_rels: list[str] = []
        for e in (packet.get("edge_records") or [])[:10]:
            src = e.get("source_label") or e.get("source_id")
            tgt = e.get("target_label") or e.get("target_id")
            etype = e.get("edge_type")
            if src and tgt and etype:
                main_rels.append(f"{src} --[{etype}]--> {tgt}")
        structured = {
            "key_concepts": list(dict.fromkeys(key_concepts))[:20],
            "main_relationships": main_rels,
        }

    return Claim(
        answer_type=answer_type,
        primary_content=claim_prose(final_answer),
        structured_data=structured,
    )


# ---------------------------------------------------------------------------
# Next-query suggestions (deterministic, non-LLM; v9 §5)
# ---------------------------------------------------------------------------

def _build_suggestions(
    query: str,
    verdict: VerdictKind,
    gaps: list[GapEntryV1],
    packet: dict,
) -> list[NextQuerySuggestion]:
    suggestions: list[NextQuerySuggestion] = []

    if verdict == "ILL_POSED":
        suggestions.append(
            NextQuerySuggestion(
                suggested_query=f"What edge types are present for the concepts in: {query}",
                reason="The query's structural shape is absent; inspect which edge types the graph actually carries.",
                expected_retrieval_strategy="compass_derivation",
            )
        )
        return suggestions

    if verdict == "CONFIRMED":
        # A confirmed answer used to return nothing, which made the follow-up
        # affordance dead on the queries that most deserve a next hop. Each
        # suggestion is an independent question — no transcript is attached.
        seen: set[str] = set()
        for node in (packet.get("node_records") or [])[1:4]:
            label = str(node.get("label") or node.get("id") or "").strip()
            if not label or label.lower() in seen:
                continue
            seen.add(label.lower())
            suggestions.append(
                NextQuerySuggestion(
                    suggested_query=f"What does the graph say about {label}?",
                    reason="A concept in the same evidence; the last answer did not rest on asking it.",
                    expected_retrieval_strategy="contract_driven",
                )
            )
        return suggestions[:3]

    for g in gaps[:3]:
        if not g.specific_node_or_concept:
            continue
        if g.type == "missing_concept":
            suggestions.append(
                NextQuerySuggestion(
                    suggested_query=f"What does the graph say about {g.specific_node_or_concept}?",
                    reason="The queried concept was absent; probe related vocabulary.",
                    expected_retrieval_strategy="exploratory",
                )
            )
        elif g.type == "coverage_shallow":
            suggestions.append(
                NextQuerySuggestion(
                    suggested_query=f"What touches {g.specific_node_or_concept}?",
                    reason="Chain was truncated here; expanding the neighbourhood may surface missing links.",
                    expected_retrieval_strategy="contract_driven",
                )
            )
    return suggestions[:5]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_agent_response(
    state: dict[str, Any],
    *,
    graph_version: str = "",
    trace_id: str = "",
) -> AgentResponse:
    """Build the Agent Contract v1 response from a final EngineState dict."""
    query = str(state.get("query", ""))
    packet = state.get("evidence_packet") or {}
    confirmation = state.get("confirmation_response") or {}
    det_verdict = state.get("deterministic_verdict") or {}

    raw_verdict = det_verdict.get("kind") or confirmation.get("verdict") or ""
    verdict = _normalise_verdict(raw_verdict)

    strategy = _normalise_strategy(state.get("retrieval_strategy") or state.get("planner_route"))

    raw_gaps = state.get("gaps") or []
    if not raw_gaps:
        ch = state.get("company_handoff") or {}
        raw_gaps = (ch.get("internal_handoff") or {}).get("gaps") or []
    gaps = _normalise_gaps(raw_gaps, query)

    if verdict == "UNKNOWN_TO_GRAPH" and not any(g.type == "missing_concept" for g in gaps):
        gaps.insert(
            0,
            GapEntryV1(
                type="missing_concept",
                specific_node_or_concept=query[:80],
                context=query[:200],
                actionable_suggestion="Add a node covering this topic.",
            ),
        )
    if verdict == "ILL_POSED" and not any(g.type == "schema_gap" for g in gaps):
        reason = confirmation.get("ill_posed_reason") or det_verdict.get("basis") or ""
        gaps.insert(
            0,
            GapEntryV1(
                type="schema_gap",
                specific_node_or_concept=query[:80],
                context=query[:200],
                actionable_suggestion=str(reason) or "Extend the graph schema to carry this relation shape.",
            ),
        )

    provenance = _build_provenance(state.get("provenance") or [], packet)
    claim = _build_claim(query, str(state.get("final_answer") or ""), verdict, packet, provenance)
    suggestions = _build_suggestions(query, verdict, gaps, packet)
    deg = list(dict.fromkeys([str(x) for x in (state.get("degradation_flags") or []) if x]))
    from sst_degradation import has_engine_fault

    return AgentResponse(
        contract_version=CONTRACT_VERSION,
        graph_version=graph_version or "",
        query=query,
        verdict=verdict,
        claim=claim,
        provenance=provenance,
        gaps=gaps,
        next_query_suggestions=suggestions,
        retrieval_strategy=strategy,
        degradation_flags=deg,
        engine_degraded=has_engine_fault(deg),
        trace_id=trace_id or f"tr_{uuid.uuid4().hex[:16]}",
    )
