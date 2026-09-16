# Architecture Decision Records

One file per decision, numbered sequentially, never deleted. A superseded ADR stays and
points at its replacement — the reasoning is what makes the history useful.

Template: [`../../.agents/templates/adr.md`](../../.agents/templates/adr.md)

## When to write one

- Choosing between technologies or approaches with lasting consequences
- Deviating from `.agents/standards/`
- Anything that will make someone ask "why is it like this?" in six months
- Every answer that comes back from the client kick-off

An ADR with no rejected alternatives records a preference, not a decision.

## Index

| # | Title | Status | Date |
|---|---|---|---|
| [0001](0001-nested-independent-project-repos.md) | Nested independent project repos, not submodules | Accepted | 2026-09-12 |
| 0002–0003 | Moved to the organisation's context repository (stack pin and namespace are not framework decisions) | — | 2026-09-12 |
| [0004](0004-english-as-workspace-language.md) | English as the workspace language | Accepted | 2026-09-12 |
| [0005](0005-workspace-portability-and-guard-rails.md) | Workspace portability and isolation guard rails | Accepted | 2026-09-12 |
| [0006](0006-framework-context-product-split.md) | Framework, context, and product as three repositories | Accepted | 2026-09-12 |
| [0007](0007-skills-in-their-own-repository.md) | Skills in their own repository, fetched by manifest | Accepted | 2026-09-12 |
| [0008](0008-two-clocks-human-and-agent-hours.md) | Two clocks — human hours and agent hours are never summed | Accepted | 2026-09-12 |
| [0009](0009-client-grouping-in-context.md) | Group projects by client inside the context repository | Accepted | 2026-09-13 |
| [0010](0010-context-repositories-follow-access-boundaries.md) | Context repositories follow access boundaries | Accepted | 2026-09-13 |
