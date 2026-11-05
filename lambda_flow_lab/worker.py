"""Private subprocess protocol for the flow runner. Only execute trusted handlers."""

from __future__ import annotations

import importlib
import json
import math
import os
from pathlib import Path
import sys
import time
import uuid

# -I prevents the current working directory and PYTHONPATH from injecting imports.
# Import our schema before adding the explicitly selected trusted project directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lambda_flow_lab.schema import (  # noqa: E402
    ValidationError,
    digest,
    evaluate_assertion,
    resolve_event,
    validate_project,
    validate_suite,
)


class BlockedOperation(RuntimeError):
    """An accidental network or child-process operation was denied."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _offline_guard(event: str, args: tuple) -> None:
    if event.startswith("socket."):
        raise BlockedOperation("NetworkBlocked")
    if event in {"subprocess.Popen", "os.system", "os.fork", "os.forkpty", "pty.spawn"}:
        raise BlockedOperation("ProcessBlocked")
    if event.startswith(("os.exec", "os.spawn", "os.posix_spawn", "os.startfile")):
        raise BlockedOperation("ProcessBlocked")


class LambdaContext:
    """Small synthetic context, not a Lambda runtime emulator."""

    def __init__(self, alias: str, deadline: float):
        self.aws_request_id = str(uuid.uuid4())
        self.function_name = alias
        self.function_version = "$LATEST"
        self.memory_limit_in_mb = 128
        self.invoked_function_arn = f"arn:aws:lambda:local:000000000000:function:{alias}"
        self.log_group_name = f"/local/lambda-flow-lab/{alias}"
        self.log_stream_name = "synthetic"
        self.identity = None
        self.client_context = None
        self._deadline = deadline

    def get_remaining_time_in_millis(self) -> int:
        return max(0, math.ceil((self._deadline - time.monotonic()) * 1000))


def _json_response(value: object, depth: int = 0) -> None:
    if depth > 64:
        raise ValueError("response exceeds nesting limit")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _json_response(item, depth + 1)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _json_response(item, depth + 1)
        return
    raise ValueError("handler response is not JSON")


def _checks(response: object, expectations: list[dict]) -> list[dict]:
    result = []
    for assertion in expectations:
        operator = next(key for key in assertion if key != "path")
        result.append(
            {
                "id": f"{assertion['path']}:{operator}",
                "definition_digest": digest(assertion),
                "passed": evaluate_assertion(response, assertion),
            }
        )
    return result


def execute(payload: dict, progress=None) -> dict:
    """Return safe identifiers and outcomes, never handler payloads or log text."""
    project = validate_project(payload["project"])
    scenario = payload["scenario"]
    validate_suite({"version": 1, "scenarios": [scenario]}, project)
    sys.path.insert(0, payload["project_dir"])
    sys.addaudithook(_offline_guard)
    deadline = time.monotonic() + payload["timeout"]
    responses = {}
    handlers = {}
    steps = []
    failed = False
    for step in scenario["steps"]:
        result = {
            "id": step["id"],
            "definition_digest": digest({"handler": step["handler"], "event": step["event"]}),
            "status": "skipped",
            "checks": [],
            "error": None,
        }
        steps.append(result)
        if failed:
            if progress is not None:
                progress(result)
            continue
        try:
            event = resolve_event(step["event"], responses)
        except (ValidationError, KeyError, IndexError, ValueError, TypeError):
            result.update(status="failed", error="MissingReference")
            failed = True
            if progress is not None:
                progress(result)
            continue
        alias = step["handler"]
        try:
            if alias not in handlers:
                module_name, function_name = project["handlers"][alias].split(":")
                handlers[alias] = getattr(importlib.import_module(module_name), function_name)
            response = handlers[alias](event, LambdaContext(alias, deadline))
        except BlockedOperation as exc:
            result.update(status="failed", error=exc.code)
            failed = True
            if progress is not None:
                progress(result)
            continue
        except BaseException:
            # Includes SystemExit and intentionally excludes exception text/type names.
            result.update(status="failed", error="HandlerError")
            failed = True
            if progress is not None:
                progress(result)
            continue
        try:
            _json_response(response)
            serialized = json.dumps(response, allow_nan=False, ensure_ascii=False)
            if len(serialized.encode("utf-8")) > 2 * 1024 * 1024:
                raise ValueError("response exceeds size limit")
            # Snapshot responses so later handler mutations cannot change prior results.
            response = json.loads(serialized)
        except (ValueError, TypeError, RecursionError, UnicodeError):
            result.update(status="failed", error="InvalidResponse")
            failed = True
            if progress is not None:
                progress(result)
            continue
        result["checks"] = _checks(response, step["expect"])
        failed = not all(check["passed"] for check in result["checks"])
        result["status"] = "failed" if failed else "passed"
        result["error"] = "AssertionFailed" if failed else None
        responses[step["id"]] = response
        if progress is not None:
            progress(result)
    return {"id": scenario["id"], "status": "failed" if failed else "passed", "steps": steps}


def main() -> int:
    # Save a dedicated protocol fd before discarding Python and native-code output.
    # This also suppresses os.write(1/2, ...) and import-time logs from handlers.
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8")

    def emit(frame: dict) -> None:
        json.dump(frame, protocol, allow_nan=False)
        protocol.write("\n")
        protocol.flush()

    with open(os.devnull, "w", encoding="utf-8") as sink:
        os.dup2(sink.fileno(), sys.stdout.fileno())
        os.dup2(sink.fileno(), sys.stderr.fileno())
        try:
            payload = json.load(sys.stdin)
            result = execute(payload, lambda step: emit({"type": "step", "step": step}))
            emit({"type": "scenario", "scenario": result})
            return 0
        except BaseException:
            return 2
        finally:
            protocol.close()


if __name__ == "__main__":
    raise SystemExit(main())
