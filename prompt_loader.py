"""Small helper for loading prompt files with import-time caching."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parent


@lru_cache(maxsize=64)
def load_prompt(relative_path: str) -> str:
    path = (_ROOT / relative_path).resolve()
    return path.read_text(encoding="utf-8")
