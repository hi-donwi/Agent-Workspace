# ADR-0014: Risk-based agent autonomy

- **Date:** 2026-09-23
- **Status:** Accepted
- **Deciders:** Workspace maintainer
- **Project:** workspace

## Context

Agentic workflows need more than a quality gate. They also need an explicit boundary between
actions an agent may perform and actions that require a human decision. The framework is public,
while its project policies and product repositories may be private.

## Decision

`ws policy check <project-key> --action <action>` reads an operator-owned JSON policy outside
the product repository. Policies use schema version 1, a default level, and action overrides.
Levels are `read`, `change`, and `approval-required`.

`read` and `change` return `allow`. `approval-required` returns that decision with a non-zero
exit status. The command is a classifier, not a proof of human approval; an orchestrator must
obtain and record approval through a separate trusted control plane before executing such an
action. Invalid or missing policy is `incomplete`, never an allow decision.

The default policy location is `.local/agent/policies/<project-key>.json`. The policy cannot
reside inside the product checkout. Public fixtures and templates contain no real project,
client, credential, or deployment information.

## Consequences

- Agent permissions become explicit and testable per project.
- A permissive product checkout cannot authorize its own merge or deployment.
- Human approval storage and enforcement remain a future control-plane concern; this command
  intentionally does not pretend an environment flag is trustworthy approval.
- Operators must protect policy files because shell action labels are only as strong as the
  orchestrator that consumes the decision.
