# Engineering Standards

The documents here are **binding**. Code that violates them does not pass review.
Deviating **is allowed**, but through an ADR in `docs/adr/` — not silently inside one
source file. If a standard is broken often because it is impractical, change the standard
through an ADR rather than letting code and documents diverge.

## Packs

Standards are grouped into packs. Which packs apply is declared in
[`workspace.conf`](../../workspace.conf):

```
packs = core, java
```

| Pack | Applies to | Contents |
|---|---|---|
| [`core/`](core/) | Every project, every language | Git workflow, REST API contract, definition of done |
| [`java/`](java/) | Projects on the Java pack | Java 21, Quarkus, PostgreSQL, Flyway, Maven, and the concrete testing, security, and observability rules for that stack |

`core` is always on. A stack pack carries the concrete rules for its language — which means
an organisation working in another stack **adds a pack** rather than editing `core`. Until
such a pack exists, that organisation has no binding rules for testing, security, or
observability, and should say so explicitly rather than assume the Java ones transfer.

## Core

| File | Contents | Read before |
|---|---|---|
| [`core/git-workflow.md`](core/git-workflow.md) | Branching, commits, review | Committing |
| [`core/api-contract.md`](core/api-contract.md) | REST shape, errors, paging, OpenAPI | Adding endpoints |
| [`core/definition-of-done.md`](core/definition-of-done.md) | Universal completion checklist (stack-neutral) | Closing a task |

## Java pack

| File | Contents | Read before |
|---|---|---|
| [`java/00-decisions.md`](java/00-decisions.md) | Locked decisions: versions, namespace, stack | Anything |
| [`java/project-layout.md`](java/project-layout.md) | Maven modules, packages, layering | Creating new files |
| [`java/java-code-style.md`](java/java-code-style.md) | Java 21 style, naming, exceptions, null | Writing Java |
| [`java/database.md`](java/database.md) | Schema, migrations, naming, audit, transactions | Touching the DB |
| [`java/security.md`](java/security.md) | Auth, hashing, validation, OWASP | Auth and input |
| [`java/testing.md`](java/testing.md) | Test pyramid, Testcontainers, gates | Writing tests |
| [`java/observability.md`](java/observability.md) | Logs, metrics, traces, health | Preparing a service |
| [`java/build-ci.md`](java/build-ci.md) | Maven, pipeline, quality gates | Changing the build |
| [`java/definition-of-done.md`](java/definition-of-done.md) | Java additions to the DoD: endpoint, DB, delivery-stage gates | Closing a task (with core) |

## Status

These are **recommended defaults**. Lines marked `[PENDING CLIENT]` await confirmation at
kick-off and may change through an ADR. Everything else applies now.

## Language

All standards, code, comments, and commit messages are written in **English**. An
organisation may keep specific domain vocabulary in another language where no precise
English equivalent exists; if so, it defines that glossary in its own context repository,
not here.
