# Related tools and design rationale

Reviewed 2026-11-05. This is a focused comparison of primary documentation, not an exhaustive market survey or a benchmark.

## What already exists

| Project | Existing contribution | Relationship to this repository |
| --- | --- | --- |
| [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-using-automated-tests.html) | A local Lambda invoke endpoint supports automated tests; the SDK-based test approach can also target a deployed function. | Use SAM when the Lambda runtime and packaging boundary matter. This repository focuses on reviewing scenario data and checking handler behavior with a real local dependency. |
| [AWS serverless-test-samples](https://github.com/aws-samples/serverless-test-samples) | Language-specific examples of unit, integration, and end-to-end serverless testing. | The appropriate next reference for an application-specific cloud test suite. This repository offers a small reusable authoring/replay workflow rather than a catalogue of deployed architectures. |
| [Moto](https://docs.getmoto.org/en/latest/docs/getting_started.html) | Python decorators and context managers mock AWS operations for tests. | Useful for AWS SDK call behavior. Mocked AWS responses are a different kind of evidence from a local database write or a deployed AWS interaction. |
| [LocalStack](https://docs.localstack.cloud/aws/services/lambda/) | Emulates AWS services locally and executes Lambda functions in containers; its Lambda documentation describes runtime reuse and Docker requirements. | Use it when local AWS API and cross-service emulation is needed. It has substantially broader service coverage. This repository does not emulate AWS APIs. |
| [Powertools for AWS Lambda, Python](https://docs.aws.amazon.com/powertools/python/latest/utilities/batch/) | Provides application utilities, including batch processing and examples for testing partial failures. | Application code can adopt these utilities independently. This repository supplies test scenarios and evidence reporting, not replacement application middleware. |

These tools can complement one another. The comparison does not imply that any project lacks AI integrations or cannot be used by an AI coding assistant. In particular, LocalStack publishes [AI and agent workflow guidance](https://docs.localstack.cloud/aws/getting-started/ai-workflows/).

## The chosen contribution

The useful scope here is a small, inspectable bridge from AI-assisted scenario authoring to repeatable local evidence:

1. Give an assistant an explicit application contract and synthetic examples, with no automatic source-code or credential upload.
2. Review declarative scenario data before execution. Test expectations need an independent business rule; model output is not an oracle.
3. Run a handler against a real local dependency and assert both responses and observed side effects.
4. Report the boundary actually exercised and the AWS behaviors still unverified.

An offline prompt bundle is an aid for an assistant or a person; producing it does not call an AI model. This combination is the design goal, not a claim that declarative testing, AI test generation, or Lambda integration testing is new.

## Evidence and semantic pitfalls

AWS distinguishes isolated code tests from interacting-component tests, and recommends cloud tests for deployed service interactions and configuration. A passing local run cannot establish IAM permissions, event delivery, quotas, runtime configuration, or AWS service behavior. [AWS Lambda testing guide](https://docs.aws.amazon.com/lambda/latest/dg/testing-guide.html).

A handler plus SQLite exercises actual Python-to-SQLite calls and persistence. SQLite is not a DynamoDB emulator. Passing an SQS-shaped JSON event directly to Python simulates the input boundary; it does not demonstrate that SQS invoked Lambda, that a message was acknowledged, or that visibility timeouts and redrive work. Those need separate tests against the actual boundary.

For SQS partial batches, checking the returned failed identifiers is only a handler-contract check. AWS also requires the event source mapping's `ReportBatchItemFailures` configuration to use partial responses; FIFO processing has ordering constraints. Do not infer that a correct response body proves retries or ordering in AWS. [AWS SQS error handling](https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-errorhandling.html).

Repeated calls in one Python process can reveal application state and duplicate-handling defects, but do not reproduce Lambda scheduling, cold starts, concurrency, or at-least-once delivery. A local temporary database also cannot prove distributed idempotency under concurrent writers.

## Attribution and licensing

This comparison credits the documentation used to choose the scope. No implementation code or fixtures from these projects were copied into this repository. Links do not imply affiliation or endorsement.

At the time of review, the upstream license files identify [SAM CLI](https://github.com/aws/aws-sam-cli/blob/develop/LICENSE) and [Moto](https://github.com/getmoto/moto/blob/master/LICENSE) as Apache-2.0, and [serverless-test-samples](https://github.com/aws-samples/serverless-test-samples/blob/main/LICENSE) and [Powertools Python](https://github.com/aws-powertools/powertools-lambda-python/blob/develop/LICENSE) as MIT No Attribution (MIT-0). Consult the [LocalStack repository](https://github.com/localstack/localstack) and the terms for the particular distribution and features you choose; this document makes no blanket licensing or pricing claim for LocalStack.

The repository's own license governs its original files. If future contributions incorporate third-party code, record the exact source and applicable license and preserve required notices.
