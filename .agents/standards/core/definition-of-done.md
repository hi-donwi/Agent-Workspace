# Definition of Done

"Done" means releasable, not "I finished typing the code".

This is the universal bar. A stack pack may add checks on top of it (see
`java/definition-of-done.md` for the Java additions) — it may not remove any.

---

## For every change

- [ ] The project's declared verification command is green locally (`./mvnw verify`, `go test ./...`, `npm test` — whichever the project defines)
- [ ] Pipeline green
- [ ] Coverage has not dropped
- [ ] No debug output, unhandled stack traces, or empty `catch`
- [ ] No `TODO` without a ticket ID
- [ ] No new secrets in code, properties, or commit messages
- [ ] No sensitive data in logs
- [ ] Commits follow Conventional Commits with a ticket reference
- [ ] MR under ~400 changed lines
- [ ] The run's `handoff.md` is updated (`context/runs/<key>/<run>/`)

## For every architecture decision

- [ ] An ADR in `docs/adr/` using `.agents/templates/adr.md`
- [ ] Rejected alternatives named with the reason
- [ ] If it deviates from `.agents/standards/`, the ADR names which standard

---

## Not done

Common claims that are still rejected:

| Claim | Why it is not done |
|---|---|
| "Works on my machine" | Not yet verified in the pipeline against real data |
| "Tests come later" | Tests are part of the change, not separate work |
| "The endpoint exists" | Without authorisation and contract documentation the frontend cannot use it |
| "We'll refactor it later" | Refactoring without a ticket never happens |
| "I checked it manually" | A manual check does not repeat on the next release |
| "It's only a small change" | Change size does not alter the standard |
