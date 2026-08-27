"""Ask: Retrieve until the packet is enough, then Claim.

The product verb is Ask. The loop matches the host-retrieval minimisation
closeout: a small Compass kernel, then only lookup, expand, path, and
search. An exact miss stays a miss. Search hits stay candidates. The
claim is the sentence over that packet — it cannot fetch.
"""

from __future__ import annotations

import json
import os
from typing import Any

from mcp_server.retrieve import Retrieve

MAX_TURNS = 6
TOOL_TEXT_CAP = 14_000

_LOOP_SYSTEM = """You retrieve evidence from a closed knowledge graph. You do not write the answer.

You own the goal loop. A graph kernel is attached for orientation — shape and schema, not a census and not a proof. The graph tools execute deterministically and never make authority judgments. Use the smallest operation that answers the question. Exact identity requests are strict: call lookup, and if it returns EXACT_MISS, finish. Never widen an exact miss to search or adjacency. Search results are candidates only. Return only IDs you actually observed in tool results. If the question needs a whole-graph listing these tools cannot express, finish without inventing one.

Reply with exactly one JSON object per turn and no Markdown. Choose one tool:
{"tool":"lookup","references":["exact id or label"],"include_content":false}
{"tool":"expand","node_ids":["id"],"edge_types":["contains"],"direction":"outgoing|incoming|both","depth":1,"edge_labels":["optional label"],"include_content":false}
{"tool":"path","source_ids":["id"],"target_ids":["id"],"edge_types":["leadsto"],"max_hops":4,"include_content":false}
{"tool":"search","query":"terms","mode":"lexical|semantic","limit":8,"include_content":false}

When the packet is enough — or an exact miss is terminal — finish with:
{"final":{"reason":"brief evidence-selection reason"}}
"""


def _extract_json(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if text.startswith("```json"):
        text = text[7:].strip()
    elif text.startswith("```"):
        text = text[3:].strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    start = text.find("{")
    if start < 0:
        return {}
    try:
        parsed, _ = json.JSONDecoder().raw_decode(text[start:])
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _call_loop_model(messages: list[Any]) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    from model_roles import ask_model

    key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    client = ChatOpenAI(
        model=ask_model(),
        temperature=0.0,
        max_tokens=1200,
        api_key=key,
        base_url="https://openrouter.ai/api/v1",
    )
    lc = []
    for m in messages:
        role = m.get("role")
        content = m.get("content") or ""
        if role == "system":
            lc.append(SystemMessage(content=content))
        else:
            lc.append(HumanMessage(content=content))
    resp = client.invoke(lc)
    return str(getattr(resp, "content", "") or "")


def _dispatch(ops: Retrieve, call: dict[str, Any]) -> dict[str, Any]:
    tool = str(call.get("tool") or "").strip()
    include = bool(call.get("include_content"))
    if tool == "lookup":
        return ops.lookup(list(call.get("references") or []), include_content=include)
    if tool == "expand":
        return ops.expand(
            list(call.get("node_ids") or []),
            edge_types=call.get("edge_types"),
            direction=str(call.get("direction") or "both"),
            depth=int(call.get("depth") or 1),
            edge_labels=call.get("edge_labels"),
            include_content=include,
        )
    if tool == "path":
        return ops.path(
            list(call.get("source_ids") or []),
            list(call.get("target_ids") or []),
            edge_types=call.get("edge_types"),
            max_hops=int(call.get("max_hops") or 4),
            include_content=include,
        )
    if tool == "search":
        return ops.search(
            str(call.get("query") or ""),
            mode=str(call.get("mode") or "lexical"),
            limit=int(call.get("limit") or 8),
            include_content=include,
        )
    return {
        "operation": tool or "unknown",
        "zero_llm": True,
        "outcome": "INVALID_ARGUMENT",
        "error": {"code": "UNKNOWN_TOOL", "allowed": ["lookup", "expand", "path", "search"]},
        "retryable": True,
    }


def _merge_packet(into: dict[str, Any], result: dict[str, Any]) -> None:
    evidence = result.get("evidence") or {}
    scope = str(result.get("evidence_scope") or "")
    for key in ("node_records", "edge_records", "path_records"):
        bucket = into.setdefault(key, [])
        seen = {
            json.dumps(row, sort_keys=True, default=str)
            for row in bucket
            if isinstance(row, dict)
        }
        for row in evidence.get(key) or []:
            if not isinstance(row, dict):
                continue
            stamped = dict(row)
            if key == "node_records" and scope:
                stamped.setdefault("origin", scope)
            marker = json.dumps(stamped, sort_keys=True, default=str)
            if marker in seen:
                continue
            seen.add(marker)
            bucket.append(stamped)
    log = into.setdefault("packet_provenance", [])
    log.append({
        "operation": result.get("operation"),
        "outcome": result.get("outcome"),
        "evidence_scope": result.get("evidence_scope"),
    })


def _verdict_from_ops(results: list[dict[str, Any]]) -> str:
    outcomes = [str(r.get("outcome") or "") for r in results]
    scopes = [str(r.get("evidence_scope") or "") for r in results]
    if any(o == "EXACT_MISS" for o in outcomes) and not any(
        o == "FOUND" and s == "closure-derived" for o, s in zip(outcomes, scopes)
    ):
        return "UNKNOWN_TO_GRAPH"
    if any(o == "FOUND" and s == "closure-derived" for o, s in zip(outcomes, scopes)):
        return "CONFIRMED"
    if any(o == "CANDIDATES" for o in outcomes):
        return "EXHAUSTED"
    if results:
        return "EXHAUSTED"
    return "EXHAUSTED"


def _clip(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) <= TOOL_TEXT_CAP:
        return text
    return text[:TOOL_TEXT_CAP] + "…"


def _session_compass(surface: Any) -> dict[str, Any]:
    try:
        compass = getattr(surface._session, "compass", None)
        if hasattr(compass, "to_dict"):
            compass = compass.to_dict()
        return compass if isinstance(compass, dict) else {}
    except Exception:
        return {}


def _graph_kernel(surface: Any) -> str:
    """The Probe B kernel: L1 shape/schema, not landmarks and not a census."""
    from mcp_server.compass_briefing import format_layer1

    profile = _session_compass(surface).get("graph_profile") or {}
    lines = [
        "# GRAPH COMPASS — SELECTIVE BRIEFING (experiment)",
        "Context policy: kernel",
        "",
    ]
    lines.extend(format_layer1(profile))
    return "\n".join(lines)


def run_ask(surface: Any, query: str) -> dict[str, Any]:
    """Retrieve, then write the claim. Returns an EngineState-shaped dict."""
    from claim import write_claim

    ops = Retrieve(surface)
    kernel = _graph_kernel(surface)
    messages = [
        {"role": "system", "content": _LOOP_SYSTEM},
        {
            "role": "user",
            "content": f"GRAPH KERNEL:\n{kernel}\n\nTASK:\n{query}",
        },
    ]
    packet: dict[str, Any] = {
        "node_records": [],
        "edge_records": [],
        "path_records": [],
        "packet_provenance": [],
        "degradation_flags": [],
    }
    results: list[dict[str, Any]] = []
    exact_miss_terminal = False

    for _ in range(MAX_TURNS):
        raw = _call_loop_model(messages)
        parsed = _extract_json(raw)
        if not parsed:
            packet["degradation_flags"].append("engine_fault:ask:unparseable_loop")
            break
        if isinstance(parsed.get("final"), dict):
            break
        tool = str(parsed.get("tool") or "")
        if exact_miss_terminal and tool in {"search", "expand", "path"}:
            refuse = {
                "operation": tool,
                "zero_llm": True,
                "outcome": "REFUSED_WIDEN",
                "error": {
                    "code": "EXACT_MISS_IS_TERMINAL",
                    "detail": "lookup missed; Ask will not widen to search or adjacency",
                },
                "retryable": False,
            }
            results.append(refuse)
            messages.append({"role": "user", "content": _clip(refuse)})
            continue
        try:
            result = _dispatch(ops, parsed)
        except (TypeError, ValueError) as exc:
            result = {
                "operation": tool or "unknown",
                "zero_llm": True,
                "outcome": "INVALID_ARGUMENT",
                "error": {"code": "BAD_ARGUMENTS", "detail": str(exc)},
                "retryable": True,
            }
        results.append(result)
        if result.get("outcome") == "EXACT_MISS":
            exact_miss_terminal = True
        if str(result.get("kind") or "") == "RETRIEVED" or result.get("evidence"):
            _merge_packet(packet, result)
        messages.append({"role": "user", "content": _clip(result)})

    verdict = _verdict_from_ops(results)
    compass = _session_compass(surface)

    if verdict == "UNKNOWN_TO_GRAPH" and not packet.get("node_records"):
        return {
            "query": query,
            "evidence_packet": packet,
            "confirmation_response": {"verdict": verdict},
            "final_answer": (
                "The graph has no node matching that name. "
                "Lookup is exact; a miss is not a candidate list."
            ),
            "provenance": [],
            "gaps": [],
            "company_handoff": {"internal_handoff": {"gaps": []}},
            "retrieval_strategy": "contract_driven",
            "degradation_flags": list(packet.get("degradation_flags") or []),
        }

    conn = surface._session.connection
    return write_claim(query, packet, conn, verdict=verdict, compass=compass)
