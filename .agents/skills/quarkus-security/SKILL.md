---
name: quarkus-security
pack: java
description: >-
  Apply and review backend security in Quarkus: Argon2id, Redis-backed sessions and cookies,
  closed-by-default RBAC with @RolesAllowed, data-level authorisation pushed into queries,
  allowlists for dynamic sort and filter, bid-document upload validation, security headers,
  CORS, and secret handling. Use when touching login or sessions, adding an endpoint that
  needs a role, accepting user input or files, building dynamic sort/filter, reviewing a PR
  that touches auth or sensitive data, or handling secrets. Do not use for error response
  shape (rest-api-contract) or infrastructure/network security (java-delivery).
keywords: auth, authentication, authorisation, authorization, login, session, password, hashing, argon, role, permission, rbac, security, injection, upload, secret, cors, token, header, allowlist
---

# Quarkus Security

Full rules: `.agents/standards/java/security.md`. This is how to apply them.

This system holds vendor records, reserve price values, and tender award decisions. A leak here is not
a technical incident — it is a legal and order-integrity problem.

## Use when
- Touching login, sessions, or passwords
- Adding an endpoint (every endpoint needs a role decision)
- Accepting user input or files
- Building a dynamic `ORDER BY` or filter
- Reviewing a PR that touches auth or sensitive data

---

## Closed by default

Every HTTP method requires an **explicit** role annotation:

```java
@GET @RolesAllowed({"ADMIN", "COMMITTEE"})     // right — restricted
@GET @PermitAll                                 // right — public, deliberately
@GET                                            // wrong — an omission; review and tests reject it
```

Protect it with an architecture test rather than relying on a reviewer's memory:

```java
@Test
void everyEndpointDeclaresARole() {
    // reflect over all *Resource classes: every method annotated
    // @GET/@POST/@PUT/@DELETE must carry @RolesAllowed or @PermitAll
}
```

With 145 endpoints, one omission will slip past a quick manual review sooner or later.

## Data-level authorisation

`@RolesAllowed` answers "may you use this endpoint?". It does **not** answer "may you see
this row?".

```java
// WRONG — data already left the database before being filtered
var all = orderRepo.listAll();
return all.stream().filter(p -> p.unit.equals(user.unit())).toList();

// RIGHT — constrain the query
return orderRepo.findByUnit(user.unit(), page);
```

Filtering after loading is wrong for two reasons: the `totalElements` count for pagination
becomes incorrect, and data the user may not see has been in the process's memory — visible
in a heap dump and in any log that prints it.

### Domain rules that need their own tests

- A vendor **never** sees the reserve price before bid opening
- A vendor **never** sees another vendor's bid
- An auditor is read-only, without exception
- A committee member manages only their own unit's orders

These are business rules, not configuration. They belong in the organisation's domain
skill under `context/skills/`, not here.

---

## Passwords and sessions

```
# Argon2id, OWASP minimum parameters: m=19456 KiB, t=2, p=1
# stored as a PHC string: $argon2id$v=19$m=19456,t=2,p=1$<salt>$<hash>
```

Storing the parameters alongside the hash allows raising the cost later without forcing
every user to reset their password.

| Item | Value |
|---|---|
| Cookie | `HttpOnly; Secure; SameSite=Lax; Path=/` |
| Store | Redis — in-memory must not reach production |
| Idle timeout | 30 minutes, sliding |
| Absolute timeout | 8 hours |
| Session ID rotation | Required after a successful login |

Rotating the session ID after login prevents session fixation: an attacker who planted a
session ID in the victim's browser finds it invalid the moment the victim logs in.

### Login

- The failure message is **identical** for an unknown user and a wrong password — different
  messages tell an attacker which accounts exist.
- Rate limit per account **and** per IP; 15-minute lockout after 5 failures.
- Record failed attempts (username, IP, time). **Never** record the password.

---

## Dynamic sort and filter

The most common SQL injection vector in an application like this, because `ORDER BY` cannot
be parameterised. The demo accepts a raw `sortCol` from the query string.

```java
private static final Map<String, String> SORTABLE = Map.of(
        "name",      "name",
        "taxId",      "taxId",
        "createdAt", "createdAt");

String column = SORTABLE.get(request.sortField());
if (column == null) {
    throw new ValidationException(ErrorCode.SORT_FIELD_INVALID, "field=" + request.sortField());
}
Sort.Direction direction = "desc".equalsIgnoreCase(request.sortDir())
        ? Sort.Direction.Descending : Sort.Direction.Ascending;
```

Allowlist, not blocklist. A list of forbidden characters can always be bypassed; a list of
permitted values cannot.

A bonus: the allowlist also restricts sorting to indexed columns — preventing an `ORDER BY`
on an unindexed column from crippling the database.

## Bid document upload

| Control | How |
|---|---|
| Type | Validate **magic bytes**, not `Content-Type` or the extension |
| Size | Hard limit per file and per request |
| Name | Generate a UUID; keep the original as metadata |
| Location | Object storage, outside the webroot |
| Access | Through an authorised endpoint, not a direct URL |
| Scanning | Antivirus before others can download it `[PENDING CLIENT]` |

A client-supplied filename may contain `../` or `..\`. Joining it into a path is path
traversal. **Always** generate a new name.

```java
// WRONG
Path target = dir.resolve(upload.fileName());

// RIGHT
String stored = UUID.randomUUID() + extensionFromMagicBytes(bytes);
Path target = dir.resolve(stored);
```

## Output

- **Never** return an entity — `passwordHash` serialises along with it.
- Errors without stack traces, table names, or SQL.
- Security headers on every response:

```properties
quarkus.http.header."X-Content-Type-Options".value=nosniff
quarkus.http.header."X-Frame-Options".value=DENY
quarkus.http.header."Referrer-Policy".value=strict-origin-when-cross-origin
quarkus.http.header."Strict-Transport-Security".value=max-age=31536000; includeSubDomains
```

## CORS

```properties
# WRONG — the demo setting
quarkus.http.cors.origins=*

# RIGHT
%prod.quarkus.http.cors.origins=${CORS_ORIGINS}
```

`origins=*` together with credentialed cookies lets any website call the API on behalf of a
logged-in user.

## Secrets

Never in code, never in properties (except as `${ENV_VAR}`), never in the repo, never in
logs, never in commit messages.

If one is committed: **rotate first**, then clean history. Deleting the file does not remove
it from history, and anyone who already cloned still has it.

---

## Security review checklist

For every PR touching auth, user input, or files:

- [ ] Every endpoint has `@RolesAllowed` or a deliberate `@PermitAll`
- [ ] Data-level authorisation is in the query, not a post-load filter
- [ ] No string concatenation into SQL/JPQL
- [ ] Dynamic sort/filter uses an allowlist
- [ ] Uploads: magic bytes, size limit, regenerated filename
- [ ] No entity returned as a response
- [ ] No new secrets
- [ ] Errors expose no internal detail
- [ ] Passwords/tokens/reserve price are not logged
- [ ] A test proves the wrong role is rejected
