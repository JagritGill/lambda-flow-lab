import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "order_workflow"


class CLITests(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run([sys.executable, "-m", "lambda_flow_lab", *map(str, args)], cwd=ROOT, text=True, capture_output=True, timeout=30)

    def test_run_validate_compare_round_trip(self):
        suite, project = EXAMPLE / "flows.json", EXAMPLE / "project.json"
        self.assertEqual(self.cli("validate", suite, "--project", project).returncode, 0)
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.json"
            run = self.cli("run", suite, "--project", project, "--output", report)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = self.cli("compare", report, report)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "passed")

    def test_prompt_and_plan_work_without_importing_handlers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "project.json").write_text(json.dumps({"version": 1, "handlers": {"echo": "does_not_exist:handler"}}))
            (root / "suite.json").write_text(json.dumps({"version": 1, "scenarios": [{"id": "flow", "steps": [{"id": "first", "handler": "echo", "event": {}, "expect": [{"path": "", "exists": True}]}]}]}))
            result = self.cli("aws-plan", root / "suite.json", "--project", root / "project.json")
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)
            self.assertIs(plan["executable"], False)
            self.assertIs(plan["cloud_verified"], False)
            prompt = self.cli("prompt", EXAMPLE / "contract.json")
            self.assertEqual(prompt.returncode, 0, prompt.stderr)
            self.assertIn("Synthetic order workflow", prompt.stdout)
            self.assertIn("has not contacted an AI service", prompt.stdout)

    def test_invalid_input_does_not_echo_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.json"
            path.write_text('{"PRIVATE_SENTINEL": NaN}')
            result = self.cli("prompt", path)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("PRIVATE_SENTINEL", result.stdout + result.stderr)

    def test_timeout_parameter_rejected(self):
        result = self.cli("run", EXAMPLE / "flows.json", "--project", EXAMPLE / "project.json", "--timeout", "nan")
        self.assertEqual(result.returncode, 2)

    def test_failed_flow_returns_one(self):
        suite = json.loads((EXAMPLE / "flows.json").read_text())
        suite["scenarios"][0]["steps"][0]["expect"] = [{"path": "", "equals": "deliberately wrong"}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "failed.json"
            path.write_text(json.dumps(suite))
            result = self.cli("run", path, "--project", EXAMPLE / "project.json")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "failed")

    def test_compare_can_read_reports_larger_than_manifest_limit(self):
        from test_compare import report

        value = report()
        # Valid reports can exceed 2 MiB through repetition of assertion metadata.
        base_step = value["scenarios"][0]["steps"][0]
        base_step["checks"][0]["id"] = "/" + "x" * 2400 + ":equals"
        value["scenarios"][0]["steps"] = [dict(copy.deepcopy(base_step), id=f"step{i}") for i in range(100)]
        base_scenario = value["scenarios"][0]
        value["scenarios"] = [dict(copy.deepcopy(base_scenario), id=f"flow{i}") for i in range(10)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large-report.json"
            path.write_text(json.dumps(value))
            self.assertGreater(path.stat().st_size, 2 * 1024 * 1024)
            result = self.cli("compare", path, path)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
