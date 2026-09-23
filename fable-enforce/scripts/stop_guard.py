#!/usr/bin/env python3
"""Claude Code Stop hook for a locally exported Outcome Gate record."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from objective_gate import check_state, completion_state

ROOT = Path(__file__).resolve().parents[2]
STATE_FILE = ROOT / ".fable" / "active_objective.json"


def main() -> int:
    # No objective record means this repo's gate has not been activated.
    if not STATE_FILE.exists():
        return 0
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(json.dumps({"decision": "block", "reason": f"Outcome Gate state cannot be read: {exc}"}))
        return 0
    result = completion_state(state)
    violations = check_state(state)
    if result["pass"] and not violations:
        return 0
    blockers = "; ".join(f"{code}:{name} — {detail}" for code, name, detail in violations)
    reason = (
        "Outcome Gate / shadow runtime v4.2 blocks ending this Claude Code turn: "
        f"objective={result['status']}, changed={result['changed']}, target_met={result['target_met']}, "
        f"before/after evidence hashes differ={result['evidence_hashes_differ']}. "
        "Execute the next real-world transition or update the record with source-attested before/after artifacts. "
        "A successful command, clean scan, code change, or claim alone is not a pass."
    )
    if blockers:
        reason += f" Gate findings: {blockers}"
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
