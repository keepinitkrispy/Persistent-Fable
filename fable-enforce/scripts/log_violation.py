#!/usr/bin/env python3
"""
fable-enforce/scripts/log_violation.py

Append a real, timestamped entry to audit_log.jsonl for a caught violation.
Timestamp comes from this process's clock at write time — not a guess, not
carried over from conversation context.

Usage:
    python3 log_violation.py --sig SIG-3 --context "text that matched" [--new-sig]
    python3 log_violation.py --sig scope_expansion --context "..." --taxonomy constraint_dropout --new-sig

After logging, run state_sync.py --push "..." separately to persist to GitHub —
this script only writes locally, so a local-only log entry can't silently be
reported as pushed.
"""
import argparse
import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT_LOG_PATH = os.path.join(HERE, "audit_log.jsonl")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sig", required=True, help="sig_id (e.g. SIG-3) or pending taxonomy name (e.g. scope_expansion)")
    ap.add_argument("--taxonomy", help="taxonomy class, required if --sig is not an existing SIG-N")
    ap.add_argument("--context", required=True, help="the actual matched/violating text")
    ap.add_argument("--new-sig", action="store_true", help="mark this as establishing a new signature, not a match of an existing one")
    args = ap.parse_args()

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sig": args.sig,
        "taxonomy": args.taxonomy,
        "context": args.context,
        "new_signature": args.new_sig,
    }
    with open(AUDIT_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"Logged locally to {AUDIT_LOG_PATH}. Run state_sync.py --push to persist to GitHub.")
    print(json.dumps(entry, indent=2))
    return 0


if __name__ == "__main__":
    exit(main())
