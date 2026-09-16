# ADR-0006: Framework, context, and product as three repositories

- **Date:** 2026-09-12
- **Status:** Accepted
- **Project:** workspace

## Context

ADR-0001 separated product code from the workspace. That left two kinds of material still
mixed together in one repository:

- **Framework** — the contract, standards, skills, templates, and CLI. How anyone builds
  anything.
- **Context** — one organisation's memory, runs, product registry, client ADRs, proposals,
  and domain glossary. What *this* organisation is building, for whom, and where it stands.

Mixing them costs on both sides. The framework cannot be shared with another team, adopted
for another client, or published, because a company name, a client's GitLab group, an
endpoint count, and a domain glossary are woven through it. And the context cannot be given
its own access rules, because it lives in the same repository as the standards everyone
needs to read.

The trigger was concrete: the framework was to be published, and an audit found client
material in standards and skills — module tables with endpoint counts, a role matrix, a
reserve-price confidentiality rule, a client's reverse-domain namespace, and a regulated
Indonesian glossary. None of that is a rule for anyone else.

## Decision

Three repositories, stacked in one working directory, distinguished by **who owns the
material** rather than by what kind of file it is.

| # | Repo | Path | Owner | Ignored by |
|---|---|---|---|---|
| 1 | Framework | the root | Whoever maintains the workspace | — |
| 2 | Context | `context/` | One organisation | 1 |
| 3 | Product | `projects/<group>/<repo>/` | Usually the client | 1 |

Context is mounted and ignored exactly as product repos already were, so the mechanism is
one people have already learned rather than a second thing to remember.

**The framework names no organisation.** Identity lives in `workspace.conf`, which is
**untracked**; the repository ships `workspace.conf.example`. `ws init` writes the real
file. This is what makes the same repository usable by anyone, and safe to publish.

**Standards are packs.** `core/` holds what is true regardless of language — git workflow,
REST contract, definition of done. `java/` holds the concrete rules for that stack. A team
on another stack adds a pack instead of editing `core`. `workspace.conf` declares which
packs apply.

**Domain knowledge is context, not framework.** A domain skill lives in `context/skills/`.
`ws route` and `ws skills` search the framework and the context together, so this costs the
person at the keyboard nothing, but the two indexes stay separate — the tracked framework
index never lists an organisation's domain skills.

**The CLI carries no brand.** `mkt` became `ws`, `.mkt-workspace` became `.workspace`,
`MKT_USER` became `WS_USER`.

**Publishing requires a new history, not a new commit.** Removing client material in a
commit leaves it in every earlier one. The public framework therefore starts from an orphan
commit; the pre-split history is kept privately and is not pushed.

## Consequences

### Positive
- The framework can be published, shared between organisations, and adopted for a new team
  or client by `ws init` + `ws context init` — with nothing of anyone else's attached.
- Context gets its own access control and its own lifecycle.
- Standards that were implicitly Java-only are now explicitly labelled, so a team on another
  stack knows what it is missing instead of assuming the Java rules transfer.
- `ws doctor` can mechanically check the boundary: it fails if context is tracked in the
  framework, and warns if the organisation's key appears in a tracked framework file.

### Negative
- Three repositories to clone, commit to, and keep pushed. Mitigated by `ws bootstrap`,
  `ws context clone`, and `ws sync`, and by `ws doctor` reporting any repo without a remote.
- Extracting context started its history fresh. The pre-split history stays in the private
  archive; the context repo's own history begins at the extraction.
- Genericising the standards replaced a concrete domain with an invented one. Examples that
  once matched the real system now merely resemble it, which is a small loss in vividness
  for a large gain in reuse.

### Neutral
- The `java` pack still carries the concrete testing, security, and observability rules.
  That is honest rather than ideal: a future stack pack must supply its own.

## Alternatives considered

| Option | Why rejected |
|---|---|
| **One repo, keep client material, never publish** | The framework is then rewritten from scratch for the next client, which is the divergence ADR-0001 exists to prevent. |
| **One repo, scrub client material, keep history** | Published history would still contain it. Scrubbing only the tip is security theatre. |
| **Two branches: `main` for the organisation, `template` neutral** | Two branches to keep in sync by hand, forever, with the leak one careless merge away. |
| **Context inside the framework but git-ignored, no repo** | Then it is backed up nowhere and shared with nobody — the opposite of what memory is for. |
| **Keep client memory in each product repo** | Puts workspace-internal material in a client-owned repository, which ADR-0001 forbids. |

## Follow-up

- [x] Context extracted to its own repository, mounted at `context/`
- [x] `workspace.conf` untracked, `workspace.conf.example` shipped, `ws init` added
- [x] Standards split into `core` and `java` packs; skills tagged with a pack
- [x] CLI renamed to `ws`; framework scrubbed of organisation and client identifiers
- [x] Publish the framework from an orphan commit; keep the pre-split history private
- [x] Give the context repository a private remote
- [x] Delete merged feature branches that still carried pre-generic example paths (GitHub `main` is the only remaining branch; merged PR objects may still be reachable)
