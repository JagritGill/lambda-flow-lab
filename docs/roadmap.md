# Roadmap: faster changes with preserved workflows

Research reviewed 2026-11-05. These are proposed extensions, not v0.1 capabilities or release commitments. Ship the Lambda-focused local runner first; no additional repository or cloud integration is required for this roadmap.

The broader goal is to help an AI coding assistant make a change, run relevant checks, and show which existing workflows still have evidence. A passing suite cannot guarantee that nothing broke. The useful contribution is an inspectable connection between product intent, tests, changes, and execution evidence.

## Existing tools to build alongside

| Tool | Relevant existing capability | Implication |
| --- | --- | --- |
| [Playwright Test Agents](https://playwright.dev/docs/test-agents) | Agents plan browser scenarios, generate tests, and propose repairs for failing tests. | Integrate browser evidence when needed; AI test generation is already available. Preserve expected behavior during repairs and make skipped tests visible. |
| [Pact](https://docs.pact.io/) | Consumer/provider contract tests check HTTP and message interactions. | Reuse contract evidence for service boundaries. It does not replace checks of complete business workflows or persisted side effects; see [Pact's scope guidance](https://docs.pact.io/getting_started/what_is_pact_good_for). |
| [Nx affected tasks](https://nx.dev/docs/features/ci-features/affected) | Selects work using changed files and configured task inputs/outputs. | Test selection is established practice. Correct dependency declarations and an understandable explanation of selection matter more than a new selector. |
| [promptfoo](https://www.promptfoo.dev/docs/intro/) | Declarative evaluations and assertions for prompts, models, and LLM applications, including CI usage. | Useful when the product itself has model behavior. Evaluating an LLM is distinct from checking ordinary application flows after AI-written code changes. Model-backed runs may send data to providers. |

## Priorities

### 1. Workflow contracts and coverage drift

Extend the existing baseline comparison with reviewed business-invariant IDs, such as `fulfillment_once`, linked to scenarios and their assertions. Record the tested revision and explicit execution boundary. Report uncovered invariants, removed checks, skipped checks, and changed expectations separately from failures. Require a visible explanation for intentional contract changes; never silently replace a baseline after a failure.

v0.1 already detects missing scenarios/steps/checks and changed definitions. This extension would explain their product significance. Success means a deliberately removed duplicate-fulfillment assertion still raises a reviewable coverage loss even when every remaining test passes. The mapping is reviewed metadata, not proof that every relevant business rule was discovered. “Coverage” here means declared invariant coverage, not line or branch coverage.

### 2. Explainable selection of affected workflows

Add a local mapping from source paths and shared dependencies to workflow IDs. Produce a selection plan with reasons before executing tests. Unknown files, configuration/schema changes, or an unavailable comparison base should fall back to the full suite. Keep a full-suite CI check while measuring selection accuracy and time savings.

This can reuse existing task graphs in repositories that already have them. The contribution would be the workflow-level explanation and explicit untested scope. Selected runs must record exclusions; an excluded test is not a pass or deleted coverage. This requires a versioned report extension because today's comparator intentionally treats missing checks as a regression. Validate the selector with seeded cross-component faults before relying on it.

### 3. Adapters for actual product entry points

Start with importing reports from existing Playwright/API/contract suites, then consider explicitly configured local HTTP execution. Associate their checks with the same workflow IDs while preserving each runner's evidence type. Verify user-visible outcomes and downstream effects together where the application supports observation. Leave browser control to Playwright and consumer/provider verification to Pact.

Add a live AWS executor only as a separately designed, opt-in boundary with scoped permissions, resource identity, cost controls, and cleanup ownership. A local handler result must never be relabeled as browser, deployed-service, or end-to-end evidence.

## Extension constraints

The current separation of strict scenario validation, reviewed handler mappings, subprocess execution, payload-free reports, and comparison provides useful seams for these additions. It is not a general adapter system yet: the worker runs trusted Python handlers, blocks ordinary network/process operations, and the report validator accepts only local component integration evidence. New adapters require explicit versioning and meaningful compatibility tests.

Keep the default dependency-free and offline. Use synthetic inputs, avoid automatic source/log uploads, and do not add model calls merely to select tests or compare results. Optional integrations need their own permissions and data-handling decisions. These recommendations are informed by existing tools; they make no first/only or guaranteed-regression-prevention claim.
