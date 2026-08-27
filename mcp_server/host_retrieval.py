"""Retrieval operations plus the regional navigation projection.

The operations themselves live in `mcp_server.retrieve.Retrieve` and are not
reimplemented here. This class is what an agent host gets *in addition*: a
deterministic Leiden region directory it can page through, and an opt-in link
from returned node identities to the regions holding them.

Those extras were never product affordances. `region_map` / `region` /
`locate_regions` are exposed by no MCP tool and no HTTP route; they and
`linked_navigation` (default off) are reachable only from
`benchmarks/host_retrieval/`, where they were built to test whether a regional
map improves a host's goal loop. Keeping them in a subclass states that
honestly: the retrieval contract is one class, and this is a research
projection layered on top of it.

The class name and import path are load-bearing. Twenty benchmark and example
scripts construct `HostRetrievalSurface` to replay recorded measurements; most
of them touch nothing regional and only ever wanted the four ops. Renaming it
would break the reproducibility record for no gain.
"""

from __future__ import annotations

import json
import time
from typing import Any

from mcp_server.retrieve import Retrieve


class HostRetrievalSurface(Retrieve):
    """`Retrieve`, plus deterministic regional navigation."""

    def __init__(
        self,
        surface: Any,
        *,
        linked_navigation: bool = False,
        structured_feedback: bool = False,
        seed_resolution_feedback: bool = True,
        endpoint_resolution_feedback: bool = True,
    ):
        super().__init__(
            surface,
            structured_feedback=structured_feedback,
            seed_resolution_feedback=seed_resolution_feedback,
            endpoint_resolution_feedback=endpoint_resolution_feedback,
        )
        self._regional_index: dict[str, Any] | None = None
        # Regional navigation stays a private experimental affordance. Seed- and
        # endpoint-resolution feedback graduated after the frozen native-MCP
        # probe and now live on the shared core; callers may disable them only
        # to replay the historical control arm.
        self._linked_navigation = bool(linked_navigation)

    @staticmethod
    def capability_card() -> dict[str, Any]:
        card = Retrieve.capability_card()
        card["operations"] = card["operations"] + [
            "region_map", "region", "locate_regions",
        ]
        card["regional_policy"] = (
            "Leiden regions are deterministic navigation projections; "
            "their exact members and crossing edges are fetchable and "
            "they never imply semantic authority"
        )
        return card

    def _regions(self) -> dict[str, Any]:
        from mcp_server.regional_compass import build_region_index

        with self._surface._read_guard():
            base = self._surface._base()
            if (
                self._regional_index is None
                or self._regional_index.get("graph_version") != base["graph_version"]
            ):
                self._regional_index = build_region_index(
                    self._surface._session.connection,
                    graph_version=base["graph_version"],
                )
            return self._regional_index

    def region_map(self) -> dict[str, Any]:
        """Return the compact deterministic graph-wide region directory."""
        from mcp_server.regional_compass import compact_region_map

        return compact_region_map(self._regions())

    def region(
        self,
        region_id: str,
        *,
        member_offset: int = 0,
        member_limit: int = 100,
        boundary_offset: int = 0,
        boundary_limit: int = 100,
    ) -> dict[str, Any]:
        """Fetch a paged exact region card and its cross-region frontier."""
        from mcp_server.regional_compass import region_card

        return region_card(
            self._regions(),
            str(region_id or "").strip(),
            member_offset=int(member_offset),
            member_limit=int(member_limit),
            boundary_offset=int(boundary_offset),
            boundary_limit=int(boundary_limit),
        )

    def locate_regions(self, node_ids: list[str]) -> dict[str, Any]:
        """Locate exact node IDs in deterministic regions; never widen a miss."""
        from mcp_server.regional_compass import locate_regions

        return locate_regions(self._regions(), node_ids)

    def _after_execute(self, result: dict[str, Any], *, collected_node_count: int) -> None:
        """Link exact returned node identities to optional regional reads.

        Annotation only: `navigation` is a continuation offer, and nothing here
        touches outcome, evidence_scope, or the evidence.
        """
        if not (self._linked_navigation and collected_node_count):
            return
        evidence = result.get("evidence") or {}
        node_ids: list[str] = []
        for key in ("node_records", "node_payloads"):
            for row in evidence.get(key) or []:
                node_id = str(row.get("id") or "").strip() if isinstance(row, dict) else ""
                if node_id:
                    node_ids.append(node_id)
        node_ids = list(dict.fromkeys(node_ids))
        if not node_ids:
            return

        cache_hit = self._regional_index is not None
        started = time.monotonic()
        index = self._regions()
        from mcp_server.regional_compass import locate_regions

        located = locate_regions(index, node_ids)
        region_ids = sorted(set(located["node_regions"].values()))
        navigation = {
            "kind": "regional",
            "index_ref": index["index_sha256"],
            "graph_version": index["graph_version"],
            "node_regions": located["node_regions"],
            "continuations": [
                {"tool": "region", "region_id": region_id}
                for region_id in region_ids
            ],
            "receipt": {
                "index_cache_hit": cache_hit,
                "elapsed_ms": round((time.monotonic() - started) * 1000, 3),
            },
        }
        navigation["receipt"]["serialized_chars"] = len(
            json.dumps(navigation, ensure_ascii=False)
        )
        result["navigation"] = navigation
