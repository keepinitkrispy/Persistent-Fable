# Outcome Gate · shadow runtime v4.2

Apply `.claude/rules/execution-contract.md` on every task. The contract and response/decision checks are active independently of whether an objective JSON file has been configured. See `fable-enforce/HOOKS.md` for registered hooks and invocation receipts.

When `.fable/active_objective.json` exists, treat its frozen objective and v4.2 execution record as the live task state.

- Keep the objective statement, baseline, and target fixed. To change a target, create a new objective revision and preserve the prior record.
- Do not mark progress from prose, a successful tool call, clean tests, generated code, or an assistant assertion. Record progress only after the measured real-world state changes.
- Do not claim PASS until the measured value changed from baseline, meets the frozen target, and has distinct before/after artifact hashes with source checks attested.
- Source checks are user attestations. Never describe the harness as independently authenticating external evidence.
- For open-world discovery, record at least five candidate fields, with each field's native solution, objective mapping, attacked assumption, reachability variable, and executable discriminator with support/reject outcomes. Select exactly two materially different routes before starting solver/search work.
- Execute both selected discriminators. If both fail to advance the target, retire the generation, record the evidence-based blocker reassessment, then continue only in a fresh child divergence generation.
- Keep taking executable next actions while the target is unmet. The Stop hook checks `.fable/active_objective.json` and blocks a turn that has not reached PASS.
- Before comparing actions, weighting evidence, asserting a boundary, or reusing a conclusion after a premise changed, write the short factual decision record to the session-specific path supplied by UserPromptSubmit, using its current turn_id. The Stop hook automatically runs the checker. K-1..K-5 violations invalidate the trace. Never use fabricated evidence or a canned trace to satisfy the checker.
- Persist actual state changes into the active JSON record, then reimport the updated export into Outcome Gate. Never edit an evidence hash or claim an external state transition that did not occur.

Use `fable-enforce/scripts/objective_gate.py --test` to verify the local outcome gate. The browser UI stores objective data in browser storage and exported JSON; it does not sync between devices automatically.

Honor explicit user stop/cancel requests. Stopping at the user’s direction leaves the objective open; it never establishes PASS.
