"""MCP tool surface — thin projection over engine seams.

Contract: ``design [new]/mcp-contract-v0.md``. Verbs implemented here (M2):
``orient``, ``discover``, ``what_governs``, ``check_conformance``, ``escalate``.
``propose`` and ``history`` are deliberately absent (M3/M4+; the reversal's
admission checklist gates ``propose``).

Design commitments enforced in code, not documentation:
- Three verdict spaces disjoint per tool; discovery returns carry no
  governance fields (Package-2 leak → stripped, always).
- Caller may reason, never rule: evidence mode omits adjudication fields.
- Honest failure: engine faults surface as ``engine_degraded`` +
  ``degradation_flags``; unknown engine verdict strings map to the space's
  honest-failure member AND set ``engine_degraded`` (never a new enum member
  on the wire); empty graph is a typed refusal, never an auto-seeded corpus.
- No ``text_content`` in evidence returns (late paging is load-bearing).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any

MCP_CONTRACT_VERSION = "mcp-v0"

# Closed vocabularies (contract §0.3)
CONFIRMATION_SPACE = {"CONFIRMED", "ALTERNATIVE", "EXHAUSTED", "ILL_POSED", "UNKNOWN_TO_GRAPH"}
COVERAGE_SPACE = {"GOVERNED", "PARTIALLY_GOVERNED", "UNGOVERNED", "ABSENT"}
RULING_SPACE = {"CONFORMS", "VIOLATES", "UNGOVERNED", "INSUFFICIENT_EVIDENCE"}

# Fields that must never appear on a discovery (confirmation-space) return.
GOVERNANCE_FIELDS = {
    "governance_verdict",
    "conformance_ruling",
    "status",
    "kind",
    "ungoverned_predicate",
}

# Grain caps — `orient` stays a cheap, zero-LLM call.
GRAIN_EXEMPLAR_CAP = 6
GRAIN_TEXT_CAP = 1200

# Evidence caps (contract §3)
NODE_RECORD_CAP = 50
EDGE_RECORD_CAP = 100
CONTENT_TEXT_CAP = 120_000

# Neutral governance frame (domain frames may override via config).
DEFAULT_GOV_FRAME = (
    "Resolve strictly per the encoded policy graph, and say so explicitly "
    "if no policy governs it:\n{q}"
)

DEFAULT_QUERY_TIMEOUT_S = 150  # Path C tail budget (contract §1)


def _trace_id() -> str:
    return uuid.uuid4().hex[:16]


def _cypher_value(value: Any) -> Any:
    """Make one Cypher cell JSON-safe without hiding what it was.

    Node and rel values arrive as dicts holding an internal ``_id`` and, for a
    Concept, a 3072-float embedding. Neither is useful to a reader and the
    embedding alone would blow any character budget, so they are dropped and
    the drop is visible in the key set.
    """
    if isinstance(value, dict):
        return {
            key: _cypher_value(item)
            for key, item in value.items()
            if key not in {"_id", "_src", "_dst", "embedding"}
        }
    if isinstance(value, (list, tuple)):
        return [_cypher_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class Surface:
    """One server surface = one GraphSession + one WritePathStore."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        store_path: Path | str | None = None,
        handbook: str | None = None,
        repo_root: Path | str | None = None,
        graph_contract_path: Path | str | None = None,
        gov_frame: str = DEFAULT_GOV_FRAME,
        timeout_s: int = DEFAULT_QUERY_TIMEOUT_S,
        capabilities: tuple[str, ...] = ("query",),
        enable_history: bool = False,
        enable_proposals: bool = False,
        write_policy: Any | None = None,
        rw_lock: Any | None = None,
        gate_provider: Any | None = None,
    ) -> None:
        from engine import GraphSession

        self._db_path = Path(db_path)
        self._store_path = Path(store_path) if store_path else self._db_path.with_suffix(".writestore.sqlite")
        self._handbook = handbook
        self._repo_root = Path(repo_root) if repo_root else None
        from mcp_server.graph_contract import resolve_graph_contract_path

        self._graph_contract_path = resolve_graph_contract_path(
            self._db_path,
            repo_root=self._repo_root,
            explicit_path=graph_contract_path,
        )
        self._graph_contract_explicit = bool(
            graph_contract_path is not None or os.environ.get("SST_GRAPH_CONTRACT")
        )
        self._workbook_traversals_path = Path(str(self._db_path) + ".traversals.json")
        self._gov_frame = gov_frame
        self._timeout_s = timeout_s
        self._capabilities = list(capabilities)
        # The configured gate battery, for the preflight only. It grants no
        # authority here: a preflight gates a throwaway copy, and the read plane
        # still cannot commit anything (see `_gate_preflight`).
        self._gate_provider = gate_provider
        self._invoke_lock = threading.RLock()  # single-owner DB: serialize invokes
        # Per-thread nesting depth for `_read_guard` (see its docstring).
        self._read_depth = threading.local()
        #: (artifact_hash, rule_id, as_of) -> (graph_version, verdict payload).
        #: Makes re-asking a decided question a no-op instead of a second roll
        #: of the dice — see `_recall_verdict`.
        self._verdict_memo: dict[tuple[str, str, str], tuple[str, dict[str, Any]]] = {}
        #: named-traversal results keyed by graph/format/recipe/parameter/evidence.
        self._traversal_cache: dict[str, dict[str, Any]] = {}
        # Shared read side of the single-owner RW lock (B13): when set, an
        # operator confirm on the write side excludes in-flight invokes.
        self._rw_lock = rw_lock

        self._session = GraphSession().open(self._db_path, auto_seed=False)
        self._graph = None  # built lazily (imports LLM client modules)
        self._adapter = None
        self._store = None

        self._snapshots = None
        if enable_history:
            from mcp_server.history import SnapshotStore

            self._snapshots = SnapshotStore(self._db_path)
            # Baseline: every version the server has served is diffable later.
            self._snapshots.capture(self._session.graph_version or self._session.refresh_version())
            if "history" not in self._capabilities:
                self._capabilities.append("history")

        self._proposals_enabled = bool(enable_proposals)
        self._write_policy = write_policy
        if self._proposals_enabled and "propose" not in self._capabilities:
            self._capabilities.append("propose")

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _base(self) -> dict[str, Any]:
        # graph_version is cached per session as an optimisation: it is a
        # content hash over every concept and edge, so recomputing it per call
        # would rescan the graph for a value that only writes can change.
        # Refresh happens at open and after swaps/encodes. It was cached for a
        # different reason — the hash was mtime-based and LadybugDB touches the
        # file on open — which stopped the churn inside a run and hid it across
        # restarts.
        gv = self._session.graph_version or self._session.refresh_version()
        return {
            "contract_version": MCP_CONTRACT_VERSION,
            "graph_version": gv,
            "trace_id": _trace_id(),
        }

    def _get_adapter(self):
        """Engine adjudication is withdrawn. This is a seam, not a path.

        It used to build the old LangGraph FSM and hand it to `EngineAdapter`,
        which is the only reason `legacy_fsm/` was reachable from the product
        at all. Nothing served ever called it: `what_governs` defaults to host
        adjudication and `check_conformance` rules on a named rule with a
        direct model call, neither of which comes through here.

        The method survives because three test files replace it to drive the
        verdict-projection code around it. Those tests never wanted the
        engine -- they wanted this attribute. Raising rather than deleting
        keeps that seam honest: a caller who has not replaced it is told the
        path is gone instead of getting an AttributeError that reads like a
        bug.
        """
        raise NotImplementedError(
            "engine adjudication was withdrawn with legacy_fsm/. Use "
            "what_governs(adjudicate='host'), or check_conformance(rule_id=...) "
            "which adjudicates a named rule directly."
        )

    def _repin(self):
        """Point process graph state back at THIS surface's graph.

        `engine` keeps the connection, structural index, compass, grain and
        source-unit index in module globals, and `GraphSession`'s properties are
        live views of them — every "session" is the same session. So constructing
        a second `Surface` silently redirected every existing one to the newest
        graph, and the redirected surface kept answering, well-formed, from the
        wrong graph. It was found by an ablation whose node-graph questions came
        back citing OWNERS rules; nothing in the payload said anything was wrong.

        Re-pinning here makes sequential multi-graph use correct, which is what a
        test suite, a batch harness and an operator switching workspaces all do.
        It does not make concurrent multi-graph use safe, and cannot: LadybugDB
        is single-owner and `GraphSession` documents that. Only an actual switch
        pays the reopen, and the structural index is read from its sidecar cache.
        """
        try:
            import engine

            current = getattr(engine, "_db_path", None)
            if current is not None and Path(current).resolve() == self._db_path.resolve():
                return
            self._session.open(self._db_path)
            self._adapter = None    # bound to the graph it was built against
        except Exception:
            # A surface that cannot re-pin is no worse off than before this
            # existed; let the operation proceed and fail with its own error.
            pass

    @contextlib.contextmanager
    def _read_guard(self):
        """The read side of the single-owner lock, for anything touching the DB.

        Every path that opens the graph takes this — not only the engine invoke.
        `orient` is zero-LLM and cheap, which is why it was missed: it does not
        look like a query, but it reads the same file a confirm rewrites. Of the
        three verbs, only `discover` was covered; `what_governs` and
        `check_conformance` reach the same file through `EngineAdapter`.

        **Re-entrant per thread.** The shared lock is writer-preferring, so a
        thread holding the read side that asks for it again while a writer is
        queued waits for that writer, which is waiting for the reader it already
        is. Verbs compose — a conformance ruling adjudicates node by node — so
        nesting is reachable, and the failure is a hung server rather than a
        wrong answer. Only the outermost guard touches the lock.

        Falls back to the process-local invoke lock when no shared lock has been
        installed, so a Surface constructed outside the HTTP wiring still
        serialises against itself.
        """
        if getattr(self._read_depth, "value", 0):
            yield                      # already inside; the outer guard holds it
            return
        self._repin()
        self._read_depth.value = 1
        try:
            ctx = (self._rw_lock.read() if self._rw_lock is not None
                   else self._invoke_lock)
            with ctx:
                yield
        finally:
            self._read_depth.value = 0

    @contextlib.contextmanager
    def _write_guard(self):
        """The exclusive side, for the read plane's one write path.

        `propose(claim_level="L1")` on an admitted policy closes the session,
        mutates the `.lbug` and reopens it. Unguarded, a concurrent reader is
        not merely reading stale data — it holds a connection that is closed
        underneath it.

        Never taken while a read guard is held on this thread: the lock is
        writer-preferring and does not upgrade, so that would be a self-
        deadlock. Asserted rather than hoped for.
        """
        assert not getattr(self._read_depth, "value", 0), (
            "write guard requested while this thread holds the read side; "
            "the lock does not upgrade")
        if self._rw_lock is None:
            with self._invoke_lock:
                yield
            return
        with self._rw_lock.write():
            yield

    def _get_store(self):
        if self._store is None:
            from interaction.write_path_store import WritePathStore

            self._store = WritePathStore(self._store_path)
        return self._store

    def _project_agent_response(self, state: dict[str, Any]) -> dict[str, Any]:
        """AgentResponse projection + unknown-verdict honesty (contract §4)."""
        from contract import build_agent_response

        base = self._base()
        raw = str(
            (state.get("deterministic_verdict") or {}).get("kind")
            or (state.get("confirmation_response") or {}).get("verdict")
            or ""
        ).strip().upper()

        resp = build_agent_response(state, graph_version=base["graph_version"], trace_id=base["trace_id"])
        out = resp.model_dump(mode="json")

        if raw and raw not in CONFIRMATION_SPACE:
            # Engine emitted an out-of-vocabulary verdict: the normaliser maps it
            # to EXHAUSTED silently; the wire must not — flag the degradation.
            flags = list(out.get("degradation_flags") or [])
            flags.append(f"engine_fault:unknown_verdict:{raw[:40]}")
            out["degradation_flags"] = flags
            out["engine_degraded"] = True
            self._record_fault("discover:unknown_verdict", flags)

        out["agent_contract_version"] = str(out.get("contract_version", ""))
        out["contract_version"] = MCP_CONTRACT_VERSION
        return out

    def _project_evidence(self, state: dict[str, Any], mode: str) -> dict[str, Any] | None:
        packet = state.get("evidence_packet") or {}
        if mode == "none" or not isinstance(packet, dict):
            return None
        node_records = list(packet.get("node_records") or [])
        edge_records = list(packet.get("edge_records") or [])
        if mode == "summary":
            return {
                "node_count": len(node_records),
                "edge_count": len(edge_records),
                "path_count": len(packet.get("path_records") or []),
                "node_ids": [n.get("id") for n in node_records][:NODE_RECORD_CAP],
                "packet_provenance": packet.get("packet_provenance") or [],
                "degradation_flags": packet.get("degradation_flags") or [],
            }
        # mode == "packet": records without text_content, depth-capped.
        truncated = len(node_records) > NODE_RECORD_CAP or len(edge_records) > EDGE_RECORD_CAP
        return {
            "node_records": [
                {k: v for k, v in n.items() if k != "text_content"}
                for n in node_records[:NODE_RECORD_CAP]
            ],
            "edge_records": edge_records[:EDGE_RECORD_CAP],
            "path_records": packet.get("path_records") or [],  # legally empty even on Path C
            "structural_facts": packet.get("structural_facts") or [],
            "packet_provenance": packet.get("packet_provenance") or [],
            "append_log": packet.get("append_log") or [],
            "degradation_flags": packet.get("degradation_flags") or [],
            "truncated": truncated,
        }

    def _compass_ref(self) -> str:
        """Content identity for planning context, distinct from graph version."""
        compass = self._session.compass
        payload = compass.to_dict() if hasattr(compass, "to_dict") else (compass or {})
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]

    def _project_direct_evidence(self, packet: dict[str, Any], mode: str) -> dict[str, Any]:
        """Project traversal and page bodies only when the caller requests them."""
        projected = self._project_evidence(
            {"evidence_packet": packet},
            "summary" if mode == "summary" else "packet",
        ) or {}
        if mode != "content":
            return projected

        from tools import get_node_payloads

        ids = [
            str(node.get("id") or "")
            for node in list(packet.get("node_records") or [])[:NODE_RECORD_CAP]
            if isinstance(node, dict) and node.get("id")
        ]
        payloads = get_node_payloads(self._session.connection, ids)
        remaining = CONTENT_TEXT_CAP
        bodies: list[dict[str, Any]] = []
        text_truncated = False
        for node_id in ids:
            payload = dict(payloads.get(node_id) or {})
            if not payload:
                continue
            body = str(payload.get("text_content") or "")
            if len(body) > remaining:
                body = body[:remaining]
                text_truncated = True
            payload["text_content"] = body
            bodies.append(payload)
            remaining -= len(body)
            if remaining <= 0:
                text_truncated = len(bodies) < len(payloads) or text_truncated
                break
        projected["node_payloads"] = bodies
        projected["content_truncated"] = text_truncated
        projected["content_char_count"] = CONTENT_TEXT_CAP - remaining
        return projected

    def _apply_recipe_project(
        self,
        projected: dict[str, Any],
        packet: dict[str, Any],
        project: dict[str, Any],
        evidence: str,
    ) -> dict[str, Any]:
        """Thin a traversal packet to the recipe's declared output schema."""
        spec = dict(project or {})
        if not spec:
            return projected
        nodes_mode = str(spec.get("nodes") or "summary").strip().lower()
        edges_mode = str(spec.get("edges") or "full").strip().lower()
        paths_mode = str(spec.get("paths") or "full").strip().lower()
        content_mode = str(spec.get("content") or "none").strip().lower()
        facts_mode = str(spec.get("structural_facts") or "full").strip().lower()

        if nodes_mode == "ids" and "node_records" in projected:
            projected["node_records"] = [
                {"id": str(row.get("id") or "")}
                for row in projected.get("node_records") or []
                if isinstance(row, dict) and row.get("id")
            ]
        elif nodes_mode == "ids" and "node_ids" in projected:
            projected["node_ids"] = [
                str(node_id)
                for node_id in projected.get("node_ids") or []
                if str(node_id)
            ]

        if edges_mode == "none":
            if "edge_records" in projected:
                projected["edge_records"] = []
            if "edge_count" in projected:
                projected["edge_count"] = 0
        if paths_mode == "none":
            if "path_records" in projected:
                projected["path_records"] = []
            if "path_count" in projected:
                projected["path_count"] = 0
        if facts_mode == "none":
            projected["structural_facts"] = []

        if evidence == "content":
            bodies = list(projected.get("node_payloads") or [])
            if content_mode == "none":
                projected["node_payloads"] = []
                projected["content_char_count"] = 0
            elif content_mode == "terminal_only":
                edges = list(projected.get("edge_records") or packet.get("edge_records") or [])
                outgoing = {
                    str(edge.get("source_id") or edge.get("source") or "")
                    for edge in edges
                    if isinstance(edge, dict)
                }
                records = list(
                    projected.get("node_records") or packet.get("node_records") or []
                )
                terminals = {
                    str(row.get("id") or "")
                    for row in records
                    if isinstance(row, dict)
                    and row.get("id")
                    and str(row.get("id") or "") not in outgoing
                }
                projected["node_payloads"] = [
                    row
                    for row in bodies
                    if isinstance(row, dict) and str(row.get("id") or "") in terminals
                ]
        return projected

    # ------------------------------------------------------------------
    # verbs (contract §2)
    # ------------------------------------------------------------------

    def orient(self, context: str = "graph_card") -> dict[str, Any]:
        """§2.1 — zero LLM."""
        from engine import describe_graph

        out = self._base()
        with self._read_guard():
            desc = describe_graph(
                self._session.connection,
                self._session.structural_index,
                self._session.compass,
                graph_id=self._db_path.stem,
            )
        desc.pop("capabilities", None)
        # describe_graph computes a fresh mtime-hash graph_version; the wire
        # carries the session's cached version (stable per open) — same
        # authority rule as contract_version above.
        desc.pop("graph_version", None)
        if context not in {"capabilities", "graph_card", "full_map"}:
            context = "graph_card"
        if context != "full_map":
            desc.pop("node_centrality", None)
            desc.pop("centrality_score_meaning", None)
        if context == "capabilities":
            desc.pop("landmark_preview", None)
        agent_cv = desc.pop("contract_version", None)
        out.update(desc)
        if agent_cv is not None:
            out["agent_contract_version"] = str(agent_cv)
        out["capabilities"] = list(self._capabilities)  # propose absent until admission
        # What the operator INTENDS, beside what the agent MAY do. Capabilities
        # are authority; posture is instruction. Announced here so an agent does
        # not have to discover the operator's policy by being refused.
        out["posture"] = self._posture()
        # What a node IS here. Agents are asked to encode in a house style they
        # previously had no way to read: the exemplars are the constitutional
        # reference for grain, they carry the same {id, label, text_content}
        # shape a proposal's concepts take, and they were visible only to
        # construction. An agent drafting a proposal is doing the same job as
        # the constructor and needs the same reference.
        out["grain"] = self._grain()
        from retrieval_program import retrieval_capability_card

        out["retrieval"] = retrieval_capability_card()
        out["graph_contract"] = self._graph_contract_block(include_markdown=False)
        out["named_traversal"] = self._named_traversal_card()
        out["compass_ref"] = self._compass_ref()
        out["context_view"] = context
        out["context_views"] = ["capabilities", "graph_card", "full_map"]
        return out

    def contract(self, *, include_markdown: bool = True) -> dict[str, Any]:
        """Return the active user-owned ``graph.md`` semantic contract."""
        out = self._base()
        out.update(self._graph_contract_block(include_markdown=include_markdown))
        out["kind"] = "GRAPH_CONTRACT"
        return out

    def _graph_contract_block(self, *, include_markdown: bool) -> dict[str, Any]:
        from mcp_server.graph_contract import GraphContractError
        from source_pipeline.traversals import WorkbookTraversalError

        try:
            document = self._load_traversal_document()
        except (GraphContractError, WorkbookTraversalError, FileNotFoundError, ValueError) as exc:
            if (
                not self._graph_contract_path.exists()
                and not self._workbook_traversals_path.exists()
            ):
                return {
                    "available": False,
                    "outcome": "ABSENT",
                    "path": str(self._workbook_traversals_path),
                    "reason": "no_graph_md",
                }
            return {
                "available": False,
                "outcome": "INVALID_CONTRACT",
                "path": str(self._workbook_traversals_path or self._graph_contract_path),
                "error": str(exc),
            }
        return {
            "available": True,
            "outcome": "FOUND",
            **document.wire(include_markdown=include_markdown),
        }

    def _named_traversal_card(self) -> dict[str, Any]:
        from mcp_server.graph_contract import (
            GraphContractError,
            load_graph_contract,
            named_traversal_card,
        )

        try:
            document = self._load_traversal_document()
            card = named_traversal_card(document)
            if document.path.endswith(".traversals.json"):
                card["opening"] = (
                    "this graph carries workbook-owned named traversal programs; "
                    "use one when it matches the job, otherwise use primitives"
                )
                card["source"] = "workbook"
            return card
        except (GraphContractError, ValueError):
            return named_traversal_card(None)

    def _load_traversal_document(self):
        """Load workbook programs first, unless a graph contract was explicit."""
        from mcp_server.graph_contract import load_graph_contract
        from source_pipeline.traversals import load_bound_workbook_traversals

        if self._graph_contract_explicit and self._graph_contract_path.exists():
            return load_graph_contract(self._graph_contract_path)
        if self._workbook_traversals_path.exists():
            expected = ""
            metadata_path = Path(str(self._db_path) + ".metadata.json")
            if metadata_path.exists():
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                expected = str(metadata.get("encoding_sha256") or "")
            return load_bound_workbook_traversals(
                self._workbook_traversals_path,
                expected_encoding_sha256=expected,
            )
        return load_graph_contract(self._graph_contract_path)

    def _grain(self) -> dict[str, Any]:
        """Grain exemplars from the `.grain.json` sidecar beside the graph.

        Returned whole while the set is small — it usually is, and inventing a
        second fetch for a file of three short nodes would cost more than it
        saves. Past the cap the texts are trimmed and `truncated` says so, so an
        agent is never silently shown a partial template as if it were the
        whole reference.

        **Always returns a block, including when there is no reference.** Most
        graphs have no sidecar — only construction writes one — and omitting the
        key left an agent unable to tell "this graph has no house style" from
        "nobody told me about it", which are different situations with different
        correct behaviour. The absent block says which one it is, and what
        follows from it: with no recorded identity the evolve gate runs
        emergent, so only the hard checks can refuse.
        """
        try:
            import json as _json

            sidecar = self._db_path.with_suffix(".grain.json")
            if not sidecar.exists():
                return self._grain_absent("none_recorded")
            data = _json.loads(sidecar.read_text(encoding="utf-8"))
            seeds = [s for s in (data.get("seeds") or []) if isinstance(s, dict)]
            if not seeds:
                return self._grain_absent("none_recorded")
            trimmed = []
            truncated = False
            for seed in seeds[:GRAIN_EXEMPLAR_CAP]:
                text = str(seed.get("text_content") or "")
                if len(text) > GRAIN_TEXT_CAP:
                    text = text[:GRAIN_TEXT_CAP] + "…"
                    truncated = True
                trimmed.append({"id": str(seed.get("id") or ""),
                                "label": str(seed.get("label") or ""),
                                "text_content": text})
            if len(seeds) > GRAIN_EXEMPLAR_CAP:
                truncated = True
            return {
                "available": True,
                "exemplars": trimmed,
                "exemplar_count": len(seeds),
                "truncated": truncated,
                "note": ("What one node is in this graph. Match this shape and "
                         "level of self-containment when you propose — a rule "
                         "node must decide on its own text."),
            }
        except Exception:
            return self._grain_absent("unreadable")

    @staticmethod
    def _grain_absent(reason: str) -> dict[str, Any]:
        """The honest empty case. `reason` distinguishes a graph that never
        recorded a grain identity from one whose sidecar could not be read —
        the first is normal, the second is a fault worth reporting."""
        return {
            "available": False,
            "reason": reason,
            "exemplars": [],
            "exemplar_count": 0,
            "note": (
                "This graph records no grain identity, so there is no house "
                "style to match and none will be enforced: only the hard checks "
                "(sanity, rule fusion) can refuse a proposal here. Encode one "
                "claim per node and keep each node able to decide on its own "
                "text."
                if reason == "none_recorded"
                else "This graph's grain reference could not be read. Treat it "
                     "as absent and report the fault — do not assume the "
                     "absence is deliberate."
            ),
        }

    def _posture(self) -> dict[str, Any]:
        """The operator's posture, or the defaults. Never absent: an agent with
        no posture would have to invent one, which is the situation this
        replaces."""
        try:
            from mcp_server.account import Account, _default_posture

            if not getattr(self, "_store_path", None):
                return _default_posture()
            return Account(Path(self._store_path).parent).posture()
        except Exception:
            from mcp_server.account import _default_posture

            return _default_posture()

    def retrieve(
        self,
        program: dict[str, Any],
        evidence: str = "content",
        *,
        context_ref: str = "",
        graph_version: str = "",
    ) -> dict[str, Any]:
        """Execute a caller-authored retrieval-v1 program, with no LLM calls."""
        from retrieval_program import canonicalise_program, execute_retrieval_program

        if evidence not in {"summary", "packet", "content"}:
            with self._read_guard():
                out = self._base()
                out["compass_ref"] = self._compass_ref()
            return {
                **out,
                "mode": "direct",
                "kind": "INVALID_PROGRAM",
                "errors": ["evidence must be summary, packet, or content"],
            }
        try:
            canonical = canonicalise_program(program, author="direct")
        except Exception as exc:
            errors = exc.errors() if hasattr(exc, "errors") else [str(exc)]
            with self._read_guard():
                out = self._base()
                out["compass_ref"] = self._compass_ref()
            return {**out, "mode": "direct", "kind": "INVALID_PROGRAM", "errors": errors}

        out: dict[str, Any] = {}
        try:
            with self._read_guard():
                # Bind identity, execution and content paging to one graph
                # snapshot. A confirm cannot swap the graph between them.
                out = self._base()
                out["mode"] = "direct"
                out["compass_ref"] = self._compass_ref()
                if graph_version and graph_version != out["graph_version"]:
                    return {
                        **out,
                        "kind": "STALE_GRAPH",
                        "provided_graph_version": graph_version,
                    }
                if context_ref and context_ref != out["compass_ref"]:
                    return {
                        **out,
                        "kind": "STALE_CONTEXT",
                        "provided_compass_ref": context_ref,
                    }
                result = execute_retrieval_program(
                    self._session.connection,
                    canonical,
                    structural_index=self._session.structural_index,
                )
                projected = self._project_direct_evidence(
                    result["evidence_packet"], evidence
                )
        except Exception as exc:
            return {
                **out,
                "kind": "RETRIEVAL_FAILED",
                "engine_degraded": True,
                "degradation_flags": [
                    f"engine_fault:direct_retrieval:{type(exc).__name__}"
                ],
            }

        receipt = dict(result["execution_receipt"])
        receipt["graph_version"] = out["graph_version"]
        receipt["compass_ref"] = out["compass_ref"]
        return {
            **out,
            "kind": "RETRIEVED",
            "program": result["program"],
            "execution_receipt": receipt,
            "evidence": projected,
        }

    def run_traversal(
        self,
        name: str,
        parameters: dict[str, Any] | None = None,
        *,
        version: int | None = None,
        evidence: str = "packet",
        graph_version: str = "",
        explain: bool = False,
    ) -> dict[str, Any]:
        """Compile and execute one graph.md named traversal, with zero LLM.

        ``explain=True`` returns the compiled plan and estimated costs without
        touching the graph beyond reading its current version.
        """
        from mcp_server.traversal_compiler import compile_named_traversal

        return self._run_compiled_traversal(
            lambda document: compile_named_traversal(
                document, name, parameters, version=version
            ),
            mode="named_traversal",
            kind="NAMED_TRAVERSAL",
            evidence=evidence,
            graph_version=graph_version,
            explain=explain,
        )

    def run_ephemeral_traversal(
        self,
        program: dict[str, Any],
        parameters: dict[str, Any] | None = None,
        *,
        evidence: str = "packet",
        graph_version: str = "",
        explain: bool = False,
    ) -> dict[str, Any]:
        """Execute one caller-authored traversal program, with zero LLM.

        Same primitives, same bounds, same graph-version receipt and evidence
        packet as a named traversal. The program is fingerprinted on the
        receipt and is never written to graph.md; a recurring one is promoted
        by adding it to the contract, not by this verb.
        """
        from mcp_server.traversal_compiler import compile_ephemeral_traversal

        return self._run_compiled_traversal(
            lambda document: compile_ephemeral_traversal(
                document, dict(program or {}), parameters
            ),
            mode="ephemeral_traversal",
            kind="EPHEMERAL_TRAVERSAL",
            evidence=evidence,
            graph_version=graph_version,
            explain=explain,
            ephemeral=True,
        )

    def _run_compiled_traversal(
        self,
        compile_traversal,
        *,
        mode: str,
        kind: str,
        evidence: str,
        graph_version: str,
        explain: bool,
        ephemeral: bool = False,
    ) -> dict[str, Any]:
        """Run one compiled traversal program against the live graph.

        The named and ephemeral verbs differ only in where the program comes
        from; bounds, cache, receipt, fingerprints and honest ``EMPTY`` /
        ``EXACT_MISS`` outcomes are shared so a promoted program keeps the
        execution semantics it was measured under.
        """
        import hashlib
        import json

        from mcp_server.graph_contract import GraphContractError
        from source_pipeline.traversals import WorkbookTraversalError
        from mcp_server.traversal_compiler import (
            TraversalCompileError,
            explain_compiled_traversal,
            traversal_cache_key,
        )
        from retrieval_program import execute_retrieval_program

        def _copy(payload: dict[str, Any]) -> dict[str, Any]:
            return json.loads(json.dumps(payload))

        with self._read_guard():
            out = self._base()
            out["mode"] = mode
            out["compass_ref"] = self._compass_ref()
        if evidence not in {"summary", "packet", "content"}:
            return {
                **out,
                "kind": "INVALID_TRAVERSAL",
                "outcome": "INVALID_RECIPE",
                "errors": ["evidence must be summary, packet, or content"],
            }
        if not self._workbook_traversals_path.exists() and not self._graph_contract_path.exists():
            return {
                **out,
                "kind": "INVALID_TRAVERSAL",
                "outcome": "NO_CONTRACT",
                "errors": ["no named traversal program set is active for this graph"],
            }
        try:
            document = self._load_traversal_document()
            compiled = compile_traversal(document)
        except (GraphContractError, WorkbookTraversalError, TraversalCompileError, ValueError) as exc:
            return {
                **out,
                "kind": "INVALID_TRAVERSAL",
                "outcome": "INVALID_RECIPE",
                "errors": [str(exc)],
            }

        plan = explain_compiled_traversal(compiled)
        try:
            with self._read_guard():
                out = self._base()
                out["mode"] = mode
                out["compass_ref"] = self._compass_ref()
                if graph_version and graph_version != out["graph_version"]:
                    return {
                        **out,
                        "kind": "STALE_GRAPH",
                        "outcome": "STALE_GRAPH",
                        "provided_graph_version": graph_version,
                    }
                cache_key = traversal_cache_key(
                    graph_version=out["graph_version"],
                    compiled=compiled,
                    evidence=evidence,
                )
                recipe_meta = {
                    "name": compiled.name,
                    "version": compiled.version,
                    "fingerprint": compiled.fingerprint,
                    "format_fingerprint": compiled.format_fingerprint,
                    "program_set_fingerprint": compiled.program_set_fingerprint,
                    "parameters": compiled.parameters,
                }
                if ephemeral:
                    recipe_meta["ephemeral"] = True
                if explain:
                    return {
                        **out,
                        "kind": "TRAVERSAL_PLAN",
                        "outcome": "PLANNED",
                        "recipe": recipe_meta,
                        "program": compiled.program.model_dump(mode="json"),
                        "plan": plan,
                        "cache_key": cache_key,
                        "cached": False,
                    }
                cached = self._traversal_cache.get(cache_key)
                if cached is not None:
                    hit = _copy(cached)
                    hit["cached"] = True
                    hit["trace_id"] = out["trace_id"]
                    return hit
                result = execute_retrieval_program(
                    self._session.connection,
                    compiled.program,
                    structural_index=self._session.structural_index,
                )
                projected = self._project_direct_evidence(
                    result["evidence_packet"], evidence
                )
                projected = self._apply_recipe_project(
                    projected,
                    result["evidence_packet"],
                    compiled.project,
                    evidence,
                )
        except Exception as exc:
            return {
                **out,
                "kind": "TRAVERSAL_FAILED",
                "outcome": "EXECUTION_FAILED",
                "engine_degraded": True,
                "degradation_flags": [
                    f"engine_fault:{mode}:{type(exc).__name__}"
                ],
            }

        packet = result["evidence_packet"]
        packet_identity = {
            "nodes": sorted(
                str(row.get("id") or "")
                for row in packet.get("node_records") or []
                if isinstance(row, dict)
            ),
            "edges": sorted(
                (
                    str(row.get("source") or row.get("source_id") or ""),
                    str(row.get("target") or row.get("target_id") or ""),
                    str(row.get("edge_type") or row.get("type") or ""),
                    str(row.get("edge_label") or row.get("predicate") or ""),
                )
                for row in packet.get("edge_records") or []
                if isinstance(row, dict)
            ),
            "paths": packet.get("path_records") or [],
        }
        result_fingerprint = hashlib.sha256(
            json.dumps(
                packet_identity, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()[:16]
        receipt = dict(result["execution_receipt"])
        receipt.update(
            {
                "recipe_name": compiled.name,
                "recipe_version": compiled.version,
                "recipe_fingerprint": compiled.fingerprint,
                "format_fingerprint": compiled.format_fingerprint,
                "program_set_fingerprint": compiled.program_set_fingerprint,
                "canonical_parameters": compiled.parameters,
                "primitive_contract_version": "retrieval-v1",
                "graph_version": out["graph_version"],
                "compass_ref": out["compass_ref"],
                "result_fingerprint": f"trr_{result_fingerprint}",
            }
        )
        if ephemeral:
            receipt["ephemeral"] = True
        packet_count = int(receipt.get("packet_node_count") or 0)

        # A traversal may name the variables that carry its answer. When it
        # does, an empty answer is EMPTY even though the packet holds context,
        # because deciding on packet size alone reported FOUND for
        # `how_are_they_connected` between two characters with no path between
        # them: looking up the two endpoints filled the packet, and a caller
        # reading FOUND would conclude they were connected.
        answers = tuple(getattr(compiled, "answers", ()) or ())
        answer_count = None
        answer_node_ids: list[str] = []
        if answers:
            variables = result.get("variables") or {}
            answer_count = sum(
                len(variables.get(name) or ()) for name in answers
            )
            # A variable holds ids for set-producing steps and node *records*
            # for path-producing ones -- `find_paths` assigns dicts carrying
            # `path_chain`. Stringifying those produced four repr blobs that
            # matched no packet row, so nothing was marked and the field read
            # as an answer while naming nothing.
            seen: set[str] = set()
            for name in answers:
                for entry in variables.get(name) or ():
                    node_id = (
                        str(entry.get("id") or "")
                        if isinstance(entry, dict)
                        else str(entry)
                    )
                    if node_id and node_id not in seen:
                        seen.add(node_id)
                        answer_node_ids.append(node_id)
            receipt["answer_variables"] = list(answers)
            receipt["answer_count"] = answer_count

        if answer_count == 0:
            outcome = (
                "EXACT_MISS"
                if int(receipt.get("resolve_miss_count") or 0)
                else "EMPTY"
            )
        elif packet_count:
            outcome = "FOUND"
        elif int(receipt.get("resolve_miss_count") or 0):
            outcome = "EXACT_MISS"
        else:
            outcome = "EMPTY"
        from mcp_server.review_policy import explain_membership

        membership, why_entered = explain_membership(
            result.get("variables") or {},
            result.get("collected_ids") or [],
            receipt.get("operations") or [],
        )
        # The packet is every node the walk touched, which is what makes it
        # evidence. It is not the answer: a `difference` over two characters'
        # places returned four places inside a fifty-node packet, and nothing
        # in `node_records` said which four. `answers` reached the outcome and
        # stopped there, so a caller reading the packet read 46 wrong nodes.
        answer_set = set(answer_node_ids)
        for row in projected.get("node_records") or []:
            if not isinstance(row, dict):
                continue
            node_id = str(row.get("id") or "")
            if node_id in why_entered:
                row["entered_via"] = why_entered[node_id]
            if answers:
                row["is_answer"] = node_id in answer_set
        # Two different truncations, and only one of them was ever reported.
        # `truncated` is about the evidence packet being projected down. A walk
        # cut short by its own bounds is a separate thing and was silent: a
        # `traverse` asking for depth 8 got depth 6, returned six nodes for a
        # forty-one-node answer, and said `truncated: false`.
        bounds_applied = [
            dict(clamp, step=operation.get("assign_to"), tool=operation.get("tool"))
            for operation in receipt.get("operations") or []
            for clamp in (operation.get("bounds_applied") or [])
        ]
        if bounds_applied:
            receipt["bounds_applied"] = bounds_applied
        receipt["truncated"] = bool(projected.get("truncated"))
        receipt["fallback_triggered"] = bool(receipt.get("contingency_triggered"))
        receipt["empty_variables"] = list(receipt.get("empty_variables") or [])
        plan["actual"] = {
            "elapsed_ms": receipt.get("elapsed_ms"),
            "operations": receipt.get("operations") or [],
            "packet_node_count": receipt.get("packet_node_count"),
            "packet_edge_count": receipt.get("packet_edge_count"),
            "truncated": receipt.get("truncated"),
            "bounds_applied": bounds_applied,
            "fallback_triggered": receipt.get("fallback_triggered"),
            "resolve_miss_count": receipt.get("resolve_miss_count"),
        }
        payload = {
            **out,
            "kind": kind,
            "outcome": outcome,
            "recipe": recipe_meta,
            "program": result["program"],
            "execution_receipt": receipt,
            "evidence": projected,
            "membership": membership,
            "why_entered": why_entered,
            # Absent, not empty, when the recipe names no answer variables:
            # an empty list would read as "this traversal found nothing".
            **({"answer_node_ids": answer_node_ids} if answers else {}),
            "plan": plan,
            "cache_key": cache_key,
            "cached": False,
        }
        self._traversal_cache[cache_key] = _copy(payload)
        return payload

    def read_cypher(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
        *,
        max_rows: int = 200,
        max_chars: int = 20000,
        timeout_ms: int = 5000,
        graph_version: str = "",
    ) -> dict[str, Any]:
        """Run one read-only Cypher statement against the live graph.

        The escape hatch below the recipe vocabulary. Everything the typed
        verbs deliberately do not express — aggregation, arbitrary property
        predicates, a shape nobody anticipated — is reachable here rather than
        being unreachable, and an abstraction that cannot be escaped is one
        that quietly removes capability.

        Read-only is enforced by the engine, not by inspecting the string: the
        statement runs inside ``BEGIN TRANSACTION READ ONLY``, so a write is
        refused by LadybugDB itself and the transaction is always rolled back.
        Bounds are the caller's: rows, characters and wall-clock all truncate
        visibly rather than returning a partial answer that reads as complete.
        """
        import hashlib
        import json
        import time

        with self._read_guard():
            out = self._base()
            out["mode"] = "read_cypher"

        statement = str(query or "").strip()
        if not statement:
            return {
                **out,
                "kind": "INVALID_CYPHER",
                "outcome": "INVALID_CYPHER",
                "errors": ["query is required"],
            }
        # One statement. The read-only wrapper is a transaction, so a caller
        # who opens or closes their own would leave the connection in a state
        # this verb did not choose and the next caller would inherit.
        body = statement[:-1] if statement.endswith(";") else statement
        if ";" in body:
            return {
                **out,
                "kind": "INVALID_CYPHER",
                "outcome": "INVALID_CYPHER",
                "errors": ["one statement per call; ';' is not a separator here"],
            }
        head = body.lstrip().split(None, 1)[0].upper() if body.strip() else ""
        if head in {"BEGIN", "COMMIT", "ROLLBACK", "CHECKPOINT"}:
            return {
                **out,
                "kind": "INVALID_CYPHER",
                "outcome": "INVALID_CYPHER",
                "errors": [
                    f"{head} is managed by this verb; send the query itself"
                ],
            }

        max_rows = max(1, min(int(max_rows or 200), 2000))
        max_chars = max(500, min(int(max_chars or 20000), 200000))
        timeout_ms = max(100, min(int(timeout_ms or 5000), 60000))
        params = dict(parameters or {})

        with self._read_guard():
            out = self._base()
            out["mode"] = "read_cypher"
            if graph_version and graph_version != out["graph_version"]:
                return {
                    **out,
                    "kind": "STALE_GRAPH",
                    "outcome": "STALE_GRAPH",
                    "provided_graph_version": graph_version,
                }
            connection = self._session.connection
            started = time.monotonic()
            columns: list[str] = []
            rows: list[list[Any]] = []
            truncated = False
            chars = 0
            in_transaction = False
            try:
                connection.set_query_timeout(timeout_ms)
                connection.execute("BEGIN TRANSACTION READ ONLY")
                in_transaction = True
                result = (
                    connection.execute(body, params) if params
                    else connection.execute(body)
                )
                columns = list(result.get_column_names() or [])
                while result.has_next():
                    if len(rows) >= max_rows:
                        truncated = True
                        break
                    row = [_cypher_value(value) for value in result.get_next()]
                    encoded = len(
                        json.dumps(row, default=str, separators=(",", ":"))
                    )
                    if chars + encoded > max_chars:
                        truncated = True
                        break
                    chars += encoded
                    rows.append(row)
            except Exception as exc:
                return {
                    **out,
                    "kind": "CYPHER_FAILED",
                    "outcome": "CYPHER_FAILED",
                    "errors": [f"{type(exc).__name__}: {exc}"],
                }
            finally:
                if in_transaction:
                    try:
                        connection.execute("ROLLBACK")
                    except Exception:
                        pass
                try:
                    # Connection-wide setting on a shared connection: restore
                    # the unbounded default so this call cannot time out the
                    # next one.
                    connection.set_query_timeout(0)
                except Exception:
                    pass
            elapsed_ms = int((time.monotonic() - started) * 1000)

        fingerprint = hashlib.sha256(
            json.dumps(
                {"query": body, "parameters": params},
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()[:16]
        return {
            **out,
            "kind": "CYPHER_RESULT",
            # EMPTY is this query returning no rows on this graph version. It
            # is not proof the graph lacks the thing asked about, exactly as
            # with the typed verbs.
            "outcome": "FOUND" if rows else "EMPTY",
            "columns": columns,
            "rows": rows,
            "execution_receipt": {
                "query_fingerprint": f"cyp_{fingerprint}",
                "graph_version": out["graph_version"],
                "parameters": params,
                "row_count": len(rows),
                "truncated": truncated,
                "max_rows": max_rows,
                "max_chars": max_chars,
                "timeout_ms": timeout_ms,
                "elapsed_ms": elapsed_ms,
                "read_only": True,
            },
        }

    def _record_fault(self, where: str, flags: list[str] | None = None) -> None:
        return

    def what_governs(self, question: str, explain: bool = False, **_kwargs) -> dict[str, Any]:
        """Host-only coverage placeholder for the correction encode oracle.

        The LangGraph adjudicator is gone. Mechanical writes still probe
        coverage before/after an encoding; this returns UNGOVERNED rather
        than inventing a ruling.
        """
        out = self._base()
        out["question"] = question
        out["status"] = "UNGOVERNED"
        out["kind"] = "UNGOVERNED"
        if explain:
            out["explain"] = False
        return out

    def propose(
        self,
        encoding: dict[str, Any],
        provenance: dict[str, Any] | None = None,
        target_gap_id: str = "",
        claim_level: str = "L0",
        dry_run: bool = False,
        check_gate: bool = False,
        expected_graph_version: str = "",
        traversal_receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate an SST-shaped proposal and commit it.

        Propose is the write. There is no human approval queue. Mechanical
        refusals (invalid encoding, grain, stale graph, red encode battery)
        return as errors; they do not wait for a person.

        L1 claims are demoted with a recorded reason; the write still proceeds.

        `dry_run=True` validates and returns without committing, emitting no
        events. It exists because the cost of a bad encoding used to fall on
        the wrong party: the agent submits, then the write runs, and only
        *then* does the gate fail. A preflight lets the agent find its own
        mistakes first.

        **A dry run is not the gate, and says so.** The closure/distractor gate
        measures the graph *after* encoding and restores a snapshot, so running
        it means mutating a single-owner database underneath live readers. What
        a dry run does check is everything that does not require encoding: SST
        shape, referential integrity of every edge endpoint, id collisions, the
        `target_gap_id` requirement, and the effective claim level. Those are
        the errors an agent actually makes. `gate_checked: false` is on the
        response so nothing can mistake a clean preflight for a green gate.

        `provenance.decision_origin` separates recovery of an already recorded
        decision (`recover_existing`) from a genuinely new proposal
        (`propose_new`).

        ``expected_graph_version`` binds the proposal to the context used to
        author it. Omitted legacy callers are bound to the live version at
        submission; callers with an earlier context must pass it explicitly.

        ``traversal_receipt`` is optional unless the active graph.md lists a
        matching ``required_traversals`` rule. When supplied, the server reruns
        the named recipe against the same graph version and refuses a mismatched
        result fingerprint before the proposal is stored. A required
        recipe that is missing, wrong, or bound to a different target is a
        refusal.

        """
        import json as _json

        from mcp_server.proposals import (
            L1_ADMISSION_INCOMPLETE,
            ProposalProvenance,
            _existing_format_kinds,
            new_proposal_id,
            validate_proposal,
        )

        out = self._base()
        if not self._proposals_enabled:
            out["error"] = "proposals are not enabled on this server"
            return out

        supplied_version = str(expected_graph_version or "").strip()
        if supplied_version and supplied_version != out["graph_version"]:
            out.update(
                {
                    "kind": "STALE_GRAPH",
                    "error_code": "STALE_GRAPH",
                    "error": (
                        "expected_graph_version does not match the live graph; "
                        "refresh proposal context before checking or queueing"
                    ),
                    "expected_graph_version": supplied_version,
                    "current_graph_version": out["graph_version"],
                    "retryable": True,
                }
            )
            return out
        checked_version = supplied_version or out["graph_version"]

        prop, err = validate_proposal(
            encoding,
            self._db_path,
            graph_contract_path=self._graph_contract_path,
        )
        if prop is None:
            out["error"] = err
            if dry_run:
                out.update({"dry_run": True, "would_queue": False,
                            "gate_checked": False})
            return out
        try:
            prov = ProposalProvenance.model_validate(provenance or {})
        except Exception as exc:
            out["error"] = f"invalid provenance: {exc}"
            if dry_run:
                out.update({"dry_run": True, "would_queue": False,
                            "gate_checked": False})
            return out

        if not str(target_gap_id or "").strip():
            # F3 (L2-4 campaign, prop_b838b5af2374): an empty target yields a
            # degenerate closure test ("What governs ?") — the proposal can
            # never be meaningfully gated. Typed refusal at propose time;
            # records stored under older code are unaffected (reject remains
            # the disposition path for them).
            out["error"] = ("target_gap_id is required: a proposal must name the gap "
                            "it fills (the predicate you escalated, or the structural "
                            "identifier being added) — the gate derives its closure "
                            "test from it")
            if dry_run:
                out.update({"dry_run": True, "would_queue": False,
                            "gate_checked": False})
            return out

        if (
            prov.decision_origin == "recover_existing"
            and not [ref for ref in prov.source_refs if str(ref).strip()]
        ):
            out["error"] = (
                "decision_origin recover_existing requires at least one source_ref; "
                "use propose_new when offering a decision for human ratification"
            )
            if dry_run:
                out.update({"dry_run": True, "would_queue": False,
                            "gate_checked": False})
            return out

        demotion = ""
        if (
            str(claim_level).upper() == "L1"
            and prov.decision_origin == "propose_new"
        ):
            demotion = (
                "L1 authority: a genuinely new decision requires human ratification; "
                "demoted to the L0 review queue"
            )
        elif str(claim_level).upper() == "L1" and self._write_policy is None:
            demotion = L1_ADMISSION_INCOMPLETE
        elif str(claim_level).upper() not in ("L0", "L1"):
            out["error"] = f"invalid claim_level: {claim_level!r}"
            if dry_run:
                out.update({"dry_run": True, "would_queue": False,
                            "gate_checked": False})
            return out

        traversal_preflight: dict[str, Any] = {"status": "NOT_SUPPLIED"}
        verified_traversal_receipt: dict[str, Any] = {}
        if traversal_receipt is not None:
            if not isinstance(traversal_receipt, dict) or not traversal_receipt:
                out["error"] = "invalid traversal_receipt: expected a non-empty object"
                return out
            recipe_name = str(traversal_receipt.get("recipe_name") or "").strip()
            parameters = traversal_receipt.get("canonical_parameters") or {}
            receipt_version = traversal_receipt.get("recipe_version")
            receipt_graph_version = str(
                traversal_receipt.get("graph_version") or ""
            ).strip()
            result_fingerprint = str(
                traversal_receipt.get("result_fingerprint") or ""
            ).strip()
            if (
                not recipe_name
                or not isinstance(parameters, dict)
                or not receipt_graph_version
                or not result_fingerprint
            ):
                out["error"] = (
                    "invalid traversal_receipt: recipe_name, canonical_parameters, "
                    "graph_version, and result_fingerprint are required"
                )
                return out
            if receipt_graph_version != checked_version:
                out.update(
                    {
                        "kind": "STALE_TRAVERSAL",
                        "error_code": "STALE_TRAVERSAL",
                        "error": (
                            "traversal receipt was produced against a different "
                            "graph version; rerun it before proposing"
                        ),
                        "traversal_preflight": {
                            "status": "STALE",
                            "receipt_graph_version": receipt_graph_version,
                            "current_graph_version": checked_version,
                        },
                    }
                )
                return out
            try:
                parsed_receipt_version = (
                    int(receipt_version) if receipt_version is not None else None
                )
            except (TypeError, ValueError):
                out["error"] = "invalid traversal_receipt: recipe_version must be an integer"
                return out
            rerun = self.run_traversal(
                recipe_name,
                parameters,
                version=parsed_receipt_version,
                evidence="summary",
                graph_version=checked_version,
            )
            fresh_receipt = rerun.get("execution_receipt") or {}
            if (
                rerun.get("kind") != "NAMED_TRAVERSAL"
                or str(fresh_receipt.get("result_fingerprint") or "")
                != result_fingerprint
                or str(fresh_receipt.get("recipe_fingerprint") or "")
                != str(traversal_receipt.get("recipe_fingerprint") or "")
                or str(fresh_receipt.get("format_fingerprint") or "")
                != str(traversal_receipt.get("format_fingerprint") or "")
            ):
                out.update(
                    {
                        "kind": "TRAVERSAL_MISMATCH",
                        "error_code": "TRAVERSAL_MISMATCH",
                        "error": (
                            "traversal receipt did not reproduce on the current "
                            "format and graph; rerun it before proposing"
                        ),
                        "traversal_preflight": {
                            "status": "MISMATCH",
                            "recipe_name": recipe_name,
                            "supplied_result_fingerprint": result_fingerprint,
                            "current_result_fingerprint": fresh_receipt.get(
                                "result_fingerprint", ""
                            ),
                        },
                    }
                )
                return out
            verified_traversal_receipt = dict(traversal_receipt)
            traversal_preflight = {
                "status": "VERIFIED",
                "recipe_name": recipe_name,
                "recipe_version": fresh_receipt.get("recipe_version"),
                "recipe_fingerprint": fresh_receipt.get("recipe_fingerprint"),
                "format_fingerprint": fresh_receipt.get("format_fingerprint"),
                "graph_version": fresh_receipt.get("graph_version"),
                "result_fingerprint": fresh_receipt.get("result_fingerprint"),
            }

        from mcp_server.graph_contract import GraphContractError, load_graph_contract
        from mcp_server.review_policy import (
            REQUIRED_TRAVERSAL_REFUSAL_CODES,
            classify_review,
        )

        contract_document = None
        if self._graph_contract_path.exists():
            try:
                contract_document = load_graph_contract(self._graph_contract_path)
            except GraphContractError:
                contract_document = None

        review = classify_review(
            contract_document,
            concepts=prop.concepts,
            edges=prop.edges,
            corrections=prop.corrections,
            source_refs=list(prov.source_refs or []),
            traversal_preflight=traversal_preflight,
            receipt=verified_traversal_receipt,
            existing_kinds=_existing_format_kinds(self._db_path),
        )
        blockers = [
            row
            for row in review.get("exceptions") or []
            if str(row.get("code") or "") in REQUIRED_TRAVERSAL_REFUSAL_CODES
        ]
        if blockers:
            first = blockers[0]
            out.update(
                {
                    "kind": "REQUIRED_TRAVERSAL",
                    "error_code": str(first.get("code") or ""),
                    "error": str(first.get("detail") or "required traversal missing"),
                    "review": review,
                    "traversal_preflight": traversal_preflight,
                    "would_queue": False,
                    "dry_run": bool(dry_run),
                }
            )
            return out

        from mcp_server.history import graph_fingerprint

        checked_fingerprint = graph_fingerprint(self._db_path)

        if dry_run:
            # Nothing stored, nothing emitted. A preflight that left a trace
            # would put unreviewed attempts in the operator's inbox, which is
            # the queue this exists to keep clean.
            grain = self._grain_preflight(prop)
            out.update({
                "dry_run": True,
                "would_queue": bool(grain.get("allowed", True)),
                "grain_checked": bool(grain),
                # `grain_verdict`, not `grain`: `orient()` already uses `grain`
                # for the house-style reference, and one agent-facing word
                # meaning both "what a node is here" and "did yours pass" is a
                # collision an agent has no way to resolve from the payload.
                "grain_verdict": grain,
                "gate_checked": False,
                "claim_level_effective": "L0" if demotion else str(claim_level).upper(),
                "decision_origin": prov.decision_origin,
                "expected_graph_version": checked_version,
                "expected_graph_fingerprint": checked_fingerprint,
                "traversal_preflight": traversal_preflight,
                "review": review,
                "concepts": len(encoding.get("concepts") or []),
                "edges": len(encoding.get("edges") or []),
            })
            if not grain.get("allowed", True):
                out["error"] = f"grain check failed: {grain.get('reason', '')}"
            out["note"] = (
                "validation + grain. The closure/distractor gate runs at "
                "commit and is NOT simulated here.")
            # The closure/distractor gate needs the proposal ENCODED before it
            # can measure anything. `check_gate` encodes it — into a throwaway
            # copy — and runs the real battery there. Off by default because it
            # costs embeddings and a battery run; grain failures are the common
            # case and are free.
            if check_gate and grain.get("allowed", True):
                gate_report = self._gate_preflight(
                    prop, target_gap_id=target_gap_id, claim_level=claim_level)
                out["gate_preflight"] = gate_report
                out["gate_checked"] = bool(gate_report.get("ran"))
                if gate_report.get("ran"):
                    out["would_queue"] = True   # queueing is never gate-blocked
                    out["note"] = (
                        "validation + grain + the real encode gate, run against "
                        "a throwaway copy. A green preflight commits nothing."
                        if gate_report.get("would_pass") else
                        "validation + grain. The encode gate was run on a copy "
                        "and WOULD FAIL — fix it before proposing for real."
                    )
                    if not gate_report.get("would_pass"):
                        out["error"] = (
                            "the encode gate would fail: "
                            + str(gate_report.get("reason", "")))
                else:
                    out["note"] += (
                        f" Gate preflight did not run: {gate_report.get('reason', '')}")
            if demotion:
                out["demotion_reason"] = demotion
            return out

        pid = new_proposal_id()
        self._get_store().save_proposal(
            {
                "proposal_id": pid,
                "target_gap_id": target_gap_id,
                "encoding_json": _json.dumps(prop.model_dump()),
                "claim_level": str(claim_level).upper(),
                "demotion_reason": demotion,
                "generating_task": prov.generating_task,
                "source_refs": prov.source_refs,
                "conversation_id": prov.conversation_id,
                "decision_origin": prov.decision_origin,
                "expected_graph_version": checked_version,
                "expected_graph_fingerprint": checked_fingerprint,
                "traversal_receipt": verified_traversal_receipt,
                "review_exceptions": review.get("exceptions") or [],
                "review_mode": review.get("review_mode") or "",
                "review_required": review.get("review_required"),
                "status": "PENDING",
            }
        )
        committed = self._attempt_green_encode(pid)
        out.update(committed)
        out["proposal_id"] = pid
        out["graph_version"] = self._session.graph_version
        out["decision_origin"] = prov.decision_origin
        out["expected_graph_version"] = checked_version
        out["expected_graph_fingerprint"] = checked_fingerprint
        out["traversal_preflight"] = traversal_preflight
        out["review"] = review
        if demotion:
            out["demotion_reason"] = demotion
            out["claim_level_effective"] = "L0"
        if committed.get("status") != "COMMITTED" and not out.get("error"):
            out["error"] = str(
                committed.get("error") or committed.get("status") or "propose did not commit"
            )
        return out

    def _attempt_green_encode(self, proposal_id: str) -> dict[str, Any]:
        """Commit a just-saved proposal. Propose is the write."""
        rec = self._get_store().get_proposal(proposal_id)
        if rec is None:
            return {"error": f"unknown proposal: {proposal_id}"}
        gate = None
        if callable(self._gate_provider):
            gate = self._gate_provider(rec)
        embedder = getattr(self, "_preflight_embedder", None)
        if embedder is None and self._write_policy is not None:
            embedder = getattr(self._write_policy, "embedder", None)
        if embedder is None:
            embedder = lambda _text: [0.0] * 3072
        from mcp_server.proposals import COMPLETE_PROBE_CAP, attempt_green_auto_commit

        with self._write_guard():
            self._session.close()
            try:
                return attempt_green_auto_commit(
                    self._db_path,
                    self._store_path,
                    proposal_id,
                    gate=gate,
                    embedder=embedder,
                    correction_oracle_factory=getattr(
                        self, "_correction_oracle_factory", None),
                    correction_probe_cap=int(getattr(
                        self, "_correction_probe_cap", COMPLETE_PROBE_CAP)),
                )
            finally:
                self._session.open(self._db_path, auto_seed=False)
                self._graph = None
                self._adapter = None
                if self._snapshots is not None:
                    self._snapshots.capture(self._session.graph_version)

    def _gate_preflight(self, prop: Any, *, target_gap_id: str,
                        claim_level: str) -> dict[str, Any]:
        """Run the real encode gate against a throwaway copy of the graph.

        The other half of the preflight. Shape and grain can be checked without
        encoding; closure and distractors cannot — they measure what the graph
        *answers* once the proposal is in it. That is why this used to report
        `gate_checked: false` and leave the discovery to a human who had already
        spent the scarcest action in the system.

        **It runs the identical code path, not a model of it.** The copy is
        confirmed through `confirm_proposal` with the same battery, the same
        grain gate, the same closure and distractor checks. An approximation
        would be worse than no preflight, because an agent would believe it.

        Three properties make this safe to expose on the read plane:

        - **The copy is the only thing mutated.** The live graph is never
          opened for writing, so no snapshot/restore cycle runs against it and
          no reader is disturbed.
        - **No authority is created.** A green preflight commits nothing; the
          copy and its store are deleted. A human confirm is still the only way
          anything reaches the real graph.
        - **The proposal is not queued.** A preflight that left a record would
          fill the operator's inbox with unreviewed attempts, which is the queue
          this exists to keep clean.

        The cost is real — the graph is copied, the new concepts are embedded,
        and the battery invokes the engine per pin — so it is opt-in rather than
        part of every dry run. Most of it is the cost the confirm would have
        paid anyway, moved to the party that can act on the answer; the copy is
        the extra, and it is what buys the live graph its immunity.
        """
        import json as _json
        import shutil
        import tempfile

        from mcp_server.proposals import new_proposal_id

        report: dict[str, Any] = {"ran": False}
        if self._gate_provider is None:
            report["reason"] = (
                "no gate battery is configured on this server, so there is "
                "nothing to preflight against")
            return report
        if not hasattr(self._gate_provider, "rebind"):
            # A battery bound to one path cannot be pointed at the copy, and
            # running it against the live graph would defeat the point.
            report["reason"] = (
                "the configured gate battery cannot be re-bound to a copy")
            return report

        room = Path(tempfile.mkdtemp(prefix="graphauthor-preflight-"))
        try:
            copy_db = room / self._db_path.name
            # Hold the read side while copying: a confirm landing mid-copy would
            # otherwise be preflighted against a half-written file.
            with self._read_guard():
                shutil.copy2(self._db_path, copy_db)
                sidecar = self._db_path.with_suffix(self._db_path.suffix + ".idx")
                if sidecar.exists():
                    shutil.copy2(sidecar, copy_db.with_suffix(copy_db.suffix + ".idx"))

            copy_store = room / "preflight.sqlite"
            pid = new_proposal_id()
            from interaction.write_path_store import WritePathStore
            from mcp_server.history import graph_fingerprint

            store = WritePathStore(copy_store)
            try:
                store.save_proposal({
                    "proposal_id": pid,
                    "target_gap_id": target_gap_id,
                    "encoding_json": _json.dumps(prop.model_dump()),
                    "claim_level": str(claim_level).upper(),
                    "demotion_reason": "",
                    "generating_task": "preflight",
                    "source_refs": [],
                    "conversation_id": "",
                    "expected_graph_version": "preflight-copy",
                    "expected_graph_fingerprint": graph_fingerprint(copy_db),
                    "status": "PENDING",
                })
                rec = store.get_proposal(pid)
            finally:
                store.close()

            gate = self._gate_provider.rebind(copy_db, copy_store)(rec)
            from mcp_server.proposals import confirm_proposal

            # Same embedder the real commit would use, so the copy is encoded
            # the way the graph would be. `None` falls through to the live one.
            embedder = (getattr(self._write_policy, "embedder", None)
                        or getattr(self, "_preflight_embedder", None))
            result = confirm_proposal(
                copy_db, copy_store, pid,
                primary_source="preflight: gated on a copy, commits nothing",
                gate=gate,
                embedder=embedder,
                authority="gate",
                actor="preflight",
            )
        except Exception as exc:               # noqa: BLE001 - reported, not raised
            report["reason"] = f"preflight failed: {type(exc).__name__}: {exc}"
            return report
        finally:
            shutil.rmtree(room, ignore_errors=True)

        status = str(result.get("status") or "")
        report.update({
            "ran": True,
            "would_pass": status == "COMMITTED",
            "status": status,
            "gate": result.get("gate") or result.get("gate_report") or {},
        })
        if status != "COMMITTED":
            report["reason"] = str(
                result.get("error")
                or f"the gate would return {status or 'no status'}")
        return report

    def _grain_preflight(self, prop: Any) -> dict[str, Any]:
        """Run the grain gate an operator confirm would run, before queueing.

        This is the half of the gate that needs no encoding. `confirm_proposal`
        checks grain *before* touching the graph — hard violations (sanity,
        rule fusion) refuse ahead of any mutation — so the same check runs here
        for free, and a GRAIN_FAILED that used to cost a human a PrimarySource
        now costs the agent one call.

        Soft drift stays advisory, exactly as it is at confirm: an incremental
        add slightly off grain is flagged, not refused. Reporting it as a
        blocker here would be stricter than the real gate and would teach agents
        to distrust the preflight.

        Best-effort: if the check cannot run, the preflight says so rather than
        implying the proposal is clean.
        """
        try:
            from mcp_server.grain import grain_gate

            added = [{"id": c.id, "label": c.label, "text_content": c.text_content}
                     for c in prop.concepts]
            edges = [(e.type, e.source_id, e.target_id, e.label) for e in prop.edges]
            if not added:
                return {"allowed": True, "reason": "",
                        "note": "no new concepts — grain has nothing to judge"}
            return grain_gate(self._db_path, added, edges)
        except Exception as exc:
            return {"allowed": True, "unavailable": True,
                    "reason": f"grain check could not run: {type(exc).__name__}"}

    def proposal_status(self, proposal_id: str) -> dict[str, Any]:
        """Additive read-only companion to propose (contract §2.6 note)."""
        import json as _json

        out = self._base()
        if not self._proposals_enabled:
            out["error"] = "proposals are not enabled on this server"
            return out
        rec = self._get_store().get_proposal(proposal_id)
        if rec is None:
            out["error"] = f"unknown proposal: {proposal_id}"
            return out
        out.update(
            {
                "proposal_id": rec["proposal_id"],
                "status": rec["status"],
                "claim_level": rec["claim_level"],
                "demotion_reason": rec["demotion_reason"],
                "target_gap_id": rec["target_gap_id"],
                "decision_origin": rec.get("decision_origin", "unspecified"),
                "expected_graph_version": rec.get("expected_graph_version", ""),
                "expected_graph_fingerprint": rec.get(
                    "expected_graph_fingerprint", ""
                ),
                "primary_source": rec["primary_source"],
                "graph_version_before": rec["graph_version_before"],
                "graph_version_after": rec["graph_version_after"],
                "submitted_at": rec["submitted_at"],
                "decided_at": rec["decided_at"],
                "gate_report": _json.loads(rec["gate_report_json"]) if rec["gate_report_json"] else None,
            }
        )
        return out

    def list_proposals(self, status: str | None = None) -> list[dict[str, Any]]:
        return self._get_store().list_proposals(status=status)

    def history(self) -> dict[str, Any]:
        """§2.7 — snapshot inventory. Zero LLM."""
        out = self._base()
        if self._snapshots is None:
            out["error"] = "history is not enabled on this server"
            return out
        out["versions"] = self._snapshots.versions()
        return out

    def diff(self, v_before: str, v_after: str) -> dict[str, Any]:
        """§2.7 — content-based structural delta between two snapshots."""
        out = self._base()
        if self._snapshots is None:
            out["error"] = "history is not enabled on this server"
            return out
        out.update(self._snapshots.diff(v_before, v_after))
        return out

    def changed_since(self, version: str) -> dict[str, Any]:
        """§2.7 — delta between snapshot `version` and the live graph."""
        out = self._base()
        if self._snapshots is None:
            out["error"] = "history is not enabled on this server"
            return out
        out.update(self._snapshots.diff_against_live(version))
        return out

    def history_action(self, args: dict[str, Any]) -> dict[str, Any]:
        """Transport dispatch for the `history` MCP tool. Revert is refused:
        agents propose forward, operators move backward (CLI only)."""
        action = str(args.get("action") or "versions")
        if action == "versions":
            return self.history()
        if action == "diff":
            return self.diff(str(args.get("v1") or ""), str(args.get("v2") or ""))
        if action == "changed_since":
            return self.changed_since(str(args.get("version") or ""))
        if action == "revert":
            out = self._base()
            out["error"] = (
                "revert is an operator action, not an MCP tool "
                "(mcp-contract-v0 §2.7); use the server CLI"
            )
            return out
        out = self._base()
        out["error"] = f"unknown history action: {action}"
        return out

    # ------------------------------------------------------------------
    # battery/support surface (not MCP tools)
    # ------------------------------------------------------------------

    def escalation_exists(self, handoff_id: str) -> bool:
        return any(h.handoff_id == handoff_id for h in self._get_store().list_handoffs())

    def reload(self) -> None:
        """Simulate restart: drop store handle so the next access reopens from disk."""
        if self._store is not None:
            self._store.close()
            self._store = None

    def close(self) -> None:
        self._traversal_cache.clear()
        if self._store is not None:
            self._store.close()
            self._store = None
        self._session.close()


# ---------------------------------------------------------------------------
# module-level constructors (battery import targets)
# ---------------------------------------------------------------------------


def open_fixture(db_path: Path | str) -> Surface:
    """Deterministic-tier surface over the no-API hexagonal fixture."""
    from mcp_server.fixture import ensure_fixture

    return Surface(ensure_fixture(db_path))


def open_credential(repo_root: Path | str) -> Surface:
    """Live-tier surface over the credential handbook (needs built .lbug + key)."""
    repo = Path(repo_root)
    return Surface(
        repo / "handbook" / "credential_governance.lbug",
        handbook="credential",
        repo_root=repo,
    )
