---
name: bulk-reporting-export
pack: java
description: >-
  Build large reporting and export endpoints that do not exhaust memory: streaming XLSX with
  Apache POI SXSSF, PDF with OpenPDF, ZIP packaging, database-side aggregation, async job
  submission with 202 plus polling or SSE progress, spool storage and cleanup, idempotency,
  and download authorisation. Use when an export is slow or runs out of memory, when
  building any endpoint in the reporting module, when a report exceeds a few thousand rows,
  or when adding progress reporting for a long-running job. Do not use for ordinary
  paginated list endpoints (rest-api-contract) or general query tuning
  (quarkus-persistence).
keywords: export, report, reporting, xlsx, excel, pdf, zip, poi, sxssf, streaming, memory, oom, out of memory, async job, sse, progress, download, spool, aggregate, summary
---

# Bulk Reporting & Export

The reporting module is 86 of 145 endpoints — 59 % of the backend scope. It is also where
memory and latency problems appear first, because it is the only place that touches whole
datasets rather than one page.

## Use when
- Building any endpoint in the `reporting` module
- An export is slow or throws `OutOfMemoryError`
- A report will exceed a few thousand rows
- Adding progress reporting to a long-running job

## Hand off when
| Need | Skill |
|---|---|
| Ordinary paginated list | `rest-api-contract` |
| Query and index tuning | `quarkus-persistence` |
| Who may download what | `quarkus-security` |
| Export duration metrics | `quarkus-observability` |

---

## The rule that prevents most of the damage

**Never hold a full result set in memory.** Not in a `List`, not in a DTO collection, not in
an in-memory workbook.

The demo works because 300 rows fit anywhere. At 100,000 rows of order transactions
the same code produces `OutOfMemoryError` — and it does so in production under real data,
not in testing under sample data.

```java
// WRONG — the whole table in a List, then a whole workbook in memory
List<TransactionRow> rows = repository.findAllForExport();
XSSFWorkbook wb = new XSSFWorkbook();
```

```java
// RIGHT — stream from the database, flush to disk every N rows
try (SXSSFWorkbook wb = new SXSSFWorkbook(100)) {   // keep 100 rows in memory
    var sheet = wb.createSheet("Transactions");
    int rowNum = 0;
    try (Stream<TransactionRow> stream = repository.streamForExport(filter)) {
        for (var row : (Iterable<TransactionRow>) stream::iterator) {
            write(sheet.createRow(rowNum++), row);
        }
    }
    try (var out = Files.newOutputStream(spoolFile)) {
        wb.write(out);
    }
    wb.dispose();   // delete the temporary files SXSSF created
}
```

`SXSSFWorkbook(100)` keeps a 100-row sliding window in memory and flushes the rest to
temporary files. `wb.dispose()` is mandatory — without it those temporary files stay on
disk, and the spool volume fills up quietly over weeks.

### Streaming from the database

```java
@ApplicationScoped
public class TransactionExportRepository {
    @Inject EntityManager em;

    public Stream<TransactionRow> streamForExport(ExportFilter filter) {
        return em.createQuery(JPQL_EXPORT, TransactionRow.class)
                 .setParameter("from", filter.from())
                 .setParameter("to", filter.to())
                 .setHint(HINT_FETCH_SIZE, 1000)   // do not buffer the whole result
                 .getResultStream();
    }
}
```

The stream must be consumed inside a transaction and closed — hence `try (…)`. Without a
fetch-size hint, the JDBC driver may still buffer everything, which defeats the purpose.

## Synchronous or asynchronous?

```
Estimated duration < 10 s  -> synchronous, stream the response directly
Estimated duration > 10 s  -> async job: 202 + job ID, then poll or SSE
Unknown                    -> async. Guessing wrong costs a timeout in production.
```

A synchronous export holds an HTTP connection and a worker thread for its whole duration.
Twenty concurrent users exporting a large report will exhaust the pool and take down
endpoints that have nothing to do with reporting.

### Async job shape

```
POST /api/v1/reporting/transaction-summary/export
  -> 202 Accepted
     { "jobId": "...", "status": "QUEUED", "statusUrl": "...", "downloadUrl": null }

GET  /api/v1/reporting/exports/{jobId}          -> current status (polling)
GET  /api/v1/reporting/exports/{jobId}/events   -> SSE progress stream
GET  /api/v1/reporting/exports/{jobId}/download -> the file, once READY
```

Job states: `QUEUED` → `RUNNING` → `READY` | `FAILED` | `EXPIRED`.

**Job state belongs in the database, not in a `ConcurrentHashMap`.** An in-memory job store
loses every running job on deploy and cannot be read by a second instance — the same defect
as in-memory sessions, in a place where the user has already waited two minutes.

```sql
CREATE TABLE export_job (
    id            UUID PRIMARY KEY,
    requested_by  VARCHAR(100) NOT NULL,
    report_type   VARCHAR(50)  NOT NULL,
    parameters    JSONB        NOT NULL,
    status        VARCHAR(20)  NOT NULL,
    progress_pct  SMALLINT     NOT NULL DEFAULT 0,
    row_count     BIGINT,
    object_key    VARCHAR(500),
    error_code    VARCHAR(50),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ  NOT NULL,
    CONSTRAINT ck_export_job_status
        CHECK (status IN ('QUEUED','RUNNING','READY','FAILED','EXPIRED'))
);
```

### Progress via SSE

```java
@GET
@Path("/{jobId}/events")
@Produces(MediaType.SERVER_SENT_EVENTS)
@RolesAllowed({"COMMITTEE", "ADMIN", "AUDITOR"})
public Multi<ExportProgress> events(@PathParam("jobId") UUID jobId) {
    return jobService.progressStream(jobId);
}
```

SSE is the right fit here: one-directional server-to-client, works over plain HTTP, and
reconnects on its own. Do not reach for WebSockets for progress reporting — they add a
protocol to operate for something that only flows one way.

Always offer polling as well. Some corporate proxies buffer SSE into uselessness, and a
frontend needs a fallback.

## Aggregate in the database

```java
// WRONG — 500,000 rows into memory to produce 12 summary lines
var all = repository.findAll(filter);
var byType = all.stream().collect(groupingBy(r -> r.type, reducing(...)));

// RIGHT — the database returns 12 rows
SELECT order_type, COUNT(*), SUM(amount)
FROM order
WHERE transaction_date BETWEEN :from AND :to AND deleted_at IS NULL
GROUP BY order_type
```

Most "slow report" tickets resolve to this one change. A summary report should never load
detail rows.

Every report query needs indexes on its filter and grouping columns, created in the same
migration as the report.

## PDF

OpenPDF, as in the demo. The same streaming rule applies: write page by page, do not build
the whole document in memory.

- A tabular PDF over roughly 5,000 rows is not a usable document. Offer XLSX instead, or
  paginate the report itself.
- Watermarks, headers, and footers are applied per page during writing, not by
  post-processing the finished file.
- Fonts must be embedded, or Indonesian characters will vary across viewers.

## ZIP

When an export produces several files, stream into the ZIP — do not create each file fully
then add it.

```java
try (var zos = new ZipOutputStream(Files.newOutputStream(target))) {
    for (var part : parts) {
        zos.putNextEntry(new ZipEntry(part.name()));
        part.writeTo(zos);          // streams straight into the ZIP
        zos.closeEntry();
    }
}
```

## Spool storage and cleanup

| Concern | Rule |
|---|---|
| Location | Object storage (MinIO/S3), not local disk — several instances must serve the same download |
| Temporary files | Under a configured `spoolDir`, cleaned up in a `finally` block |
| Retention | Exports expire (e.g. 7 days); a scheduled job deletes expired objects and rows |
| Disk alert | Spool volume above 80 % (see `quarkus-observability`) |

Cleanup is not optional. Export files are large and are generated continuously; without a
retention job the storage bill and the disk both grow without limit.

```java
@Scheduled(cron = "0 0 2 * * ?")
void purgeExpiredExports() { ... }
```

## Idempotency

A user who does not see progress will click the button again. Without protection that
doubles the load at exactly the moment the system is already struggling.

- Deduplicate by `(user, reportType, parameterHash)` while a job is `QUEUED` or `RUNNING` —
  return the existing job ID instead of starting a second one.
- The download URL carries a single-use or short-lived token, and authorisation is
  re-checked at download time. A job ID is not an access grant.

## Authorisation at download time

```java
@GET
@Path("/{jobId}/download")
@RolesAllowed({"COMMITTEE", "ADMIN", "AUDITOR"})
public Response download(@PathParam("jobId") UUID jobId, @Context SecurityIdentity identity) {
    var job = jobService.requireReadable(jobId, identity);   // owner or an authorised role
    return Response.ok(storage.stream(job.objectKey()))
            .header("Content-Disposition", "attachment; filename=\"" + job.fileName() + "\"")
            .build();
}
```

The role check alone is not enough: a committee member from another unit holds the same role
but must not download another unit's report. Ownership and unit scope are checked too.

## Performance targets

| Report size | Target |
|---|---|
| < 1,000 rows | Synchronous, < 2 s |
| 1,000–10,000 rows | Synchronous, < 10 s |
| 10,000–100,000 rows | Async, < 60 s |
| > 100,000 rows | Async, chunked, with progress |

Heap stays under 1 GB regardless of report size. If it does not, something is still being
buffered.

## Pitfalls

| Pitfall | Symptom |
|---|---|
| `XSSFWorkbook` instead of `SXSSF` | `OutOfMemoryError` at ~50k rows |
| Missing `wb.dispose()` | Spool disk fills up over weeks |
| No JDBC fetch size | The driver buffers the whole result anyway |
| Job state in memory | Jobs lost on deploy; broken behind a load balancer |
| Synchronous long export | Thread pool exhausted; unrelated endpoints time out |
| Aggregating in Java | Slow report, high memory, needless database load |
| No retention job | Storage grows without limit |
| No idempotency | Duplicate jobs when users click twice |
| Download without an ownership check | Cross-unit data exposure |
