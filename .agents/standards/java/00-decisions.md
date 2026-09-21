# Locked Decisions

Decided once, applies to every backend project in this workspace. Changing one requires an ADR.

`[PENDING CLIENT]` = workspace default, awaiting client confirmation at kick-off.

---

## Platform

| Item | Decision | Reason |
|---|---|---|
| Language | **Java 21 (LTS)** | Records, pattern matching, virtual threads. Fully supported by Quarkus. |
| Framework | **Quarkus 3.33.x (LTS)** | See the version note below. |
| Build | **Maven + Maven Wrapper (`./mvnw`)** | Wrapper is mandatory: reproducible builds without a local Maven install. |
| Database | **PostgreSQL 16+** | Matches the reference implementation and most clients. |
| Migrations | **Flyway**, forward-only | An auditable schema history. |
| Runtime | **JVM mode** (not native) | Native adds 5–15 minutes of build time and reflection complexity. No cold-start requirement exists. |

### Quarkus version note (verified 2026-09-12)

Use **the LTS, not the newest release**.

| Line | Version | LTS | EOL |
|---|---|---|---|
| **3.33** | **3.33.3.2** | **Yes** | **2027-03-25** ← **use this** |
| 3.39 | 3.39.3 | No | ~1 month (when 3.40 ships) |
| 3.27 | 3.27.5.2 | Yes | 2026-09-24 (nearly expired) |

Quarkus ships an LTS every six months with one year of support; non-LTS releases appear
every 4–6 weeks and **stop being supported as soon as the next minor ships** — about a
month in practice. For a system that will be maintained for a year after go-live, non-LTS
means a forced minor upgrade every month for the life of the project. 3.33 LTS carries
security patches through March 2027.

"Latest Quarkus" in a client-delivery context means **the latest LTS**, not the highest
version number.

Pin it in the parent POM `<properties>`:

```xml
<quarkus.platform.version>3.33.3.2</quarkus.platform.version>
```

Check for a newer micro before kick-off:
`./mvnw versions:display-property-updates -Dincludes=io.quarkus*`

---

## Namespace

```
com.example.product.<module>
```

`[PENDING CLIENT]` — reverse domain of `example.com`. **Do not** carry `com.demo.tender`
over from the demo: changing the namespace after the codebase has grown is a cross-repo
refactor touching every file, every import, and every configuration key.

**This is the number one kick-off question.** Until the answer arrives, all code is written
with the namespace above.

Maven coordinates: `groupId=com.example.product`, `artifactId=<product>-<module>`.

---

## Supporting stack

| Need | Decision | Note |
|---|---|---|
| Session store | **Redis** | `[PENDING CLIENT]` Mandatory once there is more than one instance. An in-memory `ConcurrentHashMap` must not reach production. |
| Password hashing | **Argon2id** | OWASP recommendation. The demo's PBKDF2 is not carried forward. |
| SPA auth | **Session cookie** `HttpOnly; Secure; SameSite=Lax` | `[PENDING CLIENT]` JWT only if a non-browser client appears. |
| Object storage | **S3-compatible (MinIO)** | Keep the demo's `ObjectStorage` abstraction. |
| Inter-service calls | **Synchronous REST client** + in-process async jobs | `[PENDING CLIENT]` A message queue only if throughput or retry semantics demand it; do not add Kafka without measured justification. |
| Observability | **Micrometer/Prometheus + OpenTelemetry** | `[PENDING CLIENT]` Connect to the client's existing stack if there is one. |
| Logging | **Structured JSON** + correlation ID in MDC | Plain console output is dev-only. |
| API versioning | **URL prefix `/api/v1/`** | From the first endpoint. Adding a version after release is itself a breaking change. |
| Error format | **RFC 9457 Problem Details** | `application/problem+json`. |
| OpenAPI contract | **Code-first** (`quarkus-smallrye-openapi`), spec committed | `[PENDING CLIENT]` The generated spec is committed so the frontend can work in parallel and contract diffs show up in review. |

---

## Deliberately not used

Rejected on purpose. Adding any of these requires an ADR.

| Item | Why not |
|---|---|
| Lombok | Java 21 records plus IDE generation cover the need. Lombok is an annotation processor that routinely breaks on JDK/Quarkus upgrades. |
| Panache active record (`PanacheEntity`) | Static methods make mocking hard and mix persistence into the domain model. Use `PanacheRepository`. |
| Entities as JSON responses | Leaks internal columns and couples the HTTP contract to the database schema. Use `record` DTOs. |
| Manual `@Singleton` | Use `@ApplicationScoped` and let Arc manage it. |
| Native image | Build cost and reflection debugging are not worth it without a cold-start requirement. |
| `hibernate-orm.database.generation=update` / `drop-and-create` | Flyway is the only thing that changes the schema. Always `none`. |
| Kafka / RabbitMQ | No load yet demands it. Do not add infrastructure DevOps must operate without supporting numbers. |

---

## Non-functional budgets

Targets that get tested, not aspirations. Missing one is a bug.

| Metric | Target |
|---|---|
| p95 read endpoints (grid, dashboard) | < 500 ms |
| p95 write endpoints | < 800 ms |
| Synchronous export | < 10 s, otherwise make it an async job |
| Heap per instance | < 1 GB under normal load |
| Unpaginated response size | None. Every list endpoint paginates. |
| Unit coverage (service packages) | ≥ 80 % |
| Integration coverage (endpoints) | ≥ 60 % |
| Dependency CVEs | No CVSS ≥ 7 at release |
