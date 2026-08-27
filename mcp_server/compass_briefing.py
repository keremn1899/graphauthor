"""Format a Graph Compass profile as the Layer 1 shape briefing.

Lifted out of `legacy_fsm/planner.py`, which is the old FSM and is not served.
This is a pure function of the profile dict: no graph, no model, no state. It
was the one piece of that module the product still called, and leaving it there
meant `mcp_server/ask.py` imported three thousand lines of dead planner to
format ten lines of text.
"""

from __future__ import annotations

__all__ = ["format_layer1"]


def format_layer1(profile: dict) -> list[str]:
    """v7 Layer 1 — Graph Shape. ~200 tokens, always present."""
    lines: list[str] = []
    lines.append("## LAYER 1 — GRAPH SHAPE")
    node_count = profile.get("node_count", 0)
    total_edges = profile.get("total_edges")
    edge_counts = profile.get("edge_counts", {}) or {}
    if total_edges is None:
        total_edges = sum(edge_counts.values())
    lines.append(
        f"  Nodes: {node_count} | Edges: {total_edges} | "
        f"Dominant SST: {profile.get('dominant_sst_type', '—')}"
    )
    lines.append(f"  Character: {profile.get('structural_character', 'mixed')}")
    lines.append(f"  Depth   : {profile.get('depth_profile', 'unknown')}")
    lines.append(f"  Density : {profile.get('density', 'unknown')}")
    normative_character = str(profile.get("normative_character") or "").strip()
    if normative_character:
        normative_density = profile.get("normative_density")
        density_note = (
            f", declared governing density={normative_density}"
            if normative_density is not None
            else ""
        )
        lines.append(
            f"  Normative: {normative_character}{density_note} | "
            "default verdict space="
            f"{profile.get('default_verdict_space', 'confirmation')}"
        )
    # How finely this graph cuts its sources, when it says. Nothing else in
    # this briefing distinguishes a node that is a paragraph from one that is
    # a sentence, and that decides how many nodes one answer costs: at a
    # median of 15 nodes per source unit, a single section exhausts an 8-12
    # node budget. Omitted rather than guessed on graphs that do not carry it.
    grain = profile.get("grain_character")
    if grain:
        lines.append(f"  Grain   : {grain}")
        span = profile.get("nodes_per_source_unit_max")
        if span:
            lines.append(
                f"            largest source unit spans {span} nodes; "
                f"payload median {profile.get('payload_chars_p50', 0)} chars"
            )
    if edge_counts:
        counts_str = ", ".join(
            f"{k.upper()}={v}" for k, v in sorted(edge_counts.items())
        )
        lines.append(f"  Edge mix: {counts_str}")
    role_pop = profile.get("role_populations") or {}
    if role_pop:
        top_roles = sorted(role_pop.items(), key=lambda x: x[1], reverse=True)
        role_str = ", ".join(f"{k}={v}" for k, v in top_roles if v > 0)
        lines.append(f"  Role populations: {role_str}")
    cc = profile.get("connected_components") or {}
    if cc:
        n_comp = cc.get("count", 1)
        largest_pct = cc.get("largest_pct", 100)
        top5 = cc.get("top5_sizes", [])
        if n_comp == 1:
            lines.append("  Connectivity: 1 component (fully connected — all entities reachable from each other)")
        else:
            top5_str = ", ".join(str(s) for s in top5)
            lines.append(
                f"  Connectivity: {n_comp} disconnected components "
                f"(largest={largest_pct}% of nodes; top-5 sizes: {top5_str}). "
                "find_paths between entities in different components will always return empty."
            )
    edge_schema = profile.get("edge_schema") or {}
    if edge_schema:
        lines.append("  Edge direction schema (use this to select correct edge type and direction):")
        for sst_type, info in edge_schema.items():
            summary = info.get("summary", "direction varies")
            lines.append(f"    {sst_type.upper()}: {summary}")
    edge_label_inventory = profile.get("edge_label_inventory") or {}
    if edge_label_inventory:
        has_any_labeled = any(
            any(e["label"] != "(unlabeled)" for e in entries)
            for entries in edge_label_inventory.values()
            if entries
        )
        if has_any_labeled:
            lines.append(
                "  Edge label inventory (use these in chain-contract `edge_labels` "
                "to filter within an SST type):"
            )
            for sst_type, entries in sorted(edge_label_inventory.items()):
                labeled = [e for e in entries if e["label"] != "(unlabeled)"]
                if not labeled:
                    continue
                lines.append(f"    {sst_type.upper()}:")
                for entry in labeled[:8]:
                    ex = entry.get("examples", [])
                    ex_str = (
                        f' — e.g. "{ex[0]["src"]}" → "{ex[0]["dst"]}"'
                        if ex else ""
                    )
                    lines.append(
                        f'      • "{entry["label"]}" ({entry["count"]} edges){ex_str}'
                    )
    lines.append("")
    return lines
