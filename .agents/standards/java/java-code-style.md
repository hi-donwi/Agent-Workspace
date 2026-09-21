# Java 21 Code Style

Formatting is enforced by **Spotless (google-java-format AOSP, 4-space indent)** during
`./mvnw verify`. What a machine cannot enforce is below.

```bash
./mvnw spotless:apply     # fix formatting
./mvnw spotless:check     # runs in CI, fails on unformatted code
```

---

## Immutability first

- **DTOs are always `record`s.** No setters, no mutation.
- Fields are `final` unless they genuinely must change.
- Return `List.copyOf(...)` or immutable collections from getters.
- `var` is fine when the type is obvious from the right-hand side; not for ambiguous
  literals.

```java
public record VendorResponse(
        Long id,
        String name,
        String taxId,
        VendorType type,
        boolean active,
        Instant createdAt) {}
```

## Null

Null is a design decision, not an accident.

- **Never** return `null` for a collection — return `List.of()`.
- Use `Optional` as a **return type** only, never as a field or parameter.
- Parameters that must not be null are validated at the boundary (`@NotNull`,
  `Objects.requireNonNull`), not re-checked throughout.

```java
// RIGHT
public Optional<Vendor> findByNpwp(String taxId) { ... }

// WRONG — Optional as a parameter
public void update(Long id, Optional<String> name) { ... }
```

## Exceptions

Three kinds, no more:

| Kind | When | Maps to HTTP |
|---|---|---|
| `NotFoundException` (domain) | The requested resource does not exist | 404 |
| `ValidationException` (domain) | Input passes bean validation but breaks a business rule | 422 |
| `ConflictException` (domain) | State conflict (duplicate, already approved, …) | 409 |

All extend `AppException` in `app-common` and carry a **stable error code**.

```java
public class AppException extends RuntimeException {
    private final ErrorCode code;
    // ...
    public ErrorCode code() { return code; }
}
```

Rules:

- **Never swallow an exception.** An empty `catch (Exception e) {}` does not pass review.
- **Never rewrap without adding information.** `throw new RuntimeException(e)` erases
  context and adds nothing.
- **Do not use exceptions for normal flow.** "Not found" while searching is an ordinary
  outcome → `Optional`. "Not found" when fetching by an ID that should exist → exception.
- Exception messages are for **developers**; user-facing text comes from the `ErrorCode`.

```java
// WRONG
catch (SQLException e) { throw new RuntimeException(e); }

// RIGHT
catch (SQLException e) {
    throw new AppException(ErrorCode.DB_UNAVAILABLE,
            "failed to read vendor id=" + id, e);
}
```

## Logging

- `org.jboss.logging.Logger`, one per class, `private static final`.
- **Parameterised, not concatenated**: `log.infof("vendor %s created", id)`.
- **Never** `System.out.println`. Static analysis rejects it.
- Never log sensitive data: passwords, tokens, full tax ID, confidential prices.
- `debug` for flow detail, `info` for business events, `warn` for self-recovering
  conditions, `error` only for things a human must act on.

```java
private static final Logger log = Logger.getLogger(VendorService.class);
```

## Java 21 features we use

```java
// Pattern-matching switch for document state
String label = switch (status) {
    case DRAFT              -> "Draft";
    case SUBMITTED          -> "Awaiting approval";
    case APPROVED           -> "Approved";
    case REJECTED, CANCELLED -> "Not proceeding";
};

// Text blocks for queries
private static final String SQL_SUMMARY = """
        SELECT order_type, COUNT(*) AS total, SUM(amount) AS amount
        FROM order
        WHERE transaction_date BETWEEN ?1 AND ?2
        GROUP BY order_type
        """;
```

- **Sealed interfaces** for results with a closed set of branches.
- **Virtual threads** only on I/O-bound endpoints, annotated explicitly with
  `@RunOnVirtualThread` — never as a global flag. Do not combine them with `synchronized`
  around a blocking call (carrier pinning); use `ReentrantLock`.

## Naming

- Class `PascalCase`, method/field `camelCase`, constant `UPPER_SNAKE`.
- **Identifiers are English.** The exception is Indonesian statutory order vocabulary
  with no precise English equivalent — `reservePrice`, `taxInvoice`, `auction` — which stays as-is
  and is listed in the glossary in the organisation's domain skill under `context/skills/`.
- Do not abbreviate: `orderType`, not `procType`.
- Booleans read as assertions: `active`, `approved` — not `flag`, `status1`.

## Comments

- Explain **why**, not **what**. The code already says what.
- Javadoc is required on public `service/` methods carrying non-obvious business rules.
- Every `TODO` carries a ticket ID: `// TODO(PROJ-142): ...`. Without one it is rejected.

## Size limits

Not hard rules, but review triggers:

| Item | Threshold |
|---|---|
| Method length | > 40 lines → split |
| Method parameters | > 4 → use a record parameter object |
| Class length | > 400 lines → more than one responsibility |
| Nesting depth | > 3 → use early returns |
