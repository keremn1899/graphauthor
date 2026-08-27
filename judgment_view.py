"""Bounded, auditable evidence views for LLM judgment tiers.

The :class:`EvidencePacket` remains append-only retrieval truth.  This module
does not trim or rewrite it.  It selects the smaller projection that Company
and Battalion are allowed to put into prompts for governance lookup queries.

Completeness-shaped contracts (enumeration, fanout, proof, chain, and count)
deliberately bypass the budget: for those questions, omitting a retrieved item
would change the meaning of the answer rather than merely reduce distraction.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from typing import Any


DEFAULT_JUDGMENT_NODE_BUDGET = 16
_COMPLETE_QUESTION_FORMS = frozenset(
    {"enumeration", "fanout", "proof", "chain", "count"}
)
_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "a", "about", "after", "all", "am", "an", "and", "anything",
        "are", "as", "at", "be", "because", "been", "before", "being",
        "but", "by", "can", "could", "did", "do", "does", "for", "from",
        "had", "has", "have", "how", "i", "if", "in", "into", "is", "it",
        "its", "me", "my", "no", "not", "nothing", "of", "on", "or", "our",
        "so", "some", "that", "the", "their", "them", "there", "they", "this",
        "to", "was", "we", "were", "what", "when", "where", "which", "who",
        "why", "with", "would", "you", "your",
    }
)


def _normalise_token(token: str) -> str:
    if len(token) > 7 and token.endswith("ction"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _tokens(value: Any) -> set[str]:
    return {
        _normalise_token(token)
        for token in _WORD.findall(str(value or "").lower())
        if len(token) > 1 and token not in _STOPWORDS
    }


def _budget() -> int:
    try:
        return max(1, int(os.environ.get(
            "SST_JUDGMENT_NODE_BUDGET", DEFAULT_JUDGMENT_NODE_BUDGET
        )))
    except (TypeError, ValueError):
        return DEFAULT_JUDGMENT_NODE_BUDGET


def _iter_values(value: Any):
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_values(item)
    elif isinstance(value, str) and value.strip() and not value.strip().startswith("$"):
        yield value.strip()


def _named_references(state: dict, packet: dict) -> list[str]:
    """Collect graph-native references explicitly selected before expansion."""
    refs: list[str] = []

    for contract_key in ("relational_contract", "answer_contract"):
        contract = state.get(contract_key) or {}
        if not isinstance(contract, dict):
            continue
        for key in ("source_ids", "target_ids", "coverage_sources"):
            value = contract.get(key)
            if key == "coverage_sources" and isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        refs.extend(_iter_values([item.get("id"), item.get("display")]))
            else:
                refs.extend(_iter_values(value))

    programs = [
        state.get("planner_program") or {},
        state.get("retrieval_program") or {},
        packet.get("retrieval_program") or {},
    ]
    for program in programs:
        if not isinstance(program, dict):
            continue
        strategy_a = program.get("strategy_a") or {}
        if isinstance(strategy_a, dict):
            refs.extend(_iter_values(strategy_a.get("concepts")))
        steps = list(program.get("steps") or [])
        steps.extend(((program.get("contingency") or {}).get("fallback_steps") or []))
        for step in steps:
            if not isinstance(step, dict) or step.get("tool") != "exact_node_lookup":
                continue
            params = step.get("params") or {}
            if isinstance(params, dict):
                for key in ("label_or_id", "ids", "node_ids"):
                    refs.extend(_iter_values(params.get(key)))
    return refs


def _matching_node_ids(nodes: list[dict], references: list[str]) -> set[str]:
    by_identity: dict[str, str] = {}
    for node in nodes:
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        by_identity[node_id.casefold()] = node_id
        label = str(node.get("label") or "").strip()
        if label:
            by_identity[label.casefold()] = node_id
    return {
        by_identity[ref.casefold()]
        for ref in references
        if ref.casefold() in by_identity
    }


def _bypass_reason(state: dict) -> str:
    verdict_space = str(state.get("verdict_space") or "").strip().lower()
    if verdict_space not in {"coverage", "ruling"}:
        return "verdict_space_not_governance"
    contract = state.get("relational_contract") or {}
    question_form = str(contract.get("question_form") or "").strip().lower()
    if question_form in _COMPLETE_QUESTION_FORMS:
        return f"complete_question_form:{question_form}"
    if bool(contract.get("requires_content_arithmetic")):
        return "content_arithmetic"
    return ""


def build_judgment_view(state: dict, packet: dict, conn=None) -> dict:
    """Select the prompt-facing node projection without mutating ``packet``."""
    nodes = [n for n in (packet.get("node_records") or []) if isinstance(n, dict)]
    node_ids = [str(n.get("id") or "") for n in nodes if n.get("id")]
    budget = _budget()
    bypass = _bypass_reason(state)
    if bypass or len(node_ids) <= budget:
        return {
            "policy": "coverage_relevance_v1",
            "applied": False,
            "reason": bypass or "within_budget",
            "budget": budget,
            "packet_node_count": len(node_ids),
            "node_ids": node_ids,
            "protected_node_ids": node_ids if bypass else [],
            "excluded_node_ids": [],
        }

    protected: set[str] = set()
    for path in packet.get("path_records") or []:
        if isinstance(path, dict):
            protected.update(
                str(node_id) for node_id in (path.get("node_chain") or []) if node_id
            )
    protected.update(_matching_node_ids(nodes, _named_references(state, packet)))
    for candidate in state.get("planner_governing_candidates") or []:
        if isinstance(candidate, dict) and candidate.get("id") in node_ids:
            protected.add(str(candidate["id"]))

    evidence_text: dict[str, str] = {}
    if conn is not None and node_ids:
        try:
            from tools import get_anchor_previews

            for preview in get_anchor_previews(conn, node_ids, preview_tokens=120):
                node_id = str(preview.get("id") or "")
                evidence_text[node_id] = " ".join(
                    str(preview.get(key) or "")
                    for key in ("label", "semantic_anchor", "text_preview")
                )
        except Exception:
            # A prompt budget must never make retrieval fail. Labels remain a
            # deterministic, if weaker, fallback when body paging is unavailable.
            evidence_text = {}

    # Relevance ranks the remainder.  IDF is calculated inside the retrieved
    # packet so ubiquitous container words ("returns", "policy") carry less
    # weight than the predicate-specific words that distinguish nearby rules.
    query_tokens = _tokens(state.get("query"))
    label_tokens = [_tokens(node.get("label")) for node in nodes]
    evidence_tokens = [
        _tokens(evidence_text.get(str(node.get("id") or "")) or node.get("label"))
        for node in nodes
    ]
    document_frequency = Counter(
        token for tokens in evidence_tokens for token in tokens
    )
    n_docs = max(len(nodes), 1)
    discriminative_query_tokens = {
        token for token in query_tokens
        if document_frequency[token] / n_docs <= 0.35
    }
    if not discriminative_query_tokens:
        discriminative_query_tokens = query_tokens

    def score(index: int) -> tuple[float, int, int, int]:
        overlap = discriminative_query_tokens.intersection(evidence_tokens[index])
        label_overlap = discriminative_query_tokens.intersection(label_tokens[index])
        relevance = sum(
            math.log((n_docs + 1) / (document_frequency[token] + 1)) + 1
            for token in overlap
        )
        # Stable original-order tie-break: retrieval intent still wins when
        # labels contain no useful lexical distinction.
        return relevance, len(label_overlap), len(overlap), -index

    ordered_protected = [node_id for node_id in node_ids if node_id in protected]
    ranked_indices = sorted(
        (i for i, node_id in enumerate(node_ids) if node_id not in protected),
        key=score,
        reverse=True,
    )
    room = max(0, budget - len(ordered_protected))
    selected_set = set(ordered_protected)
    selected_ranked: list[int] = []
    seen_labels = {
        str(nodes[i].get("label") or "").strip().casefold()
        for i, node_id in enumerate(node_ids)
        if node_id in protected and nodes[i].get("label")
    }
    for index in ranked_indices:
        _relevance, label_overlap, total_overlap, _tie_break = score(index)
        eligible = (
            label_overlap >= 1
            if len(discriminative_query_tokens) <= 2
            else (
                label_overlap >= 2
                or (label_overlap >= 1 and total_overlap >= 2)
            )
        )
        if not eligible:
            continue
        label_key = str(nodes[index].get("label") or "").strip().casefold()
        if label_key and label_key in seen_labels:
            continue
        selected_ranked.append(index)
        if label_key:
            seen_labels.add(label_key)
        if len(selected_ranked) >= room:
            break
    selected_set.update(node_ids[i] for i in selected_ranked)
    # A proof path can legitimately exceed the nominal budget.  It is never
    # split: a broken path is worse than a larger prompt and would misstate the
    # packet's proof shape.
    selected = [node_id for node_id in node_ids if node_id in selected_set]

    return {
        "policy": "coverage_relevance_v1",
        "applied": True,
        "reason": "governance_lookup_over_budget",
        "budget": budget,
        "packet_node_count": len(node_ids),
        "node_ids": selected,
        "protected_node_ids": ordered_protected,
        "ranked_node_scores": {
            node_ids[i]: round(score(i)[0], 4) for i in selected_ranked
        },
        "evidence_basis": "label+anchor+preview" if evidence_text else "label",
        "relevance_gate": "label>=2 | label>=1+total>=2",
        "excluded_node_ids": [node_id for node_id in node_ids if node_id not in selected_set],
    }


def packet_for_judgment(packet: dict) -> dict:
    """Return a shallow packet projection described by ``judgment_view``."""
    view = packet.get("judgment_view") or {}
    if not view.get("applied"):
        return packet
    selected = set(view.get("node_ids") or [])
    projected = dict(packet)
    projected["node_records"] = [
        node for node in (packet.get("node_records") or [])
        if isinstance(node, dict) and node.get("id") in selected
    ]
    projected["edge_records"] = [
        edge for edge in (packet.get("edge_records") or [])
        if isinstance(edge, dict)
        and edge.get("source_id") in selected
        and edge.get("target_id") in selected
    ]
    projected["path_records"] = [
        path for path in (packet.get("path_records") or [])
        if isinstance(path, dict)
        and set(path.get("node_chain") or []).issubset(selected)
    ]
    return projected


def records_for_judgment(records: list[dict], packet: dict) -> list[dict]:
    """Project a legacy candidate list using the packet's selected IDs."""
    view = packet.get("judgment_view") or {}
    if not view.get("applied"):
        return list(records)
    selected = set(view.get("node_ids") or [])
    return [record for record in records if record.get("id") in selected]
