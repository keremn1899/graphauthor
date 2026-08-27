"""Operator-plane fault envelope.

Results (Agent Contract verdicts, engine_degraded, construction run outcomes)
are not faults and must not pass through here. This is the wire shape for
everything else: the verb could not run, or the subject is not there.

The sentence is what an operator reads. The kind is what machines use for an
HTTP status and a UI slot. One helper, shared by HTTP and MCP stdio.

Host-down is not a kind: if this process cannot speak, it cannot classify.
"""

from __future__ import annotations

from typing import Any, Mapping

FaultKind = str

KINDS = (
    "not_found",
    "invalid",
    "conflict",
    "unauthorized",
    "unavailable",
    "fault",
)

STATUS: dict[str, int] = {
    "not_found": 404,
    "invalid": 400,
    "conflict": 409,
    "unauthorized": 401,
    "unavailable": 503,
    "fault": 500,
}


def operator_fault(kind: FaultKind, message: str, **extra: Any) -> dict[str, Any]:
    """One operator-readable sentence, classified once at the boundary."""
    if kind not in STATUS:
        raise ValueError(f"unknown fault kind: {kind!r}")
    body: dict[str, Any] = {"kind": kind, "error": str(message)}
    body.update(extra)
    return body


def is_fault_payload(payload: Any) -> bool:
    """A request failure, not a job record whose `error` key is None."""
    if not isinstance(payload, Mapping):
        return False
    err = payload.get("error")
    return isinstance(err, str) and bool(err)


def kind_of(payload: Mapping[str, Any]) -> str:
    kind = payload.get("kind")
    if kind in STATUS:
        return str(kind)
    return _fallback_kind(str(payload.get("error") or ""))


def status_of(payload: Mapping[str, Any]) -> int:
    return STATUS[kind_of(payload)]


def ensure_kind(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Copy the payload and set `kind` if a caller still omitted it."""
    body = dict(payload)
    body["kind"] = kind_of(body)
    return body


def json_result(payload: Any, *, ok: int = 200):
    """JSON response: fault envelope with status from kind, else `ok`."""
    from starlette.responses import JSONResponse

    if is_fault_payload(payload):
        body = ensure_kind(payload)
        return JSONResponse(body, status_code=STATUS[body["kind"]])
    return JSONResponse(payload, status_code=ok)


def _fallback_kind(message: str) -> str:
    """Transitional: old `{\"error\": ...}` dicts with no kind.

    Routes must not parse English for a status. This one prefix is the remainder
    of that habit, so a payload that still says \"unknown X\" keeps 404 until
    it is rewritten to `operator_fault`. New returns set `kind` themselves.
    """
    if message.strip().lower().startswith("unknown "):
        return "not_found"
    return "invalid"
