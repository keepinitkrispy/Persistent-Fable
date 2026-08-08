# Fable Enforce Cross-Session Persistence

## Objective
Make Fable Enforce's canonical state persist across separate Claude conversations by storing it in a GitHub repository.

## Architecture

### Canonical State Location
- Repository: `keepinitkrispy/gemini`
- Branch: `claude/fable-enforce-persistence-mesho5`
- Path: `fable-enforce/fable_state.json`

### Files
- `fable-enforce/fable_state.json` — canonical state (signatures, seed corpus, audit log)
- `fable-enforce/scripts/filter.py` — violation detection (unchanged from skill)
- `fable-enforce/scripts/persistence.py` — state retrieval and verification
- `fable-enforce/scripts/audit_log.jsonl` — detailed violation audit trail (append-only)
- `fable-enforce/PERSISTENCE.md` — this file

### State Structure
```json
{
  "version": "1.0",
  "created": "2026-08-08",
  "canonical_repo": "keepinitkrispy/gemini",
  "signatures": [
    {
      "sig_id": "SIG-1",
      "name": "deferred_action",
      "taxonomy": "constraint_dropout",
      "patterns": ["regex1", "regex2", ...],
      "suppressor_flag": null
    },
    ...
  ],
  "seed_corpus": [
    {
      "text": "test case",
      "expect_violation": true,
      "note": "description",
      "flags": {}
    },
    ...
  ],
  "audit_log": [
    {
      "timestamp": "2026-08-08T...",
      "action": "add_violation",
      "violation": {...}
    },
    ...
  ],
  "regression_test_pass": true
}
```

## Session Start Protocol

1. **Retrieve** canonical state from GitHub:
   ```bash
   git fetch origin claude/fable-enforce-persistence-mesho5
   python3 fable-enforce/scripts/persistence.py --retrieve-canonical keepinitkrispy gemini claude/fable-enforce-persistence-mesho5
   ```

2. **Verify** state structure and contents:
   ```bash
   python3 fable-enforce/scripts/persistence.py --verify-state fable-enforce/fable_state.json
   ```

3. **Load** signatures and seed corpus into runtime:
   ```python
   import json
   with open("fable-enforce/fable_state.json") as f:
       state = json.load(f)
   signatures = state["signatures"]
   seed_corpus = state["seed_corpus"]
   ```

## Violation Detection and Persistence

When a new violation is caught and classified:

1. **Add** new signature to state (if novel):
   ```json
   {
     "sig_id": "SIG-N",
     "name": "violation_name",
     "taxonomy": "taxonomy_class",
     "patterns": ["regex"],
     "suppressor_flag": null
   }
   ```

2. **Add seed case** with regression test:
   ```json
   {
     "text": "actual violation text",
     "expect_violation": true,
     "note": "context of detection",
     "flags": {}
   }
   ```

3. **Run regression suite**:
   ```bash
   python3 fable-enforce/scripts/filter.py --test
   ```

4. **Only if suite passes**: Update `fable_state.json`

5. **Commit** changes:
   ```bash
   git add fable-enforce/
   git commit -m "fable-enforce: add SIG-N (violation_name)"
   ```

6. **Push** to canonical repository:
   ```bash
   git push -u origin claude/fable-enforce-persistence-mesho5
   ```

7. **Verify** push succeeded by independent retrieval (next session)

## Independent Verification (Cross-Session)

To verify persistence across sessions:

1. In new session/environment, fetch the repository fresh
2. Retrieve canonical state:
   ```bash
   git fetch origin claude/fable-enforce-persistence-mesho5
   python3 fable-enforce/scripts/persistence.py --retrieve-canonical keepinitkrispy gemini claude/fable-enforce-persistence-mesho5 --json
   ```
3. Record commit SHA and file SHA-256
4. Hash local copy: `sha256sum fable-enforce/fable_state.json`
5. Verify hash matches remote
6. Verify new signature is present in signatures list
7. Run regression suite:
   ```bash
   python3 fable-enforce/scripts/filter.py --test
   ```

## State Transitions

- **LOCAL_ONLY**: File written to local working tree
- **COMMITTED_LOCAL**: File committed in local git
- **PUSHED_REMOTE**: Commit pushed to GitHub
- **RETRIEVED_INDEPENDENTLY**: File fetched from GitHub in separate session
- **VERIFIED_PERSISTENT**: Independent retrieval hash matches, regression tests pass

Never use "VERIFIED" for a weaker state.

## Audit Trail

`audit_log.jsonl` is append-only and logs:
- Timestamp (ISO 8601)
- Action type (add_violation, update_signature, regression_pass, regression_fail)
- Violation/change details
- Operator (CLI tool or session context)

Example:
```json
{"timestamp": "2026-08-08T12:34:56.789Z", "action": "add_violation", "sig_id": "SIG-6", "detected_in_message": true}
{"timestamp": "2026-08-08T12:34:57.012Z", "action": "regression_pass", "total_cases": 14}
```

## Error Handling

- **Push fails**: Report as COMMITTED_LOCAL, stop. Do not convert to "saved" or "persistent".
- **Verify fails**: Report mismatches explicitly (commit SHA, file hash, signature count).
- **Regression fails**: Revert state, do not push.
- **GitHub unreachable**: Clearly state "canonical repository unavailable" — do not fabricate sync.
