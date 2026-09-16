# Locked Decisions — Web pack

Applies to TypeScript/JavaScript web and Node services when `web` is in `packs`.
Changing a line requires an ADR.

`[PENDING CLIENT]` = workspace default, awaiting confirmation at kick-off.

---

## Platform

| Item | Decision | Reason |
|---|---|---|
| Language | **TypeScript** (strict) | Types at the HTTP and UI boundary; `any` is a defect |
| Runtime | **Current Node LTS** | Match the project's `engines` field; do not invent a second runtime |
| Package manager | **The one already in the repo** | `package-lock.json` → npm; `pnpm-lock.yaml` → pnpm; `yarn.lock` → yarn |
| Module format | **ESM** unless the repo is already CJS | Do not mix `require` and `import` in new files |
| UI components | **Presentational** | No queries, no persistence, no raw `fetch` in a component when a `*Service` / `*Api` exists |
| Verification | **The project's declared command** | `npm test`, `pnpm test`, `vitest`, `node --test` — doctor does not invent one |

Do not assume Next.js, Vite, React, or a CSS framework. Those are project choices, recorded
in `context/memory/projects/<key>/project.md`.

---

## Deliberately not used

| Item | Why not |
|---|---|
| `any` as an escape hatch | It disables the reason TypeScript is required |
| Secrets in source or `.env` committed | Same rule as the rest of the workspace |
| Business logic inside a React/Vue/Svelte component | Unduplicable and untestable without a browser |
| Silent `catch {}` | Errors must surface or be translated into a domain error |

---

## Non-functional budgets

| Metric | Target |
|---|---|
| LCP (interactive pages) | < 2.5 s on a mid-range mobile profile |
| INP | < 200 ms |
| CLS | < 0.1 |
| Unauthenticated API | Never returns another user's data |
