"""Behavioral checks for the declarative format and reference/assertion semantics."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from lambda_flow_lab.schema import (
    MAX_BYTES,
    ValidationError,
    digest,
    evaluate_assertion,
    load_json,
    resolve_event,
    validate_project,
    validate_suite,
)


def project():
    return {"version": 1, "handlers": {"create": "demo.orders:create"}}


def suite():
    return {
        "version": 1,
        "scenarios": [{"id": "happy_path", "steps": [{
            "id": "create", "handler": "create", "event": {"sku": "synthetic"},
            "expect": [{"path": "/status", "equals": "created"}],
        }]}],
    }


class LoadTests(unittest.TestCase):
    def load(self, raw):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_bytes(raw)
            return load_json(path)

    def test_reads_utf8_and_returns_literal_types(self):
        self.assertEqual(self.load('{"text":"café","nil":null}'.encode()), {"text": "café", "nil": None})

    def test_duplicate_keys_are_rejected_at_any_depth(self):
        for raw in (b'{"x":1,"x":2}', b'{"nested":{"x":1,"x":1}}'):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                self.load(raw)

    def test_nonfinite_and_malformed_json_rejected(self):
        for raw in (b'NaN', b'Infinity', b'-Infinity', b'1e999', b'{', b'\xff', b'{} trailing'):
            with self.subTest(raw=raw), self.assertRaises(ValidationError):
                self.load(raw)

    def test_size_limit_checked_before_decoding(self):
        with self.assertRaises(ValidationError):
            self.load(b' ' * (MAX_BYTES + 1))

    def test_utf8_size_is_not_inflated_by_ascii_escaping(self):
        value = "é" * 400_000
        self.assertEqual(self.load(json.dumps(value, ensure_ascii=False).encode()), value)
        self.assertEqual(len(digest(value)), 64)

    def test_depth_limit_and_boundary(self):
        self.load(b'[' * 64 + b'0' + b']' * 64)
        with self.assertRaises(ValidationError):
            self.load(b'[' * 65 + b'0' + b']' * 65)


class ProjectTests(unittest.TestCase):
    def test_returns_the_validated_object(self):
        value = project()
        self.assertIs(validate_project(value), value)

    def test_project_rejects_executable_or_unknown_fields(self):
        for extra in ({"hooks": ["shell"]}, {"command": "anything"}):
            value = project() | extra
            with self.assertRaises(ValidationError):
                validate_project(value)

    def test_bad_target_and_alias_rejected(self):
        for alias, target in (
            ("bad.alias", "demo:handler"), ("1bad", "demo:handler"),
            ("ok", "demo.py:handler" + "()"), ("ok", "../demo:handler"),
            ("ok", "demo:Class.handler"), ("ok", "demo:handler\n"),
            ("ok", "demo"), ("ok", 1), ("x" * 65, "demo:handler"),
        ):
            with self.subTest(alias=alias, target=target), self.assertRaises(ValidationError):
                validate_project({"version": 1, "handlers": {alias: target}})

    def test_version_is_integer_one_not_boolean(self):
        for version in (True, "1", 1.0, 2, None):
            value = project() | {"version": version}
            with self.subTest(version=version), self.assertRaises(ValidationError):
                validate_project(value)

    def test_empty_or_excessive_handler_mapping_rejected(self):
        for handlers in ({}, [], {f"h{i}": "demo:handler" for i in range(101)}):
            with self.assertRaises(ValidationError):
                validate_project({"version": 1, "handlers": handlers})


class SuiteTests(unittest.TestCase):
    def test_valid_suite_returns_same_object(self):
        value = suite()
        self.assertIs(validate_suite(value, project()), value)

    def test_unknown_fields_rejected_at_every_format_level(self):
        for level in ("suite", "scenario", "step", "assertion"):
            value = suite()
            targets = {"suite": value, "scenario": value["scenarios"][0],
                       "step": value["scenarios"][0]["steps"][0],
                       "assertion": value["scenarios"][0]["steps"][0]["expect"][0]}
            targets[level]["unknown"] = True
            with self.subTest(level=level), self.assertRaises(ValidationError):
                validate_suite(value, project())

    def test_cannot_have_zero_scenarios_steps_or_assertions(self):
        for level in ("scenarios", "steps", "expect"):
            value = suite()
            targets = {"scenarios": value, "steps": value["scenarios"][0],
                       "expect": value["scenarios"][0]["steps"][0]}
            targets[level][level] = []
            with self.subTest(level=level), self.assertRaises(ValidationError):
                validate_suite(value, project())

    def test_rejects_excessive_scenarios_steps_and_assertions(self):
        for level in ("scenarios", "steps", "expect"):
            value = suite()
            targets = {"scenarios": value, "steps": value["scenarios"][0],
                       "expect": value["scenarios"][0]["steps"][0]}
            targets[level][level] *= 101
            with self.subTest(level=level), self.assertRaises(ValidationError):
                validate_suite(value, project())

    def test_duplicate_ids_and_duplicate_checks_rejected(self):
        for level in ("scenarios", "steps", "expect"):
            value = suite()
            targets = {"scenarios": value, "steps": value["scenarios"][0],
                       "expect": value["scenarios"][0]["steps"][0]}
            targets[level][level].append(copy.deepcopy(targets[level][level][0]))
            with self.subTest(level=level), self.assertRaises(ValidationError):
                validate_suite(value, project())

    def test_aliases_must_be_in_reviewed_project(self):
        value = suite()
        value["scenarios"][0]["steps"][0]["handler"] = "other"
        with self.assertRaises(ValidationError):
            validate_suite(value, project())

    def test_backwards_references_allowed_but_self_and_forward_rejected(self):
        value = suite()
        step = copy.deepcopy(value["scenarios"][0]["steps"][0])
        step["id"] = "inspect"
        step["event"] = {"id": {"$from": "create#/order_id"}}
        value["scenarios"][0]["steps"].append(step)
        validate_suite(value, project())
        for target in ("inspect#/order_id", "later#/order_id"):
            step["event"]["id"]["$from"] = target
            with self.subTest(target=target), self.assertRaises(ValidationError):
                validate_suite(value, project())

    def test_reference_does_not_cross_scenario_boundary(self):
        value = suite()
        other = copy.deepcopy(value["scenarios"][0])
        other["id"] = "other"
        other["steps"][0]["event"] = {"$from": "create#"}
        value["scenarios"].append(other)
        with self.assertRaises(ValidationError):
            validate_suite(value, project())

    def test_arbitrary_json_event_and_literal_expected_values_allowed(self):
        value = suite()
        step = value["scenarios"][0]["steps"][0]
        step["event"] = [None, "${create}", True]
        step["expect"] = [{"path": "", "equals": {"$from": "literal#"}}]
        validate_suite(value, project())

    def test_invalid_assertion_operators_and_pointers_rejected(self):
        invalid = [
            {"path": "/x"}, {"path": "/x", "equals": 1, "exists": True},
            {"path": "/x", "exists": 1}, {"path": "/x", "length": True},
            {"path": "/x", "length": -1}, {"path": "/x", "length": 1.0},
            {"path": "x", "equals": 1}, {"path": "/~2", "equals": 1},
            {"path": "/x~", "equals": 1}, {"path": 1, "equals": 1},
        ]
        for assertion in invalid:
            value = suite()
            value["scenarios"][0]["steps"][0]["expect"] = [assertion]
            with self.subTest(assertion=assertion), self.assertRaises(ValidationError):
                validate_suite(value, project())

    def test_programmatic_inputs_cannot_smuggle_non_json_values(self):
        for invalid in (float("inf"), float("nan"), (1, 2), {1: "key"}, object()):
            value = suite()
            value["scenarios"][0]["steps"][0]["event"] = invalid
            with self.subTest(kind=type(invalid)), self.assertRaises(ValidationError):
                validate_suite(value, project())

    def test_programmatic_cycle_rejected(self):
        value = suite()
        value["loop"] = value
        with self.assertRaises(ValidationError):
            validate_suite(value, project())


class ReferenceTests(unittest.TestCase):
    def test_nested_references_copy_results_without_interpolating_strings(self):
        responses = {"create": {"id": "synthetic-1", "items": [{"sku": "test"}]}}
        event = {"id": {"$from": "create#/id"}, "all": [{"$from": "create#"}],
                 "literal": "${create#/id}"}
        result = resolve_event(event, responses)
        self.assertEqual(result["id"], "synthetic-1")
        self.assertEqual(result["literal"], "${create#/id}")
        result["all"][0]["items"][0]["sku"] = "changed"
        self.assertEqual(responses["create"]["items"][0]["sku"], "test")
        self.assertEqual(event["id"], {"$from": "create#/id"})

    def test_null_reference_is_resolved_but_missing_is_error(self):
        self.assertIsNone(resolve_event({"$from": "a#/x"}, {"a": {"x": None}}))
        with self.assertRaises(ValidationError):
            resolve_event({"$from": "a#/missing"}, {"a": {"x": None}})

    def test_invalid_reference_shape_and_syntax_rejected(self):
        invalid = [{"$from": "a#", "extra": 1}, {"$from": 1}, {"$from": "a"},
                   {"$from": "a#x"}, {"$from": "a#/~2"}, {"$from": "unknown#"}]
        for event in invalid:
            with self.subTest(event=event), self.assertRaises(ValidationError):
                resolve_event(event, {"a": {}})


class AssertionTests(unittest.TestCase):
    def test_missing_is_different_from_null(self):
        self.assertTrue(evaluate_assertion({"x": None}, {"path": "/x", "equals": None}))
        self.assertFalse(evaluate_assertion({}, {"path": "/x", "equals": None}))
        self.assertTrue(evaluate_assertion({"x": None}, {"path": "/x", "exists": True}))
        self.assertTrue(evaluate_assertion({}, {"path": "/x", "exists": False}))
        self.assertTrue(evaluate_assertion(None, {"path": "", "exists": True}))

    def test_bool_is_never_equal_to_numeric_in_nested_structures(self):
        pairs = [(True, 1), (False, 0), ({"x": [True]}, {"x": [1]}), ([False], [0.0])]
        for actual, expected in pairs:
            with self.subTest(actual=actual, expected=expected):
                self.assertFalse(evaluate_assertion(actual, {"path": "", "equals": expected}))
        self.assertTrue(evaluate_assertion(1, {"path": "", "equals": 1.0}))

    def test_pointer_escapes_empty_keys_and_array_indices(self):
        value = {"a/b": {"~x": [9]}, "": "empty", "~1": "literal"}
        for pointer, expected in (("/a~1b/~0x/0", 9), ("/", "empty"), ("/~01", "literal")):
            with self.subTest(pointer=pointer):
                self.assertTrue(evaluate_assertion(value, {"path": pointer, "equals": expected}))

    def test_invalid_array_indices_do_not_alias_elements(self):
        for pointer in ("/01", "/-1", "/-", "/2", "/" + "9" * 5000):
            with self.subTest(pointer=pointer):
                self.assertTrue(evaluate_assertion([10, 20], {"path": pointer, "exists": False}))
        self.assertTrue(evaluate_assertion({"01": "literal"}, {"path": "/01", "equals": "literal"}))

    def test_length_only_applies_to_collections_and_strings(self):
        for value in ([], {}, ""):
            self.assertTrue(evaluate_assertion(value, {"path": "", "length": 0}))
        for value in (0, False, None):
            self.assertFalse(evaluate_assertion(value, {"path": "", "length": 0}))

    def test_digest_is_order_independent_and_changes_with_assertion(self):
        self.assertEqual(digest({"a": 1, "b": 2}), digest({"b": 2, "a": 1}))
        self.assertNotEqual(digest({"equals": True}), digest({"equals": 1}))
        self.assertEqual(len(digest({})), 64)


if __name__ == "__main__":
    unittest.main()
