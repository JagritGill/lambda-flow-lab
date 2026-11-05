# Contributing

Contributions should make workflow regressions easier to detect and evidence
easier to assess. Start with a reproducible case using synthetic inputs. Explain
which components interact, what behavior changed, and which assertion should
catch the defect.

## Local development

Use Python 3.11 or later from the repository root. The core and tests need no
third-party runtime packages.

```sh
python -m unittest discover -s tests -v
python scripts/regression_demo.py
python -m lambda_flow_lab validate examples/order_workflow/flows.json --project examples/order_workflow/project.json
python -m lambda_flow_lab run examples/order_workflow/flows.json --project examples/order_workflow/project.json --output report.json
```

The regression demonstration succeeds only when it catches its intentionally
introduced defect in a temporary copy. Review failure output before changing
an assertion or expected report.

## Changes and review

Keep a change focused. Add tests for meaningful behavior, especially validation,
reference resolution, fail-fast behavior, report comparison, and accidental
network/process guards. Update examples and docs when the user-facing behavior
changes. Show the before/after behavior and checks run in your pull request.

Avoid runtime dependencies unless they solve a concrete problem. Attribute any
adapted material and preserve its license. The current implementation is
original; linked upstream tools are references, not vendored code.

Use only trusted code and synthetic data. Do not include secrets, credentials,
customer logs, or proprietary application code in issues, fixtures, reports,
or prompts. Reports omit payloads but still contain user-authored identifiers.

Keep local development offline. Proposed cloud integrations must document an
explicit activation boundary, target scoping, cost limits, least privilege,
bounded retries, cleanup, and the precise evidence they provide. See
[AWS boundary](docs/aws-boundary.md). Do not make cloud calls to validate an
ordinary contribution.

For suspected vulnerabilities, follow [SECURITY.md](SECURITY.md).
