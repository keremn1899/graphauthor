"""Operator HTTP transport — `/operator` beside `/mcp`, same process.

Reads only: health, memory, proposals, events, history, settings.
Propose auto-commits on the agent plane; revert stays on the history CLI.
"""

from __future__ import annotations

from typing import Any

from mcp_server.fault import json_result, operator_fault
from mcp_server.operator import OperatorSurface


async def _json_body(request) -> dict[str, Any]:
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def operator_routes(operator: OperatorSurface) -> list:
    """The `/operator` route table (mounted under a `/operator` prefix)."""
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def health(request):
        return JSONResponse(operator.health())

    async def memory(request):
        from mcp_server.memory import dump, snapshot

        if request.query_params.get("dump") in ("1", "true", "yes"):
            path = dump()
            body = snapshot()
            body["dumped"] = str(path)
            return JSONResponse(body)
        return JSONResponse(snapshot())

    async def proposals(request):
        status = request.query_params.get("status")
        return JSONResponse(operator.list_proposals(status=status))

    async def proposal(request):
        rec = operator.get_proposal(request.path_params["pid"])
        if rec is None:
            return json_result(operator_fault("not_found", "unknown proposal"))
        return JSONResponse(rec)

    async def audit(request):
        return json_result(operator.audit(request.path_params["pid"]))

    async def escalations(request):
        return JSONResponse(operator.list_escalations())

    async def activities(request):
        return JSONResponse(operator.activities())

    async def inbox(request):
        return JSONResponse(operator.inbox())

    async def events(request):
        since = request.query_params.get("since") or ""
        rows = operator.events()
        if since:
            index = next(
                (i for i, row in enumerate(rows) if row.get("event_id") == since),
                -1,
            )
            rows = rows[index + 1 :] if index >= 0 else rows
        return JSONResponse(rows)

    async def history(request):
        return json_result(operator.history())

    async def diff(request):
        r = operator.diff(
            str(request.query_params.get("v1", "")),
            str(request.query_params.get("v2", "")),
        )
        return json_result(r)

    async def settings(request):
        return JSONResponse(operator.settings())

    async def entitlement(request):
        return JSONResponse(operator.entitlement())

    async def set_key(request):
        body = await _json_body(request)
        r = operator.set_key(str(body.get("key", "")), validate=bool(body.get("validate", True)))
        return JSONResponse(r, status_code=400 if not r.get("set") and r.get("valid") is False else 200)

    async def key_status(request):
        return JSONResponse(operator.key_status())

    async def clear_key(request):
        return JSONResponse(operator.clear_key())

    async def set_actor(request):
        body = await _json_body(request)
        return JSONResponse(operator.set_actor(str(body.get("actor", ""))))

    async def posture(request):
        return JSONResponse(operator.posture())

    async def set_posture(request):
        body = await _json_body(request)
        r = operator.set_posture(**{k: v for k, v in body.items()})
        return json_result(r)

    return [
        Route("/health", health, methods=["GET"]),
        Route("/memory", memory, methods=["GET"]),
        Route("/proposals", proposals, methods=["GET"]),
        Route("/proposals/{pid}", proposal, methods=["GET"]),
        Route("/proposals/{pid}/audit", audit, methods=["GET"]),
        Route("/escalations", escalations, methods=["GET"]),
        Route("/activities", activities, methods=["GET"]),
        Route("/inbox", inbox, methods=["GET"]),
        Route("/events", events, methods=["GET"]),
        Route("/history", history, methods=["GET"]),
        Route("/diff", diff, methods=["GET"]),
        Route("/settings", settings, methods=["GET"]),
        Route("/entitlement", entitlement, methods=["GET"]),
        Route("/settings/key", set_key, methods=["POST"]),
        Route("/settings/key/status", key_status, methods=["GET"]),
        Route("/settings/key/clear", clear_key, methods=["POST"]),
        Route("/settings/actor", set_actor, methods=["POST"]),
        Route("/settings/posture", posture, methods=["GET"]),
        Route("/settings/posture", set_posture, methods=["POST"]),
    ]


def build_operator_app(operator: OperatorSurface, *, token: str | None):
    """Standalone operator plane: bearer gate → `/operator` routes."""
    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.routing import Mount

    from mcp_server.http import _authorized

    inner = Starlette(routes=[Mount("/operator", routes=operator_routes(operator))])

    async def _auth_gate(scope, receive, send):
        if scope["type"] == "http" and not _authorized(scope.get("headers") or [], token):
            resp = Response("unauthorized", status_code=401)
            await resp(scope, receive, send)
            return
        await inner(scope, receive, send)

    return _auth_gate
