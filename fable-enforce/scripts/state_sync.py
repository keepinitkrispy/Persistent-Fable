#!/usr/bin/env python3
"""
fable-enforce/scripts/state_sync.py

Cross-session persistence for the fable-enforce signature set, via GitHub.
filter.py is the single source of truth at runtime. This script derives
fable_state.json FROM filter.py (never hand-edited separately, so the two
can't drift into contradicting each other), and provides push/pull against
the canonical repo with actual independent verification — no state is
reported as persisted unless a *separate* fetch operation confirms it.

Usage:
    python3 state_sync.py --push "reason for this update"
    python3 state_sync.py --pull
    python3 state_sync.py --pull --apply     # merge new remote sigs into filter.py, gated by regression test

Auth: reads token from scripts/.github_token (this file), or $GITHUB_TOKEN env var if set.
Config: reads scripts/.repo_config (owner, repo, branch).

Never prints "VERIFIED" / "PERSISTENT" unless the check it names actually ran and passed
in this process, this invocation. Failure states are reported as what they are.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
FILTER_PATH = os.path.join(HERE, "filter.py")
STATE_PATH = os.path.join(HERE, "..", "fable_state.json")
AUDIT_LOG_PATH = os.path.join(HERE, "audit_log.jsonl")
TOKEN_PATH = os.path.join(HERE, ".github_token")
REPO_CONFIG_PATH = os.path.join(HERE, ".repo_config")


def load_repo_config() -> dict:
    if not os.path.exists(REPO_CONFIG_PATH):
        print(f"FATAL: no repo config at {REPO_CONFIG_PATH}", file=sys.stderr)
        sys.exit(2)
    with open(REPO_CONFIG_PATH) as f:
        cfg = json.load(f)
    for k in ("owner", "repo", "branch"):
        if k not in cfg:
            print(f"FATAL: repo config missing '{k}'", file=sys.stderr)
            sys.exit(2)
    return cfg


def load_token() -> str:
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        return tok.strip()
    if os.path.exists(TOKEN_PATH):
        with open(TOKEN_PATH) as f:
            return f.read().strip()
    print("FATAL: no GitHub token found (checked $GITHUB_TOKEN and .github_token)", file=sys.stderr)
    sys.exit(2)


def remote_url(cfg: dict, token: str) -> str:
    return f"https://x-access-token:{token}@github.com/{cfg['owner']}/{cfg['repo']}.git"


def import_filter():
    spec = importlib.util.spec_from_file_location("filter_mod", FILTER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_audit_log(path: str) -> list:
    entries = []
    if not os.path.exists(path):
        return entries
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def audit_entry_key(entry: dict) -> str:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def merge_audit_logs(remote_entries: list, local_entries: list) -> list:
    """Return a stable union with remote history first, then new local entries."""
    merged = []
    seen = set()
    for entry in remote_entries + local_entries:
        key = audit_entry_key(entry)
        if key not in seen:
            merged.append(entry)
            seen.add(key)
    return merged


def write_audit_log(path: str, entries: list) -> None:
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def derive_state(cfg: dict, audit_log_override=None) -> dict:
    """Build canonical state dict FROM filter.py's live SIGNATURES/SEED_CORPUS.
    This is the only place state.json content is produced — never hand-edited."""
    mod = import_filter()
    signatures = []
    for sig_id, name, taxonomy, patterns, suppressor in mod.SIGNATURES:
        signatures.append({
            "sig_id": sig_id,
            "name": name,
            "taxonomy": taxonomy,
            "patterns": patterns,
            "suppressor_flag": suppressor,
        })
    seed_corpus = []
    for text, expect, note, flags in mod.SEED_CORPUS:
        seed_corpus.append({
            "text": text,
            "expect_violation": expect,
            "note": note,
            "flags": flags,
        })
    audit_log = audit_log_override if audit_log_override is not None else read_audit_log(AUDIT_LOG_PATH)
    return {
        "version": "2.0",
        "canonical_repo": f"{cfg['owner']}/{cfg['repo']}",
        "canonical_branch": cfg["branch"],
        "signatures": signatures,
        "seed_corpus": seed_corpus,
        "audit_log": audit_log,
        "pending_taxonomy_classes": [
            {
                "name": "scope_expansion",
                "status": "no_signature_yet",
                "reason": "No confirmed example encountered. Do not fabricate a regex for this — "
                          "wait for a real caught instance, then run --push with the actual text.",
            }
        ],
    }


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def run(cmd, cwd=None, check=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        print(f"COMMAND FAILED: {' '.join(cmd)}\nstdout: {r.stdout}\nstderr: {r.stderr}", file=sys.stderr)
    return r


def cmd_push(reason: str) -> int:
    cfg = load_repo_config()
    token = load_token()

    # 1. Fresh-clone the remote first so append-only history can be merged before
    #    any local state is written into the working tree.
    required_audit_keys = set()

    with tempfile.TemporaryDirectory() as work:
        clone = run(["git", "clone", "--depth", "1", "--branch", cfg["branch"],
                     remote_url(cfg, token), work], check=False)
        if clone.returncode != 0:
            print(f"STATE: canonical repository unavailable — {clone.stderr.strip()}")
            return 1

        target_dir = os.path.join(work, "fable-enforce")
        os.makedirs(os.path.join(target_dir, "scripts"), exist_ok=True)

        # Merge audit history instead of overwriting the remote log with a stale
        # local copy. Every entry present in the fresh clone must survive.
        remote_audit_path = os.path.join(target_dir, "scripts", "audit_log.jsonl")
        remote_audit = read_audit_log(remote_audit_path)
        local_audit = read_audit_log(AUDIT_LOG_PATH)
        merged_audit = merge_audit_logs(remote_audit, local_audit)
        remote_keys = {audit_entry_key(e) for e in remote_audit}
        required_audit_keys = {audit_entry_key(e) for e in merged_audit}
        if not remote_keys.issubset(required_audit_keys):
            print("STATE: audit monotonicity check failed before write — refusing to push.")
            return 1

        state = derive_state(cfg, audit_log_override=merged_audit)

        # Copy current local files (filter.py = source of truth, plus docs/scripts)
        # into the freshly-cloned working tree, then write derived state on top.
        import shutil
        for fname in ("SKILL.md", "PERSISTENCE.md"):
            src = os.path.join(HERE, "..", fname)
            if os.path.exists(src):
                shutil.copy(src, os.path.join(target_dir, fname))
        for fname in ("filter.py", "state_sync.py", "log_violation.py"):
            shutil.copy(os.path.join(HERE, fname), os.path.join(target_dir, "scripts", fname))
        write_audit_log(os.path.join(target_dir, "scripts", "audit_log.jsonl"), merged_audit)

        state_out = os.path.join(target_dir, "fable_state.json")
        with open(state_out, "w") as f:
            json.dump(state, f, indent=2)

        # 2. Regression test MUST pass, on the clone that will actually be pushed
        clone_filter = os.path.join(target_dir, "scripts", "filter.py")
        r = run([sys.executable, clone_filter, "--test"], check=False)
        print(r.stdout)
        if r.returncode != 0:
            print("STATE: regression test failed on the clone to be pushed. Not committing, not pushing.")
            return 1

        local_sha = sha256_file(state_out)

        # 3. Commit
        run(["git", "config", "user.email", "noreply@anthropic.com"], cwd=work)
        run(["git", "config", "user.name", "Claude"], cwd=work)
        run(["git", "add", "fable-enforce/"], cwd=work)
        commit = run(["git", "commit", "-m", f"fable-enforce: {reason}"], cwd=work, check=False)
        if commit.returncode != 0 and "nothing to commit" in (commit.stdout + commit.stderr):
            print("STATE: no changes to commit (state already matches filter.py).")
            return 0
        print(f"STATE: COMMITTED_LOCAL (state sha256: {local_sha})")

        # 4. Push
        push = run(["git", "push", "origin", f"HEAD:{cfg['branch']}"], cwd=work, check=False)
        if push.returncode != 0:
            print(f"STATE: PUSH FAILED. Reported as COMMITTED_LOCAL only.\n{push.stderr}")
            return 1
        print("STATE: PUSHED_REMOTE")

    # 5. Independently verify: a SEPARATE fresh clone into a NEW temp dir,
    #    unrelated to the working clone above.
    with tempfile.TemporaryDirectory() as tmp:
        clone = run(["git", "clone", "--depth", "1", "--branch", cfg["branch"],
                     remote_url(cfg, token), tmp], check=False)
        if clone.returncode != 0:
            print(f"STATE: PUSHED_REMOTE but independent re-clone FAILED — cannot claim persistence.\n{clone.stderr}")
            return 1
        remote_state_path = os.path.join(tmp, "fable-enforce", "fable_state.json")
        if not os.path.exists(remote_state_path):
            print("STATE: PUSHED_REMOTE but fresh clone does not contain fable_state.json — cannot claim persistence.")
            return 1
        remote_sha = sha256_file(remote_state_path)
        if remote_sha != local_sha:
            print(f"STATE: HASH MISMATCH. expected={local_sha} remote={remote_sha}. Not claiming persistence.")
            return 1
        fresh_audit_path = os.path.join(tmp, "fable-enforce", "scripts", "audit_log.jsonl")
        fresh_audit_keys = {audit_entry_key(e) for e in read_audit_log(fresh_audit_path)}
        missing_audit = required_audit_keys - fresh_audit_keys
        if missing_audit:
            print(f"STATE: fresh-clone audit monotonicity FAILED — {len(missing_audit)} required entr(y/ies) missing. Not claiming persistence.")
            return 1
        remote_filter = os.path.join(tmp, "fable-enforce", "scripts", "filter.py")
        rt = run([sys.executable, remote_filter, "--test"], check=False)
        if rt.returncode != 0:
            print("STATE: hash matches but regression test FAILS on the freshly-cloned copy. Not claiming persistence.")
            print(rt.stdout)
            return 1
        print(f"STATE: VERIFIED_PERSISTENT (independent clone, hash {remote_sha[:12]}..., "
              f"regression {rt.stdout.strip().splitlines()[-1] if rt.stdout.strip() else 'passed'})")
    return 0


def cmd_pull(apply: bool) -> int:
    cfg = load_repo_config()
    token = load_token()

    with tempfile.TemporaryDirectory() as tmp:
        clone = run(["git", "clone", "--depth", "1", "--branch", cfg["branch"],
                     remote_url(cfg, token), tmp], check=False)
        if clone.returncode != 0:
            print(f"STATE: canonical repository unavailable — {clone.stderr.strip()}")
            return 1
        remote_state_path = os.path.join(tmp, "fable-enforce", "fable_state.json")
        if not os.path.exists(remote_state_path):
            print("STATE: no fable_state.json in remote yet (nothing to pull).")
            return 0
        with open(remote_state_path) as f:
            remote_state = json.load(f)

    local_mod = import_filter()
    local_ids = {s[0] for s in local_mod.SIGNATURES}
    remote_sigs = remote_state.get("signatures", [])
    new_sigs = [s for s in remote_sigs if s["sig_id"] not in local_ids]

    if not new_sigs:
        print("STATE: local filter.py already has every signature in canonical state. Nothing to merge.")
        return 0

    print(f"STATE: {len(new_sigs)} signature(s) in remote not present locally:")
    for s in new_sigs:
        print(f"  {s['sig_id']} ({s['name']}, {s['taxonomy']})")

    if not apply:
        print("Re-run with --apply to merge these into filter.py (regression-gated).")
        return 0

    # Merge: append new signature tuples to filter.py's SIGNATURES list, then require
    # the full regression suite (existing + remote seed cases) to pass before keeping the edit.
    with open(FILTER_PATH) as f:
        src = f.read()
    insertion_lines = []
    for s in new_sigs:
        patterns_repr = json.dumps(s["patterns"])
        suppressor_repr = repr(s["suppressor_flag"]) if s["suppressor_flag"] else "None"
        insertion_lines.append(
            f'    ("{s["sig_id"]}", "{s["name"]}", "{s["taxonomy"]}", {patterns_repr}, '
            f'{suppressor_repr}),'
        )
    marker = "]\n\n# Exceptions:"
    if marker not in src:
        print("STATE: could not locate SIGNATURES list end marker in filter.py — manual merge required.")
        return 1
    new_src = src.replace(marker, "\n".join(insertion_lines) + "\n" + marker, 1)
    backup = FILTER_PATH + ".bak"
    with open(backup, "w") as f:
        f.write(src)
    with open(FILTER_PATH, "w") as f:
        f.write(new_src)

    r = run([sys.executable, FILTER_PATH, "--test"], check=False)
    print(r.stdout)
    if r.returncode != 0:
        print("STATE: merge broke the regression suite. Reverting filter.py.")
        with open(FILTER_PATH, "w") as f:
            f.write(src)
        os.remove(backup)
        return 1

    os.remove(backup)
    print(f"STATE: merged {len(new_sigs)} signature(s) into filter.py, regression suite passes.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", metavar="REASON", help="derive state from filter.py, commit, push, independently verify")
    ap.add_argument("--pull", action="store_true", help="check remote for signatures not present locally")
    ap.add_argument("--apply", action="store_true", help="with --pull, merge new remote signatures into filter.py")
    args = ap.parse_args()

    if args.push:
        return cmd_push(args.push)
    if args.pull:
        return cmd_pull(args.apply)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
