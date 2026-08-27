"""OpenRouter-backed structured JSON model transport."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from model_roles import battalion_model, resolve_role_model

T = TypeVar("T", bound=BaseModel)


class ModelOutputTruncated(ValueError):
    """The provider stopped a response at its visible output boundary."""

    code = "OUTPUT_TRUNCATED"

    def __init__(
        self,
        *,
        model: str,
        max_tokens: int,
        finish_reason: str,
        visible_characters: int,
        usage: dict[str, Any] | None = None,
        answer_allowance: int | None = None,
        reasoning_allowance: int | None = None,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.finish_reason = finish_reason
        self.visible_characters = visible_characters
        self.usage = usage or {}
        self.answer_allowance = answer_allowance
        self.reasoning_allowance = reasoning_allowance
        self.reasoning_tokens = _reasoning_tokens(self.usage)
        # Name which budget ran out. Reading "an output budget of 8192 tokens"
        # next to 3,189 visible characters, a whole ingestion campaign was
        # scored as though the answer had been too long, when 7,308 of those
        # 8,192 tokens had gone to reasoning and the answer never got room to
        # finish. The two are different repairs.
        spent = ""
        if self.reasoning_tokens is not None:
            share = (
                f" ({100 * self.reasoning_tokens // max_tokens}% of it)"
                if max_tokens
                else ""
            )
            spent = (
                f"; reasoning took {self.reasoning_tokens} tokens{share}"
            )
            if reasoning_allowance is None:
                spent += " and was not separately capped"
        budget = f"an output budget of {max_tokens} tokens"
        if answer_allowance is not None and reasoning_allowance is not None:
            budget = (
                f"an output budget of {max_tokens} tokens "
                f"({answer_allowance} answer + {reasoning_allowance} reasoning)"
            )
        super().__init__(
            f"{self.code}: model {model!r} stopped with finish reason "
            f"{finish_reason!r} at {budget} "
            f"after {visible_characters} visible characters{spent}"
        )


class ModelTransportResponseInvalid(RuntimeError):
    """The provider response envelope was not valid JSON."""

    code = "PROVIDER_RESPONSE_INVALID_JSON"

    def __init__(self, *, model: str, detail: str) -> None:
        self.model = model
        self.detail = detail
        super().__init__(f"{self.code}: model {model!r}: {detail}")


def _reasoning_tokens(usage: dict[str, Any] | None) -> int | None:
    """Reasoning tokens from any of the shapes providers use for them."""
    if not isinstance(usage, dict):
        return None
    for container in (
        usage.get("completion_tokens_details"),
        usage.get("output_token_details"),
        usage.get("output_tokens_details"),
        usage,
    ):
        if not isinstance(container, dict):
            continue
        for key in ("reasoning_tokens", "reasoning"):
            value = container.get(key)
            if isinstance(value, int):
                return value
    return None


def _finish_reason(message: Any) -> str:
    metadata = getattr(message, "response_metadata", None) or {}
    reason = metadata.get("finish_reason") or metadata.get("stop_reason")
    if reason is None and isinstance(metadata.get("choices"), list):
        choices = metadata["choices"]
        if choices and isinstance(choices[0], dict):
            reason = choices[0].get("finish_reason")
    return str(reason or "").strip()


def _is_output_limit(reason: str) -> bool:
    normalized = reason.casefold().replace("-", "_").replace(" ", "_")
    return normalized in {
        "length",
        "max_tokens",
        "max_output_tokens",
        "max_token",
    }


def _usage(message: Any) -> dict[str, Any]:
    usage = getattr(message, "usage_metadata", None)
    if isinstance(usage, dict):
        return usage
    metadata = getattr(message, "response_metadata", None) or {}
    token_usage = metadata.get("token_usage") or metadata.get("usage")
    return token_usage if isinstance(token_usage, dict) else {}


def _undecodable(text: str, error: json.JSONDecodeError) -> ValueError:
    """A decode failure carrying the text that caused it.

    A bare JSONDecodeError says "Expecting ',' delimiter: line 81 column 6" and
    nothing about what the model wrote, so a run that dies on one malformed
    response leaves no way to tell a transient blip from a systematic
    formatting incompatibility. Set `LLM_DUMP_BAD_JSON` to a directory to keep
    the whole response.
    """

    window = text[max(0, error.pos - 400) : error.pos + 400]
    dump_note = ""
    dump_dir = os.environ.get("LLM_DUMP_BAD_JSON")
    if dump_dir:
        try:
            path = Path(dump_dir)
            path.mkdir(parents=True, exist_ok=True)
            target = path / f"bad-json-{int(time.time() * 1000)}.txt"
            target.write_text(text, encoding="utf-8")
            dump_note = f"\nfull response written to {target}"
        except OSError as write_error:  # pragma: no cover - diagnostic only
            dump_note = f"\ncould not write dump: {write_error}"

    return ValueError(
        f"model response is not valid JSON ({error.msg} at line {error.lineno} "
        f"column {error.colno}, char {error.pos} of {len(text)}).\n"
        f"--- context around the failure ---\n{window}\n"
        f"--- end context ---{dump_note}"
    )


def _extract_json(text: str) -> dict | list:
    text = (text or "").strip()
    # Only strip an outer code fence when the whole response is wrapped in one.
    # Splitting on "```" anywhere in the text would break JSON whose text_content
    # fields contain markdown code blocks.
    if text.startswith("```json"):
        text = text[7:].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    elif text.startswith("```"):
        text = text[3:].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        obj_match = re.search(r"\{[\s\S]*\}", text)
        arr_match = re.search(r"\[[\s\S]*\]", text)
        candidate = ""
        if obj_match and arr_match:
            candidate = (
                obj_match.group(0)
                if len(obj_match.group(0)) >= len(arr_match.group(0))
                else arr_match.group(0)
            )
        elif obj_match:
            candidate = obj_match.group(0)
        elif arr_match:
            candidate = arr_match.group(0)
        if candidate:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError as error:
                raise _undecodable(candidate, error) from error
        raise


#: The repository's own .env. Resolved from this file rather than from the
#: caller's cwd, because the programs this product asks agents to write live
#: outside the repository by design, and `load_dotenv()` walks up from the
#: calling script -- so it finds nothing for them. Measured: a program in a
#: scratch directory failed with "must be set" while the identical call from
#: `python -c` in the repo root succeeded.
_REPO_ENV = Path(__file__).resolve().parents[1] / ".env"


def _key_from_repo_env() -> str:
    """Read OPENROUTER_API_KEY out of the repo's .env, without importing it.

    Deliberately not `load_dotenv`: this reads one key and returns it rather
    than mutating the process environment, so a caller that has deliberately
    unset the variable stays unset for everything else.
    """
    try:
        text = _REPO_ENV.read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def _chat(
    *,
    model: str,
    temperature: float = 0.0,
    max_tokens: int = 8192,
    reasoning_tokens: int | None = None,
) -> ChatOpenAI:
    """One OpenRouter chat client.

    ``max_tokens`` is the provider's *total* output allowance, and on a
    thinking model reasoning is spent from it first. ``reasoning_tokens`` caps
    that share explicitly, so a caller's budget means the answer it thought it
    meant. Reasoning cannot be switched off on every endpoint — Gemini 3.7
    Flash refuses ``{"enabled": false}`` outright — so this bounds it rather
    than removing it.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY") or _key_from_repo_env()
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY must be set for graph generation. "
            f"Looked in the environment and in {_REPO_ENV}. Note that "
            "`load_dotenv()` searches upward from the *calling script's* "
            "directory, so a program run from outside this repository -- a "
            "workbook program, for instance -- will not find that file on "
            "its own."
        )
    extra_body: dict[str, Any] = {}
    if reasoning_tokens is not None:
        extra_body["reasoning"] = {"max_tokens": int(reasoning_tokens)}
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        extra_body=extra_body,
    )


def mid_tier_model() -> str:
    """Graph-gen draft slot → planner role (legacy WIKI_BUILDER_MODEL as last resort)."""
    return resolve_role_model("PLANNER_MODEL", "MID_TIER_MODEL", "WIKI_BUILDER_MODEL")


def heavy_tier_model() -> str:
    return battalion_model()


def invoke_json_model(
    system: str,
    user: str,
    *,
    tier: str = "mid",
    max_tokens: int = 8192,
    model: str | None = None,
    reasoning_tokens: int | None = None,
) -> dict[str, Any]:
    """tier: 'mid' | 'heavy' are role slots (planner vs battalion), not quality bands.
    `model` overrides role→env resolution (used by per-node expansion-failure
    escalation to retry one node on an escalated model). Returns parsed JSON object."""
    data, _receipt = invoke_json_model_with_receipt(
        system,
        user,
        tier=tier,
        max_tokens=max_tokens,
        model=model,
        reasoning_tokens=reasoning_tokens,
    )
    return data


def invoke_json_model_with_receipt(
    system: str,
    user: str,
    *,
    tier: str = "mid",
    max_tokens: int = 8192,
    model: str | None = None,
    transport: str | None = None,
    reasoning_tokens: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Invoke one JSON completion and retain its provider usage envelope.

    Ordinary runtime callers use :func:`invoke_json_model`. Measurement code
    uses this companion so token/call claims are recorded rather than inferred
    from character counts. It does not change retry or truncation semantics.

    ``max_tokens`` is the **answer** allowance. When ``reasoning_tokens`` is
    given, it is added on top and capped at the provider, so a frozen answer
    budget is not silently spent on thinking; the receipt records both halves
    and what reasoning actually cost. Left unset, the old behaviour stands:
    one total allowance, reasoning taking whatever share it likes.
    """

    resolved_model = model or (
        heavy_tier_model() if tier == "heavy" else mid_tier_model()
    )
    # Alternate transports are experiment-local and must be selected by an
    # explicit caller. An environment variable must not silently replace the
    # production model transport for every ordinary runtime call.
    selected_transport = (transport or "openrouter").strip().lower()
    if selected_transport in {"cursor-agent", "cursor_agent", "cursor-agent-cli"}:
        from mcp_server.cursor_json_model import invoke_json_model_via_cursor_agent

        return invoke_json_model_via_cursor_agent(
            system,
            user,
            model=resolved_model,
            max_tokens=max_tokens,
        )
    if selected_transport != "openrouter":
        raise ValueError(f"unknown JSON model transport: {selected_transport}")
    answer_allowance = int(max_tokens)
    total_allowance = answer_allowance + int(reasoning_tokens or 0)
    llm = _chat(
        model=resolved_model,
        max_tokens=total_allowance,
        reasoning_tokens=reasoning_tokens,
    )
    started = time.perf_counter()
    try:
        raw = llm.invoke(
            [SystemMessage(content=system), HumanMessage(content=user)]
        )
    except json.JSONDecodeError as error:
        # This is the OpenAI-compatible provider envelope failing to parse,
        # before a model message exists. It is neither malformed model JSON nor
        # evidence of an output-budget boundary.
        raise ModelTransportResponseInvalid(
            model=resolved_model,
            detail=(
                f"provider envelope JSON failed at line {error.lineno} "
                f"column {error.colno}"
            ),
        ) from error
    text = raw.content if hasattr(raw, "content") else str(raw)
    finish_reason = _finish_reason(raw)
    if _is_output_limit(finish_reason):
        raise ModelOutputTruncated(
            model=resolved_model,
            max_tokens=total_allowance,
            finish_reason=finish_reason,
            visible_characters=len(str(text or "")),
            usage=_usage(raw),
            answer_allowance=answer_allowance if reasoning_tokens is not None else None,
            reasoning_allowance=reasoning_tokens,
        )
    if not str(text or "").strip():
        # A completion that stopped normally and said nothing. Neither typed
        # failure fits: the envelope parsed, and the finish reason is not an
        # output-budget boundary, so the truncation ladder would raise the
        # budget against a response that never used the budget it had. It is a
        # transport-shaped fault — the same request is worth sending again —
        # and it is reported as one so the existing retry covers it. Left
        # unhandled it surfaces as `JSONDecodeError` at char 0 and kills the
        # run; one did, mid-construction, after the first batch had landed.
        raise ModelTransportResponseInvalid(
            model=resolved_model,
            detail=(
                "provider returned an empty completion "
                f"(finish_reason={finish_reason or 'unset'})"
            ),
        )
    data = _extract_json(text)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object from LLM, got {type(data)}")
    usage = _usage(raw)
    receipt = {
        "model": resolved_model,
        "max_output_tokens": total_allowance,
        "answer_allowance": answer_allowance,
        "reasoning_allowance": reasoning_tokens,
        "reasoning_tokens": _reasoning_tokens(usage),
        "finish_reason": finish_reason,
        "usage": usage,
        "input_characters": len(system) + len(user),
        "output_characters": len(str(text or "")),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }
    return data, receipt


def invoke_structured(
    system: str,
    user: str,
    model_cls: type[T],
    *,
    tier: str = "mid",
    max_tokens: int = 8192,
    model: str | None = None,
) -> T:
    data = invoke_json_model(system, user, tier=tier, max_tokens=max_tokens, model=model)
    return model_cls.model_validate(data)
