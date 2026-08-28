from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from mcp_server.bootstrap import init_project


def test_init_creates_a_cursor_ready_agent_project(tmp_path):
    project = tmp_path / "my-graph"

    result = init_project(project)

    assert result["db_path"] == str(project / "graph.lbug")
    config = json.loads((project / ".cursor" / "mcp.json").read_text())
    assert json.loads((project / ".mcp.json").read_text()) == config
    server = config["mcpServers"]["graphauthor"]
    assert server["command"] == str(Path(sys.executable).resolve())
    assert server["args"] == ["-m", "mcp_server.stdio"]
    assert server["env"]["SST_DB_PATH"] == str(project / "graph.lbug")
    prompt = (project / "AGENT_PROMPT.md").read_text()
    assert f'"{Path(sys.executable).resolve()}" -m scripts.atoms prepare' in prompt
    assert f'"{Path(sys.executable).resolve()}" -m scripts.atoms materialize' in prompt


def test_init_refuses_to_overwrite_a_nonempty_directory(tmp_path):
    project = tmp_path / "existing"
    project.mkdir()
    (project / "notes.md").write_text("keep")

    with pytest.raises(FileExistsError, match="not empty"):
        init_project(project)
