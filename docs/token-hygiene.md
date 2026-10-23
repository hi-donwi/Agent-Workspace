# Token hygiene — why input tokens grow and how to keep them down

Agent input tokens dwarf output tokens (a 160:1 ratio is normal for agentic work) because
every turn re-sends the whole context: instructions, history, and file reads. Cost is
decided less by any single file than by **what re-sends** and **whether the cache hits**.

## Session length is the biggest lever

Each request re-reads the whole context, so a session's cost is roughly *context size ×
number of requests*, and both grow the longer one session is kept. One workspace measured
45 sessions of a 1M-window model: the first request carried ~45K tokens (the instruction
payload below was ~1.5% of an average request), but the **mean request carried ~385K**,
because sessions ran until the window was nearly full before the tool compacted them.
Requests above 400K produced 69% of all cache reads. Replaying those sessions with a
300K auto-compact window roughly halved their input-side cost, compaction overhead included.

Two habits caused most of it, and both had grown recently: one session reused for several
tasks, and sessions **resumed after a break**. A prompt cache lasts minutes to an hour; the
first request after it expires re-writes the whole context at the cache-write price
(2× input on a 1-hour cache), then every later request re-reads it. In that workspace 57% of
all cache-write tokens were such full rewrites.

So, for every agent (`AGENTS.md` §6, rule 6):

- **One task, one session.** Finish, `ws checkpoint`, and start fresh; the run's
  `handoff.md` is the continuity, not the transcript.
- **Do not resume a session idle for over an hour**; start a new one from the handoff.
- **Fewer, larger tool calls.** Each tool call is one more full-context request: read
  several files in one call, and hand broad searches to a subagent where the tool has one,
  so only its conclusion enters the main context.
- **Compact earlier** where the tool allows it — see the next section.

## Per-tool settings

User-level settings, not tracked here. Each was checked against the version noted.

| Tool | Setting (file) | Value | Notes |
|---|---|---|---|
| Claude Code | `env.CLAUDE_CODE_AUTO_COMPACT_WINDOW` (`~/.claude/settings.json`) | `300000` | Compacts at 300K instead of near a 1M window. Range 100000–1000000. |
| Claude Code | `effortLevel`, `modelSettings.<model>.effortLevel` | `high` | Raise per hard task with `/effort`; thinking is output, the dearest token. |
| Codex (0.155) | `model_auto_compact_token_limit` (`~/.codex/config.toml`) | `250000` | Below every catalogue model's window (272K–500K), so it applies to all. |
| Gemini CLI (0.40) | `model.compressionThreshold` (`~/.gemini/settings.json`) | `0.3` | Fraction of the window; default `0.5`. |
| opencode (1.19) | `compaction.prune` (`~/.config/opencode/opencode.jsonc`) | `true` | Drops old tool outputs. Its compact threshold is per model (`limit.input − reserved`), so there is no absolute window to set. |
| Kilo, Antigravity, Cursor, Copilot, Codebuff | — | — | No equivalent setting found; `AGENTS.md` §6 rule 6 is what reaches them. |

`ws usage` lists each heavy record's start-to-end span and warns when sessions ran longer
than 8 hours, so the habits above can be checked rather than assumed.

## The instruction payload (what every tool loads whole)

| Payload | Size | Where it loads |
|---|---|---|
| `AGENTS.md` | ~13 KB | Every tool, every turn — keep it under 13 KB (13,312 bytes) |
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
   abandoned/superseded rows, including annotations separated by ` - `, ` – `, ` — `,
   or `: ` (for example, `done - delivered`). Ambiguous states such as `done pending review`
   remain open. An `active.md` that is large because of genuinely open,
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
ws usage                                   # records, measured input/output, cache hit %, and coverage
ws usage --month 2026-09 --project <key>   # per project or client; heaviest records with their span, long-session warning
ws doctor                                  # shared session ids, abandoned clocks, worktree noise, memory nearing the pack limit
ws agent recover                           # close clocks left open by dead sessions
```

`ws usage` separates detailed usage from unavailable or total-only records and reports
exact duplicate records it suppressed. Check coverage before comparing cache rates:
unknown cache usage must not be interpreted as a measured cache miss. The heaviest
records are ranked by cache reads, which can indicate successful reuse rather than waste.
Compare similar workloads; there is no universal cache-hit threshold that proves a problem.
See [hours.md](hours.md#ws-usage--a-third-optional-read-only-axis) for attribution and
snapshot-accounting limits. Reliable multi-agent cost review also needs request identity,
parent/child ancestry, and provider-specific token semantics from the collector.
