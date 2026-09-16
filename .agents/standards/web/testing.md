# Testing — Web pack

Tests are how module A still works after module B changed. They run in CI on every push.

---

## The pyramid

| Level | Scope | Where |
|---|---|---|
| **Unit** | Pure functions, mappers, domain rules — no browser, no network | `*.test.ts` next to the code or under `test/` |
| **Component** | One UI piece with its states (empty, error, loading, default) | Component test runner already in the repo |
| **Integration** | HTTP handler + real or test database | The project's integration harness |
| **End-to-end** | One user-visible flow | Playwright/Cypress only for flows that unit tests cannot cover |

Use the **project's declared test command**. Do not add a second runner.

**Coverage is a floor, not a goal.** Tests assert behaviour. `expect(fn).toBeDefined()` is
not a test.

---

## What must have a test

| Change | Test |
|---|---|
| New API route | Success, 400, 401/403, 404 |
| Business rule | Happy path **and every rejection** |
| Bug fix | A test that **fails before the fix** |
| Form / mutation UI | Invalid input and the success path |
| Authz change | The wrong role is rejected |

---

## What does not need tests

- Generated types and trivial one-line wrappers
- The framework itself (that Vite can bundle)
- Static copy with no logic

---

## Rules

- Tests are deterministic: no wall-clock sleeps, no live production URLs.
- Fixtures use obviously fake data. **Never** a production dump or real client records.
- Snapshot tests are allowed for stable serialised output, not for whole page HTML that
  changes with every class rename.
- A skipped test (`it.skip`, `xtest`) is a defect unless it names a ticket.

---

## Commands

Whatever `package.json` `scripts.test` (or the README) already says. Typical:

```bash
npm test
npm run test:watch
npm run test:e2e
```
