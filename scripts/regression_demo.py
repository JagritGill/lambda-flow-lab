#!/usr/bin/env python3
"""Prove that an unchanged multi-component flow catches a realistic regression.

All edits happen in a fresh temporary copy. No AWS or AI services are contacted.
The process exits successfully only if a passing baseline becomes a failing
duplicate-outbox assertion and the report comparison identifies the regression.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from lambda_flow_lab.compare import compare_reports  # noqa: E402
from lambda_flow_lab.runner import run_suite  # noqa: E402
from lambda_flow_lab.schema import load_json, validate_project, validate_suite  # noqa: E402


def demonstrate() -> dict:
    """Run baseline and one isolated code mutation; return a payload-free summary."""
    example = REPOSITORY_ROOT / "examples" / "order_workflow"
    project = validate_project(load_json(example / "project.json"))
    suite = validate_suite(load_json(example / "flows.json"), project)
    baseline = run_suite(project, suite, example)
    if baseline["status"] != "passed":
        raise RuntimeError("Baseline must pass before demonstrating a regression.")

    with tempfile.TemporaryDirectory(prefix="lambda-flow-regression-") as directory:
        mutated_example = Path(directory) / "order_workflow"
        shutil.copytree(example, mutated_example, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        target = mutated_example / "demo" / "fulfillment.py"
        source = target.read_text(encoding="utf-8")
        original = 'if order["status"] == "fulfilled":  # idempotency guard'
        replacement = 'if False:  # intentionally broken in a temporary demo copy'
        if source.count(original) != 1:
            raise RuntimeError("Expected exactly one idempotency guard to mutate.")
        target.write_text(source.replace(original, replacement), encoding="utf-8")
        changed = run_suite(project, suite, mutated_example)

    comparison = compare_reports(baseline, changed)
    failures = [
        {"scenario": scenario["id"], "step": step["id"], "check": check["id"]}
        for scenario in changed["scenarios"]
        for step in scenario["steps"]
        for check in step["checks"]
        if not check["passed"]
    ]
    expected = {"scenario": "duplicate_fulfillment", "step": "observe_state", "check": "/outbox:length"}
    caught = changed["status"] == "failed" and comparison["status"] == "failed" and expected in failures
    return {
        "regression_caught": caught,
        "baseline_status": baseline["status"],
        "changed_status": changed["status"],
        "comparison_status": comparison["status"],
        "failed_checks": failures,
        "evidence": "local-component-integration",
        "cloud_verified": False,
        "mutation": "Bypassed fulfillment idempotency guard in temporary copy; duplicate outbox row detected.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optionally write the demonstration summary as JSON.")
    arguments = parser.parse_args()
    result = demonstrate()
    rendered = json.dumps(result, indent=2) + "\n"
    if arguments.output:
        arguments.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["regression_caught"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
