# Security policy

## Scope and supported version

Security fixes are considered for the latest release and the default branch.
This is an early-stage developer tool, not an isolation or attestation system.
Run only trusted application code and dependencies.

The subprocess runner sanitizes its environment and blocks common Python
network/process audit events. It does not prevent arbitrary file access or
contain malicious code, native extensions, or direct system calls. These known
limits are documented in [architecture](docs/architecture.md).

## Reporting

If GitHub's private vulnerability reporting option is available, use
**Security → Report a vulnerability** on the repository. Include a minimal
synthetic reproduction, affected revision, expected boundary, and observed
impact. Do not attach credentials, customer data, or exploit results from
systems you do not own.

If private reporting is unavailable, open an issue requesting a private contact
method without publishing exploit details or sensitive data. A maintainer can
arrange an appropriate channel. This project does not promise a response or
remediation deadline.

Potential issues include unexpected network activity in ordinary trusted-code
use, unsafe parsing, unintended credential propagation, or payload leakage in
reports. A false test result caused by deliberately modified reports is outside
the attestation guarantees: reports are unsigned user-editable JSON.
