# Database & Migrations

PostgreSQL 16+. Flyway is the only thing that changes the schema.

```properties
quarkus.hibernate-orm.database.generation=none   # MANDATORY, in every profile
quarkus.flyway.migrate-at-start=true
```

`generation=update` has dropped production columns on other projects. There is no
justification good enough to turn it on.

---

## Flyway migrations

```
src/main/resources/db/migration/
├── V1__init_schema.sql
├── V2__catalog_vendor.sql
├── V20260912_1430__order_add_currency_column.sql
└── R__view_transaction_summary.sql
```

- Versions use a **timestamp** after `V1__init`:
  `V<YYYYMMDD>_<HHmm>__<description>.sql`. Sequential numbers (`V2`, `V3`) collide the
  moment two developers write a migration on the same day — and with two backend developers
  working in parallel, that will happen.
- `R__` (repeatable) for views and functions that can be `CREATE OR REPLACE`d.
- **Forward-only.** No rollback scripts. Mistakes are corrected by a new migration.
- **Merged files are never edited.** Flyway validates checksums; editing an old file makes
  startup fail in every environment that already ran it.
- One migration equals one logical change.

### Migrations must be safe on populated tables

The `order` table will hold millions of rows. What locks a table for a long time:

```sql
-- WRONG — rewrites the whole table, blocking writes
ALTER TABLE order ADD COLUMN currency CHAR(3) NOT NULL DEFAULT 'USD';

-- RIGHT — three steps, no long lock
ALTER TABLE order ADD COLUMN currency CHAR(3);                     -- instant
UPDATE order SET currency = 'USD' WHERE currency IS NULL;          -- batched
ALTER TABLE order ALTER COLUMN currency SET NOT NULL;              -- validate
```

Indexes on large tables use `CREATE INDEX CONCURRENTLY` (and disable the Flyway transaction
for that migration with `-- flyway:executeInTransaction=false`).

Every migration is tested against a **populated dump**, not an empty database.

---

## Schema conventions

| Item | Rule |
|---|---|
| Table | `snake_case`, **singular**: `vendor`, `order`, `contract_type` |
| Column | `snake_case`: `unit_price`, `announcement_date` |
| Primary key | `id BIGINT GENERATED ALWAYS AS IDENTITY` |
| Foreign key | `<table>_id`: `vendor_id`, `order_id` |
| Boolean | Clear prefix: `is_active`, `is_deleted` |
| Money | `NUMERIC(18,2)` — **never** `float`/`double` |
| Timestamp | `TIMESTAMPTZ`, stored in UTC |
| Enum | `VARCHAR` + `CHECK`, not a PostgreSQL enum |

PostgreSQL enums are avoided because adding a value requires `ALTER TYPE`, which cannot run
inside a transaction, and removing a value is practically impossible. `VARCHAR` plus a
`CHECK` constraint gives the same validation with ordinary migrations.

### Audit columns — required on every business table

```sql
created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
created_by  VARCHAR(100) NOT NULL,
updated_at  TIMESTAMPTZ,
updated_by  VARCHAR(100)
```

Populated automatically through a `@MappedSuperclass` with `@PrePersist`/`@PreUpdate`, not
by hand in every service. For an order system, "who changed the list price and when" is
an audit question that will certainly be asked.

### Soft delete

Only for entities referenced by historical documents (vendors, contract types, budgets):

```sql
deleted_at TIMESTAMPTZ,
-- uniqueness only among live rows
CREATE UNIQUE INDEX uq_vendor_taxId_live ON vendor (taxId) WHERE deleted_at IS NULL;
```

Repositories filter `deleted_at IS NULL` by default. Transactional data (logs, expired
notifications) is deleted for real.

---

## Panache — repositories, not active record

```java
@ApplicationScoped
public class VendorRepository implements PanacheRepository<Vendor> {

    public Optional<Vendor> findByNpwp(String taxId) {
        return find("taxId = ?1 and deletedAt is null", taxId).firstResultOptional();
    }

    public PanacheQuery<Vendor> search(String q, PageRequest page) {
        var query = (q == null || q.isBlank())
                ? find("deletedAt is null", page.toSort())
                : find("deletedAt is null and (lower(name) like ?1 or taxId like ?1)",
                       page.toSort(), "%" + q.toLowerCase() + "%");
        return query.page(page.page(), page.size());
    }
}
```

Active record is rejected because `Vendor.find(...)` is a static method, so any service
using it cannot be tested without a database — and the domain model ends up carrying
persistence responsibility.

## Transactions

- `@Transactional` **only in `service/`**. Not in resources, not in repositories.
- One transaction equals one business operation.
- **Never** call a REST client or write to S3 inside a transaction. The database connection
  is held for the duration of the network wait, and a rollback cannot undo a file that has
  already been sent.
- Read-only operations: `@Transactional(Transactional.TxType.SUPPORTS)`.

```java
// WRONG — HTTP call inside a transaction
@Transactional
public void submit(Long id) {
    var p = order.findById(id);
    p.status = SUBMITTED;
    notificationClient.send(p);   // a 30s timeout holds the DB connection for 30s
}

// RIGHT — commit first, side effects after
public void submit(Long id) {
    var snapshot = changeStatus(id);      // @Transactional
    notificationClient.send(snapshot);    // outside the transaction
}
```

## Queries

- **N+1 is a bug**, not a performance nuance. All associations are `LAZY`; load explicitly
  with `join fetch` where needed.
- Enable in dev: `quarkus.hibernate-orm.log.sql=true`. If one request prints 50 SELECTs,
  that is a finding.
- Every column used in `WHERE` or `ORDER BY` on a large table needs an index — created in
  the same migration as the feature.
- Aggregate reports use native queries in text blocks, not loading entities into memory and
  summing in Java.
- Never build SQL by concatenating user input. Always use parameters (`?1`, `:name`). For
  dynamic `ORDER BY`, use an allowlist (see `security.md`).

## Connection pool

```properties
quarkus.datasource.jdbc.max-size=20
quarkus.datasource.jdbc.min-size=2
quarkus.datasource.jdbc.acquisition-timeout=10s
```

Pool size is not "bigger is better". The total `max-size` across all instances must stay
below PostgreSQL's `max_connections`, leaving headroom for administrative connections.
