# Outcome Gate web harness

Outcome Gate is a free static PWA for phone browsers and older MacBook browsers. It uses no paid API, backend, analytics, or model service. GitHub Pages serves the app; each browser keeps its own objective state in `localStorage`. Use Download backup and Restore backup to move a JSON snapshot between browsers.

## Deploy

GitHub Pages currently serves the `main` branch root. The root `index.html` opens `fable-enforce/web/`, where the PWA lives. The public site is free to host; no Pages setting change is needed for this deployed route.

## Use

1. Open the site and create one objective with its measured baseline, frozen target, blocker, next executable transition, HTTPS evidence link, and baseline artifact.
2. For discovery, add five candidate fields. Each needs a foreign mechanism, its native solution, mapping to the frozen state, the assumption attacked, a reachability variable, an executable discriminator, and support/reject outcomes.
3. Select exactly two materially different routes. Mark that divergence preceded solver/search work before recording either route's execution. Execution results need a linked artifact, a note, and a source-check attestation.
4. If both routes fail, the generation locks. Reassess the blocker with an HTTPS evidence reference before opening a fresh generation.
5. In Verify, save a K-1..K-5 decision trace comparing at least two real options. PASS requires this trace, changed state, the target met, before/after artifact hashes that differ, and source attestations.
6. Record after-state and evidence after an actual external transition.
7. To copy the saved goal to the Pixel, open the objective screen and tap **Open GitHub request**. GitHub opens a private, prefilled issue form in a new tab. Sign in if asked, then tap **Create issue** once. SolBridge processes the issue and posts a saved or failed result. Return to Outcome Gate and tap **Open phone requests and results** to view that result. A GitHub login alone does not send the request; the Create issue tap is required.
8. Download backup and Restore backup move browser state between devices. To activate Claude Code's project Stop hook, put the exported JSON at `.fable/active_objective.json` in the repository root. This directory is gitignored. Claude Code project hooks run only in a trusted workspace; review and trust this project's hook in Claude Code.

## Limits

The app hashes locally attached artifacts and records the evidence URL. It cannot authenticate the source, independently measure arbitrary real-world facts, or prevent someone from editing exported JSON. The source-check checkbox is an attestation, not cryptographic proof. Browser data is local until exported; it does not automatically sync across devices. The Pixel handoff requires GitHub sign-in when needed and one explicit Create issue tap; the app never asks you to copy a token. The static page cannot read private GitHub results directly. After a successful active-goal write, SolBridge reads the file back, verifies an exact match, and places a return link in the private issue comment; opening that link imports the phone copy into this browser. That receipt confirms file transfer only, not real-world objective completion. The Claude Code hook runs at turn end only when the local state file exists and cannot run in this ChatGPT session or as a background daemon.

Decision traces use `scripts/kernel_check.py` for K-1..K-5: unknown evidence has zero weight; declared totals equal licensed evidence; continuation and delay are included as baseline rows; boundaries name an evidenced blocker and evaluated route; superseded premises trigger recomputation.
