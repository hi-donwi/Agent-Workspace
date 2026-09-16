# Security — Web pack

A leak of session cookies, tokens, or another user's records is a product defect, not an
ops incident to file later.

---

## Secrets

Never in source, never in committed `.env`, never in client bundles, never in logs.

- Server secrets stay in the environment. The committed file only names them (`DB_URL=` empty).
- Anything shipped to the browser is public. API keys that must stay secret do not go in
  `VITE_*` / `NEXT_PUBLIC_*` / `window.__CONFIG`.
- If a secret is committed: **rotate first**, then clean history.

---

## Authentication and cookies

| Item | Decision |
|---|---|
| Session cookie | `HttpOnly; Secure; SameSite=Lax` (or `Strict` if the app is first-party only) |
| JWT in `localStorage` | **No** — XSS steals it. Prefer a cookie or memory + refresh |
| Login errors | Identical message for unknown user and wrong password |
| CSRF | SameSite + origin check on cookie-authenticated mutations |

Rate-limit login per account and per IP. Never log the password.

---

## Authorisation

`@RolesAllowed` is a Java pattern. On the web pack the equivalent is: **every mutation
declares who may call it**, and list endpoints filter **in the query**, not after load.

```
WRONG  fetch all rows, then filter by the current user in JS
RIGHT  the query/predicate includes the owner or tenant
```

A 401 means we do not know who you are. A 403 means we do, and the answer is no.

---

## Browser threats

| Threat | Rule |
|---|---|
| XSS | Render untrusted text as text. Markdown/HTML is sanitised. `innerHTML` with user data is a defect |
| Open redirect | Allowlist redirect targets |
| CORS | Explicit origins in production. `Access-Control-Allow-Origin: *` with credentials is forbidden |
| Uploads | Magic-byte check, size cap, generated filename, stored outside the webroot |
| Dependency CVEs | No CVSS ≥ 7 at release without a documented exception |

---

## Review checklist

- [ ] Mutations authenticate and authorise
- [ ] No secret in the client bundle
- [ ] No `innerHTML` / `dangerouslySetInnerHTML` of unsanitised input
- [ ] Errors do not include stack traces, SQL, or file paths
- [ ] A test proves the wrong caller is rejected
