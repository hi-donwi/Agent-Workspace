# Two clocks — human hours and agent hours

Moved out of `AGENTS.md` §8 so the contract fits every agent's rule budget. See also
[ADR-0008](adr/0008-two-clocks-human-and-agent-hours.md).

Record both. Never add them together.

**Human hours** are payroll and invoice hours: one person's attention, which cannot run in
parallel with itself. **Agent hours** are machine time — cheap, frequently several at once,
and paid for in tokens rather than salary.

A single combined number is wrong for every purpose it could serve. It overstates effort
to a client, understates cost to finance, and tells a lead nothing about capacity. So the
two are written to separate files and `ws hours` prints them in separate columns with no
total across them.

```bash
ws clock in <project-key> "what you are about to do"     # human
ws clock out "what actually happened"

ws agent in <project-key> "what the agent is doing"      # agent
ws agent out

ws hours --month 2026-09 --project <key>
```

Records land in the context repository, append-only, one file per project per month:

```
context/works/human/<project-key>/<YYYY-MM>.jsonl
context/works/agent/<project-key>/<YYYY-MM>.jsonl
```

Each line carries ISO timestamps for a human to read and epoch seconds so reporting needs
no date parsing. Reporting merges **overlapping intervals within each column**, so two
agents running for the same hour is one hour of elapsed work, not two — and a person who
forgets to clock out of one project before clocking into another is not billed twice.

Clocking out also rewrites `context/works/rollup/<YYYY-MM>.json` — a committed summary per
month, per project, per day, so an invoice or a dashboard never has to re-scan every
session file. It is derived, never authoritative; rebuild it any time with
`ws hours --rollup`.

Agents: clock in when you start substantial work on a project and out before you stop, in
the same breath as updating the run's `handoff.md`. A session nobody recorded is a session
that did not happen, as far as next month's invoice is concerned.

## Let the editor do the agent half

Agent hours that depend on an agent remembering are agent hours that go missing. Claude
Code can keep them itself:

```bash
ws hooks install     # writes .claude/settings.json; ws hooks remove undoes it
```

It clocks in on session start and out on stop, against this session's bind first, then
the product repo the working directory is in, then `workspace.conf`'s `default_project`.
The bind comes first because §4 tells everyone to open the editor at the workspace root,
where the directory is inside no product repo at all — without it the hook would record
nothing for exactly the sessions it was installed for. The hook never fails and never
blocks a session, and when none of the three answers, it records **nothing**. An hour on
the wrong project is worse than an hour on none.

Hooks run commands by themselves, so they are opt-in: the repository ships
`.claude/settings.json.example` and installing is a deliberate act. Human hours stay
manual on purpose — only the person at the keyboard knows when they actually started.

## `ws usage` — a third, optional, read-only axis

Hours answer "how long"; token usage answers "how much it cost." That is tracked by a
**separate personal tool this workspace does not own, vendor, or require** — commonly one
kept at `~/.agent-ops` (name it via `usage_source` in `workspace.conf` if it lives
elsewhere). `ws usage [--project <key> | --client <key>]` reads that tool's records
read-only, filtering by a project's or client's real project root, and never writes
anything back or copies its data into `context/`. Absent, `ws usage` says so plainly and
`ws doctor` treats it as informational, never a failure — most workspaces will not have
this tool installed at all.

---
