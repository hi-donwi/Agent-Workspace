# ADR-0013: Operator-owned verification contracts

- **Date:** 2026-09-23
- **Status:** Accepted
- **Deciders:** Workspace maintainer
- **Project:** workspace

## Context

The workspace can route skills, create isolated runs, and invoke the deterministic
Agent-Secure gate, but a project-specific definition of verification is not yet executable.
Product repositories are independent and may contain private code. A repository must not be
able to weaken its own quality gate, and test output may contain secrets or client data.

## Decision

`ws verify <project-key>` reads a versioned JSON execution contract from an operator-owned
location outside the product repository. The default location is `.local/agent/contracts/`;
an explicit contract path is allowed only when it is also outside the product checkout.
Contracts contain command IDs, shell commands, required status, and bounded timeouts.

The verifier executes commands in the registered product repository and emits a sanitized
report containing project identity, contract name, command IDs, status, and duration. It
discards command stdout and stderr. A report is `pass` only when all required commands pass;
failed required commands produce `findings`, while malformed contracts produce `incomplete`.
With `--run`, the report is written to the private context run as `evidence.json`.

## Consequences

- Project verification becomes repeatable without placing private project configuration in
  the public framework.
- The public repository can test the mechanism with synthetic contracts only.
- Operators must protect `.local/agent/contracts/` and review shell commands as executable
  policy; this feature is not a sandbox.
- Full logs remain available only through the underlying tool's own private systems, if any;
  the workspace evidence intentionally does not preserve arbitrary output.

## Alternatives considered

| Option | Why rejected |
|---|---|
| Store contracts in product repositories | A checkout could weaken its own gate and private policy would leak into client code. |
| Capture full command output in context | Logs can contain credentials, client data, and unbounded output. |
| Hardcode one verification command in the framework | Projects use different stacks and test workflows. |
| Treat a failed or unavailable command as pass | It would turn missing evidence into a false green result. |
