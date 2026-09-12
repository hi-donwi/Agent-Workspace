---
name: quarkus-observability
pack: java
description: >-
  Make a Quarkus service diagnosable in production: structured JSON logs, a correlation ID
  via MDC and the X-Request-Id header surfaced as traceId in errors, Micrometer/Prometheus
  metrics for business events, OpenTelemetry tracing, correct liveness/readiness health
  checks, and alert thresholds. Use when preparing a new service for production, adding
  metrics, diagnosing an issue that only appears in staging or production, designing alerts,
  or when logs are not enough to follow one request. Do not use for local dev debugging,
  tests (quarkus-testing), or export performance tuning (bulk-reporting-export).
keywords: log, logging, metric, trace, tracing, health, probe, alert, prometheus, micrometer, opentelemetry, correlation, requestid, observability, monitoring, mdc
---

# Quarkus Observability

Full rules: `.agents/standards/java/observability.md`. This is how to install it.

When a user reports "the export failed" at 2 a.m., what determines time-to-fix is not
developer cleverness — it is whether there is a `traceId` to follow.

## Use when
- Preparing a new service for staging/production
- Adding metrics for business events
- An issue that only appears in staging or production
- Designing alerts
- Logs are not enough to follow a single request

---

## Correlation ID — install this first

Without it, finding one user's request across two services' logs is a blind text search.

```java
@Provider
public class RequestIdFilter implements ContainerRequestFilter, ContainerResponseFilter {

    public static final String HEADER = "X-Request-Id";

    @Override
    public void filter(ContainerRequestContext ctx) {
        String id = ctx.getHeaderString(HEADER);
        if (id == null || id.isBlank()) id = UUID.randomUUID().toString();
        MDC.put("requestId", id);
        ctx.setProperty("requestId", id);
    }

    @Override
    public void filter(ContainerRequestContext req, ContainerResponseContext res) {
        res.getHeaders().putSingle(HEADER, req.getProperty("requestId"));
        MDC.clear();       // required: threads are reused
    }
}
```

`MDC.clear()` in the response filter is not optional. The thread is reused by the next
request; an uncleared MDC makes request B's logs carry request A's `requestId` — a
misleading trail is worse than no trail.

The same ID appears in:
- every log line for that request
- the response header
- the `traceId` field of the error body (`rest-api-contract`)

Forward it to other services via the same header on the REST client.

## Logs

```properties
%prod.quarkus.log.console.json=true
%prod.quarkus.log.level=INFO
%prod.quarkus.log.category."com.example.product".level=DEBUG
```

| Level | For |
|---|---|
| `ERROR` | A human must act. If nothing needs doing, it is not an error. |
| `WARN` | Self-recovering: a retry succeeded, a fallback was used |
| `INFO` | Business events: order submitted, export finished, login |
| `DEBUG` | Flow detail, per package |

Business events use structured fields:

```java
log.infof("order submitted id=%d unit=%s amount=%s", id, unit, amount);
```

**Do not log:** passwords, tokens, session IDs, bid document contents, reserve price before opening,
full tax ID.

A common mistake: `log.error` for a failed validation. Invalid user input is a normal
event — that is `DEBUG`, or not logged at all. If `ERROR` is used for normal things, the
error-rate alert becomes useless.

## Metrics

```xml
<dependency>
  <groupId>io.quarkus</groupId>
  <artifactId>quarkus-micrometer-registry-prometheus</artifactId>
</dependency>
```

The defaults already cover HTTP rate/latency, JVM, and connection pool. Add what answers
business questions:

```java
@Inject MeterRegistry registry;

var sample = Timer.start(registry);
// ... run the export
sample.stop(registry.timer("app.export.duration", "type", type, "format", "xlsx"));

registry.counter("app.export.failed", "cause", "timeout").increment();
```

| Metric | Answers |
|---|---|
| `app_export_duration_seconds` | Which export is slowing down |
| `app_export_failed_total` (tag: cause) | Whether failures are rising |
| `app_login_failed_total` | Brute-force signal |
| `app_order_submitted_total` | Real system load |

**Never** use high-cardinality values as tags — order ID, tax ID, user ID. Every unique
value creates a new time series; that is what exhausts Prometheus's memory. A safe tag has a
bounded, enumerable set of values: type, format, cause, status.

## Tracing

```properties
quarkus.otel.exporter.otlp.traces.endpoint=${OTLP_ENDPOINT}
%dev.quarkus.otel.enabled=false
```

Spans are automatic for inbound/outbound HTTP and JDBC. Add manual spans only around long
non-I/O operations (PDF generation, report aggregation) — that is where time disappears
without a trace.

## Health checks

```java
@Readiness
@ApplicationScoped
public class StorageHealthCheck implements HealthCheck {
    @Inject ObjectStorage storage;

    @Override
    public HealthCheckResponse call() {
        try {
            storage.ping();
            return HealthCheckResponse.up("object-storage");
        } catch (Exception e) {
            return HealthCheckResponse.down("object-storage");
        }
    }
}
```

| Endpoint | Checks | Used by |
|---|---|---|
| `/q/health/live` | The process is alive. **Not** dependencies. | Restart policy |
| `/q/health/ready` | DB, storage, dependent services | Load balancer |
| `/q/health/started` | Startup finished | Startup probe |

**Liveness must not check the database.** If the DB is down, restarting every application
instance fixes nothing and destroys the capacity left to recover when the DB returns.

`/q/*` must not be exposed to the internet — restrict it at the reverse proxy.

## Alerts

On **symptoms users feel**, not causes.

| Alert | Threshold |
|---|---|
| 5xx error rate | > 1 % for 5 minutes |
| p95 read latency | > 1 s for 10 minutes |
| Export failures | > 5 % within 15 minutes |
| Readiness down | > 2 minutes |
| Connection pool | > 90 % for 5 minutes |
| Export spool disk | > 80 % |

An alert that fires often without requiring action gets ignored, and then the important one
gets ignored with it. If an alert requires no action three times in a row, raise its
threshold or delete it.

## Pre-staging checklist

- [ ] JSON logging enabled in non-dev profiles
- [ ] `X-Request-Id` accepted, generated, returned, in the MDC, and in the error `traceId`
- [ ] `MDC.clear()` in the response filter
- [ ] Readiness checks real dependencies; liveness does not
- [ ] Business metrics on critical paths (export, upload, login)
- [ ] No high-cardinality metric tags
- [ ] No sensitive data in logs
- [ ] `/q/*` not publicly exposed
- [ ] Alerts configured with the thresholds above
