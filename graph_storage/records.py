"""In-memory records accepted by the Ladybug graph writer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from models import SST_EDGE_TYPES


@dataclass
class GraphEdge:
    source: str
    target: str
    sst_type: str
    label: str = ""

    def validated_type(self) -> str | None:
        value = (self.sst_type or "").strip().lower()
        return value if value in SST_EDGE_TYPES else None


@dataclass
class GraphNode:
    id: str
    label: str
    text_content: str = ""
    semantic_anchor: str = ""
    token_count: int = 0
    is_metanode: bool = False
    linked_graph_id: str = ""
    kind: str = ""
    claim_kind: str = ""
    claim_kind_source: str = ""
    source_unit_ids: list[str] = field(default_factory=list)


@dataclass
class MaterializedGraph:
    id: str
    domain: str
    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)
    analysis: dict[str, Any] = field(default_factory=dict)
    elk_layout: dict[str, Any] | None = None
    parent_metanode_id: str | None = None

    def node_list(self) -> list[GraphNode]:
        return list(self.nodes.values())

    def labels_by_id(self) -> dict[str, str]:
        return {node_id: node.label for node_id, node in self.nodes.items()}
