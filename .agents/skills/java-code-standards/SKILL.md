---
name: java-code-standards
pack: java
description: >-
  Write and review Java 21 to the standards in this workspace: records and immutability, null and Optional
  handling, a domain exception hierarchy carrying stable ErrorCodes, logging, pattern
  matching and text blocks, naming, and method/class size limits. Use when writing a new
  Java class, reviewing a Java diff, cleaning up hard-to-read code, deciding on an exception
  shape or return type, or enforcing Spotless formatting. Do not use for endpoint shape
  (rest-api-contract), queries and entities (quarkus-persistence), or module structure and
  CDI (quarkus-service).
keywords: java, code style, record, exception, errorcode, null, optional, naming, refactor, readability, lombok, bigdecimal, spotless, switch, text block
---

# Java 21 Code Standards

Full rules: `.agents/standards/java/java-code-style.md`. This covers the decisions that come up
while writing.

## Use when
- Writing a new Java class
- Reviewing a Java diff
- Deciding: `Optional` or exception? Record or class? Checked or unchecked?
- Cleaning up code that is hard to read

## Formatting is machine-enforced

```bash
./mvnw spotless:apply     # before committing
```

Do not argue about formatting in review. Spotless has already decided.

---

## Recurring decisions

### Record or class?

**Record** for anything carrying data without identity: DTOs, parameter objects, return
values, events. This is the default.

**Class** only when mutable identity is required (a JPA entity) or the behaviour does not
fit a record.

```java
public record CreateVendorRequest(
        @NotBlank @Size(max = 200) String name,
        @NotBlank @Pattern(regexp = "\\d{15,16}") String taxId,
        @NotNull VendorType type) {}
```

A record may use a compact constructor for normalisation — but business validation stays in
the service:

```java
public record PageRequest(int page, int size, String sortField, String sortDir) {
    public PageRequest {
        if (page < 0) page = 0;
        size = Math.clamp(size, 1, 200);      // server-enforced cap
    }
}
```

### `Optional` or an exception?

| Situation | Use |
|---|---|
| "Look it up, it may not exist" — an ordinary outcome | `Optional<T>` |
| "Fetch by an ID that should exist" — absence is wrong | `throw NotFoundException` |
| An empty collection | `List.of()` — **never** `null` |

`Optional` is a **return type** only. Not a field, not a parameter.

```java
public Optional<Vendor> findByNpwp(String taxId) { ... }        // right
public Vendor getById(Long id) { ... }                          // right, throws if absent
public void update(Long id, Optional<String> name) { ... }      // wrong
```

### Which exception?

Three, all extending `AppException`, all carrying an `ErrorCode`:

```java
throw new NotFoundException(ErrorCode.VENDOR_NOT_FOUND, "vendor id=" + id);
throw new ValidationException(ErrorCode.VENDOR_tax ID_DUPLICATE, "taxId=" + taxId);
throw new ConflictException(ErrorCode.ORDER_ALREADY_APPROVED, "id=" + id);
```

`ErrorCode` is an enum that is **stable forever** — the frontend branches on it. The message
may change; the code may not.

Exception messages target the **developer** and carry debugging context (IDs, values), but
never sensitive data (passwords, reserve price, document contents).

---

## Expected patterns

### Early returns, not nesting

```java
// WRONG — four levels deep
public void process(Order p) {
    if (p != null) {
        if (p.status == DRAFT) {
            if (p.amount != null) {
                if (p.amount.compareTo(BigDecimal.ZERO) > 0) {
                    send(p);
                }
            }
        }
    }
}

// RIGHT — flat, every rejection states its reason
public void process(Order p) {
    Objects.requireNonNull(p, "order");
    if (p.status != DRAFT) {
        throw new ConflictException(ErrorCode.ORDER_NOT_DRAFT, "id=" + p.id);
    }
    if (p.amount == null || p.amount.signum() <= 0) {
        throw new ValidationException(ErrorCode.AMOUNT_INVALID, "id=" + p.id);
    }
    send(p);
}
```

### Pattern-matching switch for state

```java
String label = switch (status) {
    case DRAFT               -> "Draft";
    case SUBMITTED           -> "Awaiting approval";
    case APPROVED            -> "Approved";
    case REJECTED, CANCELLED -> "Not proceeding";
};
```

A switch over an enum without `default` makes the compiler flag any newly added enum
constant that is not handled. **Do not add a `default`** just to satisfy the compiler —
that throws away the safety net.

### Text blocks for SQL

```java
private static final String SQL_SUMMARY = """
        SELECT order_type, COUNT(*) AS total, SUM(amount) AS amount
        FROM order
        WHERE transaction_date BETWEEN ?1 AND ?2
          AND deleted_at IS NULL
        GROUP BY order_type
        """;
```

### Money

**`BigDecimal`, always.** Never `double` or `float`.

```java
BigDecimal total = price.multiply(BigDecimal.valueOf(quantity))
                        .setScale(2, RoundingMode.HALF_UP);

// compare with compareTo, not equals
if (amount.compareTo(BigDecimal.ZERO) > 0) { ... }
```

`equals` on `BigDecimal` takes scale into account: `new BigDecimal("1.0")` does not equal
`new BigDecimal("1.00")`. This is a comparison bug that is easy to miss in review.

### Logging

```java
private static final Logger log = Logger.getLogger(VendorService.class);

log.infof("vendor created id=%d taxId=%s", id, maskNpwp(taxId));
```

Parameterised, not concatenated. Never `System.out`. Never sensitive data.

---

## Naming

- Identifiers are English.
- The exception is Indonesian statutory order vocabulary with no precise English
  equivalent. That glossary lives in the organisation's domain skill under `context/skills/`.
- Do not abbreviate: `orderType`, not `procType`.
- Booleans read as assertions: `active`, `approved` — not `flag`, `status1`.

## Review triggers

| Item | Threshold | Usually means |
|---|---|---|
| Method length | > 40 lines | More than one responsibility |
| Parameters | > 4 | Needs a record parameter object |
| Class length | > 400 lines | Needs splitting |
| Nesting | > 3 | Needs early returns |
| "and" in a method name | — | It is two methods |

## Review checklist

- [ ] DTOs are `record`s with no setters
- [ ] No `null` returned for a collection
- [ ] `Optional` used only as a return type
- [ ] Domain exceptions with `ErrorCode`, not bare `RuntimeException`
- [ ] No empty `catch` or `printStackTrace`
- [ ] Money uses `BigDecimal`, compared with `compareTo`
- [ ] No `System.out`
- [ ] No sensitive data in logs or exception messages
- [ ] Every `TODO` carries a ticket ID
- [ ] `./mvnw spotless:check` passes
