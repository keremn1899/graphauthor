"""Account / settings / BYO-key — the bill-later plumbing (v1, local).

The billing model is a flat monthly subscription with **bring-your-own-token**:
the operator supplies their own OpenRouter key, which this product never proxies,
meters, or transmits. So this module is small and has three parts:

- **Entitlement** — an account with a ``subscription_active`` flag + a check the
  surface consults. Stubbed ON in v1 (not charging); flipping it to real billing
  later is a switch, not a rewrite.
- **BYO-key management** — set (validate → encrypt-at-rest, local only), status
  (is a valid key set — WITHOUT ever returning it), get (decrypt, internal use to
  inject into the environment), clear. Never logged, never returned by the API.
- **Attribution** — the configured actor a receipt records ("Alice confirmed
  ADR-9"), so the coarse ``actor`` field becomes a real identity. Login/SSO is a
  later *source* for this same actor; local v1 populates it from config.

Encryption honesty: the key is Fernet-encrypted at rest with a per-install secret
stored 0600 beside it. This defends against casual reading, accidental logging,
and commits — NOT against an attacker with full disk access (the secret is
co-located). The real guarantees are 0600 perms, never-log, never-return, and
gitignore. A passphrase-derived secret (no at-rest secret) is the upgrade if a
stronger threat model is ever required.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(key: str) -> str:
    """A stable, non-reversing id for a key (so status can say *which* key without
    revealing it)."""
    return "fp_" + hashlib.sha256(key.encode()).hexdigest()[:12]


def _mask(key: str) -> str:
    """A human hint — enough to recognise the key, not enough to use it."""
    key = key or ""
    return f"{key[:6]}…{key[-4:]}" if len(key) > 12 else "…"


#: What an agent should DO when the graph does not decide.
#:
#: Two layers govern an agent here. The first — *how this system works* — is
#: already delivered: tool schemas say what the verbs mean, and `orient` returns
#: `capabilities` saying which it may call. The second — *what this operator
#: intends* — had no home at all, so it lived in a system prompt outside
#: anything the product could see or audit.
#:
#: Fragments of it were already being enforced, but as runtime errors: a
#: proposal without `target_gap_id` is refused, an L1 claim is demoted without
#: admission. The agent discovered the operator's intent by failing. Announcing
#: it at `orient` beats erroring at `propose`.
#:
#: Advisory, deliberately. Posture tells an agent what is *wanted*; capability
#: gating and the write path decide what is *allowed*. An operator loosening
#: posture can never grant authority, so this stays configuration rather than
#: becoming a second, weaker permission system.
POSTURE_ACTIONS = ("escalate", "propose", "stop", "proceed")

def _default_posture() -> dict[str, Any]:
    return {
        # UNGOVERNED means the graph does not cover this. Escalating by default
        # puts it in front of a human rather than letting an agent invent the
        # missing governance itself.
        "on_ungoverned": "escalate",
        # "I cannot tell" is the one case where guessing is worst.
        "on_insufficient_evidence": "stop",
        # VIOLATES is a decision the graph actually made; the default is to
        # respect it rather than route it to a human for override.
        "on_violates": "stop",
        # Ceiling on what a proposal may claim, independent of admission.
        "max_claim_level": "L0",
        # Free text from the operator to any agent reading orient.
        "notes": "",
    }


def _default_settings() -> dict[str, Any]:
    return {
        "account_id": "local",
        "actor": "operator",
        "posture": _default_posture(),
        # stubbed ON in v1 — not charging. The switch-flip point for billing.
        "subscription": {"active": True, "plan": "v1_local", "since": _now_iso()},
        "model_prefs": {},
        "key": {"set": False, "valid": False, "last_validated": "",
                "fingerprint": "", "masked": ""},
    }


def openrouter_validator(key: str) -> tuple[bool, str]:
    """Default real validator: a cheap authenticated request. Network call — the
    surface may pass this; tests inject a fake. Never called automatically."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return (200 <= r.status < 300), f"http_{r.status}"
    except urllib.error.HTTPError as e:
        return False, f"http_{e.code}"
    except Exception as e:
        return False, f"unreachable:{type(e).__name__}"


class Account:
    """One local account/settings directory."""

    def __init__(self, base_dir: Path | str) -> None:
        self.dir = Path(base_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.dir / "account.json"
        self.key_path = self.dir / ".byok.enc"
        self.secret_path = self.dir / ".byok.secret"

    # --- settings ---------------------------------------------------------
    def load(self) -> dict[str, Any]:
        if not self.settings_path.exists():
            return _default_settings()
        try:
            s = json.loads(self.settings_path.read_text())
        except (ValueError, OSError):
            return _default_settings()
        # merge over defaults so new fields appear on old files
        base = _default_settings()
        base.update({k: v for k, v in s.items() if k != "key"})
        base["key"].update(s.get("key", {}))
        return base

    def save(self, settings: dict[str, Any]) -> None:
        self.settings_path.write_text(json.dumps(settings, indent=2))
        try:
            os.chmod(self.settings_path, 0o600)
        except OSError:
            pass

    # --- entitlement ------------------------------------------------------
    def is_entitled(self) -> bool:
        """The billing gate: is the subscription active? Stubbed ON in v1."""
        return bool(self.load().get("subscription", {}).get("active", False))

    def set_subscription(self, *, active: bool, plan: str | None = None) -> dict[str, Any]:
        s = self.load()
        s["subscription"]["active"] = bool(active)
        if plan is not None:
            s["subscription"]["plan"] = plan
        s["subscription"]["updated"] = _now_iso()
        self.save(s)
        return s["subscription"]

    # --- attribution ------------------------------------------------------
    def current_actor(self) -> str:
        return str(self.load().get("actor") or "operator")

    # --- posture ----------------------------------------------------------
    def posture(self) -> dict[str, Any]:
        """The operator's intent for agents. Always complete: unknown or absent
        fields fall back to the default rather than being reported empty, so an
        agent never has to guess what an unset posture means."""
        stored = self.load().get("posture")
        merged = _default_posture()
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in merged:
                    merged[key] = value
        return merged

    def set_posture(self, **fields: Any) -> dict[str, Any]:
        """Update posture. Rejects unknown keys and unknown actions rather than
        storing them: a typo that silently did nothing would be worse than an
        error, because the operator would believe they had set a policy."""
        current = self.posture()
        for key, value in fields.items():
            if value is None:
                continue
            if key not in current:
                raise ValueError(f"unknown posture field: {key}")
            if key.startswith("on_") and str(value) not in POSTURE_ACTIONS:
                raise ValueError(
                    f"{key} must be one of {', '.join(POSTURE_ACTIONS)}")
            if key == "max_claim_level" and str(value).upper() not in ("L0", "L1"):
                raise ValueError("max_claim_level must be L0 or L1")
            current[key] = (str(value).upper() if key == "max_claim_level"
                            else str(value))
        s = self.load()
        s["posture"] = current
        self.save(s)
        return current

    def set_actor(self, actor: str) -> None:
        s = self.load()
        s["actor"] = str(actor or "operator")
        self.save(s)

    def set_model_prefs(self, **prefs: Any) -> dict[str, Any]:
        s = self.load()
        s["model_prefs"].update({k: v for k, v in prefs.items() if v is not None})
        self.save(s)
        return s["model_prefs"]

    # --- BYO key ----------------------------------------------------------
    def _fernet(self):
        from cryptography.fernet import Fernet
        if not self.secret_path.exists():
            self.secret_path.write_bytes(Fernet.generate_key())
            try:
                os.chmod(self.secret_path, 0o600)
            except OSError:
                pass
        return Fernet(self.secret_path.read_bytes())

    def set_key(self, key: str, *, validator: Callable[[str], tuple[bool, str]] | None = None
                ) -> dict[str, Any]:
        """Validate (if a validator is given), then encrypt-at-rest. An invalid
        key is REFUSED — never stored. Returns the status metadata (never the key)."""
        key = (key or "").strip()
        if not key:
            raise ValueError("empty key")
        valid, detail = True, "not_validated"
        if validator is not None:
            valid, detail = validator(key)
            if not valid:
                return {"set": False, "valid": False, "detail": detail,
                        "fingerprint": _fingerprint(key), "masked": _mask(key)}
        token = self._fernet().encrypt(key.encode())
        self.key_path.write_bytes(token)
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        meta = {"set": True, "valid": bool(valid),
                "last_validated": _now_iso() if validator is not None else "",
                "fingerprint": _fingerprint(key), "masked": _mask(key), "detail": detail}
        s = self.load()
        s["key"] = meta
        self.save(s)
        return meta

    def key_status(self) -> dict[str, Any]:
        """Status WITHOUT the key — {set, valid, last_validated, fingerprint,
        masked}. The API surface returns this; it can never leak the secret."""
        st = self.load().get("key", {})
        return {k: st.get(k, "") for k in
                ("set", "valid", "last_validated", "fingerprint", "masked")}

    def get_key(self) -> str | None:
        """Decrypt the stored key for INTERNAL use (e.g. injecting into the env so
        LLM calls use the operator's own credential). Never expose over the API."""
        if not self.key_path.exists() or not self.secret_path.exists():
            return None
        try:
            return self._fernet().decrypt(self.key_path.read_bytes()).decode()
        except Exception:
            return None

    def clear_key(self) -> None:
        for p in (self.key_path,):
            try:
                p.unlink()
            except OSError:
                pass
        s = self.load()
        s["key"] = _default_settings()["key"]
        self.save(s)

    def apply_key_to_env(self) -> bool:
        """Inject the BYO key into OPENROUTER_API_KEY so the operator's own
        credential is what LLM calls use. Returns True if a key was applied."""
        k = self.get_key()
        if k:
            os.environ["OPENROUTER_API_KEY"] = k
            return True
        return False


def default_account() -> Account:
    """Account dir from SST_MCP_ACCOUNT_PATH, else ~/.graphauthor/account.

    Soft rename: prefer ``~/.graphauthor/account``; if missing, keep using
    ``~/.aporta/account`` or ``~/.cke/account``.
    """
    env = os.environ.get("SST_MCP_ACCOUNT_PATH")
    if env:
        return Account(env)
    current = Path.home() / ".graphauthor" / "account"
    aporta = Path.home() / ".aporta" / "account"
    legacy = Path.home() / ".cke" / "account"
    if not current.exists():
        if aporta.exists():
            return Account(str(aporta))
        if legacy.exists():
            return Account(str(legacy))
    return Account(str(current))
