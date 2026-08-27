"""Single-owner-DB coordination (backlog B13 slice).

One process owns one graph, but two planes touch it: the MCP read plane (invokes
that read the graph, cached index, compass) and the operator write plane
(confirms that mutate the .lbug exclusively via snapshot/apply). Without
coordination a read can observe a half-applied write, or run against a stale
cached index after a commit.

A **writer-preferring reader-writer lock**, shared between both planes, is the
fix: MCP invokes take the read (shared) side; an operator confirm takes the
write (exclusive) side — it waits for in-flight reads to drain, mutates, the
engine reloads, then reads resume against the new state. Writer-preferring so a
steady stream of reads cannot starve a pending confirm.

Consequence for the single-graph/single-operator use case (deliberately mild):
reads run concurrently as before; only a confirm briefly excludes reads for its
(rare, snapshot-bounded) duration. No read ever blocks another read.
"""

from __future__ import annotations

import contextlib
import threading


class RWLock:
    """Writer-preferring readers-writer lock."""

    def __init__(self) -> None:
        self._cond = threading.Condition(threading.Lock())
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0

    @contextlib.contextmanager
    def read(self):
        with self._cond:
            # yield to any waiting/active writer (writer preference)
            while self._writer or self._waiting_writers > 0:
                self._cond.wait()
            self._readers += 1
        try:
            yield
        finally:
            with self._cond:
                self._readers -= 1
                if self._readers == 0:
                    self._cond.notify_all()

    @contextlib.contextmanager
    def write(self):
        with self._cond:
            self._waiting_writers += 1
            while self._writer or self._readers > 0:
                self._cond.wait()
            self._waiting_writers -= 1
            self._writer = True
        try:
            yield
        finally:
            with self._cond:
                self._writer = False
                self._cond.notify_all()

    # introspection for tests/telemetry (advisory, not a lock primitive)
    def _state(self) -> dict:
        with self._cond:
            return {"readers": self._readers, "writer": self._writer,
                    "waiting_writers": self._waiting_writers}
