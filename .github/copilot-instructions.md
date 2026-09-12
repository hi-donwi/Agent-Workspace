# Copilot Instructions

The full contract is in [`AGENTS.md`](../AGENTS.md) at the repository root. Read it before
substantial work.

## Summary

This is the **engineering workspace** — standards, agent context, skills, and memory.
Product code lives in `projects/<key>/`, which are **separate git repositories ignored by
this one**.

- Binding rules: `.agents/standards/core/` and the stack pack in `.agents/standards/java/`
- Task workflows: `.agents/skills/<name>/SKILL.md` — read the matching one before starting
- Project state: `context/memory/projects/<key>/active.md`

## Hard rules

- All documentation, code, comments, and commits are written in **English**. A domain
  glossary in another language lives in the context repo, never in the framework.
- Never place agent context, standards, or memory inside a product repo.
- Never place a client or organisation name in the framework repo — only in `workspace.conf`
  and `context/`.
- Never place credentials, tokens, keys, or client data in `.agents/`, `docs/`, or a commit
  message. Client material belongs in `.local/`, which is git-ignored.

## Backend code

Java 21, Quarkus 3.33.x LTS, PostgreSQL, Flyway forward-only, Maven via `./mvnw`.

Resource → Service → Repository, strictly. Never a query in a resource, never an entity as a
JSON response, never `@Transactional` on a resource. DTOs are `record`s. Money is
`BigDecimal`. Every endpoint declares a role. Every collection paginates. Errors use
RFC 9457 with stable codes.

Details: `.cursor/rules/10-java-quarkus.mdc` and `.agents/standards/java/`.
