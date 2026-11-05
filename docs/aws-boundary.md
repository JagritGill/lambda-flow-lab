# The AWS integration boundary

Version 0.1 runs local component workflows only. It contains no live AWS
executor, SDK dependency, deployment command, credential discovery, or resource
cleanup automation. No AWS service invocation is needed to run its examples or
CI.

```sh
python -m lambda_flow_lab aws-plan examples/order_workflow/flows.json --project examples/order_workflow/project.json --output aws-plan.json
```

This creates a local inventory of the handlers and scenarios plus missing cloud
evidence. The plan is marked `executable: false` and `cloud_verified: false`.
It does not import handlers, contact AWS, check whether a deployment exists, or
verify account permissions. It is a review aid, not an infrastructure template.

## What each level proves

| Test path | Exercised boundary | Still unverified |
| --- | --- | --- |
| Included local workflow | Real Python handlers, sequential orchestration, local SQLite state and outbox assertions | AWS runtime, transport, service semantics, IAM and deployment |
| Emulator tests added by a project | The services and behavior supported by the configured emulator | Differences from AWS, production IAM and deployment configuration |
| Direct invocation of a deployed Lambda | Its deployed runtime, invocation configuration, and explicitly observed side effects | The upstream API/event-source path unless exercised separately |
| Live workflow from its real entry point | The deployed components traversed and asserted by that test | Unexecuted branches, other environments, concurrency and failure modes not tested |

A hand-built SQS-shaped event passed to a handler does not prove that SQS
delivered it, that an event source mapping is correct, or that retries and
acknowledgements work. An API-shaped event does not verify API Gateway routing
or authorization. A local SQLite transaction does not verify DynamoDB
consistency or conditional-write behavior.

AWS explains these distinctions in its
[Lambda testing guide](https://docs.aws.amazon.com/lambda/latest/dg/testing-guide.html).
It recommends testing interactions in the cloud because local tools cannot
fully reproduce the deployed configuration. The
[AWS serverless test samples](https://github.com/aws-samples/serverless-test-samples)
provide language-specific examples of those patterns.

## Before adding live tests

Live integration requires a separately approved scope. A plan should identify:

1. The dedicated test account, region, exact resources, and permitted operations.
2. The real workflow entry point and downstream evidence to assert.
3. Synthetic fixtures, ownership tags, unique run identifiers, and data retention.
4. Least-privilege credentials obtained through the team's approved mechanism.
5. Maximum invocations, polling attempts, execution time, concurrency, and costs.
6. Cleanup responsibilities and how failed or interrupted cleanup is surfaced.
7. A way to prevent production targets, accidental deployment, or automatic
   fallback from local/emulated tests to live AWS.

Cloud invocations may incur charges and trigger additional services. Budget
alerts alone are not a hard spending cap. A future runner should require
explicit activation, show the target scope, bound every retry/poll loop, and
report partial evidence and cleanup failures accurately. Do not put live AWS
credentials in example fixtures, public CI, or generated prompts.

This project intentionally leaves that boundary unexecuted. A green local run
is useful regression evidence for the covered components; it is not a live
end-to-end certification or a guarantee that nothing else broke.
