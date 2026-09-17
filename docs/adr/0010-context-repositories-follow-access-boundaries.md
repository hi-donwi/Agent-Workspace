# ADR-0010: Context repositories follow access boundaries

## Status
Accepted

## Date
2026-09-13

## Context

ADR-0009 introduced clients and groups inside `context/` so one organisation could route
project memory, runs, domain skills, and hours by client and product group. That solved
organisation and packaging, but it did not create access control. A git repository is read
as a whole by anyone who can clone it, regardless of folder names inside it.

That matters when one workspace operator has both personal/public repositories and client
work, or when a client has teams that are allowed to read only one project. Putting all
material under one `context/` tree with `clients/<client>/` folders leaks information to
anyone who needs access to only one part of that tree.

## Decision

A context repository is an **access boundary**, not merely an organisation folder. Everyone
who can read a context repository must be allowed to read every file in it, including git
history.

The framework still mounts one active context repository at `context/` per workspace clone.
When access differs, create a separate context repository and usually a separate workspace
clone for that audience:

```text
workspaces/personal/
├── context/   # private repo for personal projects
└── projects/personal/...

workspaces/client-a-api/
├── context/   # private repo for only the backend-api team
└── projects/example-org/client-a/backend-api/
```

`client`, `group`, and `context_scope` stay in the registry because they are useful for
routing, reporting, and context-pack assembly. They are not permission systems. Real read
access is controlled by which context repository is cloned and which remote grants access.

## Alternatives Considered

### One context repo with `clients/` folders

- Pros: simplest local layout; cross-project reports are easy.
- Cons: every reader of the repo can read every client and project folder, including
  history.
- Rejected: folder boundaries are not access boundaries.

### One context repo with encryption per client folder

- Pros: one remote could hold all material.
- Cons: complex key distribution, hard merges, accidental plaintext commits, and agents still
  need decrypted working trees to operate.
- Rejected: too fragile for routine delivery notes and handoffs.

### Multiple context repos mounted simultaneously

- Pros: one editor window could combine org, client, group, and project sources.
- Cons: larger CLI and conflict surface; easy to accidentally write to the wrong layer; requires
  new routing semantics for writes, hours, and runs.
- Deferred: may be added later as explicit `context_sources`, but not as the default.

### One workspace clone per active access boundary

- Pros: simple mental model; existing CLI keeps writing to `context/`; git remote enforces the
  audience; mistakes are visible in `workspace.conf`.
- Cons: shared projects that legitimately span boundaries need deliberate handoffs or copied
  sanitized facts.
- Accepted.

## Consequences

- A repository under `context/` may include multiple clients or groups only when the same
  audience may read all of them.
- A project-only team gets a project-only context repo, not a folder in a broader client repo.
- Cross-client or personal-vs-client reporting is done outside shared context repos or by a
  trusted operator with access to each source, not by granting everyone one combined repo.
- `context_scope` remains an audience selector for `ws context pack`; it does not relax or
  enforce repository access.
- Migration from a mixed context repo is split by copying allowed rows and directories into
  new private context repos, then pruning each repo's history or treating the old mixed repo as
  restricted to the broadest previous audience.

## Implementation Notes

- `workspace.conf` names one `context_dir` for the current clone. `context_remote` is
  optional for personal/private-local contexts and required in practice for team-shared
  contexts that other machines must clone.
- `personal_clients` lists client keys that are this operator's own/public work. When the
  registry also has paying-client rows, `ws doctor` treats the context as mixed: operator-local
  (no remote) is allowed; attaching a remote is refused. `ws context split --personal <key>`
  archives the mixed git history under `.local/archives/`, writes disjoint publishable copies
  under `.local/contexts/`, and restarts `context/` history so redacted secrets do not stay
  in the working repo.
- Use separate workspace clones when switching between contexts with different audiences.
- Keep `.local/` for machine-only or more-sensitive material that should not enter any shared
  context repo.
- Merged GitHub pull-request heads (`refs/pull/*/head`) can still be fetched from a public
  framework clone even after `main` is scrubbed. Those objects are documentation paths, not
  credentials. GitHub does not delete them. Do not rewrite published `main`. A new repository
  is the only way to drop pull refs.
