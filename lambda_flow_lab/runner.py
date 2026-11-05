"""Run trusted Python workflow components in isolated, offline-by-default workers.

Process and environment isolation reduce accidental coupling between scenarios.
They are not a security sandbox for untrusted Python code.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from .schema import digest, validate_project, validate_suite


LIMITATIONS = [
    "Python handlers and local components only; AWS services are not invoked.",
    "Does not verify deployed IAM, event delivery, retries, concurrency, or infrastructure.",
    "Steps share a warm Python process; scenarios have separate temporary state.",
    "The network/process guard prevents accidents; it is not a sandbox for untrusted code.",
    "Passing assertions cover the declared flows only and cannot prove absence of regressions.",
]


def _environment(state_dir: Path) -> dict[str, str]:
    """Build an allowlist environment; never inherit cloud or AI credentials."""
    home = state_dir / "home"
    temporary = state_dir / "tmp"
    home.mkdir()
    temporary.mkdir()
    result = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "TMPDIR": str(temporary),
        "TMP": str(temporary),
        "TEMP": str(temporary),
        "FLOW_LAB_STATE_DIR": str(state_dir),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }
    # Windows needs its system directory to find standard runtime libraries.
    for key in ("SystemRoot", "WINDIR"):
        if key in os.environ:
            result[key] = os.environ[key]
    return result


def _failed_scenario(scenario: dict, error: str, completed: list | None = None) -> dict:
    completed = completed or []
    already_failed = any(step["status"] == "failed" for step in completed)
    result = {
        "id": scenario["id"],
        "status": "failed",
        "steps": completed + [
            {
                "id": step["id"],
                "definition_digest": digest({"handler": step["handler"], "event": step["event"]}),
                "status": "failed" if index == 0 and not already_failed else "skipped",
                "checks": [],
                "error": error if index == 0 and not already_failed else None,
            }
            for index, step in enumerate(scenario["steps"][len(completed):])
        ],
    }
    if already_failed or len(completed) == len(scenario["steps"]):
        # A shutdown/protocol failure cannot honestly be attributed to any step.
        result["error"] = error
    return result


_ERRORS = {
    None, "HandlerError", "MissingReference", "AssertionFailed", "NetworkBlocked",
    "ProcessBlocked", "InvalidResponse",
}


def _valid_step(result: object, step: dict) -> bool:
    if not isinstance(result, dict) or set(result) != {
        "id", "definition_digest", "status", "checks", "error"
    }:
        return False
    if result["id"] != step["id"] or result["definition_digest"] != digest(
        {"handler": step["handler"], "event": step["event"]}
    ):
        return False
    if result["status"] not in {"passed", "failed", "skipped"}:
        return False
    if not isinstance(result["error"], (str, type(None))) or result["error"] not in _ERRORS:
        return False
    checks = result["checks"]
    if not isinstance(checks, list) or (checks and len(checks) != len(step["expect"])):
        return False
    for check, assertion in zip(checks, step["expect"]):
        operator = next(key for key in assertion if key != "path")
        if not isinstance(check, dict) or set(check) != {"id", "definition_digest", "passed"}:
            return False
        if check["id"] != f"{assertion['path']}:{operator}":
            return False
        if check["definition_digest"] != digest(assertion) or type(check["passed"]) is not bool:
            return False
    if result["status"] == "passed":
        return bool(checks) and all(c["passed"] for c in checks) and result["error"] is None
    if result["status"] == "skipped":
        return not checks and result["error"] is None
    return result["error"] is not None and (not checks or not all(c["passed"] for c in checks))


def _read_frames(output: str | bytes | None, scenario: dict) -> tuple[list, dict | None]:
    """Read only complete, ordered, schema-checked progress frames.

    TimeoutExpired may expose bytes even when subprocess text mode is enabled.
    A partial final line is ignored; it cannot provide completed-step evidence.
    """
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    if not output:
        return [], None
    complete_lines = output.split("\n")[:-1]
    completed = []
    final = None
    for line_index, line in enumerate(complete_lines):
        try:
            frame = json.loads(line)
            if not isinstance(frame, dict) or len(frame) != 2:
                break
            if frame.get("type") == "step" and final is None:
                if len(completed) >= len(scenario["steps"]):
                    break
                result = frame.get("step")
                if not _valid_step(result, scenario["steps"][len(completed)]):
                    break
                already_failed = any(s["status"] == "failed" for s in completed)
                if (already_failed and result["status"] != "skipped") or (
                    not already_failed and result["status"] == "skipped"
                ):
                    break
                completed.append(result)
            elif frame.get("type") == "scenario" and final is None:
                if line_index != len(complete_lines) - 1 or not output.endswith("\n"):
                    break
                candidate = frame.get("scenario")
                if not isinstance(candidate, dict) or set(candidate) != {"id", "status", "steps"}:
                    break
                expected_status = "passed" if all(s["status"] == "passed" for s in completed) else "failed"
                if (
                    len(completed) != len(scenario["steps"])
                    or candidate["id"] != scenario["id"]
                    or candidate["steps"] != completed
                    or candidate["status"] != expected_status
                ):
                    break
                final = candidate
            else:
                final = None
                break
        except (ValueError, TypeError):
            break
    return completed, final


def run_suite(
    project: dict, suite: dict, project_dir: Path, timeout: float = 10.0
) -> dict:
    """Execute each scenario in its own bounded worker and return payload-free evidence.

    ``project_dir`` contains the trusted Python modules named by ``project``.
    ``timeout`` is a positive, finite wall-clock budget in seconds *per scenario*.
    Invalid manifests fail before any handler import. Handler failures are results.
    """
    validate_project(project)
    validate_suite(suite, project)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ValueError("timeout must be a positive finite number")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a positive finite number")
    project_dir = Path(project_dir).resolve(strict=True)
    if not project_dir.is_dir():
        raise ValueError("project_dir must be a directory")
    worker = Path(__file__).with_name("worker.py").resolve()
    scenarios = []
    for scenario in suite["scenarios"]:
        with tempfile.TemporaryDirectory(prefix="lambda-flow-lab-") as directory:
            payload = {
                "project": project,
                "scenario": scenario,
                "project_dir": str(project_dir),
                "timeout": timeout,
            }
            try:
                with subprocess.Popen(
                    [sys.executable, "-I", "-B", str(worker)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    cwd=project_dir,
                    env=_environment(Path(directory)),
                ) as process:
                    timed_out = False
                    try:
                        stdout, _ = process.communicate(
                            input=json.dumps(payload, allow_nan=False), timeout=timeout
                        )
                    except subprocess.TimeoutExpired:
                        # Drain the pipes after killing. TimeoutExpired.stdout can be
                        # None if pipes closed before a shutdown/thread hang.
                        timed_out = True
                        process.kill()
                        stdout, _ = process.communicate()
                    completed, result = _read_frames(stdout, scenario)
                    if timed_out:
                        result = _failed_scenario(scenario, "Timeout", completed)
                    elif process.returncode != 0 or result is None:
                        result = _failed_scenario(scenario, "WorkerError", completed)
            except (OSError, UnicodeError):
                result = _failed_scenario(scenario, "WorkerError")
            scenarios.append(result)
    return {
        "version": 1,
        "evidence": "local-component-integration",
        "cloud_verified": False,
        "suite_digest": digest(suite),
        "project_digest": digest(project),
        "status": "passed" if all(s["status"] == "passed" for s in scenarios) else "failed",
        "scenarios": scenarios,
        "limitations": list(LIMITATIONS),
    }
