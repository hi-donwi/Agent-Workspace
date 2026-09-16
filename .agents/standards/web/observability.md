# Observability — Web pack

When a user reports "the save failed", the next person needs a `requestId` to follow, not
a guess.

---

## Logging

Structured JSON in every environment except local dev.

| Level | For |
|---|---|
| `error` | A human must act |
| `warn` | Recovered: retry succeeded, fallback used |
| `info` | Business events: signed in, export finished, payment captured |
| `debug` | Flow detail, off by default in production |

**Do not log:** passwords, tokens, session IDs, full payment PAN, document contents,
unredacted personal data.

Invalid user input is not `error`.

---

## Correlation ID

Every request gets (or forwards) `X-Request-Id`:

- stored on the request
- on every log line for that request
- returned as a response header
- included as `traceId` on error bodies (see `core/api-contract.md`)

Generate one if the caller did not send it. Do not reuse IDs across requests.

---

## Metrics and traces

Add what answers a business question. Safe tags have a bounded set of values
(route, status, cause). **Never** tag with user id, email, or document id.

Health:

| Endpoint | Checks |
|---|---|
| Liveness | The process is up. **Not** the database |
| Readiness | Database, object storage, required dependencies |

Liveness must not restart the app because the database is down.

---

## Front-end errors

Unhandled client exceptions go to the same correlation story: a visible generic message
plus an id the user can quote. Do not dump stack traces in the UI in production.
