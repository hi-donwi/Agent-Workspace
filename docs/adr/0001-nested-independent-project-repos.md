# ADR-0001: Nested independent project repos, not submodules

- **Date:** 2026-09-12
- **Status:** Accepted
- **Project:** workspace

## Context

An engineering organisation needs one place for engineering standards, AI agent context, skills, and team memory,
shared through git. Product code, however, lives in repositories that are frequently hosted
and owned by the client, and more projects follow the first one.

Two things must hold at once:

1. Agent context and standards must **not** live inside a product repo — they are
   organisation-internal, they apply across projects, and they would diverge if copied per repo.
2. A developer must be able to work on both in one editor session without extra ceremony.

## Decision

Product repositories are **cloned into `projects/<key>/` inside the workspace and
ignored** by the parent via `/projects/*` in `.gitignore`. Each keeps its own `.git` and its
own remote. They are **not** git submodules.

What the organisation's context repo tracks instead is `context/registry.tsv`: key,
folder, remote, description.
`ws bootstrap` clones every registered repo; `ws doctor` verifies the isolation holds.

For anyone who opens a product folder directly, `ws link <key>` writes a pointer
`AGENTS.md` into it and registers that file in the product repo's `.git/info/exclude` — so
it exists on disk but can never enter a client commit.

The convention is to **open the editor at the workspace root**, so agents walking up the
directory tree find `AGENTS.md`, `.cursor/rules/`, and `.agents/skills/` automatically.

## Consequences

### Positive
- Standards have one home, one version, one history, reused by every project.
- Nothing workspace-internal can reach a client repo — the parent's git cannot see inside
  `projects/`, and the pointer file is excluded locally.
- One editor session covers standards, skills, memory, and code.
- A new machine is set up with `ws bootstrap`.
- Each product repo keeps its own access control, history, and lifecycle.

### Negative
- The `workspace` repo does not pin which commit of a product repo a given state corresponds to.
  Accepted: we do not want that coupling, and release tags in the product repo serve the
  purpose better.
- A developer can accidentally run `git commit` in the wrong repo. Mitigated by `ws doctor`,
  the pointer file, and an explicit note in `AGENTS.md`.
- Anyone opening `projects/<x>` directly gets no automatic rule loading. Mitigated by the
  pointer file, which tells them to open the root.

### Neutral
- Product repos must be cloned separately; they are not part of a workspace clone.

## Alternatives considered

| Option | Why rejected |
|---|---|
| **Git submodules** | Forces the the workspace repo to hold commit pointers into client-owned repos. Mixes ownership, adds `git submodule update` to every clone and pull, and fills history with pointer bumps that carry no meaning. |
| **Copy standards into each product repo** | Guarantees divergence the moment a second project exists, and pushes the workspace's own material into client-owned repositories. |
| **Product repos in a sibling directory** | Loses automatic rule discovery by directory walk, and loses the single-workspace editor session. |
| **Monorepo containing everything** | Not possible: the client owns and hosts the product repository. |

## Follow-up

- [x] `ws bootstrap`, `ws new`, `ws link`, `ws doctor` implemented
- [x] `AGENTS.md` §2 documents the model and the "open at the root" rule
- [ ] Verify the pointer-file exclusion once a real client repo is cloned
