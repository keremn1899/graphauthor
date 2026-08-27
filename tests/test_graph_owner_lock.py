from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from engine import GraphInUseError, get_connection, reset_connection
from mcp_server.fixture import ensure_fixture
from mcp_server.history import SnapshotStore
from mcp_server.surface import Surface


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def db(tmp_path):
    dst = ensure_fixture(tmp_path / "owned.lbug")
    yield dst
    reset_connection()


def test_same_process_can_reopen_the_owned_graph(db):
    first = get_connection(db, auto_seed=False)
    second = get_connection(db, auto_seed=False)
    assert first is second
    reset_connection()
    again = get_connection(db, auto_seed=False)
    assert again is not None
    reset_connection()


def test_second_process_cannot_open_the_same_graph(db):
    get_connection(db, auto_seed=False)
    script = f"""
from pathlib import Path
from engine import GraphInUseError, get_connection
try:
    get_connection(Path({str(db)!r}), auto_seed=False)
except GraphInUseError:
    print("BUSY")
else:
    print("OPENED")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    reset_connection()
    assert "BUSY" in result.stdout, result.stdout + result.stderr
    assert "OPENED" not in result.stdout


def test_restore_refuses_while_this_process_still_owns_the_graph(db):
    surface = Surface(db, enable_history=True)
    try:
        store = SnapshotStore(db)
        store.capture("vA")
        with pytest.raises(GraphInUseError, match="still has it open"):
            store.restore("vA")
    finally:
        surface.close()
    SnapshotStore(db).restore("vA")
