# Token hygiene — why input tokens grow and how to keep them down

Agent input tokens dwarf output tokens (a 160:1 ratio is normal for agentic work) because
every turn re-sends the whole context: instructions, history, and file reads. Cost is
decided less by any single file than by **what re-sends** and **whether the cache hits**.

## The instruction payload (what every tool loads whole)

| Payload | Size | Where it loads |
|---|---|---|
| `AGENTS.md` | ~13 KB | Every tool, every turn — keep it under 20 KB |
| Hard-rules copies | 4 × ~1.8 KB | `GEMINI.md`, Copilot, Cursor, `.agents/rules/` (generated from one block) |
| Skill `description:` frontmatter | ~0.6 KB × 65 | Tool skill pickers; `index.json` (~29 KB) only when a tool reads it |
| Product repo `AGENTS.md` | project-specific | Only while working in that product |

These two numbers only grow as skills get added (`.agents/skills.manifest`). If a tool's
skill picker starts loading every description on every turn rather than one summoned by
keyword match, check this table against `ls .agents/skills | wc -l` before assuming the
instruction payload is still the small part of the prompt.

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

## Compacting — the two separate things that name means here

"Compact" covers two unrelated operations; conflating them is how one gets assumed to
cover the other.

1. **The conversation's own compaction** (the tool's built-in transcript fold, `/compact`,
   or the context window filling up). `ws hooks install` wires a `PreCompact` hook to
   `ws checkpoint` and a `SessionStart` hook (matched on `compact`) to
   `ws session compact-reminder`, so the fold does not cost a bound session its pending
   run/memory commits or the CONTEXT.md allowlist it is working under. See
   `docs/memory-and-runs.md#compaction` for what each hook actually does.
2. **`ws compact memory <key> [--apply]`** — an explicit, operator-run command, never
   fired by a hook, that archives milestones past the newest 15 out of `log.md` (to
   `log-archive.md`) and drops closed runs past the newest 3 out of `active.md`'s table.
   It exists because `context-pack` (what `ws session bind` builds) refuses any single
   memory file over 32 KiB and the whole pack over 128 KiB — `ws doctor` warns once a
   project's `active.md`/`log.md` passes 16 KiB and fails once one is actually over the
   limit, naming this command as the fix. It only touches closed/done/dropped/merged/
   abandoned/superseded rows; an `active.md` that is large because of genuinely open,
   in-progress work needs a person to curate it, not this command.
3. **`ws compact exec -- <cmd>`** — runs a command and condenses its output (by line
   count and, per line, by character count) before printing it, while saving the command's
   full, untouched output to `.local/logs/`. Reach for this around any command that might
   dump a long diff, a full test run, or a large build log straight into context.

## Reading discipline

- Read windows (`offset`/`limit`), not whole large files; search first, then read around
  the hit.
- Stop loading at the loading-order table in `AGENTS.md` §4 — do not read another
  project's memory because it is adjacent on disk.
- Prefer the model tier the task needs: a thinking tier on every small turn is the most
  expensive habit in the stack.

## Watch it

```bash
ws usage                                   # sessions, input/output, cache hit % per day and per tool
ws usage --month 2026-09 --project <key>   # per project or client; also lists the heaviest sessions
ws doctor                                  # shared session ids, abandoned clocks, worktree noise, memory nearing the pack limit
ws agent recover                           # close clocks left open by dead sessions
```

`ws usage` prints a per-tool cache-hit rate and the heaviest sessions by cache read, not
just totals — a cache-hit rate well under ~50% for one tool, or a handful of sessions
holding most of a month's cache reads, usually means one of the cache killers above hit
that tool or that session, not a workload that genuinely re-reads that much.
