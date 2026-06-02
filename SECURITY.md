# Security Policy

## Reporting A Vulnerability

Do not post secrets, private source code, exploit details, or sensitive logs in public issues.

Use GitHub private vulnerability reporting when it is available for this repository. If it is not available, contact a maintainer privately through GitHub and share only the minimum detail needed to establish the issue.

## Scope

Security-relevant reports include:

- run records storing secrets or full source unexpectedly;
- command output redaction failures;
- path traversal or unsafe file handling;
- gate execution behavior that violates the documented local contract.

## Out Of Scope

- Requests for hosted scanning or model-provider integrations.
- Reports that require publishing private repository content in public.
- Vulnerabilities in third-party tools invoked by a user-defined adapter gate.

## Maintainer Response

Maintainers should acknowledge valid private reports, reproduce the issue locally, prepare a fix, and publish a security note when disclosure is appropriate.
