---
name: quarkus-persistence
pack: java
description: >-
  Work with data in Quarkus: JPA entities, PanacheRepository, forward-only Flyway migrations
  that are safe on populated tables, PostgreSQL schema conventions, audit columns, soft
  delete, transaction boundaries, avoiding N+1, indexing, and aggregate queries for reports.
  Use when creating or changing an entity, writing a migration, writing a query, fixing a
  slow request or N+1, deciding a transaction boundary, or designing a new table. Do not use
  for API response shape (rest-api-contract), large file exports (bulk-reporting-export), or
  domain business rules (the organisation domain skill under context/skills/).
keywords: entity, panache, repository, flyway, migration, query, transaction, index, n+1, database, sql, jpa, hibernate, schema, table, column, soft delete, audit column, postgres
---

# Quarkus Persistence

Full rules: `.agents/standards/java/database.md`. This is the workflow and the patterns.

## Use when
- Creating or changing an entity or table
- Writing a Flyway migration
- Writing or optimising a query
- A slow endpoint suspected of being a data problem
- Deciding where `@Transactional` goes

---

## Workflow for a new table

**1 — Migration first.** The schema is the source of truth; the entity follows it.

```sql
-- V20260912_1430__masterdata_vendor.sql
CREATE TABLE vendor (
    id          BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        VARCHAR(200) NOT NULL,
    taxId        VARCHAR(16)  NOT NULL,
    type        VARCHAR(30)  NOT NULL,
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    deleted_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by  VARCHAR(100) NOT NULL,
    updated_at  TIMESTAMPTZ,
    updated_by  VARCHAR(100),
    CONSTRAINT ck_vendor_type CHECK (type IN ('INDIVIDUAL','COMPANY','COOPERATIVE'))
);

CREATE UNIQUE INDEX uq_vendor_taxId_live ON vendor (taxId) WHERE deleted_at IS NULL;
CREATE INDEX ix_vendor_name ON vendor (lower(name));
```

**2 — Entity.** It mirrors the table; it does not create it.

```java
@Entity
@Table(name = "vendor")
public class Vendor extends AuditableEntity {

    @Id @GeneratedValue(strategy = GenerationType.IDENTITY)
    public Long id;

    @Column(nullable = false, length = 200)
    public String name;

    @Column(nullable = false, length = 16)
    public String taxId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 30)
    public VendorType type;

    @Column(name = "is_active", nullable = false)
    public boolean active = true;

    @Column(name = "deleted_at")
    public Instant deletedAt;
}
```

`@Enumerated(EnumType.STRING)` **always**. `ORDINAL` stores the enum's position in the
source code — inserting one new value in the middle silently changes the meaning of every
existing row.

**3 — Repository.**

```java
@ApplicationScoped
public class VendorRepository implements PanacheRepository<Vendor> {

    public Optional<Vendor> findByNpwp(String taxId) {
        return find("taxId = ?1 and deletedAt is null", taxId).firstResultOptional();
    }

    public PanacheQuery<Vendor> search(String q, PageRequest page) {
        var query = (q == null || q.isBlank())
                ? find("deletedAt is null", page.toSort())
                : find("""
                       deletedAt is null
                       and (lower(name) like ?1 or taxId like ?1)
                       """, page.toSort(), "%" + q.toLowerCase() + "%");
        return query.page(page.page(), page.size());
    }
}
```

`PanacheRepository`, not active record — so services can be tested with a mock, without a
database, in milliseconds.

**4 — Automatic audit columns.**

```java
@MappedSuperclass
public abstract class AuditableEntity {
    @Column(name = "created_at", nullable = false, updatable = false)
    public Instant createdAt;
    @Column(name = "created_by", nullable = false, updatable = false)
    public String createdBy;
    @Column(name = "updated_at") public Instant updatedAt;
    @Column(name = "updated_by") public String updatedBy;

    @PrePersist void onCreate() { createdAt = Instant.now(); createdBy = CurrentUser.name(); }
    @PreUpdate  void onUpdate() { updatedAt = Instant.now(); updatedBy = CurrentUser.name(); }
}
```

---

## Migrations that are safe on real data

The `order` table will be large. What locks:

```sql
-- WRONG — rewrites the whole table
ALTER TABLE order ADD COLUMN reserve_price NUMERIC(18,2) NOT NULL DEFAULT 0;

-- RIGHT — three steps
ALTER TABLE order ADD COLUMN reserve_price NUMERIC(18,2);
UPDATE order SET reserve_price = 0 WHERE reserve_price IS NULL;
ALTER TABLE order ALTER COLUMN reserve_price SET NOT NULL;
```

Indexes on large tables:

```sql
-- flyway:executeInTransaction=false
CREATE INDEX CONCURRENTLY ix_order_date ON order (transaction_date);
```

Rules:
- Timestamp naming: `V<YYYYMMDD>_<HHmm>__<description>.sql` — sequential numbers collide as
  soon as two developers write a migration on the same day.
- **Forward-only.** Mistakes are corrected by a new migration.
- **Merged files are never edited** — Flyway's checksum will refuse startup in every
  environment that already ran it.
- Test against a populated dump, not an empty database.
- Backward-compatible by one release: do not drop a column in the same release that stops
  using it, so an application rollback stays possible.

---

## Transactions

`@Transactional` **only in services**. One transaction equals one business operation.

```java
// WRONG — an HTTP call holds the DB connection for its whole timeout
@Transactional
public void submit(Long id) {
    var p = order.findById(id);
    p.status = SUBMITTED;
    notificationClient.send(p);
}

// RIGHT — commit first, side effects after
public void submit(Long id) {
    var snapshot = changeStatus(id);        // @Transactional
    notificationClient.send(snapshot);      // outside
}

@Transactional
OrderSnapshot changeStatus(Long id) { ... }
```

Read-only: `@Transactional(TxType.SUPPORTS)`.

---

## N+1 — a bug, not merely slow

Enable it in dev and watch:

```properties
%dev.quarkus.hibernate-orm.log.sql=true
```

One request printing 50 SELECTs is a finding, not a coincidence.

```java
// WRONG — 1 + N queries
var list = orderRepo.listAll();
list.forEach(p -> use(p.vendor.name));   // one SELECT per row

// RIGHT — one query
var list = orderRepo.find("""
        select p from Order p
        join fetch p.vendor
        where p.deletedAt is null
        """).page(page).list();
```

All associations are `LAZY`; load explicitly with `join fetch` where needed. `EAGER` moves
the problem rather than removing it — it loads unused data on every other query.

## Report queries

Aggregation happens in the **database**, not in Java.

```java
// WRONG — loading 500,000 rows into memory to sum them
var all = orderRepo.listAll();
var total = all.stream().map(p -> p.amount).reduce(ZERO, BigDecimal::add);

// RIGHT
@ApplicationScoped
public class SummaryRepository {
    @Inject EntityManager em;

    public List<SummaryRow> summaryByType(LocalDate from, LocalDate to) {
        return em.createNativeQuery("""
                SELECT order_type, COUNT(*), SUM(amount)
                FROM order
                WHERE transaction_date BETWEEN :from AND :to AND deleted_at IS NULL
                GROUP BY order_type
                """, SummaryRow.class)
            .setParameter("from", from)
            .setParameter("to", to)
            .getResultList();
    }
}
```

Always parameters (`?1`, `:name`), **never** string concatenation of user input. Dynamic
`ORDER BY` uses an allowlist — see `quarkus-security`.

## Pitfalls

| Pitfall | Consequence |
|---|---|
| `generation=update` | Hibernate alters the production schema. Always `none`. |
| `EnumType.ORDINAL` | Inserting an enum value changes the meaning of old data |
| `float`/`double` for money | Rounding errors in financial reports |
| `TIMESTAMP` without a zone | Ambiguous when the server's zone changes |
| Entity returned as JSON | Internal columns leak, `LazyInitializationException` |
| Editing a merged migration | Checksum failure, startup dies in staging |
| A transaction wrapping an HTTP call | Connection pool exhausted under load |
| No index on a filter column | Sequential scan; fine in a demo, fatal in production |
