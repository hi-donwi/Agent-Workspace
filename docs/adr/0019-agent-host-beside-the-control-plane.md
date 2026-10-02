# ADR-0019: Agent host beside the control plane

- **Date:** 2026-10-02
- **Status:** Accepted
- **Deciders:** Workspace maintainer
- **Project:** workspace

## Context

The web desk of ADR-0012 is a stdlib Python server on loopback. It reads projects, context,
runs, and health, and mutates tasks, git links, and clocks. It cannot run an agent.

The desk is now required to act as a coding assistant as well: edit files, run commands,
review diffs, run several agents and tasks at once, and talk to several LLM providers
through OpenAI-compatible and Anthropic-compatible APIs. That needs things the stdlib
server does not have and should not grow:

- streaming responses and long-lived sessions (an agent turn, a live terminal);
- supervision of many child processes that may hang, crash, or need to be killed;
- LLM clients with tool calling for more than one wire protocol.

Adding these to `ws_web.py` would end the zero-dependency property that every `ws`
command relies on. ADR-0012 rejected "Replace the Python server with a Node service"
because it did not help the workflows requested *then*. The workflows requested now are
the ones a Node runtime does help.

Meanwhile, `ws chat` already launches a separate companion chat application from a
product checkout, found through a registry key or else a fixed checkout path. That is the
setup dependency ADR-0012 removed for the desk UI, back again for the agent.

What the framework already provides is most of an agent's safety envelope:
`ws agent start` (worktree, agent clock, session lock), `ws session bind` and
`ws context pack` (ADR-0011), `ws run`, `ws policy check` (ADR-0014), `ws verify`
(ADR-0013), and `ws eval` (ADR-0015). What is missing is a runtime that uses them on every
step instead of trusting an agent to.

## Decision

We split the web control into two roles with one owner each.

1. **Control plane: `ws` and `ws_web.py`.** It is the only writer of the registry,
   context, runs, tasks, clocks, policy decisions, and verification reports. It stays
   Python standard library only, and remains fully usable without Node.
2. **Agent host: a Node/TypeScript runtime.** It owns LLM calls, the agent loop, tool
   execution, sandboxing, streaming, and process supervision. It does not write context
   files itself: it calls `ws` (through `execFile` with argument arrays, never a shell
   string) or the control-plane API. Its only own state is a replayable event log per
   agent session under `.local/agent/sessions/<session-id>/`.
3. **Distribution.** The agent host is a separately versioned npm package, installed
   into `apps/workspace-control` from a lockfile, exactly as ADR-0012 installs
   `uidl-runtime`. Its source is never copied into the framework, and `ws` does not find
   it by looking for a product checkout at a fixed path. A development override names a
   local build explicitly through an environment variable.
4. **One origin.** `ws web` stays the entry point. Without Node, or without `--agent`,
   it is the Python desk of ADR-0012, unchanged. `ws web --agent` starts both processes
   and stops them together: the agent host is the browser-facing loopback server. It
   serves the desk and proxies `/api/*`, except its own `/api/agent/*`, to the control
   plane on a second loopback port, using an internal token the browser never receives.
   This revises ADR-0012's rejection of a Node service, for agent mode only.
5. **Every agent session is a framework agent.** A session starts through
   `ws agent start <key>`: its own worktree, clock, lock, and bind. It never runs in the
   primary checkout. Its file tools accept only paths inside its worktree plus the files
   its session pack lists, so ADR-0011 is enforced by the tool layer rather than requested
   in a prompt. Each session runs in its own process. External agent CLIs run in headless
   mode as drivers inside the same boundary, and are not a second architecture.
6. **Every tool call is classified before it runs.** The host maps the call to an
   action label and asks `ws policy check`. `read` and `change` proceed. For
   `approval-required`, the session pauses until a local approval exists (ADR-0020) or
   is denied. Which endpoints may receive a project's context is decided by ADR-0021.
7. **Done is still `ws verify`.** An agent's change is complete when the project's
   verification contract passes. Comparisons between agents or models use `ws eval`
   observations, not an agent's own report.
8. **Same envelope as ADR-0012, tightened.** The host binds to loopback only, checks
   `Host` and `Origin`, and allows no cross-origin access. Because it executes commands,
   the browser no longer receives its credential in a URL: a one-time code printed by
   `ws web` is exchanged for an `HttpOnly`, `SameSite=Strict` session cookie.

## Consequences

### Positive
- The desk can host coding agents without the Python server growing dependencies.
- Worktree isolation, attention isolation, policy, clocks, and verification apply to
  every agent step by construction, whichever model or driver runs it.
- Several agents can work on the same project at once, because each owns a worktree and
  a session, which the framework already supports.
- `ws chat` loses its dependency on one organisation's checkout layout.

### Negative
- Agent mode requires Node, and two processes have to be started, supervised, and stopped
  together.
- The control-plane HTTP API becomes an interface another package depends on. It needs
  versioning and compatibility tests (ADR-0016) where it had a single in-repo consumer.
- One more package to version, pin, and audit.
- Proxying adds a hop to every control-plane request in agent mode.

### Neutral
- The Python-only desk remains the default and the fallback.
- The three-repository rule is unchanged: the agent host's source lives in its own
  repository, and the framework only installs it.

## Alternatives considered

| Option | Why rejected |
|---|---|
| Agent runtime inside `ws_web.py` | Hand-written clients for several LLM protocols, streaming, and process supervision in the standard library. It ends the zero-dependency property of `ws` and puts the riskiest code in the least testable place. |
| Python stays browser-facing and proxies to Node | Proxying streaming responses and connection upgrades through `http.server` is fragile, and each new stream type means changes in two servers. |
| The agent host as a separate origin | ADR-0012 closed cross-origin access on purpose. A second origin means a second token in the browser and CORS on an API that executes commands. |
| Only wrap external agent CLIs | No control over which endpoint receives context, and no policy hook inside their loop. They are kept as drivers under the host, not as the only engine. |
| Copy the agent host source into the framework | Two diverging copies of the same code, and a product's source inside the framework, which ADR-0006 forbids. |

## Follow-up

- [x] ADR-0012 gains a note pointing at this ADR for agent mode
- [ ] Control-plane API version and compatibility fixtures
- [ ] `ws web --agent`, and `ws chat` resolving the installed package instead of a checkout path
- [ ] `ws session bind` / `ws agent start` accept the framework key (they fail today)
- [ ] Mock LLM provider for end-to-end tests, so CI never calls a real endpoint
