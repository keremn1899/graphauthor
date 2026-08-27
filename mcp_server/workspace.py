"""Controlled runtime workspace switching for the local product.

The MCP contract remains one process = one graph. A switch does not make the
process multi-graph: it takes the owner's write lock, closes the old graph
session, and opens a new Surface + OperatorSurface pair before requests resume.

Routes and the MCP server hold stable proxy objects, so existing HTTP plumbing
does not need to be rebuilt for each document. Every method lookup delegates to
the pair that is current at that instant.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from mcp_server.coordination import RWLock
from mcp_server.fault import operator_fault


class _Proxy:
    def __init__(self, owner: "WorkspaceOwner", side: str) -> None:
        object.__setattr__(self, "_owner", owner)
        object.__setattr__(self, "_side", side)

    def _target(self):
        owner = object.__getattribute__(self, "_owner")
        side = object.__getattribute__(self, "_side")
        return owner.surface if side == "surface" else owner.operator

    def __getattr__(self, name: str):
        return getattr(self._target(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_owner", "_side"}:
            object.__setattr__(self, name, value)
            return
        setattr(self._target(), name, value)


class WorkspaceOwner:
    """Own exactly one live Surface/Operator pair and switch it atomically."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        surface_factory: Callable[[Path, RWLock], Any],
        operator_factory: Callable[[Path, RWLock, Callable[[], None]], Any],
    ) -> None:
        self._state_lock = threading.RLock()
        self.lock = RWLock()
        self._surface_factory = surface_factory
        self._operator_factory = operator_factory
        self._path = Path(db_path).expanduser().resolve()
        self.surface = self._surface_factory(self._path, self.lock)
        self.operator = self._operator_factory(
            self._path,
            self.lock,
            self.surface.reload,
        )
        self.surface_proxy = _Proxy(self, "surface")
        self.operator_proxy = _Proxy(self, "operator")

    @property
    def path(self) -> Path:
        with self._state_lock:
            return self._path

    def activate(self, path: Path) -> dict[str, Any]:
        target = Path(path).expanduser().resolve()
        with self._state_lock:
            if target == self._path:
                return {"changed": False, "graph_id": target.stem}

            # Queries/confirm take this same lock. When we enter, no graph read
            # or graph mutation can still be using the session being closed.
            with self.lock.write():
                previous = self._path
                old_surface = self.surface
                old_surface.close()
                try:
                    new_surface = self._surface_factory(target, self.lock)
                    new_operator = self._operator_factory(
                        target,
                        self.lock,
                        new_surface.reload,
                    )
                except Exception as exc:
                    # A failed switch must not strand the app without a graph.
                    restored = self._surface_factory(previous, self.lock)
                    self.surface = restored
                    self.operator = self._operator_factory(
                        previous,
                        self.lock,
                        restored.reload,
                    )
                    return operator_fault(
                        "unavailable",
                        f"Could not open workspace: {type(exc).__name__}: {exc}",
                    )

                self.surface = new_surface
                self.operator = new_operator
                self._path = target
                return {
                    "changed": True,
                    "graph_id": target.stem,
                    "workspace_name": target.parent.name,
                }

    def close(self) -> None:
        with self._state_lock:
            self.surface.close()
