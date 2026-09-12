# ADR-0007: Skills in their own repository, fetched by manifest

- **Date:** 2026-09-12
- **Status:** Accepted
- **Project:** workspace

## Context

A skill is knowledge about *how to do a kind of work* — review a diff, plan a migration,
harden a service. It is not knowledge about a project, and it outlives the one that
prompted it. Vendored into a workspace, the same skill drifts into as many versions as
there are workspaces, and improving it means improving it everywhere by hand.

Two further pressures appeared as the library grew. Not every workspace wants every
skill: a Java backend team has no use for Cloudflare Workers guidance, and a workspace
that carries it pays for it in agent context and in review noise. And skills are the part
of this system most worth sharing publicly, while memory and registries are the part that
must never be.

## Decision

Skills live in **their own repository**, grouped into packs (`core`, `agent`, `web`,
`java`). A workspace declares what it wants in `.agents/skills.manifest`:

```
source = git@github.com:hi-donwi/Agent-Skills.git
ref    = main

pack core
pack java
skill web-perf
```

`ws skills sync` materialises exactly those into `.agents/skills/` and writes the resolved
commit to `.agents/skills.lock`. The manifest and the lock are **tracked**; the
materialised skills are **git-ignored**, and `ws doctor` fails if they become tracked —
the moment they do, the source repository has silently stopped being the single source.

Fetching uses a **blobless, sparse checkout**: `git clone --filter=blob:none --no-checkout`
once, then `sparse-checkout set skills/<name>` per sync. Taking three skills out of forty
downloads three skills. The source repository's `index.json` is read straight from the
object store with `git show`, so resolving `pack core` into names costs no checkout at all.

An organisation's **domain** skills are the exception: they stay in `context/skills/`,
committed to the private context repo, never published. `ws route` searches both, so the
split costs the person at the keyboard nothing.

## Consequences

### Positive
- One version and one history per skill, improvable in one place.
- A workspace carries only what it uses, which is agent context saved on every session.
- The lock makes `ws skills sync` reproducible: every teammate gets byte-identical skills.
- Skills can be public while memory stays private, because they are different repositories
  rather than different folders.

### Negative
- A fresh clone has no skills until `ws skills sync` runs. `ws bootstrap` runs it, and
  `ws doctor` reports it, but an offline first clone is genuinely worse off than a
  vendored one.
- Updating a skill is now two repositories and two commits.
- The cache under `.agents/.cache/` is disposable but not free; deleting it forces a
  re-clone.

### Neutral
- Pinning is by commit, not by tag or semver. Skills are prose, and a version number on
  prose implies a compatibility contract that does not exist.

## Alternatives considered

| Option | Why rejected |
|---|---|
| **Keep skills vendored in the workspace** | Every workspace drifts into its own copy, and the public workspace would carry stack-specific guidance nobody asked for. |
| **Git submodule** | All-or-nothing: no way to take three skills out of forty, and it adds `git submodule update` to every clone and pull. |
| **Git subtree** | Also all-or-nothing, and it rewrites the consuming repo's history on every update. |
| **npm/OCI package** | Adds a registry, a publish step, and a runtime to a thing that is forty markdown files. Git already versions and fetches. |
| **Symlink to a sibling clone** | Breaks on any machine that laid out its directories differently — exactly the portability defect ADR-0005 removed. |
| **Copy on demand with curl** | No pinning, no integrity, no offline story. |

## Follow-up

- [x] `Agent-Skills` published with 38 skills in four packs
- [x] `ws skills status|sync|add|remove|available|index` implemented
- [x] `.agents/skills/` git-ignored; `ws doctor` fails if it is tracked
- [ ] Decide whether `ws bootstrap` should hard-fail when the skills source is unreachable
