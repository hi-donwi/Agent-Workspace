# Token hygiene — why input tokens grow and how to keep them down

Agent input tokens dwarf output tokens (a 160:1 ratio is normal for agentic work) because
every turn re-sends the whole context: instructions, history, and file reads. Cost is
decided less by any single file than by **what re-sends** and **whether the cache hits**.

## The instruction payload (what every tool loads whole)

| Payload | Size | Where it loads |
|---|---|---|
| `AGENTS.md` | ~13 KB | Every tool, every turn — keep it under 20 KB |
| Hard-rules copies | 4 × ~1.8 KB | `GEMINI.md`, Copilot, Cursor, `.agents/rules/` (generated from one block) |
| Skill `description:` frontmatter | ~0.3 KB × 48 | Tool skill pickers; `index.json` (~16 KB) only when a tool reads it |
| Product repo `AGENTS.md` | project-specific | Only while working in that product |

Keep each item lean; do not duplicate content between them — link to `docs/` instead.

## Cache hits are the real lever

A stable prompt prefix is cached (at a large discount); a changing one is billed full
price every turn. The usual cache killers, all seen in real sessions:

1. **One task, one tool.** Switching between agents mid-task restarts the prefix from
   the new tool's template. Finish, or start fresh, rather than interleaving.
2. **Unique `WS_SESSION_ID` per session** (hard rule 6). Sharing `default` also mixes
   clocks and binds between concurrent agents — `ws doctor` reports both.
3. **Stable file order.** Agents that re-read the same files in a different order break
   the prefix after the first difference.
4. **Index noise is context noise.** Worktrees outside `.local/worktrees/`, build
   artifacts (`.wrangler/`), `.DS_Store`, and a mirror of this same framework under
   `projects/` all get surfaced by workspace-root search and then pasted into context.
   `.ignore` keeps the mirror's duplicate instruction payload out of the index.
5. **Client material is the heaviest noise there is.** A single pasted screenshot is
   ~100 KB of base64 in every context that touches the file. Chat transcripts, dumps,
   and screenshots belong in `.local/` (git-ignored, search-excluded, never pushed) —
   never under `context/memory/`, which `.ignore` deliberately makes searchable. One
   real case: a 2.4 MB chat-transcript backup with inline screenshots, stored twice,
   sat in a project's `notes/` for weeks.

## Reading discipline

- Read windows (`offset`/`limit`), not whole large files; search first, then read around
  the hit.
- Stop loading at the loading-order table in `AGENTS.md` §4 — do not read another
  project's memory because it is adjacent on disk.
- Prefer the model tier the task needs: a thinking tier on every small turn is the most
  expensive habit in the stack.

## Watch it

```bash
ws usage                                   # sessions, input, output per day
ws usage --month 2026-09 --project <key>   # per project or client
ws doctor                                  # shared session ids, abandoned clocks, worktree noise
ws agent recover                           # close clocks left open by dead sessions
```

A cache-hit rate well under ~50% with a high request count usually means one of the four
cache killers above, not a workload that genuinely re-reads that much.
