#!/usr/bin/env python3
"""Outcome gate for the shadow v4.2 execution harness.

An objective is PASS only when the measured external state changed, the new
state satisfies the frozen target, and before/after evidence is present with
different artifact hashes. Tool execution and prose are never substitutes.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

from kernel_check import check as check_decision_trace


HEX_256 = re.compile(r"^[a-f0-9]{64}$")
BASELINE_ROWS = {"continuation", "delay"}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(str(value).strip())
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def target_met(current: Any, target: dict[str, Any]) -> bool:
    op = target.get("operator")
    wanted = target.get("value")
    left_n, right_n = _number(current), _number(wanted)
    if op == "contains":
        return str(wanted).casefold() in str(current).casefold()
    if op == "gte":
        return left_n is not None and right_n is not None and left_n >= right_n
    if op == "lte":
        return left_n is not None and right_n is not None and left_n <= right_n
    if op == "eq":
        if left_n is not None and right_n is not None:
            return left_n == right_n
        return str(current).strip() == str(wanted).strip()
    return False


def _evidence_ok(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    uri = str(record.get("uri", ""))
    return (
        record.get("kind") == "external_artifact"
        and uri.startswith("https://")
        and bool(record.get("source_checked") is True)
        and bool(HEX_256.fullmatch(str(record.get("sha256", ""))))
    )


def completion_state(state: dict[str, Any]) -> dict[str, Any]:
    objective = state.get("objective") if isinstance(state.get("objective"), dict) else {}
    before = objective.get("baseline_value")
    after = objective.get("current_value")
    changed = before is not None and after is not None and str(before).strip() != str(after).strip()
    met = target_met(after, objective.get("target", {}))
    before_evidence = _evidence_ok(objective.get("evidence_before"))
    after_evidence = _evidence_ok(objective.get("evidence_after"))
    hashes_differ = (
        before_evidence
        and after_evidence
        and objective["evidence_before"]["sha256"] != objective["evidence_after"]["sha256"]
    )
    passed = bool(changed and met and hashes_differ)
    return {
        "changed": bool(changed),
        "target_met": bool(met),
        "before_evidence_valid": bool(before_evidence),
        "after_evidence_valid": bool(after_evidence),
        "evidence_hashes_differ": bool(hashes_differ),
        "pass": passed,
        "status": "PASS" if passed else "OPEN",
    }


def check_v42(state: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Check the v4.2 decision gates relevant to this generic task record."""
    violations: list[tuple[str, str, str]] = []
    protocol = state.get("divergence_protocol")
    if state.get("requires_divergence_protocol"):
        if not isinstance(protocol, dict):
            violations.append(("K-14", "missing_divergence_protocol", "open-world work has no divergence protocol"))
        else:
            fields = protocol.get("fields", [])
            if not isinstance(fields, list) or len(fields) < 5:
                violations.append(("K-15", "insufficient_divergence_fields", "runtime v4.2 requires at least five candidate fields"))
            for field in fields if isinstance(fields, list) else []:
                fid = str(field.get("id", ""))
                if field.get("unrelated_to_native_domain") is not True or not field.get("native_solution"):
                    violations.append(("K-16", "native_solution_missing", f"field {fid} lacks a native-domain solution"))
                for key in ("mapping_to_objective_state", "attacks_assumption", "reachability_variable"):
                    if not field.get(key):
                        violations.append(("K-16", "mapping_missing", f"field {fid} missing {key}"))
                discriminator = field.get("discriminator", {})
                for key in ("execution_plan", "rejects_route_if", "supports_route_if"):
                    if not discriminator.get(key):
                        violations.append(("K-16", "discriminator_missing", f"field {fid} missing discriminator.{key}"))
            top = list(map(str, protocol.get("top_routes", [])))
            if len(top) != 2 or len(set(top)) != 2:
                violations.append(("K-17", "top_two_not_selected", "a generation must select exactly two routes"))
            by_id = {str(f.get("id")): f for f in fields if isinstance(f, dict)} if isinstance(fields, list) else {}
            selected = [by_id.get(route, {}) for route in top]
            if len(selected) == 2 and selected[0] and selected[1]:
                if selected[0].get("field") == selected[1].get("field") or selected[0].get("attacks_assumption") == selected[1].get("attacks_assumption"):
                    violations.append(("K-17", "routes_not_materially_distinct", "selected routes share the same field or attacked assumption"))
            for assumption in protocol.get("inherited_assumptions", []):
                if assumption.get("status") not in {"proven", "borrowed"}:
                    violations.append(("K-18", "assumption_not_audited", str(assumption.get("id", "missing id"))))
            for elimination in protocol.get("eliminations", []):
                if elimination.get("premises_audited") is not True:
                    violations.append(("K-19", "elimination_premises_unaudited", str(elimination.get("id", "missing id"))))
            if protocol.get("solver_or_search_started_after_divergence") is not True:
                violations.append(("K-20", "solver_before_divergence", "search started before divergence fields were registered"))
            transition = protocol.get("post_two_route_transition")
            if isinstance(transition, dict):
                results = {str(row.get("route_id")): row for row in transition.get("executed_results", []) if isinstance(row, dict)}
                for route_id, row in results.items():
                    evidence = row.get("evidence", {})
                    evidence = evidence if isinstance(evidence, dict) else {}
                    if row.get("executed") is True and not _evidence_ok({
                        "kind": "external_artifact", "uri": evidence.get("url"),
                        "source_checked": evidence.get("sourceConfirmed"), "sha256": evidence.get("sha256"),
                    }):
                        violations.append(("K-21", "route_execution_evidence_missing", f"route {route_id} needs a linked, hashed artifact with source attestation"))
                both_failed = all(
                    results.get(route, {}).get("executed") is True
                    and results.get(route, {}).get("outcome") in {"no_target_advance", "closed", "falsified"}
                    for route in top
                )
                if both_failed:
                    reassessment = transition.get("blocker_reassessment", {})
                    if reassessment.get("performed") is not True or not str(reassessment.get("evidence", "")).startswith("https://"):
                        violations.append(("K-22", "two_route_reassessment_missing", "both selected routes failed; blocker reassessment is required"))
                    else:
                        next_action = transition.get("next_action", {})
                        if next_action.get("type") != "child_divergence":
                            violations.append(("K-23", "stale_generation_continuation", "both routes failed; retire this generation and continue only in a fresh child divergence"))
    history = state.get("generation_history", [])
    if isinstance(history, list):
        for retired in history:
            if not isinstance(retired, dict):
                violations.append(("K-22", "invalid_generation_history", "retired generation record must be an object"))
                continue
            routes = retired.get("routes", [])
            selected = [route for route in routes if isinstance(route, dict) and route.get("selected") is True]
            top = list(map(str, retired.get("topRoutes", [])))
            if len(selected) != 2 or len(top) != 2 or set(top) != {str(row.get("id")) for row in selected}:
                violations.append(("K-17", "retired_generation_top_two_invalid", f"generation {retired.get('generation')} must preserve exactly two selected routes"))
                continue
            if selected[0].get("domain") == selected[1].get("domain") or selected[0].get("attacks") == selected[1].get("attacks"):
                violations.append(("K-17", "retired_routes_not_distinct", f"generation {retired.get('generation')} selected routes were not materially distinct"))
            failed = all(route.get("status") in {"executed_no_advance", "falsified"} for route in selected)
            if failed:
                if not str(retired.get("reassessmentEvidenceUrl", "")).startswith("https://") or not retired.get("blockerAfter"):
                    violations.append(("K-22", "retired_blocker_reassessment_missing", f"generation {retired.get('generation')} failed both routes without an evidence-based reassessment"))
                if retired.get("childGeneration") != retired.get("generation", -2) + 1:
                    violations.append(("K-23", "retired_generation_without_child", f"generation {retired.get('generation')} must continue as its immediate child"))
                for route in selected:
                    evidence = route.get("evidence", {})
                    evidence = evidence if isinstance(evidence, dict) else {}
                    if not _evidence_ok({"kind": "external_artifact", "uri": evidence.get("url"), "source_checked": evidence.get("sourceConfirmed"), "sha256": evidence.get("sha256")}):
                        violations.append(("K-21", "retired_route_evidence_missing", f"generation {retired.get('generation')} route {route.get('id')} has no source-attested hashed artifact"))
    return violations


def check_state(state: dict[str, Any]) -> list[tuple[str, str, str]]:
    violations: list[tuple[str, str, str]] = []
    if not isinstance(state, dict):
        return [("K-0", "invalid_state", "state root must be an object")]
    if state.get("schema_version") != 1:
        violations.append(("K-0", "schema_version", "schema_version must be 1"))
    objective = state.get("objective")
    if not isinstance(objective, dict):
        return violations + [("K-0", "missing_objective", "objective record is required")]
    for key in ("id", "statement", "baseline_value", "current_value", "target", "next_action"):
        if key not in objective or objective[key] in (None, ""):
            violations.append(("K-0", "objective_field_missing", f"objective.{key} is required"))
    status = str(state.get("status", "OPEN")).upper()
    result = completion_state(state)
    if state.get("requires_decision_trace"):
        trace = state.get("decision_trace")
        if trace is None:
            violations.append(("K-0", "decision_trace_missing", "K-1..K-5 decision trace is required before this task can pass"))
        else:
            violations.extend(check_decision_trace(trace))
    if status == "PASS" and not result["pass"]:
        violations.append(("K-6", "pass_without_verified_state_change", "PASS requires changed measured state, target met, and distinct verified before/after evidence hashes"))
    if result["pass"] and status != "PASS":
        violations.append(("K-6", "verified_pass_not_committed", "objective evidence satisfies PASS but durable state status is not PASS"))
    if objective.get("completion_claimed") is True and not result["pass"]:
        violations.append(("K-6", "completion_claim_without_target_change", "completion claim is blocked until changed state, target, and evidence are verified"))
    if state.get("finalizing") is True and not result["pass"]:
        next_action = objective.get("next_action")
        if isinstance(next_action, dict) and next_action.get("executable") is True and next_action.get("action"):
            violations.append(("K-24", "premature_execution_boundary", "target is unmet and an executable next transition remains"))
    violations.extend(check_v42(state))
    return violations


def run_selftest() -> int:
    def fixture(before: str, after: str, status: str = "OPEN") -> dict[str, Any]:
        return {
            "schema_version": 1, "status": status,
            "objective": {
                "id": "test-objective", "statement": "Reach 1", "baseline_value": before,
                "current_value": after, "target": {"operator": "eq", "value": "1"},
                "next_action": {"executable": True, "action": "Run the real transition"},
                "evidence_before": {"kind": "external_artifact", "uri": "https://example.org/before", "source_checked": True, "sha256": "a" * 64},
                "evidence_after": {"kind": "external_artifact", "uri": "https://example.org/after", "source_checked": True, "sha256": "b" * 64},
            },
        }
    cases = [
        ("changed state + target + distinct evidence passes", fixture("0", "1", "PASS"), "clean"),
        ("tool-like/no-op state cannot pass", fixture("0", "0", "PASS"), "K-6"),
        ("changed state below target stays open", fixture("0", "0.5", "PASS"), "K-6"),
        ("same evidence artifact cannot pass", {**fixture("0", "1", "PASS"), "objective": {**fixture("0", "1")["objective"], "evidence_after": {"kind": "external_artifact", "uri": "https://example.org/after", "source_checked": True, "sha256": "a" * 64}}}, "K-6"),
        ("open objective with executable transition cannot finalize", {**fixture("0", "0"), "finalizing": True}, "K-24"),
    ]
    ok = True
    for name, sample, expected in cases:
        codes = {code for code, _, _ in check_state(sample)}
        passed = (expected == "clean" and not codes) or (expected in codes)
        ok &= passed
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {sorted(codes) or 'clean'}")
    print(f"{'ALL PASS' if ok else 'FAILURES PRESENT'} — {len(cases)} cases")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state_file", nargs="?", help="objective state JSON")
    parser.add_argument("--test", action="store_true", help="run outcome-gate regressions")
    parser.add_argument("--guard-final", action="store_true", help="reject finalization while target is unmet and a next action remains")
    args = parser.parse_args()
    if args.test:
        return run_selftest()
    if not args.state_file:
        parser.error("state_file is required unless --test is used")
    try:
        state = json.loads(Path(args.state_file).read_text())
    except Exception as exc:
        print(f"FAIL state unreadable: {exc}")
        return 2
    violations = check_state(state)
    for code, name, detail in violations:
        print(f"VIOLATION {code}:{name} | {detail}")
    result = completion_state(state)
    if args.guard_final and not result["pass"]:
        print(f"BLOCKED finalization | objective={result['status']} next_action={state.get('objective', {}).get('next_action')}")
        return 1
    if violations:
        return 1
    print(f"STATE {result['status']} | changed={result['changed']} target_met={result['target_met']} before_evidence={result['before_evidence_valid']} after_evidence={result['after_evidence_valid']} evidence_diff={result['evidence_hashes_differ']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
