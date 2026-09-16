# REST API Contract

A large API is only usable by a frontend if every endpoint's shape is predictable. This
standard makes the last endpoint behave like the first.

---

## URLs

```
/api/v1/<module>/<resource>[/<id>][/<sub-resource>]
```

- Version in the URL from day one: `/api/v1/`.
- Module matches the package: `catalog`, `orders`, `billing`, `reporting`, …
- Resources are **plural, kebab-case**: `/order-types`, `/price-lists`.
- No verbs in paths. Actions are expressed by the HTTP method.
- Non-CRUD actions become sub-resources: `POST /orders/{id}/submission`, not
  `POST /submitOrder`.

```
RIGHT  GET    /api/v1/catalog/vendors?q=abc&page=0&size=50
RIGHT  POST   /api/v1/catalog/vendors
RIGHT  GET    /api/v1/catalog/vendors/{id}
RIGHT  PUT    /api/v1/catalog/vendors/{id}
RIGHT  DELETE /api/v1/catalog/vendors/{id}
RIGHT  POST   /api/v1/reporting/transaction-summary/export

WRONG  GET    /api/v1/getVendorList
WRONG  POST   /api/v1/vendor/delete/{id}
WRONG  GET    /api/vendors                 (no version, no module)
```

## Methods and status codes

| Method | Success | Notes |
|---|---|---|
| `GET` (collection) | 200 | Always paginated. Empty is 200 with an empty list, **not** 404. |
| `GET` (single) | 200 / 404 | |
| `POST` (create) | 201 + `Location` header | Body is the created resource. |
| `POST` (action) | 200 / 202 | 202 when processed asynchronously (a job). |
| `PUT` | 200 | Full replacement. Idempotent. |
| `PATCH` | 200 | Partial. Only where genuinely needed. |
| `DELETE` | 204 | Idempotent: deleting something already gone is still 204. |

Error codes: 400 malformed · 401 not authenticated · 403 not authorised · 404 not found ·
409 state conflict · 422 well-formed but breaks a business rule · 429 rate limited ·
500 our bug.

**401 vs 403:** 401 means we do not know who you are. 403 means we do, and the answer is
no.

## Pagination

One shape for every collection. No exceptions.

Request: `?page=0&size=50&sort=name,asc`

- `page` is 0-based, default 0.
- `size` defaults to 50, **maximum 200** — enforced by the server, never trusted from the
  client.
- `sort` is `<field>,<asc|desc>`, validated against an allowlist (see `security.md`).

Response:

```json
{
  "content": [ { "id": 1, "name": "PT ABC" } ],
  "page": 0,
  "size": 50,
  "totalElements": 1284,
  "totalPages": 26,
  "sort": "name,asc"
}
```

`PageRequest` and `PageResponse<T>` live in `app-common`. **Do not invent a per-module
pagination shape** — that is what makes a frontend write seven adapters.

For datasets above ~100,000 rows scrolled sequentially, use a cursor
(`?after=<opaque>&size=50`) and record it in an ADR. Offset paging on a large table makes
the database rescan from the beginning on every page.

## Filtering

- Single field: `?type=GOODS&active=true`
- Free-text search: `?q=abc`
- Date range: `?from=2026-01-01&to=2026-03-31` (inclusive, ISO-8601)
- Multi-value: `?status=DRAFT&status=SUBMITTED`

Parameter names are consistent across modules: never `from`/`startDate` in two different
endpoints for the same concept.

## Error format — RFC 9457

Every error, without exception, returns `application/problem+json`:

```json
{
  "type": "https://api.example.com/errors/validation-failed",
  "title": "Validation failed",
  "status": 422,
  "detail": "Vendor tax ID is already registered to PT ABC",
  "instance": "/api/v1/catalog/vendors",
  "code": "VENDOR_tax ID_DUPLICATE",
  "traceId": "b7c3f1a9e2d4",
  "errors": [
    { "field": "taxId", "message": "already registered" }
  ]
}
```

| Field | Rule |
|---|---|
| `code` | **Stable, enumerated, never changes.** This is what the frontend branches on, not `title`. |
| `detail` | For humans. May change, may be translated. |
| `traceId` | Always present. This is what a user quotes when reporting a problem. |
| `errors` | Only for per-field validation errors. |

Implemented **once** in a global `ExceptionMapper` in `app-common`. Resources never build
error responses by hand.

**Never** leak stack traces, table names, or SQL to a client. Technical detail goes to the
log under the same `traceId`.

## Validation

Bean Validation at the HTTP boundary, `@Valid` on bodies and `@BeanParam`.

```java
public record CreateVendorRequest(
        @NotBlank @Size(max = 200) String name,
        @NotBlank @Pattern(regexp = "\\d{15,16}") String taxId,
        @NotNull VendorType type) {}
```

Business rules (duplicates, state, authority) are **not** bean validation — they live in
the service and raise `ValidationException` → 422.

## Dates, numbers, enums

| Type | Format | Example |
|---|---|---|
| Timestamp | ISO-8601 UTC | `2026-09-12T07:15:00Z` |
| Date | ISO-8601 | `2026-09-12` |
| Money | **decimal string**, not a float | `"1250000.00"` |
| Enum | `UPPER_SNAKE`, stable | `GOODS`, `CONSTRUCTION_SERVICES` |

**Money is never sent as a JSON number.** A `double` cannot represent rupiah amounts
exactly, and rounding that shows up in a financial report is a defect, not an
inconvenience. `BigDecimal` in Java, string in JSON.

Timestamps are stored and transmitted in UTC. Converting to WIB is a presentation concern.

Adding an enum value is compatible. Changing or removing one is a breaking change
requiring `/v2`.

## OpenAPI

Code-first. Every public endpoint requires:

```java
@Operation(summary = "Search registered vendors",
           description = "Paginated; `q` matches name and tax ID.")
@APIResponse(responseCode = "200", description = "A page of vendors")
@APIResponse(responseCode = "403", description = "Not permitted to view master data")
@Tag(name = "Master Data")
```

The generated spec is committed to `docs/openapi/api-v1.yaml`. Its diff is what makes a
breaking change visible in review — rather than after the frontend breaks.

```bash
./mvnw quarkus:dev
curl -s localhost:8080/q/openapi > docs/openapi/api-v1.yaml
```

CI fails if the committed spec differs from the generated one.

## What counts as a breaking change

Requires `/api/v2` and a deprecation period:

- Removing or renaming a response field
- Adding a required request field
- Changing a field type, or an existing enum value
- Changing the status code for the same condition
- Tightening validation on an existing field

**Not** breaking: adding an optional response field, adding an endpoint, adding a new enum
value, adding an optional query parameter.
