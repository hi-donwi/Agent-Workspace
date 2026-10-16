# ADR-0023: The desk is the agent host's UI

- **Date:** 2026-10-16
- **Status:** Accepted
- **Deciders:** Workspace maintainer
- **Project:** workspace

## Context

ADR-0012 made the framework own a web desk (`apps/workspace-control`) served by a stdlib
Python control plane (`ws_web.py`, `ws web`). ADR-0019 then put a Node agent host
(Agent-Control) beside it: the host served the desk, ran the agents, and proxied every
other `/api/*` request to the Python process. On 2026-10-14 the desk, the Python server,
and `ws web` were removed so the web control could be redesigned.

The redesign asks for one place to manage context, memory, notes, and tasks, to work with
coding agents, and to see every client, project, and agent at once, with a desktop build
later. Every part of that except the record files already lives in the agent host: chat,
approvals (ADR-0020), endpoint egress (ADR-0021), project-bound tools (ADR-0011), coding
sessions in `ws agent start` worktrees, and the loopback security envelope.

Keeping a UI in the framework means every team that clones it carries a JavaScript app,
its lockfile, and later a desktop shell, and the public framework has to hold UI fixtures
that must never name a client. A second HTTP control plane means two processes, an
internal token, and a proxy hop for data the host can read from files.

## Decision

The desk is the default UI of the agent host, and it lives in the host's repository
(Agent-Control). The framework ships no web UI and no web server.

1. **One process.** The host serves the desk and its own API on loopback. There is no
   Python control plane to proxy to; ADR-0019's two-process layout and its internal token
   are retired.
2. **Reads from files, writes through `ws`.** The host reads workspace records directly
   and read-only: the registry, project memory and runs, open agent clocks (whose
   modification time is a heartbeat), local approvals, and coding sessions. Every change
   to context, memory, notes, tasks, runs, or clocks goes through a `ws` command run with
   `execFile` and an argument array (ADR-0019 §2 unchanged). New write paths arrive as new
   `ws` subcommands, testable without a browser.
3. **Records render as UIDL.** Drawer sections that show records are UIDL documents
   rendered by the published `uidl-runtime` package through one read-only data adapter,
   keeping ADR-0012's reason for UIDL. The floor and the drawers are the host's own code.
4. **Poses come from events.** An agent's displayed activity must trace to a recorded
   event. Agents outside the host show presence only (open clock, recent heartbeat) until
   they report activity through `ws hooks`.
5. **Entry point.** `ws chat` starts the host, and with it the desk.
6. **Desktop.** A desktop build is a Tauri v2 shell in the host's repository that runs the
   host as a sidecar and opens the same loopback origin. It changes nothing here.

## Consequences

### Positive
- The UI and the API it calls change together, in one repository with one test harness.
- The framework stays a contract, a stdlib CLI, and documents; cloning it pulls no UI.
- Writes still pass through `ws`, so the rules that guard context (attention isolation,
  run ownership, clocks) are enforced in one place.

### Negative
- The desk needs Node. The Python-only fallback desk of ADR-0012 is gone.
- The host now depends on file layouts it reads directly: registry header names, run file
  names, the open-clock file name and fields. A change to any of them needs a matching host
  change, and nothing checks the pair yet.
- `ws chat` still finds the host through the registry or a checkout path, not an installed
  package (ADR-0019 follow-up, still open).

### Neutral
- ADR-0020 (approvals) and ADR-0021 (egress) apply unchanged; the operator still approves
  on loopback.
- The operator sees every registered project on one floor. Agents remain bound to one
  project each (ADR-0011); the floor is the operator's view, not an agent's context.

## Alternatives considered

| Option | Why rejected |
|---|---|
| Restore `apps/` in the framework | Every clone carries the UI and a later desktop shell; public UI fixtures risk naming clients; the subsystem was just removed for this reason. |
| A new repository for the desk alone | Splits the UI from the host whose API it calls and doubles the loopback, token, and CSP work for no gain. |
| The companion app inside UIDL-Runtime | Ties a library's release cycle to one consumer's product UI. |
| Revive `ws_web.py` as the control plane behind the host | A second process, an internal token, and a proxy hop to serve data the host can read from files; writes already go through `ws`. |
| Electron for the desktop build | Larger download and memory footprint; Tauri reuses the system webview and keeps the host unchanged as a sidecar. |

## Follow-up

- [x] ADR-0012 marked superseded; ADR-0019 notes the single-process layout
- [x] Desk phase 1 in the host: floor, menu and assistant drawers, read-only API
- [ ] `ws hooks` emits activity events the floor can show for external agents
- [ ] `ws note` and `ws task` (or retire `.agents/bin/ws_tasks.py`, which has no caller)
- [ ] Compatibility fixtures for the files the host reads (registry, runs, open clocks)
- [ ] `ws chat` resolves an installed host instead of a checkout path
