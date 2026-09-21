# Project layout — Web pack

One product repo, one layout. Do not invent a second `src/` tree.

---

## Layers

| Layer | Form | May do | Must not |
|---|---|---|---|
| UI | `*Page`, `*View`, `*Component` | Render, bind events, call a service | Query a database, hold secrets, encode business rules |
| Domain | `*Service`, `*UseCase` | Rules, orchestration | Import React/Vue/Svelte |
| Data | `*Repo`, `*Store`, `*Db` | Persistence | HTTP status codes |
| Integration | `*Api`, `*Client` | Talk to other systems | Be called from a component when a service exists |
| Contract | `*Request` / `*Response` types | Shape the HTTP/UI boundary | Be a database row dumped to JSON |

Agents **must not**:

- put SQL or ORM calls inside a component or page
- return an internal record as a JSON response
- duplicate the same fetch across three screens instead of lifting it into a service
- add a new HTTP client when one already exists for that host

---

## Files

Follow the repo you are in. Typical TypeScript:

```
src/
  ui/           or app/, pages/, components/
  domain/       or services/
  data/         or db/, repositories/
  http/         or api/, clients/
test/           or *.test.ts next to the source
```

A folder nobody owns is a folder nobody maintains. Record owners in
`context/memory/projects/<key>/project.md`.
