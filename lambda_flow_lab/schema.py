"""Strict, dependency-free validation for trusted projects and declarative flows.

Flow documents contain data, never executable expressions. Only a separately
reviewed project document selects the Python handlers that a runner may import.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


MAX_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 64
MAX_ITEMS = 100
_ID = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}\Z")
_TARGET = re.compile(
    r"[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*"
    r":[a-zA-Z_][a-zA-Z0-9_]*\Z"
)
_BAD_ESCAPE = re.compile(r"~(?:[^01]|$)")
_ARRAY_INDEX = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_MISSING = object()


class ValidationError(ValueError):
    """A document, reference, or assertion violates the flow format."""


def _reject_constant(_value: str) -> None:
    raise ValidationError("JSON must not contain NaN or infinity")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError("JSON contains a duplicate object key")
        result[key] = value
    return result


def _ensure_json(value: Any, *, size_limit: bool = True) -> None:
    """Check types/depth before serializing, including programmatic inputs."""
    pending = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if depth > MAX_DEPTH:
            raise ValidationError(f"JSON nesting exceeds {MAX_DEPTH} levels")
        kind = type(current)
        if kind is dict:
            if any(type(key) is not str for key in current):
                raise ValidationError("JSON object keys must be strings")
            pending.extend((child, depth + 1) for child in current.values())
        elif kind is list:
            pending.extend((child, depth + 1) for child in current)
        elif kind is float:
            if not math.isfinite(current):
                raise ValidationError("JSON numbers must be finite")
        elif kind not in (str, int, bool, type(None)):
            raise ValidationError("Value is not a JSON type")
    if size_limit:
        try:
            encoded = json.dumps(
                value, allow_nan=False, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        except (ValueError, OverflowError, RecursionError, UnicodeError) as exc:
            raise ValidationError("Value cannot be encoded as JSON") from exc
        if len(encoded) > MAX_BYTES:
            raise ValidationError(f"JSON document exceeds {MAX_BYTES} bytes")


def load_json(path: str | Path, *, max_bytes: int = MAX_BYTES) -> Any:
    """Load bounded UTF-8 JSON; inputs default to 2 MiB, reports may opt higher."""
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValidationError("JSON size limit must be a positive integer")
    with Path(path).open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValidationError(f"JSON document exceeds {max_bytes} bytes")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except ValidationError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ValidationError("Input must be valid UTF-8 JSON") from exc
    # The file's actual byte length is the limit here; ASCII escaping is not
    # allowed to make an otherwise valid UTF-8 file appear too large.
    _ensure_json(value, size_limit=False)
    return value


def _object(value: Any, required: set[str], optional: set[str], where: str) -> None:
    if type(value) is not dict:
        raise ValidationError(f"{where} must be an object")
    keys = set(value)
    if required - keys:
        raise ValidationError(f"{where} is missing required fields")
    if keys - required - optional:
        raise ValidationError(f"{where} contains unknown fields")


def _version(value: Any) -> None:
    if type(value) is not int or value != 1:
        raise ValidationError("version must be the integer 1")


def _identifier(value: Any, where: str) -> None:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValidationError(f"{where} must be a valid identifier of 1..64 characters")


def _items(value: Any, where: str) -> None:
    if type(value) is not list or not 1 <= len(value) <= MAX_ITEMS:
        raise ValidationError(f"{where} must contain 1..{MAX_ITEMS} items")


def _pointer(value: Any) -> list[str]:
    if type(value) is not str:
        raise ValidationError("JSON Pointer must be a string")
    if value == "":
        return []
    if not value.startswith("/") or _BAD_ESCAPE.search(value):
        raise ValidationError("Invalid RFC6901 JSON Pointer")
    return [token.replace("~1", "/").replace("~0", "~") for token in value[1:].split("/")]


def _lookup(value: Any, pointer: str) -> Any:
    current = value
    for token in _pointer(pointer):
        if type(current) is dict:
            if token not in current:
                return _MISSING
            current = current[token]
        elif type(current) is list:
            if not _ARRAY_INDEX.fullmatch(token):
                return _MISSING
            # Avoid int conversion of arbitrarily long numeric object tokens.
            if len(token) > len(str(len(current))):
                return _MISSING
            index = int(token)
            if index >= len(current):
                return _MISSING
            current = current[index]
        else:
            return _MISSING
    return current


def _reference(value: Any) -> tuple[str, str]:
    if type(value) is not str or "#" not in value:
        raise ValidationError("Reference must have the form step_id#<JSON Pointer>")
    step_id, pointer = value.split("#", 1)
    _identifier(step_id, "Reference step")
    _pointer(pointer)
    return step_id, pointer


def _validate_references(value: Any, available: set[str]) -> None:
    if type(value) is dict:
        if "$from" in value:
            if set(value) != {"$from"}:
                raise ValidationError("A reference object may contain only $from")
            step_id, _ = _reference(value["$from"])
            if step_id not in available:
                raise ValidationError("Reference must name a prior step in the same scenario")
        else:
            for child in value.values():
                _validate_references(child, available)
    elif type(value) is list:
        for child in value:
            _validate_references(child, available)


def _assertion(assertion: Any) -> str:
    _object(assertion, {"path"}, {"equals", "exists", "length"}, "Assertion")
    _pointer(assertion["path"])
    operators = set(assertion) - {"path"}
    if len(operators) != 1:
        raise ValidationError("An assertion requires exactly one operator")
    operator = next(iter(operators))
    expected = assertion[operator]
    if operator == "exists" and type(expected) is not bool:
        raise ValidationError("exists must be a boolean")
    if operator == "length" and (type(expected) is not int or expected < 0):
        raise ValidationError("length must be a nonnegative integer")
    return operator


def validate_project(obj: Any) -> dict[str, Any]:
    """Validate a reviewed alias-to-callable project mapping without importing it."""
    _ensure_json(obj)
    _object(obj, {"version", "handlers"}, set(), "Project")
    _version(obj["version"])
    handlers = obj["handlers"]
    if type(handlers) is not dict or not 1 <= len(handlers) <= MAX_ITEMS:
        raise ValidationError(f"handlers must contain 1..{MAX_ITEMS} aliases")
    for alias, target in handlers.items():
        _identifier(alias, "Handler alias")
        if type(target) is not str or not _TARGET.fullmatch(target):
            raise ValidationError("Handler target must be dotted.module:function")
    return obj


def validate_suite(obj: Any, project: dict[str, Any]) -> dict[str, Any]:
    """Validate flows, assertions and backwards-only data references."""
    validate_project(project)
    _ensure_json(obj)
    _object(obj, {"version", "scenarios"}, set(), "Suite")
    _version(obj["version"])
    _items(obj["scenarios"], "scenarios")
    scenario_ids: set[str] = set()
    for scenario in obj["scenarios"]:
        _object(scenario, {"id", "steps"}, {"description"}, "Scenario")
        _identifier(scenario["id"], "Scenario id")
        if scenario["id"] in scenario_ids:
            raise ValidationError("Scenario ids must be unique")
        scenario_ids.add(scenario["id"])
        if "description" in scenario and type(scenario["description"]) is not str:
            raise ValidationError("Scenario description must be a string")
        _items(scenario["steps"], "steps")
        step_ids: set[str] = set()
        for step in scenario["steps"]:
            _object(step, {"id", "handler", "event", "expect"}, set(), "Step")
            _identifier(step["id"], "Step id")
            if step["id"] in step_ids:
                raise ValidationError("Step ids must be unique within a scenario")
            _identifier(step["handler"], "Step handler")
            if step["handler"] not in project["handlers"]:
                raise ValidationError("Step handler alias is not in the project")
            _validate_references(step["event"], step_ids)
            _items(step["expect"], "expect")
            assertion_ids: set[str] = set()
            for assertion in step["expect"]:
                operator = _assertion(assertion)
                assertion_id = assertion["path"] + ":" + operator
                if assertion_id in assertion_ids:
                    raise ValidationError("Assertion path/operator pairs must be unique in a step")
                assertion_ids.add(assertion_id)
            step_ids.add(step["id"])
    return obj


def resolve_event(event: Any, responses: dict[str, Any]) -> Any:
    """Copy an event and replace explicit reference objects with earlier results."""
    _ensure_json(event)
    _validate_references(event, set(responses))

    def resolve(value: Any) -> Any:
        if type(value) is dict:
            if "$from" in value:
                step_id, pointer = _reference(value["$from"])
                selected = _lookup(responses[step_id], pointer)
                if selected is _MISSING:
                    raise ValidationError("Reference points to a missing response value")
                _ensure_json(selected)
                return copy.deepcopy(selected)
            return {key: resolve(child) for key, child in value.items()}
        if type(value) is list:
            return [resolve(child) for child in value]
        return value

    resolved = resolve(event)
    _ensure_json(resolved)
    return resolved


def _equal(left: Any, right: Any) -> bool:
    if type(left) in (int, float) and type(right) in (int, float):
        return left == right
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(_equal(left[key], right[key]) for key in left)
    if type(left) is list:
        return len(left) == len(right) and all(_equal(a, b) for a, b in zip(left, right))
    return left == right


def evaluate_assertion(response: Any, assertion: dict[str, Any]) -> bool:
    """Evaluate one assertion; a missing location is distinct from JSON null."""
    _ensure_json(response)
    _ensure_json(assertion)
    operator = _assertion(assertion)
    actual = _lookup(response, assertion["path"])
    if operator == "exists":
        return (actual is not _MISSING) == assertion["exists"]
    if actual is _MISSING:
        return False
    if operator == "length":
        return type(actual) in (str, list, dict) and len(actual) == assertion["length"]
    return _equal(actual, assertion["equals"])


def digest(obj: Any) -> str:
    """Return a deterministic SHA-256 for a JSON value, independent of key order."""
    _ensure_json(obj)
    canonical = json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
