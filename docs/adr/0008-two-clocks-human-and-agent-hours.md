# ADR-0008: Two clocks — human hours and agent hours are never summed

- **Date:** 2026-09-12
- **Status:** Accepted
- **Project:** workspace

## Context

Work in this workspace is done by people and by agents, often on the same task in the same
hour. Someone has to answer three different questions about that work: what to invoice a
client, what it cost to produce, and whether the team has capacity for more.

The tempting move is one "hours worked" number. It answers none of the three. A person
and three agents working for one hour is one billable hour, four hours of elapsed machine
work, and a token bill unrelated to either. Summed, the number overstates effort to the
client, understates cost to finance, and is useless for planning.

There is a second trap inside each category. Sessions overlap — a developer who forgets to
clock out of one project before starting another, or two agents running in parallel. Naive
summation of durations bills the same wall-clock hour twice.

## Decision

**Two clocks, recorded separately, reported side by side, never added.**

```bash
ws clock in <project-key> "what you are about to do"   # human
ws clock out "what actually happened"

ws agent in <project-key> "what the agent is doing"    # agent
ws agent out
```

Records are append-only JSONL in the **context** repository — hours are organisation data,
not framework data:

```
context/works/human/<project-key>/<YYYY-MM>.jsonl
context/works/agent/<project-key>/<YYYY-MM>.jsonl
```

Each line carries ISO timestamps for a human to read *and* epoch seconds, so reporting
needs no date parsing and therefore no dependency on GNU vs BSD `date`.

`ws hours` merges **overlapping intervals within each column** before totalling, so a
wall-clock hour is counted once however many sessions covered it. It prints a human total
and an agent total, and deliberately prints no combined figure.

`.gitattributes` gives these files the union merge driver: several people and agents append
to them concurrently, and both sides of a concurrent append are always right.

## Consequences

### Positive
- Invoices come from the human column, cost from the agent column, and neither has to be
  reconstructed from the other.
- Overlap merging makes the numbers defensible to a client who asks how they were derived.
- Hours live with memory and runs, so a project's state and its cost are in one repository
  with one access rule.
- Union merge means concurrent clock-outs never conflict.

### Negative
- Clocking in and out is a discipline, and discipline decays. An unclosed session is
  invisible until `ws doctor` reports it, which it now does.
- Agent hours are recorded by the agent itself, so they are as honest as the agent's
  instruction-following. They are a usage signal, not an audit trail.
- Elapsed agent time is not the same as agent cost. Tokens are the real cost driver and
  this system does not capture them.

### Neutral
- No MCP server, no daemon, no editor integration. Two shell commands and an append.

## Alternatives considered

| Option | Why rejected |
|---|---|
| **One combined "hours worked" number** | Answers none of the three questions it appears to answer, and inflates client-facing effort. |
| **Human hours only** | Loses the signal that shows where agents actually carry the work, which is the thing worth managing. |
| **Derive agent hours from tool transcripts** | Different for every tool, breaks whenever one changes its log format, and captures sessions where nothing was produced. |
| **Sum durations without merging overlaps** | Double-bills any wall-clock hour covered by two sessions. |
| **An MCP server for time tracking** | A daemon and a protocol for what an append-only file already does. Revisit if agents that cannot run shell commands need it. |
| **Store hours in the framework repo** | Hours are one organisation's data; the framework is shared and may be public. |

## Follow-up

- [x] `ws clock`, `ws agent`, `ws hours` implemented; `ws doctor` reports open sessions
- [x] Union merge for `context/works/**/*.jsonl`
- [ ] Capture token cost alongside agent hours once there is a tool-agnostic way to read it
- [ ] Monthly rollup written to a file, so a report does not have to re-scan every session
