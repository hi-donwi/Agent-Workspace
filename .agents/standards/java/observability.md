# Observability

When a user reports "the export failed" at 2 a.m. in November, what determines time-to-fix
is not developer cleverness — it is whether there is a `traceId` to follow.

---

## Logging

**Structured JSON in every environment except dev.**

```properties
%prod.quarkus.log.console.json=true
%prod.quarkus.log.level=INFO
%prod.quarkus.log.category."com.example.product".level=DEBUG
quarkus.log.console.format=%d{HH:mm:ss} %-5p [%c{2.}] (%t) %s%e%n
```

### Correlation ID — required

Every incoming request receives (or forwards) an `X-Request-Id`, stored in the MDC, emitted
on every log line, and returned to the client in the response header **and** in the error
body as `traceId`.

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
        MDC.clear();
    }
}
```

Without this, finding one user's request across two services' logs is a blind text search.

### What to log

| Level | For |
|---|---|
| `ERROR` | A human must act. If nothing needs doing, it is not an error. |
| `WARN` | Self-recovering but worth noticing: a retry succeeded, a fallback was used |
| `INFO` | Business events: order submitted, export finished, user logged in |
| `DEBUG` | Flow detail. Enabled per package, never globally. |

**Do not log:** passwords, tokens, session IDs, bid document contents, reserve price values before
opening, full tax ID.

Business events use structured fields, not sentences:

```java
log.infof("order submitted id=%d unit=%s amount=%s", id, unit, amount);
```

---

## Metrics

Micrometer plus Prometheus at `/q/metrics`.

```xml
<dependency>
  <groupId>io.quarkus</groupId>
  <artifactId>quarkus-micrometer-registry-prometheus</artifactId>
</dependency>
```

The defaults already give HTTP request rate/latency, JVM, and connection pool metrics. What
must be added are the metrics that answer business questions:

| Metric | Type | Answers |
|---|---|---|
| `app_export_duration_seconds` | Timer (tags: type, format) | Which export is slowing down |
| `app_export_rows_total` | Counter | Report volume |
| `app_export_failed_total` | Counter (tag: cause) | Whether failures are rising |
| `app_upload_bytes_total` | Counter | Storage capacity |
| `app_login_failed_total` | Counter | Brute-force signal |
| `app_order_submitted_total` | Counter (tag: type) | Real system load |

```java
@Inject MeterRegistry registry;

var sample = Timer.start(registry);
// ... run the export
sample.stop(registry.timer("app.export.duration", "type", type, "format", "xlsx"));
```

**Never** use high-cardinality values as tags (order ID, tax ID, user ID). Every unique
value creates a new time series; that is what exhausts Prometheus's memory.

---

## Tracing

OpenTelemetry, propagating `traceparent` across services.

```properties
quarkus.otel.exporter.otlp.traces.endpoint=${OTLP_ENDPOINT}
%dev.quarkus.otel.enabled=false
```

Spans are automatic for inbound/outbound HTTP and JDBC. Add manual spans only around long
non-I/O operations (PDF generation, report aggregation) — that is where time disappears
without a trace.

`[PENDING CLIENT]` — connect to the client's collector if one exists; do not stand up a new
stack without need.

---

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

| Endpoint | Meaning | Used by |
|---|---|---|
| `/q/health/live` | The process is alive. **Does not** check dependencies. | Restart policy |
| `/q/health/ready` | Ready for traffic: DB, storage, dependent services | Load balancer |
| `/q/health/started` | Startup finished | Startup probe |

**Liveness must not check the database.** If the DB is down, restarting every application
instance fixes nothing and destroys the capacity left to recover.

`/q/*` must not be exposed to the internet — restrict it at the reverse proxy.

---

## Alerts

Alert on **symptoms users feel**, not on causes.

| Alert | Threshold |
|---|---|
| 5xx error rate | > 1 % for 5 minutes |
| p95 read latency | > 1 s for 10 minutes |
| Export failures | > 5 % within 15 minutes |
| Readiness down | > 2 minutes |
| Connection pool exhausted | > 90 % for 5 minutes |
| Export spool disk | > 80 % |

An alert that fires often without requiring action gets ignored, and then the important one
gets ignored with it. If an alert requires no action three times in a row, raise its
threshold or delete it.
