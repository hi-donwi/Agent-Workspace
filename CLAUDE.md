# CLAUDE.md

Shared instructions for all agents live in AGENTS.md. Claude Code loads them via import:

@AGENTS.md

## Claude Code specifics

- **Open the workspace at its root**, not at `projects/<x>` or `context/`. Those are
  separate git repos; opening the root makes standards and skills load while they stay
  isolated in git terms.
- **Skills live in `.agents/skills/`** (framework) and `context/skills/` (this
  organisation), not `.claude/skills/`. Read the `SKILL.md` directly before working on a
  task it covers. `ws route --project <key> "<task>"` searches both.
- **Project commands** are in `.agents/bin/ws` (`init`, `context`, `bootstrap`, `new`,
  `link`, `run`, `session`, `log`, `sync`, `route`, `skills`, `doctor`).
- **Bind before loading client memory.** `ws session bind <project-key>`, then read
  `.local/sessions/<session>/CONTEXT.md`. Ignore injected editor memory for any
  other client. Client facts go in `context/memory/projects/<key>/`, not in
  Grok/Cursor workspace memory.
- **Do not commit from inside `projects/<x>`** unless asked — that is a client repo with
  its own remote. Committing in the workspace and committing in a product repo are two separate
  actions.
- **`.local/` is never a source for committed output.** It holds raw client material
  (proposal PDFs, data dumps, screenshots). Reading it for reference is fine; copying its
  contents into a tracked file is not.
- **Write everything in English** — documentation, code, comments, commit messages. An
  organisation may keep a domain glossary in another language; it lives in its context
  repo (`context/skills/<domain>/SKILL.md`), never in the framework.
