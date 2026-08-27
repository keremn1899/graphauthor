"""Named local shelf for host-agent constructions — not a merge."""

from __future__ import annotations

from pathlib import Path

from mcp_server.host_constructions import ensure_host_construction_shelf
from mcp_server.graph_http import GraphCatalogue


def test_shelf_links_named_host_graphs_into_construction_trials(tmp_path, monkeypatch):
    host = tmp_path / "host"
    kep = host / "results/kubernetes_kep_lifecycle/construction/run_1_correction/workspace_v1"
    cattrs = host / (
        "data/construction_trials/cattrs_host_owned_construction_v1/"
        "stage_b/run_1_correction/host_workspace/uncertified_preview"
    )
    kep.mkdir(parents=True)
    cattrs.mkdir(parents=True)
    (kep / "graph.lbug").write_bytes(b"kep")
    (cattrs / "graph.lbug").write_bytes(b"host")
    monkeypatch.setenv("SST_HOST_AGENT_ROOT", str(host))

    project = tmp_path / "product"
    linked = ensure_host_construction_shelf(project)

    names = {path.parent.name for path in linked}
    assert names == {"kep-kustomize", "cattrs-host-owned"}
    kep_link = project / "data/construction_trials/kep-kustomize"
    assert kep_link.is_symlink()
    assert (kep_link / "graph.lbug").read_bytes() == b"kep"

    again = ensure_host_construction_shelf(project)
    assert {path.parent.name for path in again} == names
    assert kep_link.is_symlink()


def test_shelf_skips_a_missing_host_worktree(tmp_path, monkeypatch):
    monkeypatch.setenv("SST_HOST_AGENT_ROOT", str(tmp_path / "nowhere"))
    assert ensure_host_construction_shelf(tmp_path / "product") == []


def test_catalogue_lists_shelved_host_graphs_by_the_shelf_name(tmp_path):
    from mcp_server.fixture import ensure_fixture
    import shutil

    db = tmp_path / "current.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), db)
    kep = tmp_path / "data/construction_trials/kep-kustomize"
    kep.mkdir(parents=True)
    shutil.copy2(db, kep / "graph.lbug")

    cat = GraphCatalogue(
        db,
        library_dirs=[],
        output_roots=[tmp_path / "data/construction_trials"],
    )
    labels = {row["label"] for row in cat.list()}
    assert "Kep Kustomize" in labels


def test_the_shelf_prefers_this_repository_over_the_sibling_worktree(tmp_path, monkeypatch):
    """The constructions moved here; a link into the sibling is now a liability.

    A link into another worktree breaks when that worktree is removed or checks
    out a branch without the file, and the catalogue would then offer a row that
    cannot be opened.
    """
    from mcp_server.host_constructions import SHELF, resolve_shelf_source

    name, relative = SHELF[0]
    local = tmp_path / "local"
    sibling = tmp_path / "sibling"
    for root in (local, sibling):
        (root / relative).mkdir(parents=True)
        (root / relative / "graph.lbug").write_bytes(b"x")
    monkeypatch.setenv("SST_HOST_AGENT_ROOT", str(sibling))

    assert resolve_shelf_source(local, relative) == local / relative


def test_the_sibling_is_still_the_fallback_when_a_graph_is_not_here(tmp_path, monkeypatch):
    from mcp_server.host_constructions import SHELF, resolve_shelf_source

    _, relative = SHELF[0]
    local = tmp_path / "local"
    sibling = tmp_path / "sibling"
    local.mkdir()
    (sibling / relative).mkdir(parents=True)
    (sibling / relative / "graph.lbug").write_bytes(b"x")
    monkeypatch.setenv("SST_HOST_AGENT_ROOT", str(sibling))

    assert resolve_shelf_source(local, relative) == sibling / relative


def test_a_named_shelf_link_keeps_its_name_in_the_catalogue(tmp_path):
    """Identity is the real path; the NAME comes from how it was reached.

    The catalogue de-duplicated by `resolve()` and then stored the resolved
    path, so every named link collapsed onto its target and was labelled from
    the run directory — `kep-kustomize` was offered as "Workspace V1".
    """
    from mcp_server.graph_http import GraphCatalogue

    deep = tmp_path / "runs" / "trial" / "workspace_v1"
    deep.mkdir(parents=True)
    (deep / "graph.lbug").write_bytes(b"x")
    shelf = tmp_path / "outputs"
    shelf.mkdir()
    (shelf / "kep-kustomize").symlink_to(deep, target_is_directory=True)

    catalogue = GraphCatalogue(tmp_path / "absent.lbug",
                               output_roots=[shelf, tmp_path / "runs"])
    labels = [row.get("label") for row in catalogue.list()]

    assert "Kep Kustomize" in labels, labels
    # One graph, reachable two ways, is still one row.
    assert len([lbl for lbl in labels if lbl in ("Kep Kustomize", "Workspace V1")]) == 1
