# .agents/

Everything an AI agent or a new developer needs to work to the standards in this workspace — kept in one place,
versioned in git, shared across the team, and reused by every project.

| Folder | Contents | Changes |
|---|---|---|
| `standards/` | Binding engineering rules | Rarely, via ADR |
| `skills/` | Task workflows an agent reads before starting | When practice improves |
| `memory/` | Per-project durable context | When a project's shape changes |
| `runs/` | Per-task working memory | Constantly, during work |
| `templates/` | Starting points for ADRs, runs, specs | Rarely |
| `bin/` | The `ws` CLI | Rarely |

## The distinction that matters

| | Question answered | Lifetime |
|---|---|---|
| `standards/` | "What is correct?" | Years |
| `skills/` | "How do I do this?" | Months |
| `memory/` | "What is true about this project?" | Project lifetime |
| `runs/` | "What is happening on this task right now?" | Days |

When a run produces a conclusion that will still matter in three months, promote it to
`memory/` or an ADR. Otherwise it dies with the run — which is correct.

## Reading order for a new agent

1. `../AGENTS.md` — the contract
2. `standards/java/00-decisions.md` — what is already settled
3. The `skills/<name>/SKILL.md` matching the task
4. `memory/projects/<key>/active.md` — where the project stands
5. The latest run under `runs/<key>/` — where the work stands

## Not stored here

- Secrets, credentials, keys — ever
- Client documents, data dumps, screenshots → `.local/` (git-ignored)
- Product source code → `projects/<key>/` (separate repos)
- Large raw logs
