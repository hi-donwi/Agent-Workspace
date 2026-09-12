# Definition of Done

"Done" means releasable, not "I finished typing the code".

---

## For every endpoint

- [ ] Resource, service, repository follow the layering rules (`project-layout.md`)
- [ ] Request/response are `record` DTOs — **no entity leaks**
- [ ] Path, method, status codes follow `api-contract.md`
- [ ] Pagination uses the shared `PageRequest`/`PageResponse`
- [ ] Bean Validation on all input
- [ ] Explicit role annotation (`@RolesAllowed` or a deliberate `@PermitAll`)
- [ ] Data-level authorisation is in the query, not a post-load filter
- [ ] Errors go through the global `ExceptionMapper` with a stable `ErrorCode`
- [ ] OpenAPI annotations: `@Operation`, `@APIResponse`, `@Tag`
- [ ] Integration tests: success, 400, 401/403, 404
- [ ] Unit tests for every business rule, including rejections
- [ ] OpenAPI spec regenerated and committed

## For every database change

- [ ] Forward-only Flyway migration with timestamp naming
- [ ] Tested against a populated dump, not an empty database
- [ ] Audit columns present (`created_at`, `created_by`, `updated_at`, `updated_by`)
- [ ] Indexes for columns used in `WHERE`/`ORDER BY` on large tables
- [ ] Money stored as `NUMERIC(18,2)`
- [ ] Does not lock a large table (see the three-step pattern in `database.md`)
- [ ] Backward-compatible by one release so an application rollback stays possible

## For every change

- [ ] `./mvnw verify` green locally
- [ ] Pipeline green
- [ ] Coverage has not dropped
- [ ] No `System.out`, `printStackTrace`, or empty `catch`
- [ ] No `TODO` without a ticket ID
- [ ] No new secrets in code, properties, or commit messages
- [ ] No sensitive data in logs
- [ ] Commits follow Conventional Commits with a ticket reference
- [ ] MR under ~400 changed lines
- [ ] The run's `handoff.md` is updated (`context/runs/<key>/<run>/`)

## For every architecture decision

- [ ] An ADR in `docs/adr/` using `.agents/templates/adr.md`
- [ ] Rejected alternatives named with the reason
- [ ] If it deviates from `.agents/standards/`, the ADR names which standard

## For every delivery stage (from the proposal)

| Stage | Done means |
|---|---|
| 2 — Early Development | Architecture running, CI green, at least one end-to-end endpoint per module with tests |
| 3 — Continued Development | All 145 endpoints complete, coverage above threshold, OpenAPI spec complete |
| 4 — Server Setup & SIT | Automatic staging deploy, health checks green, k6 baseline recorded, SIT passed |
| 5 — Staging & UAT | UAT defects closed or explicitly scheduled, runbook written, API documentation handed over |
| 6 — Go-Live | Production running, monitoring and alerts active, rollback tested, handover complete |

---

## Not done

Common claims that are still rejected:

| Claim | Why it is not done |
|---|---|
| "Works on my machine" | Not yet verified in the pipeline against real PostgreSQL |
| "Tests come later" | Tests are part of the change, not separate work |
| "The endpoint exists" | Without authorisation and OpenAPI annotations the frontend cannot use it |
| "We'll refactor it later" | Refactoring without a ticket never happens |
| "I checked it manually" | A manual check does not repeat on the next release |
| "It's only a small change" | Change size does not alter the standard |
