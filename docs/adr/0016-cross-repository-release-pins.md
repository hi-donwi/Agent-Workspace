# ADR-0016: Cross-repository release pins

- **Date:** 2026-09-23
- **Status:** Accepted
- **Deciders:** Workspace maintainer
- **Project:** workspace

## Context

The workspace consumes independently released tools, skills, runtimes, and security gates.
Floating branches and unrecorded compatibility assumptions make an agent workflow difficult to
reproduce and can silently change a quality gate. Public CI must not fetch private product
repositories or publish their metadata.

## Decision

Repositories may publish a generic compatibility manifest using `ws compat validate`. Every
component must declare a repository source, semantic version, 40-character commit pin, and
interface identifier. Required CI checks are named explicitly. `ws compat compare` compares
separately recorded component observations to the pinned manifest without network access.

Release changes should update one pin at a time, run the repository's tests and security gate,
run compatibility fixtures, and be reviewed as a pull request. A component's source tree is
never copied into this repository and product repositories remain independent.

## Consequences

- Release inputs become reviewable and reproducible.
- Compatibility failures are findings rather than silently accepted drift.
- The manifest does not prove that a remote commit is trustworthy; CI still needs pinned,
  verified actions and security checks.
- Private project manifests and observations remain in private context when they contain client
  or operational details; public templates use synthetic placeholders only.
