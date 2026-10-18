# ADR-0025: Project kinds

- **Date:** 2026-10-18
- **Status:** Accepted
- **Deciders:** Workspace maintainer
- **Project:** workspace

## Context

The registry, the commands, and the definition of done assumed every project is a product
repository holding code. Work that is not code - research, learning, a long-running
mission, recurring operations - was registered anyway, as a folder that had to be a git
repository, judged by a code bar (tests, pipeline, conventional commits, endpoints) that
does not apply to it. The workspace also has no way to tell such a project from a code one,
so a session pack loads stack standards that have nothing to say about it.

## Decision

A project has a **kind**, the registry's tenth column (registry v4, appended last like
`context_repo` so every positional read stays valid):

| Kind | Delivers | Product repository |
|---|---|---|
| `code` | software in a product repository | required |
| `research` | findings with sources and a stated confidence | optional |
| `learning` | a skill, shown by use | optional |
| `mission` | a long-running outcome with milestones and a review rhythm | optional |
| `ops` | recurring or administrative work left in a known state | optional |

1. **An absent or `-` kind is `code`.** A v1 to v3 registry reads unchanged;
   `ws context migrate-v4` writes the column explicitly.
2. **A non-code project may have no folder** (`-`). Its records live where every project's
   already do: `context/memory/projects/<key>/` and `context/runs/<key>/`. Nothing is cloned,
   initialised, or linked for it, `ws doctor` does not look for a repository, and a `code`
   project without a folder is an error.
3. **The done bar follows the kind.** `.agents/standards/core/kinds/<kind>.md` replaces the
   code definition of done for that kind. Secrets and ADR rules still apply to every kind.
4. **Templates follow the kind.** `ws run` and `ws new` use `run-<file>.<kind>.md` and
   `memory-project.<kind>.md` when they exist, and the code templates otherwise.
5. **The session pack states the kind**, names its done bar, and for a non-code kind does
   not imply that stack packs apply.
6. **Any project may still have a repository.** A research project whose report is published
   registers a folder and remote as a code project does; the kind changes the bar, not the
   right to have one.
7. **Missions use what already exists.** A mission is a project whose milestones are tasks of
   kind `milestone` (ADR-0024) and whose reviews are recurring reminders. No new hierarchy.

## Alternatives considered

- **A separate registry for non-code work.** Two lists to keep, two sets of commands, and a
  project that starts as a note and becomes a repository would have to move between them.
- **Infer the kind from the folder** (no repo means not code). A code project not yet cloned
  looks the same, and the inference hides the choice.
- **Per-project free-form profiles.** Flexible but unreviewable; the finite list keeps the
  done bars and templates meaningful.

## Consequences

- Every registry reader gains a column. `reg_rows` always yields ten, so older files read
  without a rewrite.
- A research or mission project no longer carries an empty git repository only to satisfy
  the tooling.
- Adding a kind means adding a done bar, optional templates, and a name in two lists
  (`PROJECT_KINDS` in `ws`, `KINDS` in `ws_state.py`); a test keeps them in step.
- Context-only records live in the private context repository, which is an access boundary
  (ADR-0010). Material meant for an audience outside it belongs in a product repository.
