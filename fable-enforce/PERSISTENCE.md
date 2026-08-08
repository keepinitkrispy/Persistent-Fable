# fable-enforce cross-session persistence

## Canonical repository
- Owner: keepinitkrispy
- Repo: persistent-fable
- Branch: main
- File: fable-enforce/fable_state.json (derived output, not hand-edited)

## Source of truth
`scripts/filter.py` is authoritative at runtime. `fable_state.json` is generated
FROM filter.py by `state_sync.py --push`, every time, from scratch — it cannot
drift out of sync with filter.py because it's never edited independently.

## Commands
```bash
python3 scripts/state_sync.py --pull            # check remote for signatures not present locally
python3 scripts/state_sync.py --pull --apply    # merge them in, regression-gated
python3 scripts/state_sync.py --push "reason"   # derive state from filter.py, commit, push, verify
python3 scripts/log_violation.py --sig SIG-3 --context "actual matched text"
```

## What each reported state actually means
- `COMMITTED_LOCAL` — committed in the local git working tree only. Not yet on GitHub.
- `PUSHED_REMOTE` — `git push` exited 0. Not yet independently confirmed.
- `VERIFIED_PERSISTENT` — a *separate* fresh clone (new temp directory, new git
  clone operation, not the working tree that just pushed) was hashed and its
  filter.py regression suite run, in this same invocation, and both passed.
  This is the only state where "the state now lives in GitHub and is retrievable
  independent of this session" is actually established, not merely claimed.

If push fails, that's reported as `COMMITTED_LOCAL`, full stop. If the independent
clone/hash/regression check fails for any reason, that's reported explicitly with
which check failed — never silently upgraded to VERIFIED_PERSISTENT.

## Known limitation
This is pull/push on request, triggered by a tool call in a session that has
bash + network access. It is not a background daemon and nothing runs
"automatically" between sessions — a new conversation must actually run
`--pull` for its filter.py to pick up signatures added elsewhere. If the
current environment doesn't have bash or network access, that should be
stated plainly rather than assumed to have synced.

## History
2026-08-08: an earlier version of this file and an accompanying
`verification_report.md` claimed `VERIFIED_PERSISTENT` status while pointing
`canonical_repo` at a different, unrelated repository (`keepinitkrispy/gemini`)
and while `audit_log.jsonl` had zero entries. That version was removed rather
than repaired, since the claim itself was the problem, not just the config.
