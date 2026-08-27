"""Handbook registry — SST architecture vs credential governance."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJ = Path(__file__).resolve().parents[1]

DEFAULT_HANDBOOK = "sst"


@dataclass(frozen=True)
class HandbookConfig:
    handbook_id: str
    label: str
    example_dir: Path
    db_filename: str
    gov_frame: str
    build_command: str

    @property
    def db_path(self) -> Path:
        return self.example_dir / self.db_filename


def credential_handbook_dir() -> Path:
    """Resolve handbook/ in the sibling credential-governance repository."""
    env = os.environ.get("CREDENTIAL_GOVERNANCE_REPO", "").strip()
    if env:
        base = Path(env).expanduser().resolve()
        hb = base / "handbook"
        return hb if hb.is_dir() else base
    sibling = (PROJ.parent / "credential-governance" / "handbook").resolve()
    if sibling.is_dir():
        return sibling
    legacy = PROJ / "examples" / "credential-governance"
    if legacy.is_dir():
        return legacy
    return sibling


def _credential_build_command() -> str:
    repo = credential_handbook_dir().parent
    return (
        f'cd "{repo}" && conda run -n agentic-graphrag python handbook/build_graph.py --rebuild'
    )


HANDBOOKS: dict[str, HandbookConfig] = {
    "sst": HandbookConfig(
        handbook_id="sst",
        label="SST architecture handbook",
        example_dir=PROJ / "examples" / "dogfood",
        db_filename="dogfood_sst.lbug",
        gov_frame=(
            "Resolve strictly per this system's published architecture handbook, and say "
            "so explicitly if no handbook rule governs it:\n{q}"
        ),
        build_command="conda run -n agentic-graphrag python examples/dogfood/build_graph.py --rebuild",
    ),
    "credential": HandbookConfig(
        handbook_id="credential",
        label="Credential & access governance handbook",
        example_dir=credential_handbook_dir(),
        db_filename="credential_governance.lbug",
        gov_frame=(
            "Resolve strictly per this credential and access governance handbook, and say "
            "so explicitly if no handbook rule governs it:\n{q}"
        ),
        build_command=_credential_build_command(),
    ),
}


def resolve_handbook(handbook: str | None = None) -> HandbookConfig:
    key = (handbook or DEFAULT_HANDBOOK).strip().lower()
    if key not in HANDBOOKS:
        known = ", ".join(sorted(HANDBOOKS))
        raise ValueError(f"Unknown handbook {handbook!r}. Known: {known}")
    return HANDBOOKS[key]


def ensure_handbook_path(cfg: HandbookConfig) -> None:
    ex = str(cfg.example_dir)
    proj = str(PROJ)
    for p in (proj, ex):
        if p not in sys.path:
            sys.path.insert(0, p)


def load_tagged_rules(cfg: HandbookConfig) -> list[Any]:
    ensure_handbook_path(cfg)
    if cfg.handbook_id == "credential":
        from credential_dispatch_rules import TAGGED_RULES

        return list(TAGGED_RULES)
    from dispatch_rules import TAGGED_RULES

    return list(TAGGED_RULES)


def load_dispatch_cases(cfg: HandbookConfig) -> list[dict]:
    ensure_handbook_path(cfg)
    if cfg.handbook_id == "credential":
        from credential_dispatch_cases import DISPATCH_CASES

        return list(DISPATCH_CASES)
    from dispatch_cases import DISPATCH_CASES

    return list(DISPATCH_CASES)


def load_rule_questions(cfg: HandbookConfig) -> dict[str, str]:
    ensure_handbook_path(cfg)
    if cfg.handbook_id == "credential":
        from rule_questions import RULE_QUESTIONS

        return dict(RULE_QUESTIONS)
    from conformance_check.framing import _RULE_QUESTIONS

    return dict(_RULE_QUESTIONS)


def load_scope_defaults(cfg: HandbookConfig) -> tuple[str, str]:
    ensure_handbook_path(cfg)
    if cfg.handbook_id == "credential":
        from rule_questions import SCOPE_MOAT_SUFFIX, SCOPE_QUESTION_DEFAULT

        return SCOPE_QUESTION_DEFAULT, SCOPE_MOAT_SUFFIX
    from conformance_check import framing as f

    return f._SCOPE_QUESTION_DEFAULT, f._SCOPE_MOAT_SUFFIX


