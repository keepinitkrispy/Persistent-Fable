#!/usr/bin/env python3
"""
fable-enforce/scripts/persistence.py

Cross-session state persistence for Fable Enforce.
Canonical state lives in GitHub; this script handles retrieval, verification,
and updates.

Usage:
    python3 persistence.py --retrieve-canonical <owner> <repo> <branch>
    python3 persistence.py --verify-state <fable_state.json>
    python3 persistence.py --add-violation <violation_json> <state_file>
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any


def sha256_file(path: str) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def retrieve_canonical_from_github(
    owner: str,
    repo: str,
    branch: str,
    state_file: str = "fable-enforce/fable_state.json"
) -> Optional[Dict[str, Any]]:
    """
    Retrieve canonical state from GitHub repository.
    Returns: (state_dict, commit_sha, file_sha256)
    """
    try:
        # Fetch the file contents from GitHub
        cmd = [
            "git", "show", f"origin/{branch}:{state_file}"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            print(f"ERROR: Could not retrieve {state_file} from {owner}/{repo}:{branch}")
            print(f"  stderr: {result.stderr}")
            return None

        state_data = json.loads(result.stdout)

        # Get commit SHA for this file
        cmd_sha = ["git", "rev-list", "-n", "1", f"origin/{branch}", "--", state_file]
        result_sha = subprocess.run(cmd_sha, capture_output=True, text=True, timeout=10)
        commit_sha = result_sha.stdout.strip() if result_sha.returncode == 0 else "unknown"

        # Compute hash of the content
        file_sha = hashlib.sha256(result.stdout.encode()).hexdigest()

        return {
            "state": state_data,
            "commit_sha": commit_sha,
            "file_sha256": file_sha,
            "retrieved_at": datetime.now().isoformat()
        }
    except Exception as e:
        print(f"ERROR retrieving canonical state: {e}")
        return None


def verify_state(state: Dict[str, Any]) -> bool:
    """Verify that state structure is valid and regression tests pass."""
    required_keys = ["version", "signatures", "seed_corpus", "audit_log"]
    for key in required_keys:
        if key not in state:
            print(f"ERROR: Missing required key in state: {key}")
            return False

    if not isinstance(state.get("signatures"), list):
        print("ERROR: 'signatures' must be a list")
        return False

    if not isinstance(state.get("seed_corpus"), list):
        print("ERROR: 'seed_corpus' must be a list")
        return False

    return True


def add_violation(
    violation: Dict[str, Any],
    state: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Add a newly caught violation to state.
    violation should contain: sig_id, name, taxonomy, patterns, suppressor_flag
    """
    sig_id = violation.get("sig_id")
    existing = [s for s in state["signatures"] if s["sig_id"] == sig_id]

    if existing:
        print(f"WARNING: Signature {sig_id} already exists, updating")
        idx = state["signatures"].index(existing[0])
        state["signatures"][idx].update(violation)
    else:
        state["signatures"].append(violation)

    # Log to audit
    audit_entry = {
        "timestamp": datetime.now().isoformat(),
        "action": "add_violation",
        "violation": violation
    }
    state["audit_log"].append(audit_entry)

    return state


def commit_state(
    state: Dict[str, Any],
    output_path: str,
    message: str
) -> bool:
    """Write state to file and prepare for commit."""
    try:
        with open(output_path, 'w') as f:
            json.dump(state, f, indent=2)
        print(f"State written to {output_path}")
        print(f"SHA256: {sha256_file(output_path)}")
        return True
    except Exception as e:
        print(f"ERROR writing state: {e}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrieve-canonical", nargs=3, metavar=("owner", "repo", "branch"),
                    help="Retrieve canonical state from GitHub")
    ap.add_argument("--verify-state", metavar="file",
                    help="Verify state file structure")
    ap.add_argument("--add-violation", nargs=2, metavar=("violation_json", "state_file"),
                    help="Add violation to state")
    ap.add_argument("--commit-state", nargs=2, metavar=("state_file", "message"),
                    help="Commit state to file")
    ap.add_argument("--json", action="store_true", help="Output as JSON")

    args = ap.parse_args()

    if args.retrieve_canonical:
        result = retrieve_canonical_from_github(*args.retrieve_canonical)
        if result:
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(f"✓ Retrieved canonical state")
                print(f"  Commit: {result['commit_sha'][:8]}...")
                print(f"  SHA256: {result['file_sha256'][:16]}...")
                print(f"  Signatures: {len(result['state'].get('signatures', []))}")

    elif args.verify_state:
        with open(args.verify_state) as f:
            state = json.load(f)
        if verify_state(state):
            print(f"✓ State structure valid")
            print(f"  Signatures: {len(state['signatures'])}")
            print(f"  Seed cases: {len(state['seed_corpus'])}")
            print(f"  Audit entries: {len(state.get('audit_log', []))}")
        else:
            sys.exit(1)

    elif args.add_violation:
        with open(args.add_violation[0]) as f:
            violation = json.load(f)
        with open(args.add_violation[1]) as f:
            state = json.load(f)
        state = add_violation(violation, state)
        with open(args.add_violation[1], 'w') as f:
            json.dump(state, f, indent=2)
        print(f"✓ Violation added")

    elif args.commit_state:
        with open(args.commit_state[0]) as f:
            state = json.load(f)
        if commit_state(state, args.commit_state[0], args.commit_state[1]):
            print("✓ State committed")
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()
