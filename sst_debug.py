"""Structured debug logging for the SST traversal engine.

Enable with SST_DEBUG=1 (or true/yes). Logs go to logger name ``sst.engine``.
Optional log file: call configure_sst_debug_logging(log_path=...).
"""

from __future__ import annotations

import logging
import os
from typing import Any

_LOGGER = logging.getLogger("sst.engine")
_CONFIGURED = False


def is_sst_debug() -> bool:
    return os.environ.get("SST_DEBUG", "").strip().lower() in ("1", "true", "yes")


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.3f}"
    if isinstance(v, str) and len(v) > 200:
        return repr(v[:200] + "...")
    return repr(v)


def configure_sst_debug_logging(log_path: str | None = None) -> None:
    """Attach handlers when SST_DEBUG is enabled (idempotent for stream)."""
    global _CONFIGURED
    if not is_sst_debug():
        return
    if not _LOGGER.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(message)s"))
        _LOGGER.addHandler(h)
        _LOGGER.setLevel(logging.DEBUG)
        _LOGGER.propagate = False
    if log_path:
        # Allow multiple file runs — check by baseFilename
        have = any(
            isinstance(x, logging.FileHandler) and getattr(x, "baseFilename", "") == os.path.abspath(log_path)
            for x in _LOGGER.handlers
        )
        if not have:
            fh = logging.FileHandler(log_path, encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(message)s"))
            _LOGGER.addHandler(fh)
    _CONFIGURED = True


def log_event(event: str, **fields: Any) -> None:
    """Emit one structured debug line: event | key=value ..."""
    if not is_sst_debug():
        return
    configure_sst_debug_logging()
    tail = " | ".join(f"{k}={_fmt(v)}" for k, v in sorted(fields.items()))
    msg = f"{event} | {tail}" if tail else event
    _LOGGER.debug(msg)
