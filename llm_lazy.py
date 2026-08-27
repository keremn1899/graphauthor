"""Lazy LLM client proxy — honest failure for missing credentials.

Client construction reads OPENROUTER_API_KEY; when it is absent, a bare
`llm = _get_x_tier()` at a call site crashes *outside* the site's
`try: llm.invoke(...)` guard, so the deterministic fallback never engages
(pre-MCP audit finding). Deferring construction to first `.invoke()` makes
credential absence fail on the same path as call failure — inside the guard.
"""

from __future__ import annotations


class LazyLLM:
    def __init__(self, factory):
        self._factory = factory
        self._client = None

    def invoke(self, *args, **kwargs):
        if self._client is None:
            self._client = self._factory()
        return self._client.invoke(*args, **kwargs)
