"""LLM *role* → OpenRouter model resolution.

Roles name which call site uses the model — not a quality/price band.

Ask has one model slot (loop + sentence). Retrieve is zero-LLM.
Planner / Squad remain for the old exploratory pipeline only.

| Slot    | Preferred env | Legacy alias                 |
|---------|---------------|------------------------------|
| ask     | ASK_MODEL     | BATTALION_MODEL, HEAVY_MODEL |
| planner | PLANNER_MODEL | MID_TIER_MODEL               |
| squad   | SQUAD_MODEL   | FAST_MODEL                   |
"""

from __future__ import annotations

import os

# Cheap default shared by all roles unless overridden.
DEFAULT_CHEAP_MODEL = "google/gemini-3.1-flash-lite-preview"


def resolve_role_model(*env_keys: str, default: str = DEFAULT_CHEAP_MODEL) -> str:
    """Return the first non-empty env value among *env_keys*, else *default*."""
    for key in env_keys:
        val = (os.environ.get(key) or "").strip()
        if val:
            return val
    return default


def planner_model() -> str:
    """Planner + Company (+ graph-gen / wiki 'mid' slot)."""
    return resolve_role_model("PLANNER_MODEL", "MID_TIER_MODEL")


def squad_model() -> str:
    """Squad local sensors."""
    return resolve_role_model("SQUAD_MODEL", "FAST_MODEL")


def ask_model() -> str:
    """The model Ask uses. Not a named agent."""
    return resolve_role_model("ASK_MODEL", "BATTALION_MODEL", "HEAVY_MODEL")


def battalion_model() -> str:
    """Legacy alias for ask_model()."""
    return ask_model()


def role_model_summary() -> dict[str, str]:
    """Resolved models for startup banners / telemetry."""
    return {
        "ask": ask_model(),
        "planner": planner_model(),
        "squad": squad_model(),
        "battalion": battalion_model(),
    }
