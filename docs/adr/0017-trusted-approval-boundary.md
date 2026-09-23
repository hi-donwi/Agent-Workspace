# ADR-0017: Trusted approval boundary

- **Date:** 2026-09-23
- **Status:** Accepted
- **Deciders:** Workspace maintainer
- **Project:** workspace

## Context

The public framework can classify an action as `approval-required`, but a classification is not
evidence that a human approved it. A product checkout, a pull request body, an arbitrary
environment variable, or a model response can be modified by an untrusted actor. Treating any
of those as approval would turn a policy label into a bypass.

## Decision

The framework's public CI validates code, templates, and deterministic helpers only. It does
not approve deployments, merges, production access, IAM changes, or other irreversible actions.
The `ws policy check` result is a necessary classification, not sufficient authorization.

Until a trusted provider is selected, approval-required actions remain blocked outside the
framework. A future approval integration must provide all of the following before it can be
implemented:

- an authenticated human or group identity;
- an immutable request ID bound to the exact project, revision, action, and policy hash;
- an auditable timestamp and expiration/revocation rule;
- a verification mechanism independent of the product checkout;
- least-privilege delivery to the executor, with no reusable secret in prompts or logs.

For GitHub-hosted public development, branch protection and required status checks are the
baseline merge boundary. Deployment approvals belong in protected GitHub environments or a
separately governed control plane, not in this public repository's files.

## Consequences

- CI can be made a required check without gaining deployment or merge authority.
- The current implementation cannot falsely claim that an agent action was human-approved.
- An administrator must enable branch protection and required checks; workflow YAML alone does
  not change repository settings.
- Choosing an approval provider is intentionally deferred until its identity, audit, and trust
  properties are known.
