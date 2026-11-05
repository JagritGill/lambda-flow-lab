"""Exercise actual workflow/storage integration and a meaningful code regression."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from lambda_flow_lab.runner import run_suite
from lambda_flow_lab.schema import load_json, validate_project, validate_suite


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "order_workflow"


class OrderWorkflowTests(unittest.TestCase):
    def test_all_documented_flows_pass_against_real_temporary_sqlite(self):
        project = validate_project(load_json(EXAMPLE / "project.json"))
        suite = validate_suite(load_json(EXAMPLE / "flows.json"), project)
        report = run_suite(project, suite, EXAMPLE)
        self.assertEqual("passed", report["status"], report)
        self.assertEqual(6, len(report["scenarios"]))
        self.assertFalse(report["cloud_verified"])
        self.assertEqual("local-component-integration", report["evidence"])
        self.assertFalse(list(EXAMPLE.rglob("*.sqlite3")), "Scenario state must stay outside source tree.")

    def test_duplicate_side_effect_regression_is_caught_without_source_changes(self):
        source_path = EXAMPLE / "demo" / "fulfillment.py"
        original = source_path.read_bytes()
        module_spec = importlib.util.spec_from_file_location("regression_demo", ROOT / "scripts" / "regression_demo.py")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        result = module.demonstrate()
        self.assertTrue(result["regression_caught"], result)
        self.assertEqual("passed", result["baseline_status"])
        self.assertEqual("failed", result["changed_status"])
        self.assertEqual(
            [{"scenario": "duplicate_fulfillment", "step": "observe_state", "check": "/outbox:length"}],
            result["failed_checks"],
        )
        self.assertEqual(original, source_path.read_bytes(), "Demo must never mutate tracked code.")


if __name__ == "__main__":
    unittest.main()
