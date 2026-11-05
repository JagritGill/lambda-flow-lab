# Test a product after an AI change

Use AI to propose scenarios, then use deterministic execution to check them.
Lambda Flow Lab does not call a model, scan source code, or send any data to an
AI provider. Its `prompt` command creates a local Markdown file containing the
contract you explicitly supplied and instructions for drafting a suite.

## Establish a baseline

Start from a trusted, working revision. Describe public behavior using synthetic
inputs: the workflow entry points, success and failure results, persisted state,
and invariants that matter across components. Keep the callable mapping in the
project file under human review.

For the included order example:

```sh
python -m lambda_flow_lab validate examples/order_workflow/flows.json --project examples/order_workflow/project.json
python -m lambda_flow_lab run examples/order_workflow/flows.json --project examples/order_workflow/project.json --output baseline.json
```

Review the baseline assertions before relying on them. Save the corresponding
source commit and dependency versions outside the report, such as in CI run
metadata. A baseline produced by already broken code can preserve a bug.

## Ask for useful scenarios

```sh
python -m lambda_flow_lab prompt examples/order_workflow/contract.json --output prompt.md
```

Inspect `prompt.md` before sharing it with your chosen assistant. Supply only
synthetic, approved information. Sending it to a hosted model is a separate
action governed by your own data and cost decisions; this CLI never does that
for you. Paste the proposed JSON into a separate local file, for example
`candidate-flows.json`.

Ask the assistant to target observable invariants across the workflow:

- Creating an order makes it visible to another component.
- Fulfillment changes persisted state and writes exactly one outbox event.
- Retrying creation or fulfillment does not duplicate the side effect.
- Invalid input creates no order or event.
- An unknown identifier produces the documented failure without unrelated writes.

Expected values should come from the product contract or an independent oracle,
not be copied from the implementation's current output. A status code alone
often misses a broken downstream write. Query observable state through a
separate handler or adapter where possible.

## Review and replay after a change

```sh
python -m lambda_flow_lab validate candidate-flows.json --project examples/order_workflow/project.json
```

Validation catches format errors and invalid references. It cannot decide
whether a test is valuable. Review the assertions, fixture provenance, handler
mapping, and missing cases. Reject a proposal that weakens expected behavior
just to make changed code pass. Preserve stable scenario and step IDs when the
behavior being checked has not changed.

After the AI modifies the application, replay the same reviewed suite:

```sh
python -m lambda_flow_lab run examples/order_workflow/flows.json --project examples/order_workflow/project.json --output current.json
python -m lambda_flow_lab compare baseline.json current.json
```

Run/test failures return exit code `1`; invalid inputs or command errors return
`2`. `compare` returns `1` for a regression, removed coverage, changed assertion
or step definitions, a changed project handler mapping, or a currently failing
run. Adding or reordering execution steps in an existing flow also requires
review. New passing scenarios and checks are allowed and reported. A successful
comparison does not prove the absence of untested regressions. Investigate
failures before refreshing the baseline. Review intentional behavior changes
and their corresponding tests together.

## Prove that a test can fail

```sh
python scripts/regression_demo.py
```

The demonstration copies the example into a temporary directory, introduces an
idempotency regression, and verifies that workflow execution and comparison
detect it. It does not edit the tracked example. Catching one deliberate defect
demonstrates the relevant assertion's value; it is not a mutation score for the
entire application.

## What still needs coverage

The local workflow runs only what you explicitly arrange and assert. Add cases
for your own authentication, authorization, idempotency keys, failure recovery,
event ordering, and downstream observations. Deliberate sequential retries do
not test concurrent races. Direct handler calls do not test transport routing,
AWS event delivery, IAM, service configuration, deployment packaging, or real
cloud side effects. See [AWS boundary](aws-boundary.md) before planning those
tests.
