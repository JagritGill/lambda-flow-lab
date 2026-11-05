# Synthetic order workflow

This example runs three handler entry points across two modules, with a separate
SQLite adapter and a real temporary database. Each scenario creates fresh state;
steps within it share that state. These are local component integration tests.

The flow creates an order, sends its returned identifier into fulfillment, then
reads persisted orders and outbox rows through a separate database connection.
It also checks repeated submission and fulfillment, conflicting use of an
idempotency key, invalid input, and a missing order. Observing the outbox matters:
a handler can return a successful response while accidentally inserting a second
event, which the regression demonstration catches.

From the repository root:

```sh
python -m lambda_flow_lab run examples/order_workflow/flows.json \
  --project examples/order_workflow/project.json --output report.json
python scripts/regression_demo.py
```

The regression script copies the example into a temporary directory, bypasses the
fulfillment idempotency guard in the copy, and checks that the unchanged flow and
report comparison detect the duplicate persisted event. Its exit code is zero
when this expected regression was caught. It never edits the tracked example.

All fixtures are synthetic. `contract.json` is a deliberately authored description
that can be exported into an AI prompt; the tool never calls an AI service.

This does **not** exercise AWS Lambda hosting, API Gateway, SQS delivery, outbox
dispatch, DynamoDB semantics, IAM, concurrency, cold starts, or a deployed product.
The `inspect` handler is a local test adapter and must not be deployed as an
unauthenticated administration endpoint. SQLite idempotency in sequential local
tests does not establish distributed idempotency under concurrent cloud requests.
