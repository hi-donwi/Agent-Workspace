# Project kinds

A project is anything with an owner, a goal, and records that outlive one session. Only some
projects are software. The registry's `kind` column says which, and the done bar, the run
templates, and the need for a product repository follow from it
([ADR-0025](adr/0025-project-kinds.md)).

| Kind | Use it for | Product repository | Done bar |
|---|---|---|---|
| `code` | software | required | `AGENTS.md` section 10 and the enabled stack packs |
| `research` | a question to answer | optional | `.agents/standards/core/kinds/research.md` |
| `learning` | a skill to acquire | optional | `.agents/standards/core/kinds/learning.md` |
| `mission` | a long-running outcome | optional | `.agents/standards/core/kinds/mission.md` |
| `ops` | recurring or administrative work | optional | `.agents/standards/core/kinds/ops.md` |

A registry row with no kind is `code`.

## Registering a project

```bash
# code: unchanged, folder required
ws new <key> projects/<group>/<repo> [remote] --client <c>

# anything else: no folder, no repository
ws new <key> --client <c> --kind research
ws new <key> --client <c> --kind mission

# a non-code project that does publish something may still have a repository
ws new <key> projects/<group>/<repo> [remote] --client <c> --kind research
```

A registry written before kinds needs one step: `ws context migrate-v4` (after
`migrate-v3` if it is older). Change a project's kind later with `ws kind set <key> <kind>`;
`ws kind list` shows them all, and `ws list` and `ws tree` mark non-code kinds.

## Where the work lives

A project without a repository keeps everything in the private context repository, where
every project's records already are:

| What | Where |
|---|---|
| Purpose, stage, focus, decisions | `context/memory/projects/<key>/` |
| Runs (brief, plan, progress, evidence, handoff) | `context/runs/<key>/` |
| Tasks, milestones, reminders | `ws task`, `ws remind` |
| Notes | `ws note <key> "title"` |
| Raw sources, dumps, documents | `.local/` - never committed |

`context/` is an access boundary (ADR-0010): everyone who can clone it reads all of it.
Material meant for a wider audience belongs in a product repository.

## What each kind adds

- **research** - runs start from a question and a method, and `evidence.md` is a table of
  claims, sources, and confidence. Findings that matter name their source.
- **learning** - runs start from a goal, a starting level, and the evidence of learning.
  Review dates are reminders, not intentions.
- **mission** - milestones are tasks of kind `milestone` (`ws task add <key> "..." --kind
  milestone`); a review rhythm is a recurring reminder. Each run names the milestone it
  serves. Related projects are listed in `project.md`.
- **ops** - runs record what was done and the resulting state; steps that repeat become a
  standing checklist in `project.md`, and renewals become reminders.

## How tools treat a project without a folder

`ws bootstrap`, `ws link`, and `ws sync` skip it (nothing to clone or point at), `ws doctor`
reports it as context-only instead of looking for a repository, and `ws session bind` writes
a pack that states the kind and its done bar and does not point at the code standards. A
`code` project without a folder is a doctor failure.

## Adding a kind

Add the name to `PROJECT_KINDS` in `.agents/bin/ws` and `KINDS` in `.agents/bin/ws_state.py`,
write `.agents/standards/core/kinds/<kind>.md`, add any `run-<file>.<kind>.md` and
`memory-project.<kind>.md` templates, and extend the test that keeps the lists in step.
