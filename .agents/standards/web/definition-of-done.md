# Definition of Done — Web additions

These checks apply **on top of** `core/definition-of-done.md`. They apply only when the
`web` pack is enabled.

---

## For every change

- [ ] The project's declared verification command is green (`npm test`, `pnpm test`, …)
- [ ] No secrets in source, committed env files, or the client bundle
- [ ] No unsanitised HTML of user input
- [ ] Errors do not leak internals
- [ ] The run's `handoff.md` is updated

## For every HTTP endpoint

- [ ] Path, method, and status codes follow `core/api-contract.md`
- [ ] Authn/authz is explicit (public is a deliberate `@PermitAll` equivalent)
- [ ] List endpoints paginate
- [ ] Tests: success, 400, 401/403, 404 as applicable

## For every user-visible UI change

- [ ] Empty, loading, and error states exist
- [ ] Keyboard reachable; visible focus
- [ ] Contrast holds in the theme the app actually ships
- [ ] Layout checked at a mobile width, not only desktop

## For every delivery stage (per contracted proposal)

Stage names belong to the project's proposal. Record them in
`context/memory/projects/<key>/`, not here.
