# ADR-0022: Opt-in context checkpoint publication

- **Date:** 2026-10-12
- **Status:** Accepted
- **Deciders:** Workspace maintainer
- **Project:** workspace

## Context

The context repository is the continuity store for runs, memory, and team decisions. The
existing `ws checkpoint` command commits the current agent's context work locally, while
`ws context sync` only retrieves remote changes. That separation protects against silently
publishing unrelated local history, but it also leaves shared context stale when an operator
has deliberately configured a private remote.

The framework and product repositories have different owners and audiences. A remote URL alone
does not prove that it is private, that it is the configured context audience, or that the
local branch is safe to publish. Automatic publication must not turn a compaction hook into a
blind push or overwrite another agent's remote work.

## Decision

We add a machine-local `context_publish` setting with `manual` as the default and `auto` as an
explicit opt-in. `ws context publish` is the guarded publication command. `ws checkpoint
--publish` combines an owned checkpoint with explicit publication; in `auto` mode, a normal
checkpoint may publish only when the remote branch still equals the pre-checkpoint local tip.
Publication requires a matching configured `context_remote`, a non-mixed private context, a
clean non-detached branch, a successful fetch, and no remote divergence. It pushes only the
current context branch without force or tag propagation. Compaction always passes
`--no-publish`; normal stop hooks follow the local mode. Product and framework repositories do
not inherit this policy.

## Consequences

### Positive

- Shared context can be published automatically without granting that behavior to product or
  framework repositories.
- A stale or concurrent context branch fails closed instead of being force-pushed.
- Auto publication cannot silently publish pre-existing unpublished commits from another session.
- The default remains local-only for new and existing workspaces.

### Negative

- An operator must review and explicitly publish a context branch that is already ahead of its
  remote or that diverged during the checkpoint.
- The privacy probe uses anonymous Git access and can miss a public remote when the network
  fails; the remote host's visibility setting remains authoritative.
- The stop hook may create a local checkpoint even when a session ends unexpectedly, as the
  existing continuity workflow already does.

### Neutral

- `ws context sync` remains pull/rebase only and never publishes.
- The setting lives in untracked `workspace.conf`, so different workspace clones may choose
  different publication modes.

## Alternatives considered

| Option | Why rejected |
|---|---|
| Push whenever any remote exists | A remote does not prove privacy, audience, branch freshness, or authorization. |
| Push from the compaction hook | Compaction is a continuity checkpoint, not an operator publication decision. |
| Reuse product or framework push policy | The three repositories have different owners and disclosure boundaries. |
| Allow force-push to recover divergence | It can erase another agent's context; fetch/review/rebase is safer. |

## Follow-up

- [x] Add guarded context publication and regression tests.
- [x] Document `manual` and `auto` modes.
- [ ] Add a trusted control-plane approval record if remote publication later needs group or
  four-eyes authorization.
