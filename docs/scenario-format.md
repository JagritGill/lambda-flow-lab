# Scenario format, version 1

Two JSON files separate trusted code selection from test data. Unknown
configuration fields are rejected. Arbitrary event and expected-value payloads
remain JSON data.

## Project file

```json
{
  "version": 1,
  "handlers": {
    "create": "demo.orders:create",
    "inspect": "demo.orders:inspect"
  }
}
```

Aliases map to a dotted Python module and one function name. The project file's
parent is the import root. Running a suite imports that code; validation does
not. Handler functions accept `(event, context)` and must return JSON-compatible
values. Aliases, scenario IDs, and step IDs match
`[a-zA-Z][a-zA-Z0-9_-]{0,63}`.

## Suite file

This illustrates the format; use the bundled example files for a complete
runnable workflow and its exact handler contract.

```json
{
  "version": 1,
  "scenarios": [
    {
      "id": "create_then_read",
      "description": "A created order is visible through the read component.",
      "steps": [
        {
          "id": "created",
          "handler": "create",
          "event": {"sku": "synthetic-item"},
          "expect": [
            {"path": "/status", "equals": "created"},
            {"path": "/order_id", "exists": true}
          ]
        },
        {
          "id": "read_back",
          "handler": "inspect",
          "event": {"order_id": {"$from": "created#/order_id"}},
          "expect": [
            {"path": "/status", "equals": "created"}
          ]
        }
      ]
    }
  ]
}
```

`description` is optional; `id` and `steps` are required on every scenario.
Every step requires `id`, `handler`, `event`, and a nonempty `expect` list.
Scenario IDs are unique within a suite; step IDs are unique within a scenario.

## Assertions

Each assertion has `path` and exactly one operator:

| Operator | Meaning | Example |
| --- | --- | --- |
| `equals` | Strict JSON equality; booleans do not equal numbers | `{"path":"/count","equals":1}` |
| `exists` | Whether the path resolves, regardless of its value | `{"path":"/error","exists":false}` |
| `length` | Length of an array, object, or string | `{"path":"/events","length":1}` |

A missing property is different from a property whose value is `null`.
`exists: true` accepts a present `null`; `equals: null` requires it. Array
order matters for equality. `length` requires a nonnegative integer, not a
boolean. Assertions with the same path and operator cannot repeat in a step.

Paths use JSON Pointer syntax: `""` selects the whole response, `/items/0/id`
selects an array element, `~1` represents `/`, and `~0` represents `~` inside
a property name. Paths operate on returned JSON data. If an API response has
a JSON-encoded `body` string, it remains a string; use a trusted adapter that
decodes it when you need assertions on body fields.

## References

An event object containing exactly `{"$from":"STEP_ID#POINTER"}` is replaced
with the selected value from an earlier step's response in the same scenario.
For example, `{"$from":"created#/order_id"}` references its `order_id`, while
`{"$from":"created#"}` references the entire response. References can appear
inside nested event objects or arrays. Unknown and forward step references are
invalid; a reference whose path is absent fails at execution time.

Ordinary strings are never interpolated. Assertion expectations are literal
JSON, not references or executable expressions. There are no shell hooks,
Python expressions, dynamic callable paths, or secret-fetching directives in
a suite.

## Isolation and limits

Each scenario receives a fresh process and temporary state directory; all its
steps share that state. `FLOW_LAB_STATE_DIR` is available to trusted handlers
that need local persistence. Scenarios cannot reference each other's responses.
Handler output and state are not retained after the scenario completes.

Version 1 accepts at most 2 MiB per input file and nesting depth 64, with
1–100 scenarios, 1–100 steps per scenario, and 1–100 assertions per step.
JSON must not contain duplicate object keys, NaN, or infinity. These bounds
limit accidental runaway inputs; they do not make untrusted code safe to run.

Use `validate` before `run` and review the format's
[execution and trust boundary](architecture.md).
