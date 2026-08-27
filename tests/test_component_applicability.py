"""Unit tests for component-applicability gate (no API)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ))

from component_applicability import (
    evaluate_component_applicability,
    governed_components_for_rule,
    resolve_change_component,
)
from conformance_verdict import ConformanceKind
from governance_dispatch import DispatchRouter


@pytest.fixture(scope="module")
def credential_conn(tmp_path_factory):
    import shutil

    from conformance_check.handbooks import resolve_handbook
    from engine import get_connection, reset_connection

    cfg = resolve_handbook("credential")
    if not cfg.db_path.exists():
        pytest.skip(f"handbook graph missing: {cfg.db_path}")
    dest = tmp_path_factory.mktemp("cred_handbook") / "credential_governance.lbug"
    shutil.copy2(cfg.db_path, dest)
    for suffix in (".idx", ".wal"):
        side = cfg.db_path.with_name(cfg.db_path.name + suffix)
        if side.exists():
            shutil.copy2(side, dest.with_name(dest.name + suffix))
    # Pass db_path explicitly (no SST_DB_PATH env write — that leaked into other
    # tests). Reset on teardown so the global engine connection is not left open
    # to the credential graph for a later test that expects the default graph.
    reset_connection()
    conn = get_connection(db_path=dest)
    try:
        yield conn
    finally:
        reset_connection()


def test_purpose_limitation_governs_scoped_client_only(credential_conn):
    governed = governed_components_for_rule(credential_conn, "PurposeLimitationRule")
    assert governed == ["ScopedAccessClient"]


def test_loader_maps_to_credential_loader_component(credential_conn):
    comp = resolve_change_component(
        credential_conn,
        snippet_label="credential_loader.py",
        target_file="app/scoped_access/credential_loader.py",
    )
    assert comp == "CredentialLoader"


def test_gate_fires_purpose_on_loader(credential_conn):
    result = evaluate_component_applicability(
        credential_conn,
        rule_id="PurposeLimitationRule",
        snippet_label="credential_loader.py",
        target_file="app/scoped_access/credential_loader.py",
    )
    assert result.gated is True
    assert "CredentialLoader" in result.predicate
    assert "ScopedAccessClient" in result.predicate


def test_gate_passes_purpose_on_scoped_client(credential_conn):
    result = evaluate_component_applicability(
        credential_conn,
        rule_id="PurposeLimitationRule",
        snippet_label="scoped_client.py",
        target_file="app/scoped_access/scoped_client.py",
    )
    assert result.gated is False
    assert result.change_component == "ScopedAccessClient"


def test_unresolved_file_does_not_gate(credential_conn):
    result = evaluate_component_applicability(
        credential_conn,
        rule_id="ScopeUseMatchRule",
        snippet_label="scope_grant.py",
        target_file="app/scoped_access/scope_grant.py",
    )
    assert result.gated is False
    assert result.ambiguous is True


def test_dispatch_router_short_circuits_oos_semantic(credential_conn):
    from conformance_check.handbooks import load_tagged_rules, resolve_handbook
    from conformance_verdict import ConformanceVerdict

    tagged = load_tagged_rules(resolve_handbook("credential"))
    router = DispatchRouter(
        tagged,
        PROJ,
        semantic_runner=lambda c: ConformanceVerdict(verdict=ConformanceKind.CONFORMS),
        db_conn=credential_conn,
    )
    case = {
        "id": "oos_purpose_loader",
        "rule_ids": ["PurposeLimitationRule"],
        "snippet": "import os\n",
        "snippet_label": "credential_loader.py",
        "target_file": "app/scoped_access/credential_loader.py",
    }
    report = router.dispatch_change(case)
    assert report.overall == ConformanceKind.UNGOVERNED
    assert report.semantic_llm_calls == 0
    rr = report.rule_results[0]
    assert rr.short_circuited is True
    assert rr.semantic is not None
    assert rr.semantic.verdict == ConformanceKind.UNGOVERNED
    assert "does not govern CredentialLoader" in (rr.semantic.predicate or "")
