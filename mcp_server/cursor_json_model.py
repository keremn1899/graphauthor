"""JSON completion transport over the Cursor Agent CLI.

Callers still emit the same system/user prompts. This module
only replaces OpenRouter as the billed completion backend. Each call uses
ask/print mode in an empty trusted workspace so the caller cannot write
files, load this repo's MCP servers, or treat the graph as already writable.

Cursor Agent is not a raw chat-completions API. Receipts therefore include
agent scaffolding tokens and `transport=cursor-agent-cli`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from typing import Any

CURSOR_AGENT_TRANSPORT = "cursor-agent-cli"
DEFAULT_TIMEOUT_SECONDS = 900


class CursorAgentCLIError(RuntimeError):
    """The Cursor Agent CLI did not return a usable JSON completion."""

    code = "CURSOR_AGENT_CLI_FAILED"


def normalize_cursor_usage(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    input_tokens = raw.get("inputTokens", raw.get("input_tokens"))
    output_tokens = raw.get("outputTokens", raw.get("output_tokens"))
    total_tokens = raw.get("totalTokens", raw.get("total_tokens"))
    usage: dict[str, Any] = {"cursor_raw": raw}
    if isinstance(input_tokens, (int, float)):
        usage["input_tokens"] = int(input_tokens)
        usage["prompt_tokens"] = int(input_tokens)
    if isinstance(output_tokens, (int, float)):
        usage["output_tokens"] = int(output_tokens)
        usage["completion_tokens"] = int(output_tokens)
    if isinstance(total_tokens, (int, float)):
        usage["total_tokens"] = int(total_tokens)
    elif "input_tokens" in usage and "output_tokens" in usage:
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    return usage


def build_cursor_agent_prompt(system: str, user: str, *, max_tokens: int) -> str:
    return (
        "You are acting as a JSON completion endpoint for a frozen experiment.\n"
        "Do not use tools. Do not inspect the filesystem. Do not explain.\n"
        "Reply with one JSON object and nothing else.\n"
        "Evidence quotes must be copied verbatim from the supplied source atoms.\n"
        f"Stay within approximately {max_tokens} output tokens.\n\n"
        "SYSTEM:\n"
        f"{system}\n\n"
        "USER:\n"
        f"{user}\n"
    )


def parse_cursor_agent_envelope(stdout: str) -> dict[str, Any]:
    text = (stdout or "").strip()
    if not text:
        raise CursorAgentCLIError("CLI returned empty stdout")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise CursorAgentCLIError("CLI stdout was not a JSON envelope")
        payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise CursorAgentCLIError("CLI envelope was not a JSON object")
    return payload


def extract_cursor_agent_result_text(payload: dict[str, Any]) -> str:
    if payload.get("is_error") is True:
        raise CursorAgentCLIError(str(payload.get("result") or "CLI reported is_error"))
    result = payload.get("result")
    if isinstance(result, dict):
        return json.dumps(result)
    if isinstance(result, str) and result.strip():
        return result
    raise CursorAgentCLIError("CLI envelope contained no result text")


def invoke_json_model_via_cursor_agent(
    system: str,
    user: str,
    *,
    model: str,
    max_tokens: int,
    cursor_bin: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from mcp_server.json_model import ModelTransportResponseInvalid, _extract_json

    binary = cursor_bin or os.environ.get("CURSOR_AGENT_BIN") or shutil.which("cursor")
    if not binary:
        raise ModelTransportResponseInvalid(
            model=model,
            detail="cursor CLI was not found on PATH",
        )
    prompt = build_cursor_agent_prompt(system, user, max_tokens=max_tokens)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="json-model-") as workspace:
        # Pass the caller payload on stdin. argv cannot carry PEP 8-sized
        # raw HTML without hitting OSError E2BIG.
        completed = subprocess.run(
            [
                binary,
                "agent",
                "--print",
                "--mode",
                "ask",
                "--trust",
                "--workspace",
                workspace,
                "--model",
                model,
                "--output-format",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
            input=prompt,
            timeout=timeout_seconds,
            cwd=workspace,
            env={
                key: value
                for key, value in os.environ.items()
                if key not in {"OPENROUTER_API_KEY"}
            },
        )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[:800]
        raise ModelTransportResponseInvalid(
            model=model,
            detail=f"cursor agent exited {completed.returncode}: {detail or 'no stderr'}",
        )
    try:
        payload = parse_cursor_agent_envelope(completed.stdout)
        text = extract_cursor_agent_result_text(payload)
        data = _extract_json(text)
    except (CursorAgentCLIError, json.JSONDecodeError, ValueError) as error:
        raise ModelTransportResponseInvalid(model=model, detail=str(error)) from error
    if not isinstance(data, dict):
        raise ModelTransportResponseInvalid(
            model=model,
            detail=f"expected JSON object, got {type(data)}",
        )
    usage = normalize_cursor_usage(payload.get("usage"))
    receipt = {
        "model": model,
        "max_output_tokens": max_tokens,
        "finish_reason": str(payload.get("subtype") or "success"),
        "usage": usage,
        "input_characters": len(system) + len(user),
        "output_characters": len(text),
        "elapsed_ms": elapsed_ms,
        "transport": CURSOR_AGENT_TRANSPORT,
        "output_limit_enforcement": "prompt_only",
        "cursor_session_id": payload.get("session_id"),
        "cursor_request_id": payload.get("request_id"),
        "cursor_duration_ms": payload.get("duration_ms"),
    }
    return data, receipt
