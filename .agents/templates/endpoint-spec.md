# Endpoint Spec: {{NAME}}

Fill this in **before** writing code. Five minutes here saves a contract change after the
frontend has started consuming it.

## Identity

| Field | Value |
|---|---|
| Module | `masterdata` / `dashboard` / `inbox` / `auction` / `reporting` / … |
| Path | `/api/v1/<module>/<plural-kebab-resource>` |
| Method | GET / POST / PUT / PATCH / DELETE |
| Ticket | PROJ-XXX |
| Owner | |

## Authorisation

| Question | Answer |
|---|---|
| Roles allowed | |
| Data-level scope | e.g. own unit only, own vendor only, all |
| How is the scope enforced? | **Must be in the query, not a post-load filter** |

## Request

```jsonc
// body, or n/a
```

| Parameter | Type | Required | Validation |
|---|---|---|---|
| | | | |

## Response — success

Status: `200` / `201` / `202` / `204`

```jsonc
```

## Response — errors

| Status | `code` | When |
|---|---|---|
| 400 | | Malformed request |
| 403 | | |
| 404 | | |
| 409 | | State conflict |
| 422 | | Business rule violated |

Error codes must be new values on the `ErrorCode` enum, stable forever.

## Business rules

1.
2.

## Data

| Question | Answer |
|---|---|
| Tables read/written | |
| New migration needed? | |
| New indexes needed? | |
| Expected row count at scale | |
| Paginated? | Required for any collection |

## Tests to write

- [ ] Integration: success path
- [ ] Integration: 400 malformed
- [ ] Integration: 403 wrong role
- [ ] Integration: 404 missing
- [ ] Unit: each business rule, including rejections
- [ ] Data-scope test: another unit's data is not visible

## Performance

| Question | Answer |
|---|---|
| Expected p95 | < 500 ms read / < 800 ms write |
| Could it exceed 10 s? | If yes → async job, see `bulk-reporting-export` |
