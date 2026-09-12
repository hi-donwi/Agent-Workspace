# Agent Skills

Each skill is a folder holding a `SKILL.md` (what it does + when to use it) and an optional
`references/` folder for depth.

**Before starting a task, check whether a skill applies. If one does, read its `SKILL.md`
first and follow it.** Open `references/` only when `SKILL.md` is not enough.

```bash
ws route "add order transaction summary endpoint"   # find the relevant skill
ws skills                                                 # regenerate index.json
```

## Skills vs standards

| | Contents | Question answered |
|---|---|---|
| `.agents/standards/` | Binding rules | "What is correct?" |
| `.agents/skills/` | Workflows | "How do I do this?" |

A skill **points at** a standard rather than copying it. If the two conflict, the standard
wins — and that is a bug in the skill to be fixed.

## Catalogue

| Skill | Use when |
|---|---|
| [`quarkus-service`](quarkus-service/SKILL.md) | Adding a Quarkus endpoint/service, setting up a module, config, DI |
| [`java-code-standards`](java-code-standards/SKILL.md) | Writing or reviewing Java 21: naming, records, exceptions, null |
| [`rest-api-contract`](rest-api-contract/SKILL.md) | Designing endpoint shape, errors, pagination, OpenAPI, versioning |
| [`quarkus-persistence`](quarkus-persistence/SKILL.md) | Entities, repositories, Flyway migrations, queries, transactions, N+1 |
| [`quarkus-security`](quarkus-security/SKILL.md) | Auth, sessions, RBAC, input validation, uploads, security review |
| [`quarkus-testing`](quarkus-testing/SKILL.md) | Unit tests, integration tests, Testcontainers, coverage gates |
| [`quarkus-observability`](quarkus-observability/SKILL.md) | Structured logs, correlation IDs, metrics, traces, health checks |
| [`bulk-reporting-export`](bulk-reporting-export/SKILL.md) | Large reports, XLSX/PDF/ZIP export, async jobs, SSE, streaming |
| [`java-delivery`](java-delivery/SKILL.md) | Maven build, CI, releases, systemd/container deploy, rollback |

## Writing a new skill

1. `mkdir -p .agents/skills/<name>/references`
2. Start `SKILL.md` with YAML frontmatter:

```yaml
---
name: <kebab-case-name>
description: >-
  What this skill does. Use when: <concrete triggers>.
  Do not use for: <what should route to another skill>.
keywords: term, term, term
---
```

3. Cover: when to use, when to hand off, the workflow, patterns, pitfalls.
4. Run `ws skills` to refresh `index.json`.

The frontmatter `description` is what an agent reads to decide relevance. Make the triggers
concrete — "new endpoint", "slow export" — not abstract like "code quality".

### The `keywords` field

`ws route` scores a task description as **5 x keyword hits + 1 x description word hits**.
Curated keywords carry the weight; prose matching only breaks ties. With ten skills whose
descriptions share a lot of vocabulary, matching on prose alone returns five-way ties —
the keyword list is what makes routing decisive.

Write keywords as the words someone would actually type, including:

- the obvious nouns (`export`, `migration`, `session`)
- the technology names (`flyway`, `testcontainer`, `sxssf`)
- **both spellings** where they differ (`authorisation, authorization`)
- Indonesian domain terms where a developer would use them (`auction`, `budget`)

Keep them comma-separated on one line. Re-run `ws skills` after editing.

## Language

All skills are written in English, matching the workspace language policy in `AGENTS.md`.
