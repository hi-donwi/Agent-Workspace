# Git Workflow

## Branching — trunk-based

```
main                      always deployable, protected
\-- feat/PROJ-142-transaction-summary     short-lived, < 3 days
```

- Branch from `main`, merge back to `main`.
- **Maximum branch age is 3 days.** Longer than that and conflicts get expensive — and with
  two developers working on adjacent modules, that happens quickly.
- No `develop` branch. GitFlow adds an integration branch to maintain without giving a team
  this size anything in return.
- Tag `v*` from `main` for releases.

Prefixes: `feat/` · `fix/` · `refactor/` · `chore/` · `docs/` · `test/`

Format: `<type>/<TICKET>-<short-slug>`

## Commits — Conventional Commits

```
<type>(<scope>): <summary>

<body: why, not what>

Refs: PROJ-142
```

| Type | For |
|---|---|
| `feat` | New feature or endpoint |
| `fix` | Bug fix |
| `refactor` | Structural change, behaviour unchanged |
| `perf` | Performance improvement |
| `test` | Adding or fixing tests |
| `docs` | Documentation |
| `build` | Build, dependencies, CI |
| `chore` | Everything else |

Scope is the module: `masterdata`, `dashboard`, `inbox`, `auction`, `reporting`, `common`.

```
RIGHT  feat(masterdata): add vendor search by tax ID
RIGHT  fix(reporting): prevent OOM when exporting more than 50k rows

       The export loaded the full result set into a List before writing.
       Replaced with streaming in 5000-row batches via SXSSF.

       Refs: PROJ-201

WRONG  update code
WRONG  fix bug
WRONG  WIP
```

Breaking changes: `feat(api)!: ...` plus a `BREAKING CHANGE: <explanation>` footer.

### Atomic commits

One commit equals one logical change that builds green. Not "today's work".

If the commit summary needs the word "and", it is usually two commits.

## Merge Requests

Template in `.gitlab/merge_request_templates/` (or `.github/`).

Required:

- [ ] Title follows Conventional Commits
- [ ] References a ticket
- [ ] Explains **why**, not restating the diff
- [ ] Tests added or updated
- [ ] OpenAPI spec regenerated if the contract changed
- [ ] Migration tested against a populated database
- [ ] Pipeline green
- [ ] **At least 1 approval** (Lead Developer for architectural changes)

**MR size: under 400 changed lines.** Review above that becomes rubber-stamping; a defect
that slips through a 2,000-line MR gets found by users, not reviewers.

Merge with **squash** so `main`'s history stays clean — one commit per MR.

## Review

Reviewers check, in order:

1. **Correct?** Edge cases, nulls, errors, race conditions.
2. **Secure?** The checklist in `security.md`.
3. **Standard-conforming?** Layering, API contract, naming.
4. **Tested?** The tests genuinely fail if the code is wrong.
5. **Clear?** Someone else can change it in six months.

Comments state **why**, and distinguish blocking from optional. Use prefixes:
`must:` `should:` `question:` `nit:`.

## Never committed

`.gitignore` blocks most of this, but it remains a human responsibility:

- Secrets, `.env`, keys, certificates
- Client documents, data dumps, signed screenshots → `.local/` in the workspace
- `target/`, `node_modules/`
- Personal IDE files
- Commented-out code — git already keeps the history

## Hooks

```bash
# .git/hooks/commit-msg  — validate Conventional Commits
# .git/hooks/pre-commit  — spotless:check + secret scan
```

Installed via `./mvnw initialize` (git-build-hook-maven-plugin) so it does not depend on
everyone remembering.
