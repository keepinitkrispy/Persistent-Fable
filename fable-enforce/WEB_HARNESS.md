# Outcome Gate web harness

Outcome Gate is a static, free-to-host PWA for phone browsers and older MacBook browsers. It has no paid API, backend, account, analytics, or model dependency. GitHub Pages serves the app; browser `localStorage` holds objective state on that device. Use Export/Import to move a JSON snapshot between browsers.

## Deploy

The repository workflow at `.github/workflows/pages.yml` tests the canonical filter, v4.2 objective gate, state exporter, and JavaScript syntax, then publishes `fable-enforce/web` from `main` to GitHub Pages. GitHub Pages on this public repository does not need a paid hosting service. One-time owner setup: open [repository Pages settings](https://github.com/keepinitkrispy/Persistent-Fable/settings/pages) and set **Build and deployment → Source → GitHub Actions**. GitHub's `GITHUB_TOKEN` cannot create the repository's Pages site. After that, the next workflow run publishes the app at `https://keepinitkrispy.github.io/Persistent-Fable/`.

## Use

1. Open the site and create one objective with its measured baseline, frozen target, blocker, next executable transition, HTTPS evidence link, and baseline artifact.
2. For discovery, add five candidate fields. Each needs a foreign mechanism, its native solution, mapping to the frozen state, the assumption attacked, a reachability variable, an executable discriminator, and support/reject outcomes.
3. Select exactly two materially different routes. Mark that divergence preceded solver/search work before recording either route's execution. Execution results need a linked artifact, a note, and a source-check attestation.
4. If both routes fail, the generation locks. Reassess the blocker with an HTTPS evidence reference before opening a fresh generation.
5. In Verify, save a K-1..K-5 decision trace comparing at least two real options. PASS requires this trace, changed state, the target met, before/after artifact hashes that differ, and source attestations.
6. Record after-state and evidence after an actual external transition.
7. Export the state. To activate Claude Code's project Stop hook, put that exported JSON at `.fable/active_objective.json` in the repository root. This directory is gitignored. Claude Code project hooks run only in a trusted workspace; review and trust this project's hook in Claude Code.

## Limits

The app hashes locally attached artifacts and records the evidence URL. It cannot authenticate the source, independently measure arbitrary real-world facts, or prevent someone from editing exported JSON. The source-check checkbox is an attestation, not cryptographic proof. Browser data is local until exported; there is no automatic cross-device synchronization. The Claude Code hook runs at turn end only when the local state file exists and cannot run in this ChatGPT session or as a background daemon. No phone bridge is required for the web app.

Decision traces use `scripts/kernel_check.py` for K-1..K-5: unknown evidence has zero weight; declared totals equal licensed evidence; continuation and delay are included as baseline rows; boundaries name an evidenced blocker and evaluated route; superseded premises trigger recomputation.
