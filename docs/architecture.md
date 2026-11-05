# Architecture and evidence

Lambda Flow Lab replays a product workflow across Python Lambda-style handlers.
One scenario can create an order, invoke its fulfillment component, and query
persisted state. Assertions describe the observable behavior that must survive
a code change. The bundled example integrates actual handler code with SQLite;
it does not emulate AWS services.

## Execution

```text
project.json         flows.json
trusted handlers     reviewed events and assertions
       \              /
        validate inputs
              |
       isolated scenario worker
       step 1 -> step 2 -> step 3
       handlers + temporary local state
              |
       payload-free result report
              |
       compare with a saved baseline
```

The project file maps aliases to Python callables. The suite can select only
those aliases. The runner starts a new Python process and temporary state
directory for each scenario. Steps within a scenario share a process, imported
modules, and `FLOW_LAB_STATE_DIR`. This models a deliberate sequence with warm
module state; it does not model Lambda's scheduling or concurrency.

Events can reference an earlier step's JSON response. Each step must contain at
least one assertion. A failing step stops that scenario, marking later steps
skipped; other scenarios still run. A configurable timeout bounds each scenario.
Workers receive a synthetic Lambda context, not an AWS runtime context.

Workers send payload-free progress after each completed step. If a worker times
out or exits unexpectedly, the report preserves that completed evidence and marks
the next uncompleted step failed. A failure during shutdown, or after a step has
already failed, appears as a scenario-level `error` without blaming an earlier
completed step. Remaining steps are skipped.

The order workflow's SQLite file and outbox records are real local storage.
Calling the fulfillment handler explicitly is a simulated delivery boundary.
There is no actual SQS polling, API Gateway routing, or deployed Lambda runtime.
Use the example as a pattern for your own test adapters and dependencies, not as
evidence that a production AWS deployment works.

## Reading the evidence

Every run is labeled `local-component-integration` and
`cloud_verified: false`. A passing report means the executed steps met the
specified assertions in the local environment. It does not establish complete
coverage, deployment correctness, or freedom from regressions outside the
tested behavior.

The evidence label names the runner mode. It does not prove that an arbitrary
user-supplied handler touched a downstream component: pure functions or mocked
dependencies provide narrower evidence. The bundled SQLite workflow does
exercise real persistence, checked through a separate observation component.

Reports retain scenario, step, and assertion identifiers, status, safe error
codes, and digests of assertion definitions. They omit handler logs, exception
messages, raw events, responses, and expected values. Names and identifiers are
still user-selected text: keep them non-sensitive. Definition digests are not
encryption and may reveal low-entropy values through guessing.

The suite and project digests identify configuration, not the full application
source or dependency graph. Preserve the source revision and dependency versions
alongside any baseline used for a release decision. Reports are ordinary JSON,
not signed attestations; someone who can alter them can falsify evidence.

Comparison uses stable scenario, step, and assertion identities. It flags current
failures, removed coverage, changed assertion definitions, changed step inputs
or handler aliases, and changes to the project's handler mapping, as well as a
pass becoming a failure. Step definition digests cover the handler alias and
event. Added passing scenarios and checks are reported separately. Adding a step
to an existing flow requires review because it can change the state seen by old
checks; reordering existing steps also fails comparison. A changed
expectation or contract may be an intentional product change, but requires
review before accepting a new baseline. Do not overwrite a known-good baseline
merely to get a green run.

The comparison loader accepts reports up to 64 MiB because assertion metadata
can make a report larger than its 2 MiB input suite.

## Trust boundary

The default runner has no AWS SDK, AI API client, deployment path, or telemetry.
It passes a sanitized environment to workers and redirects temporary home and
state locations. A Python audit hook blocks common socket/DNS and child-process
operations to catch accidental network use.

**This is not a security sandbox. Run only trusted application code and trusted
dependencies.** Imported code executes with the current OS user's permissions.
Native extensions, direct system calls, file reads, or other techniques can
bypass Python-level restrictions. Temporary state and process isolation do not
contain malicious code. Use an independently configured OS/container sandbox if
you need a stronger boundary; review that environment before executing code.

Validation and AWS planning do not import handlers. Running a suite does. Keep
the trusted project configuration under review when accepting AI-generated
scenarios. No generated scenario may introduce shell hooks or callable paths.

## Extending the project

Keep orchestration independent of dependencies under test. New runners should
provide truthful evidence labels and explicit activation. An emulator runner
must distinguish emulator behavior from AWS behavior. A live runner would need
the separate controls described in [AWS boundary](aws-boundary.md); v0.1 does
not include one.
