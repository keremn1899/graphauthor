from pathlib import Path


class _Surface:
    def __init__(self, path, lock):
        self._db_path = Path(path)
        self._rw_lock = lock
        self._capabilities = ["query"]
        self.closed = False

    def orient(self):
        return {"graph": self._db_path.stem}

    def reload(self):
        pass

    def close(self):
        self.closed = True


class _Operator:
    def __init__(self, path, lock, reload_hook):
        self._db = Path(path)
        self._rw_lock = lock
        self._reload_hook = reload_hook

    def health(self):
        return {"graph": self._db.stem}


def _owner(path):
    from mcp_server.workspace import WorkspaceOwner

    return WorkspaceOwner(
        path,
        surface_factory=lambda graph, lock: _Surface(graph, lock),
        operator_factory=lambda graph, lock, reload: _Operator(
            graph, lock, reload
        ),
    )


def test_workspace_switch_keeps_stable_proxies_and_swaps_both_planes(tmp_path):
    first = tmp_path / "first.lbug"
    second = tmp_path / "second.lbug"
    first.touch()
    second.touch()
    owner = _owner(first)
    surface_proxy = owner.surface_proxy
    operator_proxy = owner.operator_proxy
    old_surface = owner.surface

    result = owner.activate(second)

    assert result["changed"] is True
    assert old_surface.closed is True
    assert surface_proxy.orient()["graph"] == "second"
    assert operator_proxy.health()["graph"] == "second"
    assert owner.path == second
