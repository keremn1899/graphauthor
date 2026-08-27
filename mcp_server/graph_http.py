"""`/graph` — read-only map plane for the ambient canvas.

Deliberately NOT under `/operator` and NOT MCP: the canvas browses the knowledge
graph, it does not govern it. Same process, same bearer gate, zero authority —
every route is a read of a `.lbug` this server already owns.

Ordinary reads never name a filesystem path. They ask for a graph by an opaque
catalogue id. The explicit ``open`` command is the one exception: on this local,
authenticated server a human may add an existing ``.lbug`` file to the
session. The path is validated as a real graph before it becomes an opaque id;
it is never accepted by map or query routes.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Callable

from mcp_server.fault import operator_fault


class GraphCatalogue:
    """The set of graphs this server is willing to read, keyed by id.

    Membership is decided here, never by the caller. `current` is the graph the
    operator plane itself is pointed at; the rest are published bundles sitting
    beside it.
    """

    def __init__(
        self,
        db_path: Path | str,
        *,
        published_dir: Path | str | None = None,
        library_dirs: list[Path | str] | tuple[Path | str, ...] | None = None,
        output_roots: list[Path | str] | tuple[Path | str, ...] | None = None,
        on_activate: Callable[[Path], dict[str, Any]] | None = None,
        rw_lock: Any | None = None,
    ) -> None:
        self._db = Path(db_path)
        # The single-owner lock, shared with the MCP and operator planes. The
        # catalogue's own RLock below is a different thing entirely: it
        # serialises this object's bookkeeping and knows nothing about writes.
        self._rw_lock = rw_lock
        self._published = Path(published_dir) if published_dir else self._db.parent / "graphs"
        self._library_dirs = tuple(Path(p) for p in (library_dirs or ()))
        # Trees the product writes into, as opposed to directories it reads
        # from. Walked rather than globbed, because a construction chooses its
        # own workspace and the catalogue does not get to decide how deep that
        # is allowed to be.
        self._output_roots = tuple(Path(p) for p in (output_roots or ()))
        self._opened: list[Path] = []
        self._lock = threading.RLock()
        self._on_activate = on_activate
        # Listing used to reopen every graph on every shell/map request. Counts
        # are content metadata, so cache them against the file stat signature;
        # writes naturally invalidate without a second authority channel.
        self._summary_cache: dict[Path, tuple[tuple[int, int], dict[str, Any]]] = {}

    #: Directories a scan never descends into. `runtime_dbs` is this process's
    #: own scratch — an auto-seeded empty database that lists as an unreadable
    #: graph, which is noise wearing the shape of a defect.
    SKIP_DIRS = frozenset({"runtime_dbs", "__pycache__"})

    @staticmethod
    def _eligible(path: Path) -> bool:
        return (
            path.is_file()
            and path.suffix == ".lbug"
            and not path.name.endswith(".rejected.lbug")
        )

    #: How far below an output root a graph may sit and still be found. Three
    #: covers `construction_trials/<trial>/graph.lbug` and the `graphs/graphs/`
    #: drift, and stops well short of turning this into a crawl of `data`.
    OUTPUT_SCAN_DEPTH = 3

    #: How far below a library dir a graph may sit. Two covers
    #: `data/demo/<set>/<graph>.lbug` and `data/source_demo/<graph>.lbug`
    #: without turning a listing into a crawl of every run tree under `data`.
    LIBRARY_SCAN_DEPTH = 2

    #: Written beside a graph when a person publishes it. Its presence is the
    #: whole of the state: publication is a decision someone made, and until
    #: this file existed the product inferred it from which directory a file
    #: happened to sit in, which is not a decision at all.
    PUBLISH_SUFFIX = ".published.json"

    @classmethod
    def _publish_marker(cls, path: Path) -> Path:
        return path.with_name(path.name + cls.PUBLISH_SUFFIX)

    def _under_output_root(self, path: Path) -> bool:
        """Did a construction write this graph, wherever it is listed from?

        Deliberately independent of the `source` tag. `source` records how a
        graph was *discovered*, and the process's own graph is discovered as
        `current` no matter where it lives — so a construction being looked at
        right now would drop out of a list filtered on `source`, which is the
        one moment it most needs to be in it.

        Tested against the path as discovered *and* as resolved, because a
        workspace shelf is routinely a symlink. Measured here: of four graphs
        listed as constructions, `kep-kustomize` resolves into a different
        checkout of this project entirely, so resolving first said it was not
        a construction while the row above it said it was.
        """
        forms = [path.expanduser()]
        try:
            forms.append(path.expanduser().resolve())
        except OSError:
            pass
        for root in self._output_roots:
            roots = [root.expanduser()]
            try:
                roots.append(root.expanduser().resolve())
            except OSError:
                pass
            for form in forms:
                for base in roots:
                    try:
                        form.relative_to(base)
                    except ValueError:
                        continue
                    return True
        return False

    def _state(self, path: Path) -> str:
        """`construction` | `published` | `""`.

        Empty is not a third state of the same kind: it means the graph is not
        on this axis at all — a bundled example, or a file someone opened from
        disk. Only a graph a construction produced can be published, because
        publication is a statement about work that had to be reviewed.
        """
        if not self._under_output_root(path):
            return ""
        return "published" if self._publish_marker(path).exists() else "construction"

    def _topology_of(self, path: Path) -> str:
        """The graph's shape, or `""` if it could not be read.

        Empty rather than raising: a graph that will not open is a graph
        somebody may still want to mark as done with, and refusing the whole
        act over a sidecar field would be the tail wagging the dog. The empty
        string is honest — it says "we could not record what was approved" —
        and a later comparison against it must treat it as unknown rather than
        as a mismatch.
        """
        try:
            import graph_read

            conn = graph_read._open(path)
            try:
                nodes = graph_read.read_nodes(conn)
                edges = graph_read.read_edges(conn)
            finally:
                conn.close()
                del conn
            return graph_read.topology_version(nodes, edges)
        except Exception:
            return ""

    def publish(self, graph_id: str, published: bool) -> dict[str, Any]:
        """Record — or withdraw — a person's decision that a graph is ready.

        Withdrawal deletes the marker rather than stamping a second field. A
        graph that comes back for another cut is in exactly the state it was
        in before it was published, and a marker that recorded both would let
        the two disagree.
        """
        path = self.resolve(graph_id)
        if path is None:
            return operator_fault("not_found", f"unknown graph {graph_id!r}")
        if not self._under_output_root(path):
            return operator_fault(
                "invalid",
                "only a graph a construction produced can be published; "
                f"{path.name} was not built under this workspace",
            )
        marker = self._publish_marker(path)
        if published:
            import datetime

            payload = {
                "published_at": datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat(timespec="seconds"),
                # The *shape* the person approved, so a later rebuild can tell
                # that the graph moved underneath its own publication.
                #
                # `graph_version` would be the obvious choice and is the wrong
                # one: it hashes size and mtime, and `compute_structural_index`
                # writes `centrality_score` back on every cold read — so merely
                # listing the catalogue would report the graph as changed.
                # `topology_version` hashes which nodes exist and which edges
                # connect them, which is the question being asked.
                #
                # Nothing reads this yet. It is recorded now because it cannot
                # be recovered afterwards: once a rebuild has run, what was
                # approved is gone.
                "published_topology_version": self._topology_of(path),
            }
            marker.write_text(json.dumps(payload, indent=2) + "\n")
        else:
            marker.unlink(missing_ok=True)
        return {"graph_id": graph_id, "state": self._state(path)}

    @classmethod
    def _walk(cls, root: Path, max_depth: int | None = None) -> list[Path]:
        """Every eligible graph under `root`, bounded and snapshot-free."""
        limit = cls.OUTPUT_SCAN_DEPTH if max_depth is None else max_depth
        found: list[Path] = []
        frontier = [(root, 0)]
        while frontier:
            # Breadth-first, so the SHALLOWEST route to a graph is discovered
            # first. That is the route a person navigates, and it is the one
            # whose directory name they chose — `data/construction_trials/
            # kep-kustomize` rather than the seven-deep run directory it links
            # to, whose last component is `workspace_v1`.
            directory, depth = frontier.pop(0)
            try:
                entries = sorted(directory.iterdir())
            except OSError:
                continue
            for entry in entries:
                if entry.is_dir():
                    # `<graph>.lbug.snapshots/` holds one file per version. They
                    # are history, not graphs to open, and there are hundreds.
                    if (
                        depth >= limit
                        or ".lbug" in entry.name
                        or entry.name in cls.SKIP_DIRS
                    ):
                        continue
                    frontier.append((entry, depth + 1))
                elif cls._eligible(entry):
                    found.append(entry)
        return found

    def _candidates(self) -> list[tuple[Path, str]]:
        """Paths plus their product provenance, de-duplicated by real path."""
        candidates: list[tuple[Path, str]] = []
        if self._eligible(self._db):
            candidates.append((self._db, "current"))
        if self._published.is_dir():
            candidates.extend(
                (p, "published")
                for p in sorted(self._published.glob("*.lbug"))
                if self._eligible(p)
            )
        # Construction outputs are user work, not bundled examples. Preserve
        # that provenance so the product can surface them as a first-class
        # reopening path. Walked before the shallow library dirs so a graph
        # under both is claimed by the tree that built it.
        for root in self._output_roots:
            if root.is_dir():
                candidates.extend((p, "construction") for p in sorted(self._walk(root)))
        # Walked, not globbed. A shallow glob of `data/` found nothing under
        # `data/demo/<set>/`, which is where every demo graph actually lives —
        # so the library the product ships was invisible to the product, and
        # the only way to open one was to know its path and type it. Bounded
        # shallower than an output root: a library is a shelf someone arranged,
        # and a graph three directories down is a run, not a shelf.
        for directory in self._library_dirs:
            if directory.is_dir():
                candidates.extend(
                    (p, "example")
                    for p in self._walk(directory, max_depth=self.LIBRARY_SCAN_DEPTH)
                )
        with self._lock:
            candidates.extend((p, "opened") for p in self._opened if self._eligible(p))

        found: list[tuple[Path, str]] = []
        seen: set[Path] = set()
        for path, source in candidates:
            try:
                key = path.expanduser().resolve()
            except OSError:
                continue
            if key in seen:
                continue
            seen.add(key)
            # Identity is the real path — the same graph reached two ways is one
            # row. The path KEPT is the one it was discovered by, because that
            # is what carries the name: resolving first collapsed every named
            # shelf link onto its target and labelled it from the run directory,
            # so `kep-kustomize` was offered as "Workspace V1" and
            # `cattrs-host-owned` as "Uncertified Preview".
            found.append((path.expanduser(), source))
        return found

    def _records(self) -> list[tuple[str, Path, str]]:
        """Stable opaque ids. A same-stem graph gets a short path hash."""
        candidates = self._candidates()
        stem_counts: dict[str, int] = {}
        for path, _source in candidates:
            stem_counts[path.stem] = stem_counts.get(path.stem, 0) + 1
        records = []
        for path, source in candidates:
            graph_id = path.stem
            if stem_counts[graph_id] > 1:
                suffix = hashlib.sha256(str(path).encode()).hexdigest()[:7]
                graph_id = f"{graph_id}-{suffix}"
            records.append((graph_id, path, source))
        return records

    @staticmethod
    def _label(path: Path) -> str:
        name = path.stem
        if name.startswith("corpus_"):
            name = name[len("corpus_"):]
        # A construction names its workspace and calls the file `graph.lbug`,
        # so the file name carries no information and five distinct trials would
        # all be offered as "Graph". Borrow the directory, which is the name the
        # person actually chose.
        if name == "graph" or name.startswith("graph_"):
            qualifier = name[len("graph"):].strip("_-")
            name = f"{path.parent.name} {qualifier}".strip()
        return name.replace("_", " ").replace("-", " ").strip().title()

    def _summary(self, graph_id: str, path: Path, source: str) -> dict[str, Any]:
        st = path.stat()
        signature = (st.st_mtime_ns, st.st_size)
        row = {
            "id": graph_id,
            "label": self._label(path),
            "is_current": path == self._db.expanduser().resolve(),
            "source": source,
            # Where a graph is in the product, as opposed to how it was found.
            # `source` answers "which shelf did this come off"; `state` answers
            # "has a person said this is ready", and only the second decides
            # which surface it belongs on.
            "state": self._state(path),
            "workspace_name": path.parent.name,
            "size_bytes": st.st_size,
            "modified": st.st_mtime,
            "node_count": None,
            "edge_count": None,
            "read_error": "",
        }
        with self._lock:
            cached = self._summary_cache.get(path)
        if cached is not None and cached[0] == signature:
            row.update(cached[1])
            return row
        try:
            import contextlib

            import graph_read

            # Counting nodes opens the file. For the graph this process owns,
            # that races a confirm; for a library graph nobody here is writing,
            # so it would only queue an unrelated browse behind a commit.
            owned = (self._rw_lock is not None
                     and path == self._db.expanduser().resolve())
            guard = self._rw_lock.read() if owned else contextlib.nullcontext()
            with guard:
                conn = graph_read._open(path)
                try:
                    row["node_count"] = int(
                        conn.execute("MATCH (n:Concept) RETURN count(n)").get_next()[0]
                    )
                    row["edge_count"] = int(sum(
                        conn.execute(f"MATCH ()-[e:{t}]->() RETURN count(e)").get_next()[0]
                        for t in graph_read.REL_TYPES
                    ))
                finally:
                    conn.close()
                    # The connection owns the temporary Database wrapper.
                    # Release it before taking the post-read file signature;
                    # its native destructor is what finalises the read open.
                    del conn

                # Kuzu may touch its database file while opening it, even for a
                # read. Cache the signature it leaves behind, not the one from
                # immediately before the open, or the next list would miss.
                st = path.stat()
                signature = (st.st_mtime_ns, st.st_size)
                row["size_bytes"] = st.st_size
                row["modified"] = st.st_mtime
        except Exception as exc:
            # Keep the file visible, but make the failure inspectable. One bad
            # example must not turn the entire catalogue into a 500.
            row["read_error"] = f"{type(exc).__name__}: {exc}"
        with self._lock:
            self._summary_cache[path] = (
                signature,
                {
                    "node_count": row["node_count"],
                    "edge_count": row["edge_count"],
                    "read_error": row["read_error"],
                },
            )
        return row

    def list(self) -> list[dict[str, Any]]:
        """The catalogue, with counts so the picker can say what a graph *is*.

        Counting opens each database, which is why it is a count query and not a
        map read: the size on disk tells the operator nothing about whether a
        graph is worth opening, and "14 nodes" does.
        """
        rows = []
        for graph_id, path, source in self._records():
            try:
                rows.append(self._summary(graph_id, path, source))
            except Exception:
                # The candidate may have disappeared between discovery and
                # stat. Treat it as gone; other graphs remain usable.
                continue
        return rows

    def resolve(self, graph_id: str | None) -> Path | None:
        """id → path, or None. Never interprets the id as a path."""
        if not graph_id:
            return self._db if self._db.exists() else None
        for candidate_id, path, _source in self._records():
            if candidate_id == graph_id:
                return path
        return None

    def browse(self, raw_path: str = "") -> dict[str, Any]:
        """One directory listing, for choosing a graph by looking for it.

        The browser cannot do this itself. A native file dialog hands JavaScript
        a `File`, never a path — deliberately, and `C:\\fakepath` is what you get
        if you ask. The operator's host and their browser are the same machine
        here, but the browser has no way to say so, and the server needs a real
        path to open a graph. So the listing has to come from the side that can
        actually see the disk.

        This grants nothing. `open_path` already accepts any path the operator
        types, so every file named here was already openable; what changes is
        that they no longer have to have memorised where it is. Directories are
        listed so they can be walked, not opened, and only `.lbug` files are
        offered as graphs.
        """
        raw = str(raw_path or "").strip()
        try:
            base = (
                Path(raw).expanduser().resolve()
                if raw
                else self._db.expanduser().resolve().parent
            )
        except OSError as exc:
            return operator_fault("invalid", f"Could not resolve that path: {exc}")
        if base.is_file():
            base = base.parent
        if not base.is_dir():
            return operator_fault("not_found", f"No directory at {base}")

        directories: list[dict[str, Any]] = []
        graphs: list[dict[str, Any]] = []
        try:
            entries = sorted(base.iterdir(), key=lambda p: p.name.lower())
        except PermissionError:
            return operator_fault("unavailable", f"Not allowed to read {base}")
        except OSError as exc:
            return operator_fault("unavailable", f"Could not read {base}: {exc}")
        for entry in entries:
            try:
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    # Snapshot sidecars are version history, one file per
                    # version. Walking into one is never what someone means.
                    if ".lbug" in entry.name:
                        continue
                    directories.append({"name": entry.name, "path": str(entry)})
                elif self._eligible(entry):
                    stat = entry.stat()
                    graphs.append({
                        "name": entry.name,
                        "path": str(entry),
                        "size_bytes": stat.st_size,
                        "modified": stat.st_mtime,
                    })
            except OSError:
                continue

        parent = str(base.parent) if base.parent != base else ""
        return {
            "path": str(base),
            "parent": parent,
            "directories": directories,
            "graphs": graphs,
        }

    def open_path(self, raw_path: str) -> dict[str, Any]:
        """Validate and register a graph chosen by the local human.

        This does not call ``chdir``: process-global cwd would make concurrent
        jobs race. The graph's parent is instead the workspace directory
        associated with this document, matching modern IDE workspace models.
        """
        raw = str(raw_path or "").strip()
        if not raw:
            return operator_fault("invalid", "Choose a .lbug graph file.")
        try:
            path = Path(raw).expanduser().resolve()
        except OSError as exc:
            return operator_fault("invalid", f"Could not resolve that path: {exc}")
        if not self._eligible(path):
            return operator_fault(
                "invalid", "Open requires an existing certified .lbug file."
            )

        # A file with the right suffix is not necessarily a graph. Open and
        # perform the cheapest schema read before admitting it to the catalogue.
        try:
            import contextlib

            import graph_read

            # Counting nodes opens the file. For the graph this process owns,
            # that races a confirm; for a library graph nobody here is writing,
            # so it would only queue an unrelated browse behind a commit.
            owned = (self._rw_lock is not None
                     and path == self._db.expanduser().resolve())
            guard = self._rw_lock.read() if owned else contextlib.nullcontext()
            with guard:
                conn = graph_read._open(path)
            try:
                conn.execute("MATCH (n:Concept) RETURN count(n)").get_next()
            finally:
                conn.close()
        except Exception as exc:
            return operator_fault(
                "invalid",
                f"That file is not a readable graph: {type(exc).__name__}",
            )

        with self._lock:
            if path not in self._opened:
                self._opened.append(path)
        record = next(
            (r for r in self._records() if r[1] == path),
            None,
        )
        if record is None:
            return operator_fault(
                "unavailable", "The graph disappeared while it was opening."
            )
        graph_id, admitted, source = record
        return {
            "graph": self._summary(graph_id, admitted, source),
            "workspace": {
                "name": admitted.parent.name,
                "directory": str(admitted.parent),
            },
        }

    def activate(self, graph_id: str) -> dict[str, Any]:
        """Make a catalogue document the process-owned workspace graph.

        The owner callback performs the guarded Surface/Operator swap first.
        The catalogue only changes ``current`` after that succeeds.
        """
        path = self.resolve(str(graph_id or ""))
        if path is None:
            return operator_fault("not_found", "unknown graph")
        if self._on_activate is not None:
            result = self._on_activate(path)
            if result.get("error"):
                return result
        with self._lock:
            self._db = path
        record = next((r for r in self._records() if r[1] == path.resolve()), None)
        if record is None:
            return operator_fault(
                "unavailable", "The graph disappeared while it was activating."
            )
        active_id, active_path, source = record
        return {
            "graph": self._summary(active_id, active_path, source),
            "workspace": {
                "name": active_path.parent.name,
                "directory": str(active_path.parent),
            },
        }


def _overlay_for(db_path: Path, result: dict[str, Any]) -> dict[str, Any]:
    """Project a discover result onto the map as an ids-and-roles overlay.

    Best-effort: a map that cannot be read costs the overlay, not the answer.
    """
    try:
        import graph_overlay
        import graph_read

        conn = graph_read._open(db_path)
        try:
            node_ids = {n["id"] for n in graph_read.read_nodes(conn)}
            edges = graph_read.read_edges(conn)
        finally:
            conn.close()
        claim = result.get("claim") or {}
        primary = ""
        if isinstance(claim, dict):
            primary = str(claim.get("primary_content") or "")
        verdict = str(result.get("verdict") or "").upper()
        # Confirmed turns light what the sentence stood on. A miss still
        # lights the retrieved set — that is where it looked.
        claim_text = (
            primary if verdict in {"CONFIRMED", "ALTERNATIVE"} else ""
        )
        return graph_overlay.evidence_overlay(
            result.get("evidence"),
            edges,
            result.get("gaps") or [],
            node_ids,
            claim_text=claim_text,
        )
    except Exception:
        return {}


def graph_routes(catalogue: GraphCatalogue, *, current_surface: Any | None = None,
                 rw_lock: Any | None = None) -> list:
    """The `/graph` route table (mounted under a `/graph` prefix).

    `rw_lock` is the single-owner lock shared with the MCP and operator planes.
    The canvas opens the same `.lbug` a confirm rewrites, so a map refresh timed
    against a commit could read a half-applied write. The catalogue's own
    `RLock` does not help: it serialises the catalogue's bookkeeping and knows
    nothing about the operator plane.
    """
    import contextlib

    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from mcp_server.fault import is_fault_payload, json_result, operator_fault

    import graph_read

    owned = None
    if current_surface is not None:
        try:
            owned = Path(getattr(current_surface, "_db_path", "")).resolve()
        except (TypeError, OSError):
            owned = None

    @contextlib.contextmanager
    def _guard(path: Path):
        """Hold the read side only for the graph this process actually owns.

        A library graph is not being written by anyone here, and taking the
        write-preferring read side for it would let an unrelated browse queue
        behind a confirm on a different file.
        """
        if rw_lock is None or owned is None or path.resolve() != owned:
            yield
            return
        with rw_lock.read():
            yield

    async def graphs(request):
        return JSONResponse({"graphs": catalogue.list()})

    async def browse_graphs(request):
        result = catalogue.browse(request.query_params.get("path", ""))
        return json_result(result)

    async def open_graph(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        result = catalogue.open_path(str(body.get("path", "")) if isinstance(body, dict) else "")
        return json_result(result)

    async def activate_graph(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        result = catalogue.activate(
            str(body.get("graph_id", "")) if isinstance(body, dict) else ""
        )
        return json_result(result)

    async def publish_graph(request):
        """The one write on this plane, and it writes no graph.

        Publication is a human act with no agent equivalent — an agent that
        could mark its own output ready would be ratifying its own work — so
        it is a route the browser calls and the MCP surface does not have.
        """
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        result = catalogue.publish(
            str(body.get("graph_id", "")),
            body.get("published") is not False,
        )
        return json_result(result)

    async def graph_map(request):
        path = catalogue.resolve(request.query_params.get("graph"))
        if path is None:
            return json_result(operator_fault("not_found", "unknown graph"))
        # An unknown lens falls back to canonical rather than 400ing: a stale
        # bookmark should not cost the operator their map.
        with _guard(path):
            result = graph_read.read_map(path, request.query_params.get("lens"))
        if is_fault_payload(result):
            return json_result(result)
        result["graph_id"] = path.stem
        return JSONResponse(result)

    async def graph_node(request):
        """Late payload for the node reader — one body, never the full map."""
        path = catalogue.resolve(request.query_params.get("graph"))
        if path is None:
            return json_result(operator_fault("not_found", "unknown graph"))
        node_id = request.query_params.get("id") or ""
        with _guard(path):
            result = graph_read.read_node(path, node_id)
        if is_fault_payload(result):
            if result.get("error") == "missing node id":
                result = operator_fault("invalid", result["error"])
            return json_result(result)
        return JSONResponse(result)

    def _surface_call(path: Path, method: str, *args, **kwargs):
        """Call one authority-free query verb on the selected graph.

        The process-owned graph reuses its coordinated Surface (and therefore
        its shared read lock and caches). Library graphs get a short-lived
        read-only Surface. This keeps the browser plane contract-equivalent to
        MCP without giving it proposal or commit capabilities.
        """
        from mcp_server.surface import Surface

        reuse = (
            current_surface is not None
            and Path(getattr(current_surface, "_db_path", "")).resolve()
            == path.resolve()
        )
        surface = current_surface if reuse else Surface(path)
        try:
            return getattr(surface, method)(*args, **kwargs)
        finally:
            if not reuse:
                surface.close()

    async def orient(request):
        path = catalogue.resolve(request.query_params.get("graph"))
        if path is None:
            return json_result(operator_fault("not_found", "unknown graph"))
        context = str(request.query_params.get("context") or "graph_card")
        try:
            from starlette.concurrency import run_in_threadpool

            return JSONResponse(
                await run_in_threadpool(_surface_call, path, "orient", context)
            )
        except Exception as exc:
            return json_result(
                operator_fault(
                    "unavailable", f"orient failed: {type(exc).__name__}: {exc}"
                )
            )

    async def run_traversal(request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        name = str(body.get("name") or "").strip()
        parameters = body.get("parameters") or {}
        if not name:
            return json_result(
                operator_fault("invalid", "Choose a named traversal first.")
            )
        if not isinstance(parameters, dict):
            return json_result(
                operator_fault("invalid", "Traversal parameters must be an object.")
            )
        path = catalogue.resolve(str(body.get("graph_id") or "") or None)
        if path is None:
            return json_result(operator_fault("not_found", "unknown graph"))

        def run_recipe():
            return _surface_call(
                path,
                "run_traversal",
                name,
                parameters,
                version=body.get("version"),
                evidence="packet",
                graph_version=str(body.get("graph_version") or ""),
                explain=bool(body.get("explain", False)),
            )

        try:
            from starlette.concurrency import run_in_threadpool

            result = await run_in_threadpool(run_recipe)
            if isinstance(result, dict):
                result["overlay"] = await run_in_threadpool(
                    _overlay_for, path, result
                )
            return JSONResponse(result)
        except Exception as exc:
            return json_result(
                operator_fault(
                    "unavailable",
                    f"named traversal failed: {type(exc).__name__}: {exc}",
                )
            )

    async def graph_sources(request):
        """Resolve a node's source units, or the whole coverage picture.

        `?id=<node>` returns the passages that node was built from.
        No `id` returns the coverage view: every source unit in document order
        with whether it produced a node.

        A graph without a sidecar answers `available: false` rather than an
        empty list. "This graph cannot show its sources" and "this graph's
        sources produced nothing" are opposite facts and an empty list says
        the wrong one.
        """
        from source_pipeline.sources_sidecar import Sources

        path = catalogue.resolve(request.query_params.get("graph"))
        if path is None:
            return json_result(operator_fault("not_found", "unknown graph"))

        sources = Sources.for_graph(path)
        if sources is None:
            return JSONResponse({
                "available": False,
                "reason": (
                    "no sources sidecar beside this graph; it was built before "
                    "sidecars, or by a path that does not write one"
                ),
                "units": [],
            })

        node_id = (request.query_params.get("id") or "").strip()
        if node_id:
            with _guard(path):
                node = graph_read.read_node(path, node_id)
            if is_fault_payload(node) or node.get("error"):
                return json_result(operator_fault("not_found", "unknown node"))
            cited = node.get("source_unit_ids") or []
            resolved = sources.resolve_all(cited)
            return JSONResponse({
                "available": True,
                "graph_id": path.stem,
                "node_id": node_id,
                "cited_unit_ids": list(cited),
                "units": [u.to_json() for u in resolved],
                # A node can cite a unit this sidecar does not carry -- a
                # different run, a hand-edited node. Name them rather than
                # returning a short list that looks complete.
                "unresolved_unit_ids": [
                    c for c in cited if sources.resolve(c) is None
                ],
            })

        with _guard(path):
            conn = graph_read._open(path)
            try:
                nodes = graph_read.read_nodes(conn)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        producers: dict[str, list[str]] = {}
        for node in nodes:
            for unit in node.get("source_unit_ids") or []:
                producers.setdefault(str(unit), []).append(node["id"])
        cited = set(producers)
        # Document order, which is the order atoms were written. A *run* of
        # uncovered units is a skipped section; sorting destroys the only
        # thing that distinguishes that from scattered misses.
        rows = []
        for unit_id in sources.unit_ids_in_order():
            unit = sources.resolve(unit_id)
            rows.append({
                "unit_id": unit_id,
                "locator": unit.locator if unit else "",
                "heading_path": list(unit.heading_path) if unit else [],
                "excerpt": (unit.excerpt[:280] if unit else ""),
                "node_ids": producers.get(unit_id, []),
                "produced": unit_id in cited,
                # `atoms coverage` has always separated these two, and a view
                # that does not is misleading in both directions: a hundred
                # ignored page footers bury the one long passage that is a
                # real miss, and boilerplate that *did* produce a node is how
                # a translator's name ends up as a character.
                "chrome": bool(unit.chrome) if unit else False,
                "chars": (unit.chars if unit else 0),
            })
        missed = [r for r in rows if not r["produced"] and not r["chrome"]]
        return JSONResponse({
            "available": True,
            "graph_id": path.stem,
            "source_fingerprint": sources.source_fingerprint,
            "unit_count": len(rows),
            "produced_count": sum(1 for r in rows if r["produced"]),
            #: Substantive misses only -- chrome excluded, largest first.
            #: Document order is kept in `units` because a *run* of misses is
            #: a skipped section; size order answers the other question.
            "missed_by_size": [r["unit_id"] for r in
                               sorted(missed, key=lambda r: -r["chars"])][:20],
            "missed_chars": sum(r["chars"] for r in missed),
            #: Boilerplate that produced nodes anyway.
            "chrome_that_produced": [r["unit_id"] for r in rows
                                     if r["chrome"] and r["produced"]],
            "units": rows,
        })

    return [
        Route("/graphs", graphs, methods=["GET"]),
        Route("/browse", browse_graphs, methods=["GET"]),
        Route("/open", open_graph, methods=["POST"]),
        Route("/activate", activate_graph, methods=["POST"]),
        Route("/publish", publish_graph, methods=["POST"]),
        Route("/map", graph_map, methods=["GET"]),
        Route("/node", graph_node, methods=["GET"]),
        Route("/sources", graph_sources, methods=["GET"]),
        Route("/orient", orient, methods=["GET"]),
        Route("/run-traversal", run_traversal, methods=["POST"]),
    ]
