---
name: quarkus-service
pack: java
description: >-
  Build or change Quarkus services and endpoints: Maven module structure, resource/service/
  repository layering, CDI and scopes, typed configuration, REST clients between services,
  and lifting demo-grade code to production standard. Use when adding a new endpoint,
  creating a new Quarkus module, untangling code that mixes layers, moving configuration to
  @ConfigMapping, or calling another service over REST. Do not use for HTTP contract shape
  (rest-api-contract), queries and migrations (quarkus-persistence), auth
  (quarkus-security), tests (quarkus-testing), or large exports (bulk-reporting-export).
keywords: endpoint, resource, service layer, module, cdi, inject, scope, configmapping, config, rest client, scaffold, quarkus, layering, arc, virtual thread
---

# Quarkus Service

The parent skill for day-to-day backend work. The binding rules live in
`.agents/standards/java/project-layout.md` and `00-decisions.md`; this is the workflow.

## Use when
- Adding an endpoint to an existing module
- Creating a new Quarkus module
- Cleaning up code that mixes layers
- Moving scattered configuration to typed config
- Calling another service

## Hand off when
| Need | Skill |
|---|---|
| URL shape, status codes, error format | `rest-api-contract` |
| Entities, queries, migrations, transactions | `quarkus-persistence` |
| Roles, sessions, security validation | `quarkus-security` |
| Writing tests | `quarkus-testing` |
| Logs, metrics, traces | `quarkus-observability` |
| Large exports/reports | `bulk-reporting-export` |
| Domain business rules | the organisation's domain skill in `context/skills/` |

---

## Workflow for a new endpoint

The order is deliberate: contract first, tests second, implementation last.

**1 — Settle the contract.** Path, method, request, response, errors, roles. If any of that
is unclear, do not start coding. Use `.agents/templates/endpoint-spec.md`.

**2 — Write failing tests.** An integration test for the HTTP shape, unit tests for the
business rules. They must fail because the endpoint does not exist yet — not because of a
typo.

**3 — DTOs.** `record`s in `dto/`, bean validation on the fields.

**4 — Repository**, if a new query is needed. A specific method, not `listAll()` filtered
in Java afterwards.

**5 — Service.** Business rules, the `@Transactional` boundary, domain exceptions.

**6 — Resource.** Thin: bind, delegate, return. Add the role and OpenAPI annotations.

**7 — Verify.** `./mvnw verify`, regenerate the OpenAPI spec, check the logs leak nothing.

## The correct shape

```java
@Path("/api/v1/masterdata/vendors")
@Produces(MediaType.APPLICATION_JSON)
@Consumes(MediaType.APPLICATION_JSON)
@Tag(name = "Master Data")
public class VendorResource {

    @Inject VendorService vendorService;

    @POST
    @RolesAllowed({"ADMIN", "COMMITTEE"})
    @Operation(summary = "Register a new vendor")
    @APIResponse(responseCode = "201", description = "Vendor created")
    @APIResponse(responseCode = "422", description = "tax ID already registered")
    public Response create(@Valid CreateVendorRequest request, @Context UriInfo uriInfo) {
        var created = vendorService.create(request);
        return Response.created(uriInfo.getAbsolutePathBuilder().path(String.valueOf(created.id())).build())
                .entity(created)
                .build();
    }
}
```

A resource does not contain: queries, business rules, `@Transactional`, or `try/catch`
blocks turning exceptions into status codes (that is the global `ExceptionMapper`'s job).

## CDI and scopes

| Scope | For |
|---|---|
| `@ApplicationScoped` | Default for services, repositories, clients — stateless |
| `@RequestScoped` | Only when genuinely per-request (user identity, request context) |
| `@Singleton` | **Don't.** Use `@ApplicationScoped`. |

Use constructor injection for classes that need testing without CDI; field injection
(`@Inject`) is fine in resources.

```java
@ApplicationScoped
public class VendorService {
    private final VendorRepository vendors;

    @Inject
    public VendorService(VendorRepository vendors) {   // can be `new`ed in a unit test
        this.vendors = vendors;
    }
}
```

**An `@ApplicationScoped` bean must not hold mutable state.** One instance serves all
concurrent requests; a mutable field is a race condition that only appears under load —
usually during UAT or in production.

## Configuration

Typed, not `@ConfigProperty` scattered around:

```java
@ConfigMapping(prefix = "app.export")
public interface ExportConfig {
    @WithDefault("5000") int batchSize();
    @WithDefault("PT10M") Duration jobTimeout();
    Path spoolDir();
}
```

The benefit is concrete: missing configuration fails at **startup** rather than the first
time the endpoint is called in production.

Secrets always come from the environment: `quarkus.datasource.password=${DB_PASSWORD}`.

## REST clients between services

```java
@RegisterRestClient(configKey = "export-service")
@Path("/api/v1/export")
public interface ExportClient {
    @POST Response submit(ExportRequest request);
}
```

```properties
quarkus.rest-client.export-service.url=${EXPORT_SERVICE_URL}
quarkus.rest-client.export-service.connect-timeout=5000
quarkus.rest-client.export-service.read-timeout=30000
```

**Timeouts must be explicit.** An unbounded default means one slow service exhausts its
caller's thread pool until the caller dies too.

Add fault tolerance where a call is allowed to fail:

```java
@Retry(maxRetries = 2, delay = 500)
@Timeout(value = 30, unit = ChronoUnit.SECONDS)
@Fallback(fallbackMethod = "markPending")
Response submit(ExportRequest request);
```

Retry only **idempotent** operations. Retrying a `POST` that creates data produces
duplicates.

## Virtual threads

Java 21 provides virtual threads, but this is not a "go faster" switch.

- Apply `@RunOnVirtualThread` **per endpoint** where the work is I/O-bound (many JDBC/HTTP
  calls).
- **Do not** enable it globally.
- Do not use `synchronized` around a blocking call inside one — the carrier thread gets
  pinned and the benefit disappears. Use `ReentrantLock`.
- It does not help CPU-bound work (PDF generation, in-memory aggregation).

## Lifting demo code to production

The gap between `.local/demo` and the standards:

| Demo | Production |
|---|---|
| `com.demo.tender` | `com.example.product` |
| Entities returned as JSON | `record` DTOs |
| Queries in resources | Repositories |
| `PanacheEntityBase` active record | `PanacheRepository` |
| `cors.origins=*` | Per-environment allowlist |
| Password in `application.properties` | `${ENV_VAR}` |
| `ConcurrentHashMap` sessions | Redis |
| PBKDF2 | Argon2id |
| No API version | `/api/v1/` |
| Raw string errors | RFC 9457 problem+json |
| H2 for tests | Testcontainers PostgreSQL |
| No correlation ID | MDC `requestId` |

The demo is a proof of concept that worked, not a foundation. Copying its patterns into 145
endpoints multiplies every gap in that table 145 times.

## Pitfalls

- **`@Transactional` on a resource** — wraps JSON serialisation, holds the DB connection.
- **Entities as responses** — leaks internal columns, couples HTTP to the schema.
- **`Optional` as an entity field** — not serialisable, not its purpose.
- **Blocking calls on a reactive endpoint** — blocks the event loop; the whole instance
  stops serving. When in doubt, use imperative style (not `Uni`/`Multi`).
- **`@ApplicationScoped` with mutable fields** — a race condition under load.
- **Guessing Quarkus APIs** — the version moves fast. Verify against `quarkus.io/guides`
  for 3.33 instead of relying on recall.
