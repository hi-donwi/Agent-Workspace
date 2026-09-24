# Workspace layout — `projects/` and the framework root

Moved out of `AGENTS.md` §2 so that every agent can load the contract whole (some tools
cut a rule file off at 24 KB). The summary and the rules stay in `AGENTS.md`; this is the
detail and the reasoning.

Yes, this is valid and deliberate. Every repository under `projects/` is an **independent
git repository** with its own remote (usually the client's GitLab). The parent ignores them
via `/projects/*` in `.gitignore`, so the parent's git never sees their contents.

**The local folder mirrors the remote's full path, not just the immediate parent.** A
remote at `gitlab.com/example-org/client-a/backend-api.git` becomes
`projects/example-org/client-a/backend-api/` — the top-level group included, not
silently dropped in favour of only its subgroup. The segment name does not have to be a
byte-for-byte copy of the host's group name (`example` for `example-org` is fine, matching
the organisation's own short name), but the *number of levels* must match: dropping the
top level works only until a second top-level group enters the registry and one of its
subgroups collides with a name already in use. `/projects/*` ignores the whole tree
regardless of depth, so nesting further costs nothing.

**One checkout, two keys.** A monorepo holding, say, an API and its mobile app may be
registered as two projects. The inner row's folder sits inside the outer row's folder
and names the **same remote**; that is what makes it a subproject rather than a nested
repository. It has no clone of its own, so `ws bootstrap` skips it (it arrives with its
parent — cloning the same remote into it would plant the monorepo inside itself),
`ws link` writes nothing into it (the exclude entries and guard hook are anchored at the
repo root, where a subdirectory's `AGENTS.md` would slip past both), `ws new` neither
clones nor inits there, and `ws doctor` checks that the folder really is part of the
parent's checkout. A folder inside another project with a *different* remote is still
required to be its own repository. The agent-hours hook resolves the working directory
to the most specific registered folder, so time spent in the subproject is its own.

**This is not a submodule, and must not become one.** A submodule would force the
workspace repo to hold a commit pointer into a client-owned repo — extra friction on every
clone (`git submodule update`) and a blurring of ownership. What this repo tracks instead
is `context/registry.tsv`: a map of name → remote → project key.

To set up a new machine:

```bash
.agents/bin/ws bootstrap      # skills, then the context repo, then every product repo
.agents/bin/ws ide            # copy the shared editor defaults into this clone
.agents/bin/ws doctor         # verify repo isolation, ignores, and links
```

`ws bootstrap` pulls skills first — they are what an agent reads before touching any of
the code it then clones. An unreachable skills source is a warning, not a failure: a new
machine on a bad network still ends up with its repositories, and `ws doctor` keeps
reporting the missing skills until someone syncs them.

## Local web control — `ws web`

`ws web` is a **loopback** control UI for this clone (board, runs, hours, health). It is
not a hosted product.

- Default runtime is **UIDL** using npm `uidl-runtime` in this framework's
  `apps/workspace-control`. Build with `npm ci && npm run build` in that directory.
- Build lookup prefers `WS_UIDL_DIST`, then `apps/workspace-control/dist`, then a legacy
  companion under `projects/**/apps/workspace-control/dist`. If no build exists, it
  **falls back** to the stdlib vanilla UI. Force vanilla with `ws web --runtime vanilla`.
- The UI supports Light, Dark, and System themes. See
  [`apps/workspace-control/README.md`](../apps/workspace-control/README.md) for development
  and browser tests. The server accepts loopback hosts and same-origin browser requests.
- The process prints a URL with `?token=`. Opening `/` without the query also works: the
  server injects the token into the companion HTML so it redirects to `/?token=...`. The
  token is per-process, loopback-only, and is not written to disk.
- APIs under `/api/` still require `Authorization: Bearer <token>`.
- For AI-assisted workspace interaction and LLM chat, use `ws chat` (or `ws web --runtime agent-control`).
  This runs Agent-Control, connecting multi-provider LLMs to the workspace via `ws` tooling.

## Open your editor at the workspace root, not at `projects/<x>`

Agents discover rules by walking up the directory tree. Opening the workspace root makes
`AGENTS.md`, `.cursor/rules/`, and `.agents/skills/` load automatically while the product
repo stays isolated in git terms. Where you cloned the workspace does not matter — nothing
tracked here assumes a path. `ws where` resolves the root from anywhere.

## Searching from the root: `.ignore`

`/projects/*` in `.gitignore` hides product code from every gitignore-aware search tool —
ripgrep, VS Code search, and the search tools of Claude Code, Cursor, and Copilot. Left
alone, the "open at the root" rule above would mean **no agent can grep the code it is
working on**.

`.ignore` at the workspace root fixes that for search only:

```
!projects/*/          # visible to search tools
projects/**/.git/     # but not the plumbing
projects/**/target/
```

Git is unaffected: `git check-ignore projects/<key>` still reports it ignored, and
`git add -A` still refuses to embed it. Never do this in `.gitignore` — a negation there
makes git track the product repo as a gitlink, which is exactly what ADR-0001 rejects.

If someone does open a project folder directly, `ws link <project>` writes two
**untracked** files into the product repo and registers them in `.git/info/exclude` —
present on disk, never in a client commit:

| File | For | Contents |
|---|---|---|
| `AGENTS.md`, or `.workspace-instructions.md` when product rules already exist | Humans and agents | A local pointer telling them where workspace standards live |
| `.workspace` | Tools without `ws` on PATH | `workspace=`, `project_key=`, `generated=` |

A product may track its own portable `AGENTS.md` as a client-owned code contract.
`ws link` preserves it, including before its first commit, and writes the generated pointer
to `.workspace-instructions.md` instead. Only generated pointers are excluded and blocked;
the product's own rules remain versionable. Open the optional pointer explicitly when an
agent does not discover it automatically.

Exactly one generated pointer exists at a time. Which file it is switches when a product
starts or stops tracking its own `AGENTS.md`, so `ws link` removes the superseded one —
a pointer left behind keeps its absolute paths forever, and a stale pointer beside a
correct one is how a reader ends up following the wrong one. A client-owned file is never
removed; only a file carrying the generated marker is.

When the project has a `context_repo` (see §3), the pointer names **that** repository for
memory and runs rather than the root context's routing stubs, and `.workspace` records
`context_repo=` for tools without `ws` on PATH. A column naming a directory that is not
cloned falls back to the root context and says so, because a pointer to a repository
nobody has is worse than a pointer to the stub that explains it.

**The generated files are machine-local and hold absolute paths**, so they are regenerated per machine —
never shared. `ws bootstrap` writes them automatically after each clone, so a teammate on
a different device gets their own paths without doing anything extra. They are *not* in the
client repo's `.gitignore`; the exclusion lives in `.git/info/exclude`, which is per-clone
and never pushed, so nothing workspace-specific can reach a client's tracked tree.

`ws link` also installs a `pre-commit` hook in the product repo that refuses a commit
containing generated pointers. The exclude entry keeps them out of `git status`; the hook is what
stops `git add -f`. An existing hook that is not ours is never overwritten — `ws link` says so and
leaves it alone.

If the workspace is later moved or renamed, those paths go stale. `ws doctor` detects that
and names the fix (`ws link <key>`). `ws where` does not depend on them: it finds the root
by looking for a directory that has both `AGENTS.md` and `.agents/standards/`, and only
falls back to the breadcrumb for a product repo cloned outside the workspace.

## The one way to lose work: `git clean -ff`

Because `projects/` is ignored, it is a target for `git clean -x`. Plain `git clean -xdf`
refuses to delete a nested repository, but **`git clean -ffxd` deletes the product repo
outright** — working tree, `.git`, and any commit not yet pushed. Never use `-ff` at the
workspace root. Put `.agents/bin` on PATH: the `git` wrapper there refuses `-ff` at this
root. Push product work the same day; nothing in a workspace clone backs it up.

---
