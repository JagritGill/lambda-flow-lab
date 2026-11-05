# Contributor and AI-agent guidance

This repository helps test product workflows after AI-assisted code changes.
Preserve meaningful assertions across components and report exactly what ran.

- Use Python 3.11+ and keep the runtime and test suite dependency-free unless a
  change has a clear, reviewed reason to add a dependency.
- Default workflows must be local. Do not invoke AWS, deploy resources, discover
  or change credentials, send data to AI APIs, or introduce telemetry as part of
  ordinary development or testing.
- Use synthetic fixtures. Do not read or copy customer/employer source, logs,
  tokens, or datasets into this project. Do not add CodeRabbit integration.
- Only run trusted handlers and dependencies. The Python audit hook is a guard
  against accidental network/process use, not a security sandbox.
- Keep reports free of raw event/response payloads, logs, exception messages, and
  expected values. Keep identifiers non-sensitive.
- Label local component integration, simulation/emulation, and live cloud
  evidence accurately. A green run never proves that nothing else broke.
- Validate generated suites before execution. Review handler mappings and
  assertions. Never weaken checks or overwrite baselines merely to make a
  regression pass.
- For changes to scenario or report formats, update validation, documentation,
  examples, and meaningful compatibility tests together.

Run `python -m unittest discover -s tests -v` and
`python scripts/regression_demo.py`. Use the documented example commands as
smoke checks when modifying the CLI. Do not edit tracked examples to demonstrate
a failure; use a temporary copy.

An explicitly authorized publication of this original repository is permitted.
Live cloud operations, paid API calls, or transmission of user data require their
own scope and approval; publishing source does not authorize those actions.
