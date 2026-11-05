"""Real subprocess/component tests; no AWS SDK or live network calls."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lambda_flow_lab.runner import _failed_scenario, _read_frames, run_suite


FIXTURE = '''
import json
import os
import sqlite3
import sys
from pathlib import Path

print("SENSITIVE_IMPORT_LOG")
os.write(2, b"SENSITIVE_IMPORT_NATIVE_LOG")

def create(event, context):
    db = sqlite3.connect(Path(os.environ["FLOW_LAB_STATE_DIR"]) / "orders.db")
    db.execute("CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, amount INTEGER)")
    db.execute("INSERT OR IGNORE INTO orders VALUES (?, ?)", (event["id"], event["amount"]))
    db.commit()
    db.close()
    return {"id": event["id"], "status": "created"}

def inspect(event, context):
    db = sqlite3.connect(Path(os.environ["FLOW_LAB_STATE_DIR"]) / "orders.db")
    row = db.execute("SELECT amount FROM orders WHERE id = ?", (event["id"],)).fetchone()
    count = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    db.close()
    return {"amount": row[0], "count": count}

counter = 0
def increment(event, context):
    global counter
    counter += 1
    return {"count": counter}

def echo(event, context):
    return event

def noisy(event, context):
    print("SENSITIVE_HANDLER_LOG")
    print("SENSITIVE_STDERR_LOG", file=sys.stderr)
    os.write(1, b"SENSITIVE_NATIVE_LOG")
    os.write(2, b"SENSITIVE_NATIVE_ERROR")
    raise ValueError("SENSITIVE_EXCEPTION_TEXT")

def net(event, context):
    import socket
    socket.socket()
    return {}

def dns(event, context):
    import socket
    socket.getaddrinfo("example.invalid", 443)
    return {}

def process(event, context):
    import subprocess
    subprocess.run([sys.executable, "-c", "print('forbidden')"], check=True)
    return {}

def environment(event, context):
    return {"aws": os.environ.get("AWS_SECRET_ACCESS_KEY"),
            "ai": os.environ.get("OPENAI_API_KEY"),
            "custom": os.environ.get("COMPANY_SECRET"),
            "pythonpath": os.environ.get("PYTHONPATH"),
            "home": Path(os.environ["HOME"]).parent == Path(os.environ["FLOW_LAB_STATE_DIR"]),
            "empty_home": not any(Path(os.environ["HOME"]).iterdir())}

def context_info(event, context):
    return {"name": context.function_name,
            "has_id": bool(context.aws_request_id),
            "memory": context.memory_limit_in_mb,
            "has_arn": bool(context.invoked_function_arn),
            "has_group": bool(context.log_group_name),
            "has_stream": bool(context.log_stream_name),
            "time_positive": context.get_remaining_time_in_millis() > 0}

def slow(event, context):
    import time
    time.sleep(10)
    return {}

def invalid(event, context):
    return {"value": float("nan")}

def non_json(event, context):
    return {1: "integer key"}

def oversized(event, context):
    return {"value": "x" * (2 * 1024 * 1024)}

def terminate(event, context):
    os._exit(0)

def unfinished_thread(event, context):
    import threading
    import time
    threading.Thread(target=lambda: time.sleep(10), daemon=False).start()
    return {}
'''


def step(identifier="call", handler="echo", event=None, expect=None):
    return {
        "id": identifier,
        "handler": handler,
        "event": event if event is not None else {},
        "expect": expect if expect is not None else [{"path": "", "equals": {}}],
    }


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "components.py").write_text(FIXTURE, encoding="utf-8")
        self.project = {
            "version": 1,
            "handlers": {
                name: f"components:{name}"
                for name in (
                    "create", "inspect", "increment", "echo", "noisy", "net", "dns",
                    "process", "environment", "context_info", "slow", "invalid", "non_json",
                    "oversized", "terminate", "unfinished_thread",
                )
            },
        }

    def run_steps(self, steps, timeout=10):
        return run_suite(
            self.project,
            {"version": 1, "scenarios": [{"id": "flow", "steps": steps}]},
            self.root,
            timeout,
        )

    def test_real_sqlite_multi_component_flow_and_reference(self):
        report = self.run_steps([
            step("create", "create", {"id": "synthetic-order", "amount": 25},
                 [{"path": "/status", "equals": "created"}]),
            step("repeat", "create", {"id": "synthetic-order", "amount": 25},
                 [{"path": "/status", "equals": "created"}]),
            step("inspect", "inspect", {"id": {"$from": "create#/id"}},
                 [{"path": "/amount", "equals": 25}, {"path": "/count", "equals": 1}]),
        ])
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["evidence"], "local-component-integration")
        self.assertFalse(report["cloud_verified"])
        self.assertEqual(report["scenarios"][0]["steps"][2]["checks"][0]["id"], "/amount:equals")
        self.assertNotIn("synthetic-order", json.dumps(report))
        self.assertFalse((self.root / "orders.db").exists())

    def test_warm_state_within_scenario_and_isolation_between_scenarios(self):
        steps = [
            step("first", "increment", expect=[{"path": "/count", "equals": 1}]),
            step("second", "increment", expect=[{"path": "/count", "equals": 2}]),
        ]
        suite = {"version": 1, "scenarios": [
            {"id": "one", "steps": steps}, {"id": "two", "steps": steps},
        ]}
        self.assertEqual(run_suite(self.project, suite, self.root)["status"], "passed")

    def test_failure_skips_remaining_steps_but_continues_other_scenarios(self):
        suite = {"version": 1, "scenarios": [
            {"id": "bad", "steps": [
                step("wrong", expect=[{"path": "/missing", "equals": None}]), step("later")
            ]},
            {"id": "good", "steps": [step()]},
        ]}
        report = run_suite(self.project, suite, self.root)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["scenarios"][0]["steps"][0]["error"], "AssertionFailed")
        self.assertEqual(report["scenarios"][0]["steps"][1]["status"], "skipped")
        self.assertEqual(report["scenarios"][1]["status"], "passed")

    def test_missing_reference_is_a_safe_failure(self):
        report = self.run_steps([
            step("first"), step("later", event={"id": {"$from": "first#/missing"}}),
        ])
        self.assertEqual(report["scenarios"][0]["steps"][1]["error"], "MissingReference")

    def test_handler_logs_native_output_and_exception_text_are_not_reported(self):
        report = self.run_steps([step(handler="noisy")])
        self.assertEqual(report["scenarios"][0]["steps"][0]["error"], "HandlerError")
        self.assertNotIn("SENSITIVE", json.dumps(report))

    def test_network_and_dns_are_blocked_before_io(self):
        for handler in ("net", "dns"):
            with self.subTest(handler=handler):
                report = self.run_steps([step(handler=handler)])
                self.assertEqual(report["scenarios"][0]["steps"][0]["error"], "NetworkBlocked")

    def test_child_processes_are_blocked(self):
        report = self.run_steps([step(handler="process")])
        self.assertEqual(report["scenarios"][0]["steps"][0]["error"], "ProcessBlocked")

    def test_credentials_and_custom_environment_not_inherited(self):
        with patch.dict(os.environ, {
            "AWS_SECRET_ACCESS_KEY": "SYNTHETIC_DO_NOT_INHERIT",
            "OPENAI_API_KEY": "SYNTHETIC_DO_NOT_INHERIT",
            "COMPANY_SECRET": "SYNTHETIC_DO_NOT_INHERIT",
            "PYTHONPATH": str(self.root),
        }):
            report = self.run_steps([step(handler="environment", expect=[
                {"path": "", "equals": {"aws": None, "ai": None, "custom": None,
                                         "pythonpath": None, "home": True, "empty_home": True}},
            ])])
        self.assertEqual(report["status"], "passed")

    def test_context_is_synthetic_and_has_remaining_time(self):
        report = self.run_steps([step(handler="context_info", expect=[
            {"path": "", "equals": {"name": "context_info", "has_id": True, "memory": 128,
                                     "has_arn": True, "has_group": True, "has_stream": True,
                                     "time_positive": True}},
        ])])
        self.assertEqual(report["status"], "passed")

    def test_timeout_is_failure_and_skips_remaining_steps(self):
        report = self.run_steps([step(handler="slow"), step("later")], timeout=0.3)
        self.assertEqual(report["scenarios"][0]["steps"][0]["error"], "Timeout")
        self.assertEqual(report["scenarios"][0]["steps"][1]["status"], "skipped")

    def test_timeout_preserves_completed_steps_and_marks_pending_step(self):
        report = self.run_steps([
            step("finished"), step("hang", handler="slow"), step("later")
        ], timeout=0.5)
        steps = report["scenarios"][0]["steps"]
        self.assertEqual(steps[0]["status"], "passed")
        self.assertIsNone(steps[0]["error"])
        self.assertEqual(steps[1]["error"], "Timeout")
        self.assertEqual(steps[2]["status"], "skipped")

    def test_worker_termination_preserves_completed_steps(self):
        report = self.run_steps([step("finished"), step("terminate", handler="terminate")])
        self.assertEqual(report["scenarios"][0]["steps"][0]["status"], "passed")
        self.assertEqual(report["scenarios"][0]["steps"][1]["error"], "WorkerError")

    def test_timeout_after_steps_is_scenario_level_failure(self):
        report = self.run_steps([step(handler="unfinished_thread")], timeout=0.5)
        scenario = report["scenarios"][0]
        self.assertEqual(scenario["status"], "failed")
        self.assertEqual(scenario["error"], "Timeout")
        self.assertEqual(scenario["steps"][0]["status"], "passed")

    def test_worker_failure_after_failed_step_does_not_add_another_failed_step(self):
        definitions = [step("wrong", expect=[{"path": "/missing", "equals": 1}]), step("later")]
        completed = self.run_steps(definitions)["scenarios"][0]["steps"][:1]
        result = _failed_scenario({"id": "flow", "steps": definitions}, "WorkerError", completed)
        self.assertEqual([s["status"] for s in result["steps"]], ["failed", "skipped"])
        self.assertEqual(result["error"], "WorkerError")

    def test_trailing_malformed_frame_never_preserves_a_success(self):
        definitions = [step()]
        result = self.run_steps(definitions)["scenarios"][0]
        stream = json.dumps({"type": "step", "step": result["steps"][0]}) + "\n"
        stream += json.dumps({"type": "scenario", "scenario": result}) + "\n"
        scenario = {"id": "flow", "steps": definitions}
        for trailer in ("broken\n", "{", '{"type":"bogus"}\n'):
            with self.subTest(trailer=trailer):
                completed, final = _read_frames(stream + trailer, scenario)
                self.assertEqual(len(completed), 1)
                self.assertIsNone(final)

    def test_invalid_json_responses_fail(self):
        for handler in ("invalid", "non_json", "oversized"):
            with self.subTest(handler=handler):
                report = self.run_steps([step(handler=handler)])
                self.assertEqual(report["scenarios"][0]["steps"][0]["error"], "InvalidResponse")

    def test_worker_termination_is_failure(self):
        report = self.run_steps([step(handler="terminate")])
        self.assertEqual(report["scenarios"][0]["steps"][0]["error"], "WorkerError")

    def test_missing_handler_module_is_safe_failure(self):
        self.project["handlers"]["echo"] = "does_not_exist:handler"
        report = self.run_steps([step()])
        self.assertEqual(report["scenarios"][0]["steps"][0]["error"], "HandlerError")

    def test_timeout_validation(self):
        for timeout in (0, -1, float("inf"), float("nan"), True, "10"):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                self.run_steps([step()], timeout=timeout)


if __name__ == "__main__":
    unittest.main()
