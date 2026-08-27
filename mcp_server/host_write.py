"""Host-agent write surface over the existing correction commit path.

Same loop the operator uses:

    propose → gate report → acknowledge → complete-universe rerun → commit

What changes is **who may supply a valid acknowledgement**. The host agent is
the happy-path interpreter for interpretable moves. Cardinal / unevaluable
outcomes still escalate; the gate, probe cap, snapshot restore, PrimarySource
requirement, and atomicity are unchanged.

This module is deliberately **not** wired into MCP TOOLS. The agent plane stays
propose-only; a host goal-loop (or the operator BFF carrying an agent-built
acknowledgement) calls this surface. Giving MCP a confirm verb that bypasses
the gate remains refused by construction — this surface only calls
``confirm_proposal``.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from mcp_server.proposals import COMPLETE_PROBE_CAP, GateSpec, confirm_proposal


class HostWriteSurface:
    """Thin host loop over propose + gated confirm.

    ``gate_provider`` is server-configured, never caller-supplied as a bypass:
    without it the surface can queue but cannot advance to commit — same rule
    as the operator BFF.
    """

    TOOL_NAMES = (
        "write_context",
        "write_check",
        "write_submit",
        "write_advance",
    )

    def __init__(
        self,
        surface: Any,
        *,
        gate_provider: Callable[[dict[str, Any]], GateSpec | None] | None = None,
        embedder: Callable[[str], list[float]] | None = None,
        actor: str = "agent:host",
        correction_oracle_factory: Callable[..., Any] | None = None,
        correction_probe_cap: int = COMPLETE_PROBE_CAP,
    ) -> None:
        self.surface = surface
        self._gate_provider = gate_provider
        self._embedder = embedder
        self._actor = actor
        self._oracle_factory = correction_oracle_factory
        self._probe_cap = int(correction_probe_cap)
        if embedder is not None:
            surface._preflight_embedder = embedder
        surface._correction_oracle_factory = correction_oracle_factory
        surface._correction_probe_cap = int(correction_probe_cap)
        if gate_provider is not None and getattr(surface, "_gate_provider", None) is None:
            surface._gate_provider = gate_provider

    @staticmethod
    def capability_card() -> dict[str, Any]:
        return {
            "kind": "HOST_WRITE_CAPABILITY",
            "execution": "deterministic_zero_llm",
            "path": [
                "propose",
                "report",
                "acknowledge",
                "rerun",
                "commit",
            ],
            "operations": list(HostWriteSurface.TOOL_NAMES),
            "authority": {
                "agent_can_check": True,
                "agent_can_queue": True,
                # Advance still requires PrimarySource + server gate battery.
                "agent_can_acknowledge": True,
                "agent_can_commit_via_gate": True,
                "agent_bypasses_gate": False,
                "mcp_exposes_confirm": False,
                "human_role": "optional_audit_and_cardinal_escalation",
            },
            "invariants": [
                "complete_probe_universe_or_refuse",
                "no_mixed_correction_and_add",
                "acknowledgement_identity_neutral",
                "cardinal_ungoverned_to_governed_escalates",
                "unevaluable_not_acknowledgeable",
                "snapshot_restore_on_red",
                "primary_source_required",
            ],
            "decision_origin_policy": (
                "recover_existing is the main correction route; propose_new "
                "remains human-ratified and is not auto-advanced here"
            ),
        }

    def context(self) -> dict[str, Any]:
        orient = self.surface.orient()
        return {
            **self.capability_card(),
            "graph_version": orient["graph_version"],
            "can_advance": self._gate_provider is not None,
            "correction_probe_cap": self._probe_cap,
        }

    def check(
        self,
        encoding: dict[str, Any],
        *,
        target_gap_id: str,
        provenance: dict[str, Any] | None = None,
        expected_graph_version: str = "",
    ) -> dict[str, Any]:
        return self._queue(
            encoding,
            target_gap_id=target_gap_id,
            provenance=provenance,
            expected_graph_version=expected_graph_version,
            submit=False,
        )

    def submit(
        self,
        encoding: dict[str, Any],
        *,
        target_gap_id: str,
        provenance: dict[str, Any] | None = None,
        expected_graph_version: str = "",
    ) -> dict[str, Any]:
        return self._queue(
            encoding,
            target_gap_id=target_gap_id,
            provenance=provenance,
            expected_graph_version=expected_graph_version,
            submit=True,
        )

    def advance(
        self,
        proposal_id: str,
        *,
        primary_source: str,
        acknowledgement: Mapping[str, Any] | None = None,
        accept_moves: Sequence[str] | None = None,
        acknowledged_by: str = "",
    ) -> dict[str, Any]:
        """Run or continue the gated confirm for a PENDING proposal.

        First call without an acknowledgement: mechanical clears commit;
        interpretable movement returns a bound report; cardinal/unevaluable
        escalates and refuses inline acceptance.

        Second call: pass ``acknowledgement`` (or ``accept_moves`` to build one
        from the prior report fields embedded in a previous response) to bind
        the interpreter's affirmation and re-run the complete probe universe.
        """
        if self._gate_provider is None:
            return {
                "kind": "REFUSED",
                "error_code": "NO_GATE_PROVIDER",
                "message": (
                    "host write surface has no gate provider: nothing to measure, "
                    "nothing to commit"
                ),
                "agent_mutated_graph": False,
            }
        if not str(primary_source).strip():
            return {
                "kind": "REFUSED",
                "error_code": "PRIMARY_SOURCE_REQUIRED",
                "message": (
                    "primary_source is required: the standing source of the "
                    "decision remains recorded even when the host agent affirms "
                    "interpretable movement"
                ),
                "agent_mutated_graph": False,
            }

        rec = self.surface.proposal_status(proposal_id)
        if rec.get("error"):
            return {
                "kind": "REFUSED",
                "error_code": "UNKNOWN_PROPOSAL",
                "message": str(rec["error"]),
                "agent_mutated_graph": False,
            }
        # Only an ASSERTED recovery may be advanced by the host. `propose_new`
        # is a declared new decision and `unspecified` is an undeclared one —
        # neither is a fidelity repair, and treating silence as recovery would
        # hand the agent the route that skips human ratification by default.
        origin = str(rec.get("decision_origin") or "unspecified")
        if origin != "recover_existing":
            return {
                "kind": "REFUSED",
                "error_code": "HUMAN_RATIFICATION_REQUIRED",
                "message": (
                    "host advance is for corrections that assert "
                    "decision_origin=recover_existing; "
                    + ("a declared new decision stays on the human confirm path"
                       if origin == "propose_new" else
                       "an undeclared origin is not a fidelity repair — declare "
                       "recover_existing with its source_refs, or use the "
                       "operator path")
                ),
                "decision_origin": origin,
                "agent_mutated_graph": False,
                "next_action": "operator_confirm",
            }

        gate = self._gate_provider(rec)
        if gate is None:
            return {
                "kind": "REFUSED",
                "error_code": "NO_GATE_BATTERY",
                "message": "gate provider returned no battery for this proposal",
                "agent_mutated_graph": False,
            }

        ack = dict(acknowledgement) if acknowledgement else None
        if ack is None and accept_moves is not None:
            return {
                "kind": "REFUSED",
                "error_code": "ACKNOWLEDGEMENT_INCOMPLETE",
                "message": (
                    "accept_moves needs a prior report_digest and moves; call "
                    "advance once to obtain the report, then resubmit with "
                    "acknowledgement=build_acknowledgement(...)"
                ),
                "agent_mutated_graph": False,
            }
        if ack is not None and not ack.get("acknowledged_by"):
            ack["acknowledged_by"] = acknowledged_by or self._actor

        result = confirm_proposal(
            self.surface._db_path,
            self.surface._store_path,
            proposal_id,
            primary_source=primary_source,
            gate=gate,
            embedder=self._embedder,
            authority="agent",
            actor=self._actor,
            correction_probe_cap=self._probe_cap,
            correction_oracle_factory=self._oracle_factory,
            correction_acknowledgement=ack,
        )
        return self._project(result)

    @staticmethod
    def build_acknowledgement(
        report: Mapping[str, Any],
        *,
        accepts: Sequence[str],
        acknowledged_by: str = "agent:host",
    ) -> dict[str, Any]:
        """Bind an interpreter's acceptances to a prior correction report.

        Does not copy the gate's full ``changed`` map into declared acceptance
        blindly: the caller must name which interpretable moves it affirms.
        Cardinal / unevaluable keys are still refused by ``correction_ack``.

        This deliberately does NOT pre-validate ``accepts`` against the report's
        interpretable set. Rejecting overreach here would be caller-side
        convenience bought at the cost of the server-side boundary's
        testability: an adversarial acknowledgement — an agent affirming a
        cardinal flip — could then no longer be CONSTRUCTED through the public
        helper, and the test that proves the gate refuses it would have nothing
        to hand it. The refusal belongs where it cannot be skipped, and it must
        stay reachable.
        """
        return {
            "report_digest": report.get("report_digest") or "",
            "moves": dict(report.get("moves") or {}),
            "accepts": list(accepts),
            "acknowledged_by": acknowledged_by,
        }

    def _queue(
        self,
        encoding: dict[str, Any],
        *,
        target_gap_id: str,
        provenance: dict[str, Any] | None,
        expected_graph_version: str,
        submit: bool,
    ) -> dict[str, Any]:
        current = self.surface.orient()["graph_version"]
        prov = dict(provenance or {})
        # DELIBERATELY NOT INFERRED. `decision_origin` is the field that decides
        # whether a human must ratify: `propose_new` stays on the operator path,
        # `recover_existing` may be advanced by the host agent. Defaulting it to
        # `recover_existing` whenever a source_ref happened to be attached let
        # the agent self-select the route that skips ratification — the party
        # being checked choosing its own check, which is the same circularity
        # that made declaration-derived probes unusable.
        #
        # Silence now stays `unspecified`, and `unspecified` cannot advance. The
        # agent must ASSERT recovery, which is a recorded claim an auditor can
        # disagree with, rather than a silence that reads as one.
        outcome = self.surface.propose(
            encoding=encoding,
            target_gap_id=target_gap_id,
            provenance=prov,
            expected_graph_version=expected_graph_version or current,
            claim_level="L0",
            dry_run=not submit,
        )
        status = str(outcome.get("status") or "")
        if submit and status == "COMMITTED":
            return {
                "kind": "COMMITTED",
                "proposal_id": outcome["proposal_id"],
                "graph_version": outcome.get("graph_version"),
                "decision_origin": outcome.get("decision_origin", "unspecified"),
                "agent_mutated_graph": True,
                "next_action": "done",
                "status": status,
            }
        if submit and status and status != "PENDING":
            return {
                "kind": "REFUSED",
                "proposal_id": outcome.get("proposal_id"),
                "status": status,
                "error_code": outcome.get("error_code") or status,
                "message": str(outcome.get("error") or status),
                "agent_mutated_graph": False,
                "next_action": "revise_or_abandon",
                "correction_gate": outcome.get("correction_gate"),
                "correction_report": outcome.get("correction_report") or {},
            }
        if outcome.get("error") or outcome.get("error_code"):
            return {
                "kind": "REFUSED",
                "error_code": outcome.get("error_code") or "PROPOSAL_VALIDATION_FAILED",
                "message": str(outcome.get("error") or outcome.get("message") or ""),
                "current_graph_version": current,
                "validation": outcome,
                "agent_mutated_graph": False,
                "next_action": "revise_and_check",
            }
        if submit:
            return {
                "kind": "PENDING",
                "proposal_id": outcome["proposal_id"],
                "graph_version": outcome["graph_version"],
                "decision_origin": outcome.get("decision_origin", "unspecified"),
                "agent_mutated_graph": False,
                "next_action": "write_advance",
            }
        return {
            "kind": "VALID",
            "graph_version": outcome["graph_version"],
            "would_queue": outcome.get("would_queue"),
            "grain_verdict": outcome.get("grain_verdict", {}),
            "agent_mutated_graph": False,
            "next_action": "write_submit",
        }

    @staticmethod
    def _project(result: Mapping[str, Any]) -> dict[str, Any]:
        status = str(result.get("status") or "")
        report = result.get("correction_report") or {}
        base = {
            "proposal_id": result.get("proposal_id"),
            "status": status,
            "agent_mutated_graph": bool(result.get("agent_mutated_graph")),
            "correction_gate": result.get("correction_gate"),
            "correction_report": report,
            "gate_report": result.get("gate_report"),
            "error": result.get("error"),
        }
        if status == "COMMITTED":
            return {
                **base,
                "kind": "COMMITTED",
                "graph_version_after": result.get("graph_version_after"),
                "next_action": "done",
            }
        if status == "CORRECTION_REPORTED":
            requires = list(report.get("requires_escalation") or [])
            if requires:
                return {
                    **base,
                    "kind": "ESCALATE",
                    "requires_escalation": requires,
                    "acknowledgeable": list(report.get("acknowledgeable") or []),
                    "next_action": "human_review_or_refuse",
                }
            return {
                **base,
                "kind": "REPORT",
                "report_digest": report.get("report_digest"),
                "moves": report.get("moves") or {},
                "acknowledgeable": list(report.get("acknowledgeable") or []),
                "next_action": "acknowledge_and_advance",
            }
        if status == "CORRECTION_REFUSED":
            return {
                **base,
                "kind": "REFUSED",
                "error_code": "CORRECTION_REFUSED",
                "message": str(result.get("error") or report.get("detail") or ""),
                "next_action": "revise_or_abandon",
            }
        if status in ("GATE_FAILED", "ENCODE_FAILED", "GRAIN_FAILED"):
            return {
                **base,
                "kind": "REFUSED",
                "error_code": status,
                "message": str(result.get("error") or status),
                "next_action": "revise_or_abandon",
            }
        if result.get("error"):
            return {
                **base,
                "kind": "REFUSED",
                "error_code": "ADVANCE_FAILED",
                "message": str(result["error"]),
                "next_action": "revise_or_abandon",
            }
        return {**base, "kind": "UNKNOWN", "next_action": "inspect"}
