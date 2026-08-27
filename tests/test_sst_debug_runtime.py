from __future__ import annotations

import io
import logging

import sst_debug


def test_log_event_emits_structured_line_when_debug_enabled(monkeypatch):
    monkeypatch.setenv("SST_DEBUG", "1")
    monkeypatch.setattr(sst_debug, "_CONFIGURED", False)

    logger = logging.getLogger("sst.engine")
    old_handlers = list(logger.handlers)
    old_level = logger.level
    old_propagate = logger.propagate

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))

    try:
        logger.handlers = [handler]
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        sst_debug.log_event("unit_test_event", query_preview="abc", elapsed_ms=12.3456)
        line = stream.getvalue().strip()

        assert line.startswith("unit_test_event | ")
        assert "elapsed_ms=12.346" in line
        assert "query_preview='abc'" in line
    finally:
        logger.handlers = old_handlers
        logger.setLevel(old_level)
        logger.propagate = old_propagate

