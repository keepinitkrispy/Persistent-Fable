#!/usr/bin/env python3
import unittest

from objective_gate import check_state, completion_state


def state(before="0", after="1", target="1", status="OPEN", before_sha="a", after_sha="b"):
    return {
        "schema_version": 1,
        "status": status,
        "objective": {
            "id": "test",
            "statement": "Reach target",
            "baseline_value": before,
            "current_value": after,
            "target": {"operator": "eq", "value": target},
            "next_action": {"executable": True, "action": "advance state"},
            "evidence_before": {"kind": "external_artifact", "uri": "https://example.org/before", "source_checked": True, "sha256": before_sha * 64},
            "evidence_after": {"kind": "external_artifact", "uri": "https://example.org/after", "source_checked": True, "sha256": after_sha * 64},
        },
    }


class ObjectiveGateTests(unittest.TestCase):
    def test_pass_requires_changed_state_target_and_distinct_evidence(self):
        sample = state(status="PASS")
        self.assertTrue(completion_state(sample)["pass"])
        self.assertEqual(check_state(sample), [])

    def test_noop_action_cannot_pass(self):
        violations = check_state(state(before="0", after="0", status="PASS"))
        self.assertIn("K-6", {item[0] for item in violations})

    def test_target_not_met_cannot_pass(self):
        violations = check_state(state(before="0", after="0.5", status="PASS"))
        self.assertIn("K-6", {item[0] for item in violations})

    def test_same_evidence_hash_cannot_pass(self):
        violations = check_state(state(status="PASS", before_sha="a", after_sha="a"))
        self.assertIn("K-6", {item[0] for item in violations})

    def test_finalization_blocked_when_next_action_remains(self):
        sample = state(before="0", after="0")
        sample["finalizing"] = True
        violations = check_state(sample)
        self.assertIn("K-24", {item[0] for item in violations})

    def test_reached_target_without_a_state_change_is_not_pass(self):
        sample = state(before="1", after="1", target="1", status="PASS")
        self.assertFalse(completion_state(sample)["pass"])
        self.assertIn("K-6", {item[0] for item in check_state(sample)})

    def test_v42_requires_five_candidate_fields_before_two_routes(self):
        sample = state()
        sample["requires_divergence_protocol"] = True
        sample["divergence_protocol"] = {"fields": [], "top_routes": [], "solver_or_search_started_after_divergence": False}
        codes = {item[0] for item in check_state(sample)}
        self.assertIn("K-15", codes)
        self.assertIn("K-17", codes)
        self.assertIn("K-20", codes)

    def test_v42_blocks_failed_routes_without_reassessment_and_child(self):
        sample = state()
        sample["requires_divergence_protocol"] = True
        evidence = {"url": "https://example.org/result", "sha256": "c" * 64, "sourceConfirmed": True}
        fields = []
        for number in range(5):
            fields.append({
                "id": f"r{number}", "field": f"domain-{number}", "unrelated_to_native_domain": True,
                "native_solution": "native solution", "mapping_to_objective_state": "maps to objective",
                "attacks_assumption": f"assumption-{number}", "reachability_variable": "variable",
                "discriminator": {"execution_plan": "run test", "rejects_route_if": "fails", "supports_route_if": "passes"},
            })
        sample["divergence_protocol"] = {
            "fields": fields, "top_routes": ["r0", "r1"], "solver_or_search_started_after_divergence": True,
            "inherited_assumptions": [], "eliminations": [],
            "post_two_route_transition": {
                "executed_results": [
                    {"route_id": "r0", "executed": True, "outcome": "no_target_advance", "evidence": evidence},
                    {"route_id": "r1", "executed": True, "outcome": "falsified", "evidence": evidence},
                ],
            },
        }
        codes = {item[0] for item in check_state(sample)}
        self.assertIn("K-22", codes)

    def test_required_kernel_trace_blocks_missing_record(self):
        sample = state(status="PASS")
        sample["requires_decision_trace"] = True
        codes = {item[1] for item in check_state(sample)}
        self.assertIn("decision_trace_missing", codes)

    def test_required_kernel_trace_is_checked(self):
        sample = state(status="PASS")
        sample["requires_decision_trace"] = True
        sample["decision_trace"] = {"options": [], "baseline_rows": ["continuation"], "boundary": None}
        codes = {item[0] for item in check_state(sample)}
        self.assertIn("K-3", codes)


if __name__ == "__main__":
    unittest.main()
