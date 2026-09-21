# ADR-0009: Group projects by client inside the context repository

- **Date:** 2026-09-13
- **Status:** Accepted
- **Project:** workspace

## Context

ADR-0006 gave each organisation a context repository, keyed flat by project:
`memory/projects/<key>/`, `runs/<key>/`, `registry.tsv` mapping a key to a folder and
remote. That is correct for *project* state. It has no answer for *client* state — and
the moment one client has more than one project, three things break.

The concrete trigger: Client Alpha's proposal, kick-off notes, production-namespace ADR, and
domain glossary were all sitting directly under `context/docs/` and `context/skills/` —
correct-looking with one client and one project, indistinguishable from workspace-wide
material the instant a second client arrives, and with no place for a second Client Alpha
project (a frontend companion, say) to share that same namespace and glossary without
duplicating them into its own project folder.

Three concrete failures follow: cross-project client knowledge (namespace, infra choices,
a role matrix) has no home and gets copied per project, where copies diverge on the first
edit; billing a client requires manually summing every one of their projects' hours,
external to the tool that already merges overlapping sessions correctly; and there is no
seam to cut along if a client's material must one day move to its own repository or
region.

## Decision

`registry.tsv` gains a **client** column: `key<TAB>client<TAB>folder<TAB>remote<TAB>
description`. A new `clients/<client-key>/` directory holds what is true regardless of
which of that client's projects it is:

```
context/clients/<client>/
├── client.md          who they are, contract, stakeholders
├── decisions.md        decisions that hold across every one of their projects
├── skills/<domain>/    their domain glossary and business rules
└── docs/                their proposals, kick-off notes, client-specific ADRs
```

`ws client new <key>` scaffolds it from templates the same way `ws new` scaffolds a
project. `ws new <project-key> <folder> --client <key>` links a project to it, and fails
if the client does not exist yet — a typo'd client name should not silently create an
orphan. **`--client` is required**, not optional (see Addendum below): `ws new` refuses to
register a project without one, and `ws doctor` fails on any existing project that has
none.

**Project keys stay flat.** `memory/projects/<key>/`, `runs/<key>/<run>/`, and
`works/{human,agent}/<key>/` are **not** nested under a client
(`memory/clients/<c>/projects/<key>/`). A key is unique workspace-wide either way; flat
means a project changing client is one row in a registry, not a move across four directory
trees, and it means `runs/` and `works/`, which already assumed a flat key before this
ADR, need no change at all.

`ws route` and `ws skills` search `clients/*/skills/` alongside the framework's and the
organisation's own skills. `ws hours --client <key>` and the monthly rollup's `by_client`
resolve a client's project keys through the registry and merge their sessions together —
using the same overlap-merging `hours_net` already applied per project, so a client total
is not a naive sum of per-project totals (which would double-count time spent split across
two of their projects in parallel).

**A decision belongs in `clients/<c>/decisions.md` only once a second project confirms it
is genuinely client-wide.** One project cannot distinguish a client-wide fact from a
project-specific one that happens to be true today.

## Consequences

### Positive
- A client's cross-project material (namespace, glossary, stakeholders) has exactly one
  home, found the same way whether it is read from any of their projects.
- Billing and reporting by client is a first-class query, correctly overlap-merged, not a
  spreadsheet exercise external to the tool that already does the merging correctly for
  projects.
- A client's material now sits in one subtree (`clients/<key>/` plus whatever project rows
  name that client), which is what makes a future split — a dedicated repository, a
  different jurisdiction — mechanical rather than an archaeology exercise.
- `ws doctor` can and does check the new invariant: every project names a client that
  exists.

### Negative
- One more concept to learn (`ws client new`), and one more thing that can be forgotten —
  registering a project with no `--client` is legal (a lone freelance engagement need not
  invent a client), but `ws doctor` and `ws hours --client` then cannot find it.
- The registry's schema changed shape (4 columns to 5). Every `reg_rows` consumer in `ws`
  needed updating in lockstep; a partial update silently reads the wrong column instead of
  failing loudly, which is exactly what happened once during this change (`agent_auto`'s
  hook-driven project resolution) and was only caught by the test suite.

### Neutral
- A client with exactly one project looks almost identical to the pre-ADR-0006 layout,
  just with `clients/<key>/` holding one project's worth of client-shaped material. The
  benefit is entirely in what happens when the second project or client arrives.

## Three pre-existing bugs found while making this change

**`ws route` was silently broken for almost every query.** Wiring it to also search
`clients/*/skills/` surfaced a bug unrelated to this ADR: any skill lacking a `keywords:`
frontmatter line made its scoring pipeline die outright. `grep -v '^$'` exits 1 on empty
input; under `pipefail` that becomes the exit status of the `kw="$(...)"` assignment; under
`errexit` that silently kills the whole script the moment the loop reaches such a skill.
Since the alphabetically-first framework skill (`api-design`) has no `keywords:` line,
`ws route` had been broken for effectively every query since these skills were added —
invisible on a developer's own machine only because nobody had run it attentively enough to
notice the empty output. Fixed alongside this ADR's work, with a regression test that adds
a keywords-less skill and asserts `ws route` still returns.

**Every union-merge rule this workspace claimed was dead.** ADR-0005 and ADR-0006 put
`merge=union` for `log.md`, `registry.tsv`, and the hours files in the *workspace root's*
`.gitattributes`. But `context/` is an independent git repository, ignored by the
workspace's own git — a merge attribute only ever governs merges run inside the repository
that tracks it, and git never merges across a repository boundary. Confirmed by test: an
outer repository's `merge=union` rule for a path inside a nested, independently
`git init`'d directory has zero effect on merges run inside that inner repository. So two
people appending to the same project's `log.md` on the same day would have conflicted like
any other line edit, not merged automatically as documented. Fixed by moving the rules into
`context/.gitattributes`, tracked by the context repository itself, and shipping that file
from `ws context init` via `.agents/templates/context-gitattributes` so every future
organisation gets it from the start rather than rediscovering the same bug.

**`ws hours --client` died the moment a client's projects had uneven activity.** Found by
simulating the real case this ADR exists for — a second client with two projects, a second
project added to the first client — rather than reasoning about it in the abstract: the
ordinary situation where one of a client's projects was worked on this month and a sibling
was not crashed the report outright. Same family as the `ws route` bug: `cat file1 file2`
exits nonzero the instant *any* argument is missing, even though it still prints what does
exist; under `pipefail` + `errexit` that killed `hours_net`'s pipeline from inside the
`a="$(...)"` / `h="$(...)"` assignment that calls it. Fixed by filtering to files that
actually exist before handing them to `cat`.

## Alternatives considered

| Option | Why rejected |
|---|---|
| **Nest project keys under their client** (`memory/clients/<c>/projects/<key>/`) | A project changing client becomes a move across four directory trees instead of one registry row; `runs/` and `works/` would need the same nesting for consistency, touching more of the CLI than the benefit justifies. |
| **A `client` field only in `memory/projects/<key>/project.md`, no `clients/` directory** | Answers "which client owns this project" but not "where do I put the thing true of all their projects" - it would still end up duplicated per project or dumped in `docs/` with no boundary. |
| **One context repository per client** | Right answer eventually for access control or jurisdiction, wrong default: most agencies want one team seeing every client, and splitting early adds N repositories to clone, sync, and keep a remote for. `clients/<key>/` makes a later split mechanical rather than foreclosing it. |
| **Compute client totals by summing per-project rollup figures** | Double-counts time when two of a client's projects have overlapping sessions (two agents, one per project, running at once). Routing the client's full session list through the same merge function `hours_net` uses per project avoids that. |

## Follow-up

- [x] `registry.tsv` gains `client`; every `reg_rows` consumer updated
- [x] `ws client new|list`; `ws new --client`; client validated to exist
- [x] `ws route`/`ws skills` search `clients/*/skills/`
- [x] `ws hours --client`; rollup `by_client`
- [x] `ws doctor` fails when a project names a client with no directory
- [x] `context/.gitattributes`, shipped by `ws context init` via a new template
- [x] `ws route` fixed and regression-tested against a skill with no `keywords:` line
- [x] Decided (2026-09-13, see Addendum): a client is required, not optional

## Addendum (2026-09-13): `--client` made required

The open follow-up above was resolved before the model saw any real use beyond one
client: leaving it optional means a forgotten `--client` produces a project invisible to
`ws hours --client` and to that client's domain skills, discovered only when a report
comes up short — the worst time to find a data-entry gap. `ws new` now refuses to
register a project without `--client`, and `ws doctor` fails (not warns) on any existing
project with none. A workspace with genuinely client-less work — internal tooling,
overhead — creates a client for it (`ws client new internal`) rather than the tooling
special-casing an empty column.

This was tightened after simulating the real multi-client, multi-project case directly
(two clients, several projects each) rather than reasoning about it in the abstract; the
same simulation is what surfaced the third bug above (`ws hours --client` dying on a
client whose projects have uneven activity).
