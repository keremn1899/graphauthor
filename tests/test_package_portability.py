"""The installed public package must work outside the engine checkout."""

from __future__ import annotations

import os
import subprocess
import sys


def test_public_package_imports_from_an_unrelated_working_directory(tmp_path):
    env = dict(os.environ)
    # Do not let the source checkout leak in through an explicitly supplied
    # module path. Editable-install metadata in site-packages is the contract.
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import closed_knowledge_engine as cke; "
                "import engine_state, retrieval_program; "
                "assert cke.__version__"
            ),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
