# Security

This system holds customer records, contract values, and award decisions. A leak here is
not a technical incident — it is a legal and data-integrity problem.

---

## Authentication

| Item | Decision |
|---|---|
| Password hashing | **Argon2id** (`m=19456, t=2, p=1` OWASP minimum) |
| Session | Cookie `HttpOnly; Secure; SameSite=Lax; Path=/` |
| Session store | **Redis** — `[PENDING CLIENT]` |
| Idle timeout | 30 minutes, sliding |
| Absolute timeout | 8 hours |
| Session ID rotation | Required after a successful login |

**In-memory sessions must not reach production.** The demo's `ConcurrentHashMap` means
users are logged out on every deploy, and login breaks the moment a second instance sits
behind a load balancer. This blocks horizontal scaling — raise it at kick-off.

The demo's PBKDF2 is not carried forward. Argon2id is the current OWASP recommendation
because its memory cost resists GPU and ASIC attacks.

```
# store algorithm + parameters + salt + hash in one PHC string
# $argon2id$v=19$m=19456,t=2,p=1$<salt>$<hash>
```

Storing the parameters alongside the hash allows raising the cost later without forcing
every user to reset their password.

### Login rules

- The failure message is **identical** for an unknown user and a wrong password. Different
  messages tell an attacker which accounts exist.
- Rate limit per account **and** per IP. 15-minute lockout after 5 failures.
- Record failed attempts (username, IP, time). **Never** record the password.

---

## Authorisation

Declarative, not hand-written `if` statements inside services.

```java
@GET
@Path("/{id}/list-price")
@RolesAllowed({"COMMITTEE", "ADMIN"})
public PriceResponse viewListPrice(@PathParam("id") Long id) { ... }
```

- **Closed by default**: every resource method requires a role annotation. A method without
  one is a bug, caught by a test (see `testing.md`).
- Public endpoints are marked explicitly with `@PermitAll` — so "public" is a visible
  decision, not an omission.
- **Data-level** authorisation (a user may only see their own unit's orders) cannot
  be handled by `@RolesAllowed`. It belongs in the repository query, not in a Java filter
  applied after the data has been loaded.

```java
// WRONG — load everything, then filter; the data already left the database
var all = orderRepo.listAll();
return all.stream().filter(p -> p.unit.equals(user.unit())).toList();

// RIGHT — constrain the query
return orderRepo.findByUnit(user.unit(), page);
```

### Example roles

`[PENDING CLIENT]` — every project confirms its own matrix at kick-off and records it in
`context/memory/projects/<key>/`. The shape that matters is this:

| Role | Scope |
|---|---|
| `ADMIN` | Master data, system configuration |
| `STAFF` | Create and manage records in their own unit |
| `COUNTERPARTY` | External party — sees **only their own** submissions |
| `AUDITOR` | Read-only across units, including history |
| `EXECUTIVE` | Dashboards and aggregate reports |

The rule to take from this: wherever an external party and an internal one share an
endpoint, the confidentiality boundary between them is a **business rule that needs its own
test**, not merely a note in a document.

---

## Input

- Bean Validation on every request DTO (this does not replace `api-contract.md`).
- **Allowlist, not blocklist.** Define what is permitted and reject the rest.
- Size limits: maximum request body, pagination `size` capped at 200, maximum string length
  on every field.

### Dynamic sort and filter — the most common SQL injection vector

`ORDER BY` cannot be parameterised. The demo accepts a raw `sortCol` from the query string.

```java
// WRONG — user input reaches SQL
find("... order by " + sortCol + " " + sortDir);

// RIGHT — allowlist
private static final Map<String, String> SORTABLE = Map.of(
        "name", "name",
        "taxId", "taxId",
        "createdAt", "createdAt");

String column = SORTABLE.get(request.sortField());
if (column == null) throw new ValidationException(ErrorCode.SORT_FIELD_INVALID, ...);
Sort.Direction direction = "desc".equalsIgnoreCase(request.sortDir())
        ? Sort.Direction.Descending : Sort.Direction.Ascending;
```

### File upload

Where modules accept uploaded documents, the rules:

| Control | Rule |
|---|---|
| Type | Validate **magic bytes**, not `Content-Type` or the extension |
| Size | Hard limit per file and per request |
| Filename | Regenerate (UUID). **Never** use a client-supplied name in a path |
| Storage | Object storage, outside the webroot |
| Serving | Through an authorised endpoint, not a direct URL |
| Scanning | Antivirus before the file can be downloaded by others `[PENDING CLIENT]` |

A client-supplied filename can contain `../` — that is path traversal. Always generate a
new name and keep the original as database metadata.

---

## Output

- **Never** return an entity. `passwordHash` and `internalNote` serialise along with it.
- Errors never expose stack traces, framework versions, table names, or SQL.
- Security headers on every response:

```properties
quarkus.http.header."X-Content-Type-Options".value=nosniff
quarkus.http.header."X-Frame-Options".value=DENY
quarkus.http.header."Referrer-Policy".value=strict-origin-when-cross-origin
quarkus.http.header."Strict-Transport-Security".value=max-age=31536000; includeSubDomains
```

## CORS

```properties
# WRONG — the demo setting; never in production
quarkus.http.cors.origins=*

# RIGHT — explicit per environment
%prod.quarkus.http.cors.origins=${CORS_ORIGINS}
```

`origins=*` together with credentialed cookies lets any website call the API on behalf of a
logged-in user.

---

## Secrets

| Rule | |
|---|---|
| In code | **Never.** Including tests, including comments. |
| In `application.properties` | Only the env var **name**: `${DB_PASSWORD}` |
| In the repo | Never. `.env` is in `.gitignore`. |
| In logs | Never. Including while debugging. |
| In commit messages | Never. |
| Rotation | On a schedule; immediately on any sign of exposure. |

If a secret is committed: **rotate first**, then clean history. Deleting the file does not
remove it from history, and anyone who already cloned still has it.

## Dependencies

- OWASP Dependency-Check in CI. **Build fails on CVSS ≥ 7.**
- Quarkus BOM upgrades follow LTS patch releases (roughly every two months).
- A new dependency needs justification in the PR: why it is needed, what the Quarkus BOM
  alternative is.

## Security review checklist

For every PR touching auth, user input, or files:

- [ ] Endpoint has a role annotation (or a deliberate `@PermitAll`)
- [ ] Data-level authorisation is in the query, not a post-load filter
- [ ] No string concatenation into SQL/JPQL
- [ ] Dynamic sort/filter uses an allowlist
- [ ] No entity returned as a response
- [ ] No new secrets in code or properties
- [ ] Errors expose no internal detail
- [ ] Sensitive data is not logged
