from __future__ import annotations

import pytest

from tests.fixture_db import create_dependencies_db, create_fixture_db


@pytest.fixture
def deps_conn(tmp_path):
    """Ladybug connection with dependencies seed (no API calls)."""
    return create_dependencies_db(tmp_path / "deps_fixture.lbug")


@pytest.fixture
def metabolism_conn(tmp_path):
    """Ladybug connection with metabolism example graph (no API calls)."""
    return create_fixture_db("metabolism", tmp_path / "metabolism_fixture.lbug")


@pytest.fixture
def auth_conn(tmp_path):
    """Ladybug connection with auth_service example graph (no API calls)."""
    return create_fixture_db("auth_service", tmp_path / "auth_fixture.lbug")


@pytest.fixture
def memory_conn(tmp_path):
    """Ladybug connection with memory_cognition example graph (no API calls)."""
    return create_fixture_db("memory_cognition", tmp_path / "memory_fixture.lbug")
