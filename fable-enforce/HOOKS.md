# Installed governance integration

The project contract supplied by Ryan is installed verbatim in
`.claude/rules/execution-contract.md`. The repository's newer filter and kernel
checker are retained: they contain the supplied checks plus later fixes.

`.claude/settings.json` registers Python command hooks:

- SessionStart loads the contract, including after compact/resume events.
- UserPromptSubmit creates a fresh, session-specific turn ID and supplies the
  decision-record path. The agent writes a short factual record there.
- Stop scans `last_assistant_message`, validates the decision record for that
  exact turn, and checks `.fable/active_objective.json` when present. A missing
  objective file does not disable response or decision checks. Missing messages,
  missing/stale traces, unreadable state, and checker exceptions block stopping.
  `stop_hook_active=true` does not bypass checks.

Local invocation receipts are appended under `.fable/runtime/<session-hash>/`.
They contain status, hashes, and findings rather than full prompts/responses.
SessionStart `loaded`, UserPromptSubmit `started`, and Stop `blocked`/`allowed`
receipts distinguish configuration from actual invocation in that checkout.
`allowed` is a mechanical check result, never an objective PASS.

An exact user stop/cancel prompt ends that turn with `user_stopped`, leaving the
objective intact. User interrupts remain under the host's control.

## Verification and activation

`python3 -m unittest discover -s fable-enforce/scripts -p 'test_*.py' -v`
executes the actual configured commands in temporary checkouts. These tests run
on GitHub Actions as well. No model API, token, or paid service is introduced.

A Claude Code session must load this repository revision and its project hooks.
Existing sessions using an older checkout need that checkout updated and the
session restarted. A remote commit/CI test does not demonstrate activation in
an already-running user session. Check its local receipts for that evidence.

The filter recognizes its defined patterns; evidence licenses and decision
claims remain declared data, not independently authenticated facts. The host
controls hook execution and may impose continuation limits. These hooks request
correction at Stop; they do not prevent text already streamed from being seen.
They do not install hooks into ChatGPT or edit ChatGPT account/project settings.
`GLOBAL_INSTRUCTIONS.txt` retains the supplied global field replacement for
platforms where that settings field is separately writable.

Reference: https://code.claude.com/docs/en/hooks
