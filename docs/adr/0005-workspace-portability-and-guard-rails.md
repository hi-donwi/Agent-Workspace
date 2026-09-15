# ADR-0005: Workspace portability and isolation guard rails

- **Date:** 2026-09-12
- **Status:** Accepted
- **Project:** workspace

## Context

ADR-0001 put product repos inside `projects/`, ignored by the parent. That model was
audited before the team grew past one machine. Testing the actual git behaviour — rather
than reasoning about it — turned up four things that the model itself does not address.

1. **Tracked files carried one machine's absolute paths.** `context/memory/projects/index.md`
   and two `project.md` files named a home directory that exists on exactly one laptop.
   `index.md` is the table an agent consults to resolve a project root, so it was wrong for
   every teammate.

2. **Product code was invisible to search.** `/projects/*` in `.gitignore` hides the product
   repos from every gitignore-aware tool: ripgrep, VS Code search, and the search tools of
   Claude Code, Cursor, and Copilot. Measured in this workspace, `rg --files projects/`
   returned two files, both belonging to the parent. The rule in AGENTS.md §2 to open the
   editor at the root therefore guaranteed that agents could not grep the code they were
   working on.

3. **`ws doctor` could not fail.** Its per-project checks ran inside a `reg_rows | while`
   pipeline, so any `fail=1` was set in a subshell and lost. The check for the most
   dangerous condition — the workspace pointer becoming tracked inside a client repo —
   printed in red and then let the command exit 0.

4. **`git clean -ffxd` at the root deletes a product repo outright.** Because `projects/`
   is ignored it is a target for `-x`, and the second `-f` lifts git's refusal to delete a
   nested repository. Plain `-xdf` is safe. Nothing in a workspace clone backs up an unpushed
   commit in a product repo.

## Decision

**Portability.** No tracked file may contain a machine-specific absolute path. Project roots
in memory are workspace-relative; prose uses `~`. `ws where` resolves the workspace root by
looking for a directory containing both `AGENTS.md` and `.agents/standards/`, and only falls
back to the `.workspace` breadcrumb for a product repo cloned outside the workspace. The
breadcrumb and the pointer `AGENTS.md` stay absolute and stay machine-local, because they are
regenerated per clone and never shared. `ws doctor` fails on any absolute path in a tracked
file.

**Search.** A `.ignore` file at the workspace root re-includes `projects/*/` for search tools
only, and re-excludes `.git`, build output, and dependencies underneath. Git is untouched:
`git check-ignore` still reports the product repo ignored and `git add -A` still refuses to
embed it. The negation must never be written in `.gitignore` — tested, and it immediately
makes git stage the product repo as a `160000` gitlink, which is what ADR-0001 rejects.

**Guard rails.** `ws link` installs a `pre-commit` hook in each product repo that refuses a
commit containing `AGENTS.md` or `.workspace`, and excludes each pointer independently so
a clone linked by an older version of `ws` is repaired rather than half-covered. `ws doctor`
runs without a subshell, sets a failure flag on every red condition, and additionally checks:
a remote exists for the workspace and for each product repo, the registry has no duplicate
keys or folders, both pointers are excluded and neither is tracked, the guard hook is present,
`.ignore` is in place, and `index.json` is not stale. `ws doctor --ci` skips the
developer-toolchain block so it can gate CI.

**Concurrency.** `.gitattributes` gives `log.md` and `registry.tsv` the union merge driver,
so concurrent appends from different people both survive. `index.md` and `decisions.md` are
deliberately excluded: a conflict there means two people changed the same fact and a human
should read both sides. `ws log` appends a milestone through one code path, and run
directories are named `<timestamp>-<person>-<tool>-<slug>` so two people using the same
agent never collide.

## Consequences

### Positive
- A clone works identically on any machine, at any path, with no per-machine editing.
- Agents can search product code while the editor is open at the root, as the contract asks.
- The pointer files now have two independent defences against reaching a client repo.
- `ws doctor` is usable as a CI gate and as a pre-flight check.
- The common concurrent writes to shared memory resolve themselves.

### Negative
- `.ignore` duplicates part of `.gitignore`'s intent with the opposite sign, which reads as a
  contradiction until you know that git and ripgrep consult different files. Both files carry
  a comment explaining it, and `ws doctor` checks `.ignore` is present.
- Union merge can interleave two log rows out of chronological order, and will happily keep
  two rows that say the same thing. Accepted: a duplicate row is cheaper than a conflict in a
  file nobody's work depends on.
- The guard hook is per-clone, like `.git/info/exclude`. A clone made without `ws` has
  neither; `ws doctor` reports it.

### Neutral
- `git clean -ff` cannot be prevented from inside the repo. It is documented in AGENTS.md §2
  and in the README's list of most-broken rules instead.

## Alternatives considered

| Option | Why rejected |
|---|---|
| **Negate `/projects/*` in `.gitignore` to restore search** | Tested: git immediately stages the product repo as a gitlink. Breaks ADR-0001. |
| **Disable ignore files in the editor (`search.useIgnoreFiles: false`)** | Only fixes VS Code, and only for people who copied the shared settings. Agents and ripgrep stay blind. |
| **Symlink product code into a searchable directory** | Two paths to the same file confuses agents and tools far more than one ignore file does. |
| **Drop `index.json` from git to avoid conflicts** | A fresh clone would have no machine-readable skill index until someone runs `ws skills`. Staleness check is cheaper. |
| **Union merge for `decisions.md` too** | Silently keeping both halves of a contradicted decision is worse than a conflict. |

## Follow-up

- [x] `.ignore`, `.gitattributes`, hardened `ws link` / `doctor` / `where`, `ws log`, `ws sync`
- [x] Absolute paths removed from tracked files
- [ ] Push the workspace to a remote — everything above is moot while it lives on one laptop
- [ ] Enable `.gitlab-ci.yml` once the remote exists
