# Testing & Quality Gates

With many endpoints and more than one developer working in parallel, tests are not
ceremony — they are the only way to know module A still works after module B changed.

---

## The pyramid

| Level | Scope | Speed | Target |
|---|---|---|---|
| **Unit** | Services, mappers, validators — no Quarkus | < 1 s total | **≥ 80 %** of `service/` |
| **Integration** | Endpoint + real DB via Testcontainers | seconds | **≥ 60 %** of endpoints |
| **Contract** | The OpenAPI spec has not changed accidentally | instant | 100 % of endpoints |
| **Load** | k6, nightly | minutes | Critical endpoints |

Gates are enforced by JaCoCo during `./mvnw verify`. Below the threshold the build fails —
it is not a warning.

**Coverage is a floor, not a goal.** 80 % reached with `assertNotNull` is worth nothing.
What gets tested is behaviour and edge cases, not lines.

---

## Unit tests — no `@QuarkusTest`

`@QuarkusTest` boots the whole CDI container. To test one service method, that is 100×
slower for no benefit.

```java
class VendorServiceTest {

    private final VendorRepository repo = mock(VendorRepository.class);
    private final VendorService service = new VendorService(repo);

    @Test
    void rejectsAlreadyRegisteredNpwp() {
        when(repo.findByNpwp("012345678901234"))
                .thenReturn(Optional.of(new Vendor("PT ABC")));

        var request = new CreateVendorRequest("PT XYZ", "012345678901234", COMPANY);

        assertThatThrownBy(() -> service.create(request))
                .isInstanceOf(ValidationException.class)
                .extracting("code").isEqualTo(ErrorCode.VENDOR_tax ID_DUPLICATE);
    }
}
```

This is the second reason for rejecting Panache active record: a static
`Vendor.findByNpwp(...)` cannot be mocked without PowerMock. Constructor injection makes
services testable in milliseconds.

**Test names describe behaviour**, not the method under test: `rejectsAlreadyRegisteredNpwp`,
not `testCreate2`. The test name is what someone reads when CI goes red.

---

## Integration tests — Testcontainers, not H2

```java
@QuarkusTest
class VendorResourceIT {

    @Test
    void createReturns201WithLocation() {
        given()
            .contentType(JSON)
            .auth().oauth2(committeeToken())
            .body("""
                  {"name":"PT XYZ","taxId":"012345678901234","type":"COMPANY"}
                  """)
        .when()
            .post("/api/v1/catalog/vendors")
        .then()
            .statusCode(201)
            .header("Location", matchesPattern(".*/api/v1/catalog/vendors/\\d+"))
            .body("name", equalTo("PT XYZ"));
    }
}
```

**H2 is not used for tests that matter.** The demo used it for speed, but H2 differs from
PostgreSQL precisely where it counts here: `NUMERIC` precision, date functions,
`TIMESTAMPTZ`, window functions for reporting, and `CREATE INDEX CONCURRENTLY` behaviour. A
test that passes on H2 and then fails in production is worse than no test — it grants false
confidence.

Quarkus Dev Services starts PostgreSQL automatically when Docker is available; no manual
configuration is needed.

```properties
%test.quarkus.datasource.db-kind=postgresql
# Dev Services starts the container; do not set jdbc.url in the test profile
```

Containers are shared across the whole test run via `QuarkusTestResourceLifecycleManager`,
not started per class.

---

## What must have tests

These changes do not pass review without tests:

- New endpoint → integration tests: success, 400, 401/403, 404
- New business rule → unit tests for the happy path **and every rejection**
- Bug fix → a test that **fails before the fix**. If you cannot make it fail, the bug is
  not yet understood.
- Flyway migration → run against a populated dump
- Authorisation change → a test proving the wrong role is rejected

### Authorisation tests are not optional

```java
@Test
void supplierCannotViewListPrice() {
    given().auth().oauth2(supplierToken())
    .when().get("/api/v1/orders/{id}/list-price", orderId)
    .then().statusCode(403);
}
```

Plus one architecture test that keeps the closed-by-default rule honest:

```java
@Test
void everyEndpointDeclaresARole() {
    // reflection: every method annotated @GET/@POST/... must carry
    // an explicit @RolesAllowed or @PermitAll
}
```

---

## What does not need tests

Testing time is finite; spend it in the right place.

- Getters/setters, `record` accessors
- The framework itself (that Panache can persist)
- Trivial mappers with no logic
- Configuration without branching

## Test data

- `@BeforeEach` builds the data that test needs; never depend on execution order.
- Builders/fixtures live in `src/test/java/.../fixture/`, not copy-pasted literals across
  40 tests.
- No test depends on production data or a client dump.
- Test data uses obviously fictional names: `PT Example One`, tax ID `000000000000000`.

## Load tests

`k6` scripts in `tools/k6/`, run nightly in CI.

| Scenario | Target |
|---|---|
| Master data grid, 100 VU | p95 < 500 ms |
| Dashboard aggregates, 50 VU | p95 < 800 ms |
| Export 100k-row report | < 60 s, stable memory |

The baseline is captured during Stage 4 (Server Setup) so that a Stage 5 regression shows
up as a number rather than a feeling.

## Commands

```bash
./mvnw test                    # unit only, fast
./mvnw verify                  # unit + integration + coverage gate
./mvnw verify -Pit             # integration only
./mvnw quarkus:test            # continuous testing during development
```
