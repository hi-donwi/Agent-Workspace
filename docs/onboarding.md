# Onboarding — First Day

For a developer or an AI agent joining a project in this workspace.

---

## 1. Set up (15 minutes)

```bash
git clone <workspace-remote> workspace && cd workspace
echo "export PATH=\"$PWD/.agents/bin:\$PATH\"" >> ~/.zshrc && source ~/.zshrc

ws bootstrap     # clone the product repos
ws ide           # copy the shared VS Code defaults into this clone
ws doctor        # verify toolchain and repo isolation
```

Clone it wherever you like. Nothing tracked in this repo assumes a path, so your location
never has to match anyone else's; `ws where` resolves the root from anywhere.

Runs and log entries are attributed to you by the local part of your git email. If that
gives an awkward handle, set your own once: `export WS_USER=doni` in your shell profile.

`ws doctor` must be green before you write anything. It checks Java 21, git, Docker (needed
for Testcontainers), that no product repo has leaked into this repo's git index, that
`.local/` is ignored, that no tracked file carries one machine's absolute paths, and that
each product repo still has its pointer, its exclude entries, and its commit guard.

**Open your editor at that root**, not at `projects/<x>`. Agents find rules by walking up
the directory tree; opening the root makes standards and skills load while the product repo
stays isolated in git terms.

---

## 2. Read, in this order (60 minutes)

| # | File | What you get |
|---|---|---|
| 1 | [`../AGENTS.md`](../AGENTS.md) | How we work. The contract. |
| 2 | [`../.agents/standards/README.md`](../.agents/standards/README.md) | Which standards packs apply here |
| 3 | [`../.agents/standards/java/00-decisions.md`](../.agents/standards/java/00-decisions.md) | What is already settled, and why — **only if** `java` is in `packs` |
| 4 | `../context/docs/` | What this organisation is building, and by when |
| 5 | `../context/skills/<domain>/SKILL.md` | The business domain, if your organisation has one |
| 6 | `../context/memory/projects/<key>/active.md` | Where your project stands today |

Items 4–6 live in the [context repository](context-repository.md), which is specific to
your organisation. Run `ws list` to see which project keys exist.

Do not read all twelve standards up front. Read the one the task needs, when the task needs
it — `ws route "<task>"` will point you at it.

---

## 3. Your first change

1. **Pick up the ticket.** Confirm its scope against
   [`../.agents/standards/core/definition-of-done.md`](../.agents/standards/core/definition-of-done.md).
2. **Find the skill:** `ws route "your task description"`. Read that `SKILL.md` first.
3. **Create a run:** `ws run <project-key> "short title"`. Fill in `brief.md`.
4. **Spec the endpoint** using `.agents/templates/endpoint-spec.md`, if it is an endpoint.
5. **Write the failing test** before the implementation.
6. **Implement**, in the layer order: migration → entity → repository → service → resource.
7. **Verify:** `./mvnw verify`, regenerate the OpenAPI spec.
8. **Commit** per [`git-workflow.md`](../.agents/standards/core/git-workflow.md).
9. **Update `handoff.md`** before you stop, even if the work is finished.

---

## 4. Things that surprise people

| Expectation | Reality |
|---|---|
| "`projects/<group>/<repo>` is part of this repo" | It is a separate git repo with its own remote. Committing here and committing there are two actions. |
| "The demo is the starting point" | It is a proof of concept. The gap to production is tabulated in `quarkus-service/SKILL.md`. |
| "Latest Quarkus means the highest version" | It means the latest **LTS** (3.33.x). Non-LTS is supported for about a month. |
| "H2 is fine for tests" | Not here. It differs from PostgreSQL exactly where reporting and money are concerned. |
| "I'll add tests after" | A change without tests does not pass review. |
| "The standards are suggestions" | They are binding. Deviating is fine — through an ADR. |

---

## 5. Where to put things

| Thing | Where |
|---|---|
| Product code | `projects/<group>/<repo>/` (separate repo) |
| A standard that applies to every project | `.agents/standards/` |
| A workflow for a kind of task | `.agents/skills/<name>/SKILL.md` |
| Durable project context | `context/memory/projects/<key>/` (separate repo) |
| What you are doing right now | `context/runs/<key>/<run>/` |
| An architecture decision about the workspace itself | `docs/adr/` |
| An architecture decision about a project | `context/docs/adr/` |
| A client PDF, a data dump, a screenshot | `.local/` — **always**, it is git-ignored |
| A secret | Nowhere in any repo. Environment variables only. |

---

## 6. Getting unstuck

| Situation | Do this |
|---|---|
| Not sure which skill applies | `ws route "<task>"` |
| Not sure if something is allowed | Check `.agents/standards/`; if it is silent, ask the Lead Developer and write an ADR |
| A standard seems wrong | Say so. Change it through an ADR — do not work around it silently. |
| Picking up someone else's work | Read that run's `handoff.md` first, not the diff |
| Something in memory contradicts the code | The code is right. Fix the memory. |
| A merge conflict in `context/memory/` | `log.md` and `registry.tsv` merge themselves. In `index.md` or `decisions.md`, keep both sides unless they state the same fact differently — then ask whoever wrote the other one. |
| `index.json` conflicts | Do not hand-merge it. `ws skills`, then commit. |
