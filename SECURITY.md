# Security Policy

## Reporting a vulnerability

**Do not open a public issue.** Email **connect@agience.ai** with:

- what the issue is and which module carries it,
- how to reproduce it — a failing snippet is worth more than a description,
- the version of `agience-prism` you ran, and your Python version.

Expect an acknowledgement within three working days. Once a fix is released, the report is credited
in the release notes unless you ask otherwise.

## Supported versions

Fixes land on the latest released version. There are no maintained release branches.

## What is in scope

This package is the SDK, not the platform. In scope:

- `prism.canonical` — the JCS canonicaliser every content address and signature is taken over. A
  divergence from RFC 8785 is a security issue here, because it re-addresses stored content.
- `prism.trust` — key handling, JWT signing and verification, scope checks.
- `prism.host` and `prism.server` — token verification, the delegation token capture and forward.
- `prism.runner` — bundle sha verification and the signature/provenance gate. A path that reaches
  `exec` without `_verify_sha` is a security issue.
- `prism.plane` — AES-256-GCM sealing.

Out of scope: the Agience platform services, which are reached over the wire and have their own
reporting path; and anything requiring an attacker to already control the process importing prism.
