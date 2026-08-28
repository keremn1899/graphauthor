from __future__ import annotations

import json
import sys

import pytest

from mcp_server.bootstrap import attach_workspace


def test_attach_adds_only_a_sidecar_and_preserves_existing_cursor_servers(tmp_path):
    workspace = tmp_path / "existing-project"
    workspace.mkdir()
    (workspace / "README.md").write_text("existing work")
    cursor = workspace / ".cursor"
    cursor.mkdir()
    (cursor / "mcp.json").write_text(json.dumps({
        "mcpServers": {"other": {"command": "other-mcp"}}
    }))

    result = attach_workspace(workspace, ["cursor", "claude"])

    sidecar = workspace / ".graphauthor"
    assert result["sidecar"] == str(sidecar)
    assert sidecar.is_dir()
    assert not (sidecar / "build.py").exists()
    assert (workspace / "README.md").read_text() == "existing work"
    cursor_config = json.loads((cursor / "mcp.json").read_text())
    assert set(cursor_config["mcpServers"]) == {"other", "graphauthor"}
    assert json.loads((workspace / ".mcp.json").read_text())["mcpServers"]["graphauthor"] == (
        cursor_config["mcpServers"]["graphauthor"]
    )
    server = cursor_config["mcpServers"]["graphauthor"]
    assert server["command"] == sys.executable
    assert server["env"]["SST_DB_PATH"] == str(sidecar / "graph.lbug")
    assert ".graphauthor/build.py" in result["agent_prompt"]


def test_attach_refuses_to_overwrite_invalid_mcp_config(tmp_path):
    (tmp_path / ".cursor").mkdir()
    path = tmp_path / ".cursor" / "mcp.json"
    path.write_text("not json")

    with pytest.raises(ValueError, match="refusing to overwrite"):
        attach_workspace(tmp_path, ["cursor"])
