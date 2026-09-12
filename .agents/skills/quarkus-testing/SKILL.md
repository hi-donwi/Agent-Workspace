---
name: quarkus-testing
pack: java
description: >-
  Write tests for a Quarkus backend: fast unit tests without @QuarkusTest, integration tests
  with @QuarkusTest and Testcontainers PostgreSQL (not H2), RestAssured, authorisation tests,
  architecture tests, fixtures, JaCoCo coverage gates, and k6 load tests. Use when adding an
  endpoint or business rule, fixing a bug (failing test first), dealing with slow or flaky
  tests, setting up Testcontainers, or when coverage is below the gate. Do not use for
  diagnosing production issues (quarkus-observability) or non-test performance tuning
  (bulk-reporting-export).
keywords: test, testing, junit, mock, testcontainer, coverage, jacoco, assertion, restassured, flaky, fixture, quarkustest, integration test, unit test
---

# Quarkus Testing

Full rules: `.agents/standards/java/testing.md`. This is how to write them.

With 145 endpoints and two developers in parallel, tests are the only way to know module A
still works after module B changed.

## Use when
- Adding an endpoint or business rule
- Fixing a bug — write the failing test first
- Tests are slow, flaky, or red for no clear reason
- Coverage is below the gate

---

## Pick the right level

```
Business rules, mappers, validators   -> unit, no @QuarkusTest        (< 10 ms)
Endpoints, serialisation, real DB     -> @QuarkusTest + Testcontainers (seconds)
Contract has not silently changed     -> OpenAPI spec diff in CI
Throughput and latency                -> k6, nightly
```

Default to unit tests. `@QuarkusTest` boots the whole CDI container — to test one service
method that is 100× slower for no added benefit.

## Unit tests

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

    @Test
    void savesVendorWithUniqueNpwp() { ... }
}
```

This is the second reason for rejecting Panache active record: a static
`Vendor.findByNpwp(...)` cannot be mocked without PowerMock. Constructor injection makes
services testable in milliseconds.

**Test names describe behaviour**, not the method: `rejectsAlreadyRegisteredNpwp`, not
`testCreate2`. The test name is what someone reads when CI goes red.

## Integration tests

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
            .post("/api/v1/masterdata/vendors")
        .then()
            .statusCode(201)
            .header("Location", matchesPattern(".*/api/v1/masterdata/vendors/\\d+"))
            .body("name", equalTo("PT XYZ"));
    }

    @Test
    void duplicateNpwpReturns422WithStableCode() {
        // ...
        .then().statusCode(422).body("code", equalTo("VENDOR_tax ID_DUPLICATE"));
    }
}
```

`*IT` classes run under Failsafe (`./mvnw verify`); `*Test` under Surefire (`./mvnw test`).

### Real PostgreSQL, not H2

```properties
%test.quarkus.datasource.db-kind=postgresql
# Dev Services starts the container automatically — do not set jdbc.url in the test profile
```

H2 differs from PostgreSQL exactly where it matters here: `NUMERIC` precision, date
functions, `TIMESTAMPTZ`, window functions for reporting, and `CREATE INDEX CONCURRENTLY`. A
test that passes on H2 and fails in production is worse than no test — it grants false
confidence.

Containers are shared across the run via `QuarkusTestResourceLifecycleManager`, not started
per class.

## Tests that must exist

| Change | Test |
|---|---|
| New endpoint | Integration: success, 400, 401/403, 404 |
| Business rule | Unit: happy path **and every rejection** |
| Bug fix | A test that **fails before the fix** |
| Migration | Run against a populated dump |
| Authorisation change | The wrong role is rejected |

### Bug fixes: red first

Write the test, run it, **confirm it is red**, then fix. If the test cannot be made red, the
bug is not yet understood — and what you "fixed" may not be the cause.

### Authorisation tests are not optional

```java
@Test
void vendorCannotViewHps() {
    given().auth().oauth2(vendorToken())
    .when().get("/api/v1/orders/{id}/reserve-price", id)
    .then().statusCode(403);
}
```

The rule "a vendor must not see the reserve price before opening" is only real if a test goes red when
someone loosens it.

## What does not need tests

Testing time is finite.

- Getters/setters, `record` accessors
- The framework itself (that Panache can persist)
- Trivial mappers with no logic
- Configuration without branching

## Fixtures

```java
public final class VendorFixture {
    public static Vendor active(String name) { ... }
    public static CreateVendorRequest request() { ... }
}
```

In `src/test/java/.../fixture/`. Not copy-pasted literals across 40 tests — when a new
required field appears, those 40 tests have to be edited one at a time.

Test data uses obviously fictional names: `PT Example One`, tax ID `000000000000000`.
**Never** a production dump or real client data.

## Coverage

```bash
./mvnw verify                 # unit + integration + JaCoCo gate
open target/site/jacoco/index.html
```

Thresholds: services ≥ 80 %, endpoints ≥ 60 %. Below that the build fails.

**Coverage is a floor, not a goal.** 80 % reached with `assertNotNull` is worth nothing. If
coverage is short, add tests for untested behaviour — do not add tests that call the code
without checking the result.

## Flaky tests

| Symptom | Cause | Fix |
|---|---|---|
| Red when order changes | Shared state | Build data in `@BeforeEach` |
| Intermittently red | `Thread.sleep`, time dependence | Await on a condition, inject a `Clock` |
| Red in CI, green locally | Timezone, locale, Docker | Pin `TZ=UTC` and locale in test config |
| Slow | `@QuarkusTest` for pure logic | Drop it to a unit test |

## Commands

```bash
./mvnw test                # unit, fast
./mvnw verify              # everything + coverage gate
./mvnw quarkus:test        # continuous testing during development
./mvnw test -Dtest=VendorServiceTest
```
