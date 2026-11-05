import copy
import unittest

from lambda_flow_lab.compare import compare_reports, validate_report
from lambda_flow_lab.schema import ValidationError, digest


def report():
    return {
        "version": 1,
        "evidence": "local-component-integration",
        "cloud_verified": False,
        "suite_digest": digest("suite"),
        "project_digest": digest("project"),
        "status": "passed",
        "scenarios": [{"id": "purchase", "status": "passed", "steps": [{
            "id": "create", "status": "passed", "definition_digest": digest("step"),
            "checks": [{"id": "/state:equals", "definition_digest": digest("expected"), "passed": True}],
            "error": None,
        }]}],
    }


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.before = report()
        self.after = copy.deepcopy(self.before)

    def reasons(self):
        result = compare_reports(self.before, self.after)
        self.assertEqual(result["status"], "failed")
        return {d["reason"] for d in result["differences"]}

    def test_unchanged_pass(self):
        result = compare_reports(self.before, self.after)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["counts"], {"differences": 0, "additions": 0})

    def test_failed_assertion(self):
        self.after["status"] = self.after["scenarios"][0]["status"] = "failed"
        step = self.after["scenarios"][0]["steps"][0]
        step.update(status="failed", error="AssertionFailed")
        step["checks"][0]["passed"] = False
        self.assertEqual(self.reasons(), {"check_regressed", "current_step_failed"})

    def test_existing_failure_still_fails_comparison(self):
        self.test_failed_assertion()
        self.before = copy.deepcopy(self.after)
        self.assertEqual(self.reasons(), {"current_step_failed"})

    def test_removed_scenario(self):
        self.after["scenarios"][0]["id"] = "different"
        self.assertIn("scenario_removed", self.reasons())

    def test_removed_step(self):
        self.after["scenarios"][0]["steps"][0]["id"] = "different"
        self.assertIn("step_removed", self.reasons())

    def test_removed_assertion(self):
        self.after["scenarios"][0]["steps"][0]["checks"][0]["id"] = "/other:equals"
        self.assertIn("check_missing_or_not_run", self.reasons())

    def test_rewritten_oracle(self):
        self.after["scenarios"][0]["steps"][0]["checks"][0]["definition_digest"] = digest("weakened")
        self.assertEqual(self.reasons(), {"assertion_definition_changed"})

    def test_changed_input_and_project(self):
        self.after["project_digest"] = digest("new map")
        self.after["scenarios"][0]["steps"][0]["definition_digest"] = digest("new event")
        self.assertEqual(self.reasons(), {"project_definition_changed", "step_definition_changed"})

    def test_reordered_steps(self):
        second = copy.deepcopy(self.before["scenarios"][0]["steps"][0])
        second["id"] = "inspect"
        self.before["scenarios"][0]["steps"].append(second)
        self.after = copy.deepcopy(self.before)
        self.after["scenarios"][0]["steps"].reverse()
        self.assertEqual(self.reasons(), {"step_order_changed"})

    def test_inserted_repair_step_requires_review(self):
        added = copy.deepcopy(self.after["scenarios"][0]["steps"][0])
        added["id"] = "repair"
        self.after["scenarios"][0]["steps"].insert(0, added)
        self.assertEqual(self.reasons(), {"step_added_requires_review"})

    def test_new_passing_checks_are_visible(self):
        step = self.after["scenarios"][0]["steps"][0]
        step["checks"].append({"id": "/count:equals", "definition_digest": digest(1), "passed": True})
        result = compare_reports(self.before, self.after)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["additions"], [{"scenario": "purchase", "step": "create", "check": "/count:equals"}])

    def test_does_not_accept_empty_success(self):
        self.after["scenarios"][0]["steps"][0]["checks"] = []
        with self.assertRaises(ValidationError):
            validate_report(self.after)

    def test_does_not_accept_inconsistent_status(self):
        self.after["scenarios"][0]["steps"][0]["checks"][0]["passed"] = False
        with self.assertRaises(ValidationError):
            validate_report(self.after)

    def test_rejects_duplicates_and_cloud_claim(self):
        for mutate in (
            lambda r: r.update(cloud_verified=True),
            lambda r: r["scenarios"].append(copy.deepcopy(r["scenarios"][0])),
            lambda r: r["scenarios"][0]["steps"][0].update(error={}),
        ):
            with self.subTest(mutate=mutate):
                value = report()
                mutate(value)
                with self.assertRaises(ValidationError):
                    validate_report(value)

    def test_long_valid_pointer_is_comparable(self):
        self.before["scenarios"][0]["steps"][0]["checks"][0]["id"] = "/" + "x" * 2050 + ":equals"
        self.assertEqual(compare_reports(self.before, self.before)["status"], "passed")

    def test_process_failure_after_completed_steps(self):
        self.after["status"] = self.after["scenarios"][0]["status"] = "failed"
        self.after["scenarios"][0]["error"] = "Timeout"
        self.assertEqual(self.reasons(), {"current_scenario_failed"})


if __name__ == "__main__":
    unittest.main()
