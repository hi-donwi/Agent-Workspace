# ADR-0024: Project management records

- **Date:** 2026-10-17
- **Status:** Accepted
- **Deciders:** Workspace maintainer
- **Project:** workspace

## Context

An operator who works for several clients at once needs one place to see and steer all of
the work: tasks and todos, a board, a backlog, milestones, due dates, reminders, and alerts.
They also need the facts about each client in that same place. Coding agents need to read and
change the same records, so the plan an agent follows is the plan the operator sees.

Part of this exists already. Operator tasks are one file per task in
`context/tasks/<key>/` (`ws task`). Runs carry an agent's plan. Project memory carries
stage, focus, and blockers. `context/clients/<c>/client.md` profiles each client. The hours
are kept in `works/` (ADR-0008). The desk reads these files and writes them through `ws`
(ADR-0023). What is missing: due dates and reminders, assignees, ordering, milestones,
client-level work that belongs to no project, a single view across clients, alerts, a
record of client interactions, and a way for agents to read all of this in a structured
form. There is also no rule yet for client facts that should never reach a model.

## Decision

All project management lives in the same records as before: files in `context/`, changed
only through `ws`, with every rule implemented once in the framework. The desk, the CLI,
the session pack, and an MCP server all go through that one implementation.

1. **Tasks, schema version 2.** A task keeps every version 1 field and gains the following
   optional fields:
   - `kind`: `task`, `milestone`, or `reminder`;
   - `due`: a date;
   - `remind_at`: a local time with its offset;
   - `recur`: `daily`, `weekly`, or `monthly`;
   - `assignee`: a person's key, or `agent:<tool>`;
   - `rank`: the manual order in the backlog;
   - `parent`: the milestone or larger task it belongs to;
   - `depends_on`: task ids.

   The body may hold a checklist (`- [ ]` lines) and an `## Activity` section, which `ws`
   appends to on every comment, status change, block, and edit. The entry records who did
   it, a person or an agent. Version 1 files are still read. A file is written as version 2
   the first time `ws` changes it, so an older `ws` refuses to write a version 2 file rather
   than silently dropping its new fields.
2. **Client-level tasks.** Work that belongs to a client and to none of its projects (a
   follow-up, an invoice pack) is a task with a `client` field and no project. These tasks
   live beside the client's profile, in `clients/<c>/tasks/`.
3. **No cycles.** The plan is a ranked backlog with due dates and milestones. A milestone
   is a task of kind `milestone` with a due date; its progress comes from the tasks whose
   `parent` names it. Sprints, burndown, and velocity are not modelled.
4. **Reminders and alerts are computed, not stored.**
   - A reminder is a task with `remind_at`. A recurring task, when done, gets its next
     occurrence.
   - `ws today` and `ws alerts` compute the following from the records, using thresholds
     in `context/pm.json`: what is overdue or due today, reminders that are due, blocked or
     stale work, reviews that are waiting, approvals that are pending, and agents that
     raised a hand.
   - Snoozes belong to one operator and stay in `.local/`.
   - Alerts are delivered only on the operator's machine: in the desk, as a browser
     notification, and in the tab title. No outside channel is used.
5. **Client records, with restricted classes.**
   - A client has its profile (`client.md`), its decisions, an append-only interaction
     log (`ws client log`), and its tasks.
   - Contacts (`contacts.md`) and commercial terms (`commercial.md`) are **restricted**.
     They are kept in `context/` and shown by the desk, but they are never written into a
     session pack, never returned by the MCP server, and never sent to a remote endpoint
     (ADR-0021).
   - Raw client documents stay in `.local/`, as before.
6. **Agents get the same records, within their bind.**
   - `ws task`, `ws today`, `ws alerts`, and `ws client` answer with `--json`.
   - `ws session bind` writes a work digest into `CONTEXT.md`: the bound project's open
     tasks, due and overdue work, blockers, and its client's tasks and profile.
   - `ws mcp` serves the same operations over stdio.
   - An agent bound to a project sees that project and its client, never another client
     (ADR-0011). Only the operator's workspace scope sees everything.
   - Adding, moving, and commenting on a task are `change` actions. Deleting work is
     `approval-required` (ADR-0014).

## Consequences

### Positive
- One truth: the operator, the desk, and every agent read the same tasks, alerts, and rules,
  and a rule changes in one place.
- No database and no sync service. The records merge in git like the rest of `context/`,
  and every change carries its author in the task's activity.
- Agents start every session knowing the project's priorities, without an extra call.
- Personal and commercial client data has a stated boundary that the tools enforce.

### Negative
- Computing alerts means scanning the records. That is cheap for hundreds of tasks per
  organisation, but it is not an index; a much larger backlog would need one.
- Activity appended to the task file makes busy tasks longer, and two writers editing the
  same task conflict, as they already do for status (the revision check refuses the second
  write).
- No sprints means no velocity: an operator who later wants time-boxed planning needs a
  further decision.

### Neutral
- Version 1 task files keep working; the desk's existing task views read version 2 files,
  which only add fields.
- The project room and the mission board keep their stations; the board across clients
  uses the same ones.

## Alternatives considered

| Option | Why rejected |
|---|---|
| A database (SQLite) behind the desk | Breaks the file-based, git-merged `context/`, and agents would need a second access path |
| Logic in the desk only | Agents would see a different truth than the operator, or none |
| An external tracker (Linear, Jira, GitHub Projects) | Client data leaves the machine, and agents need credentials and network access |
| Workspace-wide or per-client sprints | The owner chose a ranked backlog with milestones; time-boxing can come later |
| Contacts and commercial terms readable by agents | Personal and financial data would reach remote models (ADR-0021, AGENTS.md §8) |
| Alerts by email or chat | Task titles and client names would leave the machine |

## Follow-up

- [x] Task schema version 2 and the `ws task` commands (`add` flags, `edit`, `show`, `list --json`, `comment`, `check`)
- [x] Client-level tasks (`@<client>`), `ws remind`, recurrence
- [x] `ws today`, `ws alerts`, `context/pm.json`
- [x] Milestones (progress from children; `ws task list --kind milestone`)
- [ ] `ws client show|log`, restricted records
- [ ] Work digest in the session pack
- [ ] `ws mcp`
- [ ] The desk: Today, Missions board, Backlog, Timeline, Clients, Inbox
