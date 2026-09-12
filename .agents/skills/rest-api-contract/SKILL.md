---
name: rest-api-contract
pack: core
description: >-
  Design and review REST contracts: URL shape and HTTP method choice, status codes, uniform
  pagination and filtering, RFC 9457 problem+json errors with stable ErrorCodes, date/money/
  enum formats, OpenAPI annotations and the committed spec, versioning and breaking-change
  identification. Use when designing a new endpoint, aligning endpoints that have diverged,
  choosing a status code, shaping an error response, updating the OpenAPI spec, or judging
  whether a change is breaking. Do not use for internal implementation (quarkus-service),
  queries (quarkus-persistence), or roles and authorisation (quarkus-security).
keywords: api, contract, openapi, swagger, status code, pagination, paging, filter, error response, problem json, versioning, breaking change, dto, request, response
---

# REST API Contract

Full rules: `.agents/standards/core/api-contract.md`. This is how to decide.

With 145 endpoints built by two developers in parallel, consistency is not aesthetics —
every divergent shape is one more adapter the frontend has to write.

## Use when
- Designing a new endpoint (before coding)
- Choosing a status code or response shape
- Introducing a new error
- Judging whether a change is breaking
- Reviewing the OpenAPI spec

---

## Design first, code second

Fill in `.agents/templates/endpoint-spec.md` before writing code. Five minutes here saves a
contract change after the frontend has started consuming it.

## Choosing method and status

```
Reading many?        GET    paginated collection -> 200 (empty is still 200)
Reading one?         GET    -> 200 / 404
Creating?            POST   -> 201 + Location
Full replacement?    PUT    -> 200
Partial update?      PATCH  -> 200   (only where genuinely needed)
Deleting?            DELETE -> 204   (idempotent)
Non-CRUD action?     POST /resource/{id}/<action-as-noun> -> 200 / 202
```

Actions are expressed as sub-resources, not verbs:

```
RIGHT  POST /api/v1/orders/{id}/submission
RIGHT  POST /api/v1/orders/{id}/cancellation
WRONG  POST /api/v1/orders/submit/{id}
WRONG  GET  /api/v1/getOrderById
```

### Which 4xx?

| Condition | Status |
|---|---|
| Malformed JSON, wrong type, missing required field | 400 |
| Not logged in / session expired | 401 |
| Logged in, not permitted | 403 |
| ID does not exist | 404 |
| State conflict (already approved, unique duplicate) | 409 |
| Well-formed but breaks a business rule | 422 |

**401 vs 403:** 401 means we do not know who you are → log in again. 403 means we do, and
the answer is no → logging in again will not help.

**400 vs 422:** 400 when the request cannot be parsed. 422 when it parses but breaks a rule
(duplicate tax ID, insufficient budget, tender date before announcement).

---

## Pagination — one shape everywhere

```
GET /api/v1/masterdata/vendors?q=abc&page=0&size=50&sort=name,asc
```

```json
{
  "content": [],
  "page": 0,
  "size": 50,
  "totalElements": 1284,
  "totalPages": 26,
  "sort": "name,asc"
}
```

Use `PageRequest`/`PageResponse<T>` from `app-common`. **Do not invent a per-module
pagination shape.**

- `size` caps at 200, enforced server-side — do not trust the client.
- `sort` is validated against an allowlist (`quarkus-security`).
- An unpaginated collection does not pass review. The `order` table will hold millions
  of rows; an endpoint returning 50 rows today will return 500,000 in year two.

For sequential scrolling over very large datasets, use a cursor and write an ADR.

## Errors — RFC 9457

```json
{
  "type": "https://api.example.com/errors/validation-failed",
  "title": "Validation failed",
  "status": 422,
  "detail": "Vendor tax ID is already registered to PT ABC",
  "instance": "/api/v1/masterdata/vendors",
  "code": "VENDOR_tax ID_DUPLICATE",
  "traceId": "b7c3f1a9e2d4",
  "errors": [{ "field": "taxId", "message": "already registered" }]
}
```

Built **once** in the global `ExceptionMapper`. Resources never construct error responses
by hand.

Adding a new error means adding an `ErrorCode` value, not writing a new response.

| Field | For |
|---|---|
| `code` | Frontend logic. Stable forever. |
| `detail` | Humans. May change. |
| `traceId` | What a user quotes when reporting. Always present. |

Never leak stack traces, table names, or SQL. Technical detail goes to the log under the
same `traceId`.

## Data types

| Type | Format | Example |
|---|---|---|
| Timestamp | ISO-8601 UTC | `2026-09-12T07:15:00Z` |
| Date | ISO-8601 | `2026-09-12` |
| **Money** | **decimal string** | `"1250000.00"` |
| Enum | `UPPER_SNAKE` | `CONSTRUCTION_SERVICES` |

Money as a JSON number passes through JavaScript's `double` and loses precision. In a system
holding contract values and reserve price, rounding that surfaces in a report is a defect, not an
inconvenience. String in JSON, `BigDecimal` in Java.

## OpenAPI

Every public endpoint requires `@Operation`, `@APIResponse` (success plus likely errors),
and `@Tag`.

```bash
./mvnw quarkus:dev
curl -s localhost:8080/q/openapi > docs/openapi/api-v1.yaml
git add docs/openapi/api-v1.yaml
```

The spec is committed so its diff shows up in review. CI fails when the committed spec
differs from the generated one — that is what stops a contract change slipping through
unnoticed.

## Breaking changes

**Breaking** (needs `/v2` plus deprecation):
- Removing or renaming a response field
- Adding a required request field
- Changing a field type or an existing enum value
- Changing the status code for the same condition
- Tightening validation on an existing field

**Not breaking:**
- A new optional response field
- A new endpoint
- A new enum value (clients must tolerate unknown ones)
- A new optional query parameter

When unsure: imagine an old client that has not changed. Does it still work? Then it is not
breaking.

## Checklist

- [ ] Path: `/api/v1/<module>/<plural-kebab-case-resource>`
- [ ] No verbs in the path
- [ ] Method and status match the tables above
- [ ] Collections paginated with `PageResponse`
- [ ] `size` capped server-side
- [ ] Request and response are `record`s, not entities
- [ ] Bean Validation on all input
- [ ] Errors via the global mapper with a stable `ErrorCode`
- [ ] Money as a string, timestamps UTC ISO-8601
- [ ] `@Operation`, `@APIResponse`, `@Tag` complete
- [ ] Spec regenerated and committed
- [ ] If breaking: ADR plus a `/v2` plan
