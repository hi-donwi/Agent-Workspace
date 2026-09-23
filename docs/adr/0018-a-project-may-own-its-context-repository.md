# ADR-0018: A project may own its context repository

## Status
Accepted

## Date
2026-09-24

## Context

ADR-0010 made a context repository an access boundary: everyone who can clone it may read
every file in it, including history. Where audiences differ, it prescribed a separate
context repository and usually a separate workspace clone.

That is correct and too coarse in one common case. An operator serving several clients
wants one private context for themselves — the registry, client material, and the hours
behind invoices — while **one** project's memory, runs and decisions must also be readable
by that project's delivery team, who may not read anything else. Under ADR-0010 alone the
answer is a whole second workspace clone per such project.

It was already being solved without the framework. One project here keeps its context in
its own repository on the client's GitLab, with the root context reduced to routing stubs
pointing at it. Those stubs are well written and the arrangement works for a human. It does
not work for `ws`:

- `ws context pack` reads only the root context, so a bind returned seven stubs and no
  facts, under a header reading "Load only these files". An agent that obeys its allowlist
  reads pointers it is forbidden to follow.
- Nothing recorded the arrangement, so no tool could know it existed.
- The product repo grew a second, hand-written linking script duplicating `ws link`,
  because `ws link` pointed at the stubs.

## Decision

A project may own its context repository, declared in the registry.

`registry.tsv` gains a ninth column, `context_repo`: a workspace-relative folder, or `-`
(the default) meaning the project's context lives in the root context repo as usual. It is
appended **after** `description` so every existing positional read keeps its column, and
`reg_rows` normalises any older file to nine columns, so reading works before migrating.
`ws context migrate-v3` makes the column visible for editing.

When the column is set, `ws context pack` packs both trees: the root's material *and*
`<context_repo>/{project,active,decisions,log}.md` plus `client/{client,decisions}.md`,
resolving the external paths against the workspace root. A run resolves in either tree —
`runs/<project>/<run>` in the root context, `runs/<run>/` in a project's own repo, where
the repo is the project.

Both are packed rather than one replacing the other. Deciding which file is a stub and
which is authoritative would mean guessing; a stub is a few lines, it explains the
arrangement, and the reader gets the explanation together with the facts.

**Hours never move.** `works/` stays in the root context whatever this column says. It is
the invoice basis, and a project context repo may be readable by the client.

## Consequences

- One project can be shared with its delivery team without a second workspace clone.
- The access boundary and the attention pack now coincide: what a session is allowed to
  load is what its audience is allowed to read.
- A third nesting level exists where a project context repo is mounted inside the tree.
  `git clean -ffxd` destroys it exactly as it destroys a product repo; the same warning
  applies.
- `context_repo` is a routing fact, not a permission. Real access is still who can clone
  which remote — ADR-0010 is unchanged on that point.
- A project context repo hosted by the client has the client's team as readers. That is
  the point when it is intended, and a disclosure when it is not. Choosing the host is a
  separate decision from setting this column.

## Alternatives Considered

### Convention over configuration — look for `<folder>-context/`

- Pros: no registry change; matches what the hand-written script already assumed.
- Cons: silently does nothing when the directory is named differently, and silently picks
  up an unrelated directory that happens to match.
- Rejected: a routing fact that fails silently is worse than one that must be declared.

### Let the pack follow pointers found inside stub files

- Pros: no registry change; the stubs already say where to look.
- Cons: requires parsing prose to decide what is a pointer, and makes the allowlist depend
  on file contents.
- Rejected: too implicit to reason about, and unverifiable.

### A second workspace clone per shared project, as ADR-0010 prescribes

- Pros: no framework change; the strongest isolation.
- Cons: a full clone, bootstrap and set of product checkouts per project; hours and
  registry then fragment across clones, which is what the root context exists to prevent.
- Rejected for this case: the cost is paid per project, while the audience differs for
  only some of them. Still the right answer when *everything* about a client must be
  separate.
