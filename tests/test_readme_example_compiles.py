"""The traversal program in README.md must be a program that compiles.

Written because the first draft of it did not. It used `assign_to` for the
step's output variable, which is the *internal* IR field -- the input key is
`assign`. The compiler rejects that, so the example in the front-page README
would have failed for anyone who copied it, and nothing would have said so.

It also omitted `collect`, which is required.

A README is documentation nobody runs, which is exactly why the example in it
should be executable by something. This reads the program out of the file, so
editing the README edits the test input.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from mcp_server.graph_contract import parse_graph_contract
from mcp_server.traversal_compiler import (
    TraversalCompileError,
    compile_ephemeral_traversal,
)
from tests.workbook_graph_fixture import PERSONAL_RECIPE_CONTRACT

ROOT = Path(__file__).resolve().parents[1]
def _program_from_readme() -> dict:
    text = (ROOT / "README.md").read_text()
    blocks = re.findall(r"```json\n(\{.*?\n\})\n```", text, re.S)
    assert blocks, "README no longer contains a json program block"
    return json.loads(blocks[0])


def test_the_readme_program_is_valid_json():
    program = _program_from_readme()
    assert program.get("steps"), "the example has no steps"


def test_the_readme_program_compiles_against_the_contract_it_shows():
    compile_ephemeral_traversal(
        parse_graph_contract(PERSONAL_RECIPE_CONTRACT), _program_from_readme(), {}
    )


def test_the_readme_program_only_uses_ops_the_vocabulary_serves():
    """A published example may not demonstrate an op the server does not have."""
    from mcp_server.graph_contract import _RECIPE_OP_KEYS

    used = {str(step.get("op")) for step in _program_from_readme()["steps"]}
    unknown = used - set(_RECIPE_OP_KEYS)
    assert not unknown, f"README shows ops that do not exist: {sorted(unknown)}"


def test_the_compiler_rejects_the_mistake_this_file_exists_for():
    """Positive control. Without it, a compiler that accepted anything would
    make every assertion above vacuous."""
    program = _program_from_readme()
    for step in program["steps"]:
        step["assign_to"] = step.pop("assign")

    with pytest.raises(TraversalCompileError):
        compile_ephemeral_traversal(
            parse_graph_contract(PERSONAL_RECIPE_CONTRACT), program, {}
        )
