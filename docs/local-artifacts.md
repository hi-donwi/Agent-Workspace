# Local artifact layout

`.local/` is machine-local and ignored by Git. Keep generated output out of the
workspace root so it stays easy to browse and does not enter a product repository.

## Project output

Mirror the full project path below `.local/projects/`, including every group or nested
folder represented below `projects/`:

```text
.local/projects/<group>/<nested-path>/<repo>/<run-id>/<kind>/
```

Use a short, consistent `<kind>` such as `logs`, `reports`, `evidence`, `assets`,
`packages`, or `data`. Keep project output together under the same project path.

## Workspace and temporary output

```text
.local/workspace/<domain>/<run-id>/<kind>/
.local/tmp/<domain>/<session-id>/
.local/archive/<domain>/<year>/
```

Use `workspace/` for generic tooling output with no project data, `tmp/` for disposable
work, and `archive/` for completed material retained for reference. Remove temporary
files when their task ends and no active process refers to them.

## Existing files and managed directories

- Put new work output in the directories above. Keep the `.local/` root for its index,
  layout guide, and legacy compatibility links.
- Do not store credentials, private keys, or tokens in `.local/`.
- Do not relocate active sessions, worktrees, caches, or tool-managed state.
- Before moving an existing file, check its references. Keep the old path available until
  callers are updated; use a compatibility link while paths are still used. The local
  migration map is `.local/workspace/maintenance/MIGRATION-MAP.tsv`.
- Keep real project artifacts below `.local/projects/`, following the registered project
  path. Use `.local/domains/` only while ownership is unknown; assign a verified project
  path before later moving an artifact into a project tree.
