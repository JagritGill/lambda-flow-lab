"""Compare stable workflow evidence without treating missing tests as success."""

from __future__ import annotations

import re
from typing import Any

from .schema import ValidationError

_ID = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ERRORS = {
    "AssertionFailed", "HandlerError", "Timeout", "MissingReference",
    "NetworkBlocked", "ProcessBlocked", "InvalidResponse", "WorkerError",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(f"Invalid report: {message}")


def _keys(value: Any, required: set[str], optional: set[str] | None = None) -> None:
    _require(isinstance(value, dict), "expected object")
    _require(required <= value.keys() <= required | (optional or set()), "unexpected or missing fields")


def _identifier(value: Any) -> None:
    _require(isinstance(value, str) and bool(_ID.fullmatch(value)), "invalid identifier")


def _hash(value: Any) -> None:
    _require(isinstance(value, str) and bool(_HASH.fullmatch(value)), "invalid digest")


def validate_report(report: Any) -> dict:
    """Reject incomplete or inconsistent reports before evaluating regressions."""
    _keys(report, {"version", "evidence", "cloud_verified", "suite_digest", "project_digest", "status", "scenarios"}, {"limitations"})
    _require(type(report["version"]) is int and report["version"] == 1, "unsupported version")
    _require(report["evidence"] == "local-component-integration", "unsupported evidence boundary")
    _require(report["cloud_verified"] is False, "cloud evidence is unsupported")
    _hash(report["suite_digest"])
    _hash(report["project_digest"])
    if "limitations" in report:
        _require(isinstance(report["limitations"], list) and all(isinstance(x, str) for x in report["limitations"]), "invalid limitations")
    _require(isinstance(report["scenarios"], list) and 1 <= len(report["scenarios"]) <= 100, "invalid scenarios")
    seen_scenarios: set[str] = set()
    for scenario in report["scenarios"]:
        _keys(scenario, {"id", "status", "steps"}, {"error"})
        scenario_error = scenario.get("error")
        _require(scenario_error is None or scenario_error in ("Timeout", "WorkerError"), "invalid scenario error")
        _identifier(scenario["id"])
        _require(scenario["id"] not in seen_scenarios, "duplicate scenario")
        seen_scenarios.add(scenario["id"])
        _require(isinstance(scenario["steps"], list) and 1 <= len(scenario["steps"]) <= 100, "invalid steps")
        seen_steps: set[str] = set()
        failed = False
        for step in scenario["steps"]:
            _keys(step, {"id", "status", "definition_digest", "checks", "error"})
            _identifier(step["id"])
            _hash(step["definition_digest"])
            _require(step["id"] not in seen_steps, "duplicate step")
            seen_steps.add(step["id"])
            _require(step["status"] in ("passed", "failed", "skipped"), "invalid step status")
            _require(step["error"] is None or (isinstance(step["error"], str) and step["error"] in _ERRORS), "invalid error code")
            _require(isinstance(step["checks"], list) and len(step["checks"]) <= 100, "invalid checks")
            seen_checks: set[str] = set()
            for check in step["checks"]:
                _keys(check, {"id", "definition_digest", "passed"})
                _require(isinstance(check["id"], str) and bool(check["id"]), "invalid check id")
                _require(check["id"] not in seen_checks, "duplicate check")
                seen_checks.add(check["id"])
                _hash(check["definition_digest"])
                _require(type(check["passed"]) is bool, "invalid check outcome")
            if step["status"] == "passed":
                _require(not failed, "passed step after scenario failure")
                _require(step["error"] is None and bool(step["checks"]) and all(c["passed"] for c in step["checks"]), "vacuous or inconsistent passed step")
            elif step["status"] == "failed":
                _require(not failed, "multiple failed steps in fail-fast scenario")
                _require(step["error"] is not None, "failed step needs error")
                failed = True
            else:
                _require(failed and not step["checks"], "invalid skipped step")
        _require(scenario["status"] == ("failed" if failed or scenario_error else "passed"), "inconsistent scenario status")
    expected = "passed" if all(s["status"] == "passed" for s in report["scenarios"]) else "failed"
    _require(report["status"] == expected, "inconsistent report status")
    return report


def compare_reports(baseline: dict, current: dict) -> dict:
    """Flag failures, removed coverage, and rewritten definitions; list additions."""
    validate_report(baseline)
    validate_report(current)
    differences: list[dict] = []
    additions: list[dict] = []

    def note(reason: str, scenario: str | None = None, step: str | None = None, check: str | None = None) -> None:
        entry = {"reason": reason}
        entry.update({k: v for k, v in (("scenario", scenario), ("step", step), ("check", check)) if v is not None})
        differences.append(entry)

    if baseline["project_digest"] != current["project_digest"]:
        note("project_definition_changed")
    before = {s["id"]: s for s in baseline["scenarios"]}
    after = {s["id"]: s for s in current["scenarios"]}
    for sid, old_scenario in before.items():
        if sid not in after:
            note("scenario_removed", sid)
            continue
        old_steps = {s["id"]: s for s in old_scenario["steps"]}
        new_steps = {s["id"]: s for s in after[sid]["steps"]}
        # Reordering can change effects even with unchanged individual definitions.
        shared_old = [s for s in old_steps if s in new_steps]
        shared_new = [s for s in new_steps if s in old_steps]
        if shared_old != shared_new:
            note("step_order_changed", sid)
        for tid, old_step in old_steps.items():
            if tid not in new_steps:
                note("step_removed", sid, tid)
                continue
            new_step = new_steps[tid]
            if old_step["definition_digest"] != new_step["definition_digest"]:
                note("step_definition_changed", sid, tid)
            old_checks = {c["id"]: c for c in old_step["checks"]}
            new_checks = {c["id"]: c for c in new_step["checks"]}
            for cid, old_check in old_checks.items():
                if cid not in new_checks:
                    note("check_missing_or_not_run", sid, tid, cid)
                elif old_check["definition_digest"] != new_checks[cid]["definition_digest"]:
                    note("assertion_definition_changed", sid, tid, cid)
                elif old_check["passed"] and not new_checks[cid]["passed"]:
                    note("check_regressed", sid, tid, cid)
            for cid in new_checks.keys() - old_checks.keys():
                additions.append({"scenario": sid, "step": tid, "check": cid})
        for tid in new_steps.keys() - old_steps.keys():
            additions.append({"scenario": sid, "step": tid})
            # A prep/repair step can mask a defect by changing the state observed
            # by existing checks. New scenarios/checks are safe additions; a new
            # execution step in a baseline flow needs explicit review.
            note("step_added_requires_review", sid, tid)
    for sid in after.keys() - before.keys():
        additions.append({"scenario": sid})
    for scenario in current["scenarios"]:
        if scenario.get("error"):
            note("current_scenario_failed", scenario["id"])
        for step in scenario["steps"]:
            if step["status"] == "failed":
                note("current_step_failed", scenario["id"], step["id"])
    differences.sort(key=lambda x: (x.get("scenario", ""), x.get("step", ""), x.get("check", ""), x["reason"]))
    additions.sort(key=lambda x: (x.get("scenario", ""), x.get("step", ""), x.get("check", "")))
    return {
        "version": 1,
        "status": "failed" if differences else "passed",
        "evidence": "local-component-integration",
        "cloud_verified": False,
        "baseline_status": baseline["status"],
        "current_status": current["status"],
        "counts": {"differences": len(differences), "additions": len(additions)},
        "differences": differences,
        "additions": additions,
    }
