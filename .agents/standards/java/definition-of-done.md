# Definition of Done — Java additions

These checks apply **on top of** `core/definition-of-done.md`. Both bars apply
to every change; neither replaces the other. This pack also records the
delivery-stage completion criteria for contracted, stage-gated projects.

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

## Java-specific "for every change" additions

- [ ] `./mvnw verify` green locally (this stack's declared verification command)
- [ ] No `System.out`, `printStackTrace`, or empty `catch`

## For every delivery stage (per contracted proposal)

Delivery-stage criteria are project scope, not workspace scope. They belong to
the proposal of the specific client project and are recorded here only as this
workspace's active example.

| Stage | Done means |
|---|---|
| 2 — Early Development | Architecture running, CI green, at least one end-to-end endpoint per module with tests |
| 3 — Continued Development | Contracted API scope complete, coverage above threshold, OpenAPI spec complete |
| 4 — Server Setup & SIT | Automatic staging deploy, health checks green, k6 baseline recorded, SIT passed |
| 5 — Staging & UAT | UAT defects closed or explicitly scheduled, runbook written, API documentation handed over |
| 6 — Go-Live | Production running, monitoring and alerts active, rollback tested, handover complete |
