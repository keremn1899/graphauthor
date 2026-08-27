from __future__ import annotations

import subprocess
from pathlib import Path

from benchmarks.external.cattrs_software.admission import (
    UV_VERSION,
    build_inventory,
    classify_path,
    uv_version_matches,
)
from benchmarks.external.cattrs_software.study import _imports, _module_name
from benchmarks.external.cattrs_software.reference import build_reference_graph
from benchmarks.external.cattrs_software.product_runner import (
    _excerpt_is_grounded,
    _response_string_fields,
    _turn_budget_instruction,
)


def test_cattrs_path_boundary_is_closed_and_intentional():
    assert classify_path("src/cattrs/converters.py") == (
        "construction_source",
        "production Python",
    )
    assert classify_path("tests/test_converter.py")[0] == "construction_source"
    assert classify_path("docs/migrations.md")[0] == "construction_source"
    assert classify_path("docs/cattrs.gen.rst") == (
        "excluded",
        "generated API index",
    )
    assert classify_path("uv.lock")[0] == "admission_only"
    assert classify_path("bench/test_primitives.py")[0] == "excluded"
    assert classify_path("docs/_static/logo.png")[0] == "excluded"


def test_uv_version_accepts_platform_suffix_but_not_another_version():
    assert uv_version_matches(f"uv {UV_VERSION} (x86_64-unknown-linux-gnu)")
    assert not uv_version_matches("uv 0.12.2 (x86_64-unknown-linux-gnu)")
    assert not uv_version_matches(f"uv {UV_VERSION}")


def test_inventory_hashes_and_classifies_every_tracked_file(tmp_path: Path):
    repo = tmp_path / "upstream"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repo, check=True
    )
    (repo / "src").mkdir()
    (repo / "src/module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (repo / "image.bin").write_bytes(b"\x00\x01")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()

    manifest = build_inventory(repo, expected_sha=head)

    assert manifest["schema"] == "cattrs-external-source-manifest-v1"
    assert len(manifest["manifest_fingerprint"]) == 64
    by_path = {item["path"]: item for item in manifest["files"]}
    assert set(by_path) == {"image.bin", "src/module.py", "uv.lock"}
    assert by_path["src/module.py"]["classification"] == "construction_source"
    assert by_path["uv.lock"]["classification"] == "admission_only"
    assert by_path["image.bin"]["classification"] == "excluded"
    assert by_path["image.bin"]["lines"] is None
    assert all(len(item["sha256"]) == 64 for item in by_path.values())


def test_study_resolves_internal_absolute_and_relative_imports():
    modules = {
        "cattrs",
        "cattrs.converters",
        "cattrs.preconf",
        "cattrs.preconf.json",
        "cattrs.strategies",
    }
    source = """
from .. import BaseConverter
from ..converters import Converter
from ..strategies import configure_union_passthrough
from json import dumps
import attrs
"""

    assert _module_name("src/cattrs/preconf/json.py") == "cattrs.preconf.json"
    assert _module_name("src/cattrs/preconf/__init__.py") == "cattrs.preconf"
    assert _imports("src/cattrs/preconf/json.py", source, modules) == {
        "cattrs",
        "cattrs.converters",
        "cattrs.strategies",
    }


def test_reference_graph_is_minimal_and_quarantines_history():
    graph = build_reference_graph()

    assert len(graph.nodes) == 24
    assert len(graph.edges) == 30
    decisions = [node for node in graph.nodes.values() if node.id.startswith("decision_")]
    assert len(decisions) == 16
    assert sum(node.claim_kind == "governing" for node in decisions) == 11
    historical = [node for node in decisions if node.claim_kind == "contextual"]
    assert len(historical) == 5
    assert all("NOT GOVERNING" in node.text_content for node in historical)
    assert all(not node.text_content.startswith("GOVERNING:") for node in historical)


def test_judge_excerpt_grounding_handles_decoded_multiline_strings():
    final = {
        "answer": "Current default.\n\nTo restore legacy behavior:\n- register hook A",
        "source_evidence": [{"quote": "exact source line"}],
    }

    assert _response_string_fields(final) == [
        "Current default.\n\nTo restore legacy behavior:\n- register hook A",
        "exact source line",
    ]
    assert _excerpt_is_grounded(
        "To restore legacy behavior:\n- register hook A", final
    )
    assert not _excerpt_is_grounded("restore behavior with a hook", final)


def test_frozen_agent_budget_reserves_the_final_turn_for_output():
    assert "7 model turn(s) remain" in _turn_budget_instruction(1)
    final = _turn_budget_instruction(8)
    assert final.startswith("FINAL TURN:")
    assert "Do not call another tool" in final
