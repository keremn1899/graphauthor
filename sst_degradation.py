"""Typed degradation helpers — engine faults vs graph silence."""

from __future__ import annotations

from typing import Iterable


ENGINE_FAULT_PREFIX = "engine_fault:"


def mark_engine_fault(flags: list[str] | None, site: str) -> list[str]:
    """Append ``engine_fault:<site>`` if missing. Preserves order + uniqueness."""
    out = list(flags or [])
    flag = f"{ENGINE_FAULT_PREFIX}{site}"
    if flag not in out:
        out.append(flag)
    return out


def has_engine_fault(flags: Iterable[str] | None) -> bool:
    return any(str(f).startswith(ENGINE_FAULT_PREFIX) for f in (flags or []))
