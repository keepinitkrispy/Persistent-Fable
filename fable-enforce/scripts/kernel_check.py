#!/usr/bin/env python3
"""Executable K-1..K-5 checks for declared decision traces."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

LICENSES = {"TOOL", "MEMORY", "STATED", "INFERENCE", "UNKNOWN"}
REQUIRED_BASELINE = {"continuation", "delay"}
EPS = 1e-9


def check(trace: Any) -> list[tuple[str, str, str]]:
    if not isinstance(trace, dict):
        return [("K-0", "invalid_trace", "decision trace root must be an object")]
    violations: list[tuple[str, str, str]] = []
    options = trace.get("options", [])
    if not isinstance(options, list):
        return [("K-0", "invalid_options", "options must be a list")]
    if len(options) < 2:
        violations.append(("K-3", "alternative_missing", "decision trace must compare at least two actual options"))
    for option in options:
        if not isinstance(option, dict):
            violations.append(("K-0", "invalid_option", "each option must be an object"))
            continue
        evidence = option.get("evidence", [])
        if not isinstance(evidence, list):
            violations.append(("K-0", "invalid_evidence", f"option {option.get('id')} evidence must be a list"))
            continue
        for item in evidence:
            if not isinstance(item, dict):
                violations.append(("K-0", "invalid_evidence", f"option {option.get('id')} contains a non-object evidence row"))
                continue
            license_name = item.get("license")
            try:
                weight = float(item.get("weight", 0.0))
            except (ValueError, TypeError):
                weight = math.nan
            if license_name not in LICENSES:
                violations.append(("K-0", "invalid_license", f"option {option.get('id')}: license {license_name!r} is invalid"))
            if not math.isfinite(weight):
                violations.append(("K-0", "invalid_weight", f"option {option.get('id')}: evidence weight must be finite"))
                continue
            if license_name == "UNKNOWN" and abs(weight) > EPS:
                violations.append(("K-1", "unknown_carries_weight", f"option {option.get('id')}: UNKNOWN evidence {item.get('claim')!r} carries weight {weight}"))
    for option in options:
        if not isinstance(option, dict) or not isinstance(option.get("evidence", []), list):
            continue
        values = [item.get("weight", 0.0) for item in option.get("evidence", []) if isinstance(item, dict)]
        try:
            evidence_sum = sum(float(value) for value in values)
            total = float(option.get("total_weight", evidence_sum))
        except (ValueError, TypeError):
            continue
        if not math.isfinite(evidence_sum) or not math.isfinite(total):
            continue
        if abs(total - evidence_sum) > 1e-6:
            beneficiary = "incumbent/default" if option.get("incumbent") else "option"
            violations.append(("K-2", "unlicensed_weight_bonus", f"{beneficiary} {option.get('id')}: declared total {total} != licensed evidence sum {round(evidence_sum, 6)}"))
    rows = trace.get("baseline_rows", [])
    rows = set(rows) if isinstance(rows, list) else set()
    missing = REQUIRED_BASELINE - rows
    if missing:
        violations.append(("K-3", "cost_free_baseline", f"comparison omits required baseline row(s): {sorted(missing)}"))
    boundary = trace.get("boundary")
    if boundary is not None:
        if not isinstance(boundary, dict) or not str(boundary.get("blocker", "")).strip():
            violations.append(("K-4", "unevidenced_boundary", "boundary asserted with no named blocker"))
        routes = boundary.get("routes_evaluated", []) if isinstance(boundary, dict) else []
        if not isinstance(routes, list) or not any(str(route).strip() for route in routes):
            violations.append(("K-4", "unevidenced_boundary", "boundary asserted with no materially different route evaluated"))
    superseded = trace.get("superseded_premises", [])
    superseded = set(superseded) if isinstance(superseded, list) else set()
    for option in options:
        if not isinstance(option, dict) or not isinstance(option.get("evidence", []), list):
            continue
        cited = {item.get("premise") for item in option.get("evidence", []) if isinstance(item, dict)} & superseded
        if cited and not option.get("recomputed"):
            violations.append(("K-5", "stale_dependent_conclusion", f"option {option.get('id')} cites superseded premise {sorted(cited)} without recompute"))
    return violations


def selftest() -> int:
    clean = {"options": [{"id": "continuation", "evidence": []}, {"id": "delay", "evidence": []}], "baseline_rows": ["continuation", "delay"], "boundary": None, "superseded_premises": []}
    negative = {
        "K-1": {"options": [{"id": "a", "evidence": [{"claim": "unknown", "license": "UNKNOWN", "weight": 0.4}]}], "baseline_rows": ["continuation", "delay"]},
        "K-2": {"options": [{"id": "default", "incumbent": True, "evidence": [{"claim": "fact", "license": "TOOL", "weight": 0.4}], "total_weight": 0.9}], "baseline_rows": ["continuation", "delay"]},
        "K-3": {"options": [], "baseline_rows": ["continuation"]},
        "K-4": {"options": [], "baseline_rows": ["continuation", "delay"], "boundary": {"blocker": "", "routes_evaluated": []}},
        "K-5": {"options": [{"id": "a", "recomputed": False, "evidence": [{"claim": "fact", "license": "TOOL", "weight": 0.5, "premise": "p1"}]}], "baseline_rows": ["continuation", "delay"], "superseded_premises": ["p1"]},
    }
    passed = not check(clean)
    print(f"[{'PASS' if passed else 'FAIL'}] clean control")
    all_passed = passed
    for expected, trace in negative.items():
        codes = {code for code, _, _ in check(trace)}
        passed = expected in codes
        all_passed &= passed
        print(f"[{'PASS' if passed else 'FAIL'}] negative {expected}: {sorted(codes)}")
    print(f"{'ALL PASS' if all_passed else 'FAILURES PRESENT'} — {1 + len(negative)} cases")
    return 0 if all_passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", nargs="?", help="decision trace JSON")
    parser.add_argument("--test", action="store_true", help="run K-1..K-5 regressions")
    args = parser.parse_args()
    if args.test:
        return selftest()
    if not args.trace:
        parser.error("trace is required unless --test is used")
    violations = check(json.loads(Path(args.trace).read_text(encoding="utf-8")))
    for code, name, detail in violations:
        print(f"VIOLATION {code}:{name} | {detail}")
    if violations:
        return 1
    print("CLEAN — decision trace satisfies K-1..K-5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
