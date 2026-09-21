# Project Layout & Layering

## Maven modules

```
app-backend/                      ← product repo (projects/<group>/<repo>)
├── mvnw, mvnw.cmd, .mvn/           ← wrapper, MUST be committed
├── pom.xml                         ← parent, packaging=pom, pins versions
├── app-common/                   ← shared DTOs, errors, utils, constants
├── app-api/                      ← main REST API (one Maven module per bounded context)
├── app-reporting/                ← reporting and export
└── docs/
    ├── openapi/api-v1.yaml       ← generated spec, COMMITTED
    └── adr/
```

Rules:

- **`app-common` must not depend on any other module.** If it needs to, the code is in
  the wrong place.
- Modules never import each other's internal classes. Cross-module traffic goes through
  DTOs in `common` or a REST client.
- Every module has a `README.md`: what it does, how to run it, its port, its required env.

## Package structure

```
com.example.product.<module>.
├── api/            *Resource        HTTP endpoints
├── service/        *Service         business rules, transaction boundaries
├── repository/     *Repository      queries (PanacheRepository)
├── entity/         *Entity          JPA @Entity
├── dto/            record *Request/*Response
├── mapper/         *Mapper          entity ↔ DTO (static, pure)
├── client/         *Client          external systems
└── config/         *Config          @ConfigMapping
```

Example domain modules (the real list comes from the project brief):

| Package | Owner |
|---|---|
| `catalog` | Backend Dev 1 |
| `orders` | Backend Dev 1 |
| `reporting` | Backend Dev 2 |

One package per bounded slice of the domain, one named owner each. Record the real list in
the project's `context/memory/projects/<key>/project.md`, not here — this table exists to
show the shape, and a module that no one owns is a module nobody maintains.

## Layering — checked at review

| Layer | May call | Must not touch |
|---|---|---|
| `api/` | `service/` | Repositories, entities, queries, `EntityManager` |
| `service/` | `repository/`, `client/`, other `service/` | `jakarta.ws.rs.*`, `HttpHeaders`, `Response` |
| `repository/` | `entity/` | Services, business rules, HTTP calls |
| `client/` | DTOs | Entities, repositories |
| `mapper/` | entities + DTOs | Anything stateful or CDI-managed |

### Why resources must not touch repositories

This is not ceremony. Three concrete consequences:

1. The same logic gets rewritten in every endpoint that needs it — with a large API,
   that is many places to get it wrong.
2. Transaction boundaries become unclear. `@Transactional` on a resource wraps JSON
   serialisation and holds a database connection longer than necessary.
3. The logic cannot be tested without starting HTTP. Tests become slow, then get skipped.

### Example

```java
// WRONG — query in the resource, entity leaking into JSON
@GET @Path("/vendor")
public List<Vendor> list(@QueryParam("q") String q) {
    return Vendor.find("name like ?1", "%" + q + "%").list();
}
```

```java
// RIGHT
@Path("/api/v1/catalog/vendors")
@Produces(MediaType.APPLICATION_JSON)
public class VendorResource {

    @Inject VendorService vendorService;

    @GET
    @Operation(summary = "Search registered vendors")
    public PageResponse<VendorResponse> list(@BeanParam @Valid PageRequest page,
                                             @QueryParam("q") String q) {
        return vendorService.search(q, page);
    }
}

@ApplicationScoped
public class VendorService {

    @Inject VendorRepository vendors;

    public PageResponse<VendorResponse> search(String q, PageRequest page) {
        var result = vendors.search(q, page);
        return PageResponse.of(result.map(VendorMapper::toResponse), page);
    }
}
```

## Configuration

- Typed config via `@ConfigMapping` — not `@ConfigProperty` scattered around.
- Profiles: `application.properties` (shared), `%dev.`, `%test.`, `%prod.`.
- **No secrets in `application.properties`.** Secrets come from environment variables; the
  properties file only names them.

```java
@ConfigMapping(prefix = "app.export")
public interface ExportConfig {
    @WithDefault("5000")  int batchSize();
    @WithDefault("PT10M") Duration jobTimeout();
    Path spoolDir();
}
```

```properties
# RIGHT — value from the environment, not in the file
quarkus.datasource.password=${DB_PASSWORD}

# WRONG
quarkus.datasource.password=changeme
```

## File naming

| Kind | Pattern | Example |
|---|---|---|
| Resource | `<Domain>Resource` | `VendorResource` |
| Service | `<Domain>Service` | `VendorService` |
| Repository | `<Entity>Repository` | `VendorRepository` |
| Entity | `<Domain>` (singular) | `Vendor` |
| Request DTO | `<Action><Domain>Request` | `CreateVendorRequest` |
| Response DTO | `<Domain>Response` | `VendorResponse` |
| Test | `<Class>Test` / `<Class>IT` | `VendorServiceTest`, `VendorResourceIT` |

One public class per file. File name equals class name.
