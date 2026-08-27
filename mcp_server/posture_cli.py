"""Operator CLI for agent posture — what agents should DO when the graph does
not decide.

    python -m mcp_server.posture_cli show <settings-dir>
    python -m mcp_server.posture_cli set  <settings-dir> \
        --on-ungoverned escalate --on-insufficient-evidence stop \
        --on-violates stop --max-claim-level L0 --notes "..."

Two layers instruct an agent. The first — how this system works — the tool
schemas and `orient`'s `capabilities` already deliver. The second — what *this
operator* intends — had nowhere to live, so it sat in a system prompt outside
anything the product could see or audit. This is that second layer, and agents
read it back from `orient`.

Advisory by design. Posture says what is wanted; capability gating and the write
path decide what is allowed. Loosening posture can never grant authority, which
is what keeps it configuration rather than a second, weaker permission system.

`<settings-dir>` is the directory holding `account.json` — the same directory
the operator store lives in.
"""

from __future__ import annotations

import json
import sys

_FLAGS = {
    "--on-ungoverned": "on_ungoverned",
    "--on-insufficient-evidence": "on_insufficient_evidence",
    "--on-violates": "on_violates",
    "--max-claim-level": "max_claim_level",
    "--notes": "notes",
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__)
        return 2
    cmd, rest = args[0], args[1:]

    from mcp_server.account import Account

    if cmd == "show" and len(rest) == 1:
        print(json.dumps(Account(rest[0]).posture(), indent=2))
        return 0

    if cmd == "set" and rest:
        account = Account(rest[0])
        fields: dict[str, str] = {}
        i = 1
        while i < len(rest):
            flag = rest[i]
            if flag not in _FLAGS:
                print(f"unknown option: {flag}\n\n{__doc__}")
                return 2
            if i + 1 >= len(rest):
                print(f"{flag} needs a value")
                return 2
            fields[_FLAGS[flag]] = rest[i + 1]
            i += 2
        if not fields:
            print("nothing to set")
            return 2
        try:
            print(json.dumps(account.set_posture(**fields), indent=2))
        except ValueError as exc:
            print(str(exc))
            return 1
        return 0

    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
