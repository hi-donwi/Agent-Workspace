# Copilot Instructions

The full contract is in [`AGENTS.md`](../AGENTS.md) at the repository root. Read it before
substantial work. The hard rules below are the part that is never optional.

## Summary

This is the **engineering workspace** — standards, agent context, skills, and memory.
Product code lives in `projects/<key>/`, which are **separate git repositories ignored by
this one**.

- Binding rules: `.agents/standards/core/` and the stack pack in `.agents/standards/java/`
- Task workflows: `.agents/skills/<name>/SKILL.md` — read the matching one before starting
- Project state: `context/memory/projects/<key>/active.md`

<!-- hard-rules:begin -->
## Hard rules - read these even if you read nothing else

1. **This framework repository is public.** Never put a client, group, project key,
   organisation name, client document, credential, or absolute path from your machine
   into a tracked file here or into a commit message. Product documents go in the
   product repo; plans, notes, and evidence go in `context/`.
2. **Commit only where and when the user asked; never push unless asked.** Never bypass
   hooks with `--no-verify`: the framework's guard hooks refuse any commit or push that
   names a client.
3. **Three repositories, three owners.** The framework (this folder), `context/`, and
   each repo under `projects/` are separate git repositories. Nothing from `context/` or
   `projects/` enters the framework; nothing from the framework or `context/` enters a
   product repo.
4. **Bind before you read project material:** `ws session bind <project-key>`, then load
   only the files that `.local/sessions/<session>/CONTEXT.md` lists.
5. **Runs come only from `ws run <project-key> "title"`** (`workspace` for work on this
   framework). Never hand-make a run folder, and never key one by client or group.
6. **Say who you are.** Every shell that runs `ws` exports `WS_AGENT=<your tool>` and
   `WS_SESSION_ID=<unique id>`; otherwise your work is logged as `dev` on a shared
   `default` session.
7. **English** in every file and every commit message.

The full contract is `AGENTS.md`. Where it and this list differ, this list wins.
<!-- hard-rules:end -->

## Backend code

Java 21, Quarkus 3.33.x LTS, PostgreSQL, Flyway forward-only, Maven via `./mvnw`.

Resource → Service → Repository, strictly. Never a query in a resource, never an entity as a
JSON response, never `@Transactional` on a resource. DTOs are `record`s. Money is
`BigDecimal`. Every endpoint declares a role. Every collection paginates. Errors use
RFC 9457 with stable codes.

Details: `.cursor/rules/10-java-quarkus.mdc` and `.agents/standards/java/`.
