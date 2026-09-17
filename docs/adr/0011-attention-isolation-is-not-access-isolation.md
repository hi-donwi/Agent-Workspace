# ADR-0011: Attention isolation is not access isolation

- **Date:** 2026-09-17
- **Status:** Accepted
- **Deciders:** PT Mumpuni Kolaborasi Teknologi
- **Project:** workspace

## Context

ADR-0010 decided that a context repository is an **access** boundary: everyone
who can clone it may read every file in it, including history. Folder names
(`clients/<client>/`, `memory/projects/<key>/`) organise material; they are
not ACLs.

That is the right rule for humans and for git. It is the wrong rule for an
agent session. This workspace is opened at the root so standards and skills
load, product repos are search-visible (`.ignore` un-hides `projects/` for
ripgrep), and editor/tool memory (Grok workspace memory, Cursor memories, and
similar) treats the framework clone as **one** project. The last client's
facts are then injected into the next client's session. Git isolation never
saw that leak: nothing was committed to the wrong remote.

A named project, a run folder, and `ws agent start` already existed. None of
them pinned "this conversation may only load client X." `ws context pack`
already built the allowlist and excluded sibling clients; agents did not call
it first.

## Decision

Attention isolation is a separate contract from access isolation.

1. Every agent session that does product work **binds** to one registry
   project: `ws session bind <key>` (and `ws agent start <key>`, which binds
   as well as creating a worktree).
2. The bind writes under `.local/sessions/<session-id>/` (`bind`, `pack.json`,
   `CONTEXT.md`). One directory per conversation. Not a workspace-level
   "active project" file, which concurrent sessions would overwrite.
3. The pack is the same allowlist as `ws context pack <key>`: that project's
   memory, that client's (or group's) docs according to `context_scope`,
   optional run files. Sibling clients are not packed.
4. Injected editor/tool memory whose project or client is not the bound key
   is ignored. Recency is not relevance.
5. Client facts are written to `context/memory/projects/<key>/` and the run,
   never to editor/tool workspace memory. Those stores are workspace-scoped.
6. `ws doctor` warns when a named session (`WS_SESSION_ID` or equivalent) has
   no bind. A `default` session without a bind is noted, not failed.

ADR-0010 is unchanged. Split workspace clones when **readers** differ. Bind
sessions when **the same operator** switches clients.

## Consequences

### Positive

- A session for one client does not start by loading another client's notes.
- Concurrent agents can bind different projects without a shared rules file.
- The allowlist is a command, not a hope that the model will skip adjacent
  folders.

### Negative

- Agents must resolve a project key before substantial work. Ambiguous
  requests have to ask instead of grepping the whole tree.
- Editor/tool memory products that have only "global" and "workspace" scopes
  cannot be the system of record for client facts. Continuity lives in
  `context/`.

### Neutral

- `ws context pack` stays the packager; bind is pack plus a session-scoped
  pointer.
- Product git worktrees stay the isolation for `HEAD`. Bind does not replace
  `ws agent start`.

## Alternatives considered

| Option | Why rejected |
|---|---|
| Put "active project = X" in `.grok/rules/` or a root `AGENTS.local.md` | Applies to every session in this cwd; concurrent agents overwrite each other |
| One workspace clone per client (ADR-0010 only) | Correct when audiences differ; does not fix a solo operator with many clients in one clone |
| Disable editor/tool memory for this clone | Stops the leak, also stops framework-level habits; too blunt, and other tools still grep from root |
| Teach agents in prose to "read `context/memory/projects/<key>/`" without a bind | Already said that; they still received the previous client's injected memory |
| Filter Grok/Cursor memory by project inside those products | Not under this repository's control; bind is the workspace-side contract |

## Follow-up

- [x] `AGENTS.md` §4 session gate
- [x] `ws session bind` / `status` / `clear`; `ws agent start` binds
- [x] `ws doctor` warns on an unbound named session
- [ ] Editor/tool memory products grow a project scope (out of tree)
