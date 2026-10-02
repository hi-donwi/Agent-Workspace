# ADR-0021: LLM endpoints by protocol, and context egress per project

- **Date:** 2026-10-02
- **Status:** Accepted
- **Deciders:** Workspace maintainer
- **Project:** workspace

## Context

The agent host of ADR-0019 sends prompts to LLM endpoints. Those prompts contain what an
agent works with: the files of a session pack, product source code, command output, and
diffs. `AGENTS.md` already says client data must not reach third-party services, and
every session pack ends with "not approved for cloud upload". Nothing enforces either
statement yet.

The agent host must also be multi-provider: endpoints compatible with the OpenAI API,
endpoints compatible with the Anthropic API, and vendors that expose one of those
interfaces. Two failure modes are likely:

- **Per-vendor code.** Each new vendor needs a code change and a release, though most of
  them speak one of a few wire protocols.
- **Egress as a dropdown.** The model picker in a chat UI quietly decides where a client's
  code goes, message by message, with no record and no rule.

## Decision

**Endpoints are configured by wire protocol, not by vendor.**

1. The agent host implements three protocols: `openai-chat` (Chat Completions and
   compatible APIs), `openai-responses`, and `anthropic-messages`. A vendor is a named
   endpoint: a base URL, a protocol, a credential reference, and optional per-model
   capability overrides (tool calling, parallel tools, vision, reasoning, prompt caching,
   context window). Any vendor or local server that exposes one of these protocols is
   added by configuration, not by code.
2. Endpoint configuration is operator-owned, per machine, and outside every repository:
   `.local/agent/endpoints.json`. A credential is a reference, `env:NAME` or
   `keychain:NAME`. The loader rejects a literal secret. Credentials never appear in
   context, framework, or product files, nor in prompts, event logs, or run evidence.
3. Each endpoint's locality is **derived, not declared**. A base URL whose host is a
   loopback address is `local`; every other URL, including a LAN host, is `remote`.

**Context egress is decided per project, and denied by default.**

4. The operator policy of ADR-0014 (`.local/agent/policies/<project-key>.json`) gains an
   optional key: `"llm": {"endpoints": ["<endpoint-name>", ...]}`. It lists the endpoints
   that may receive this project's context. The key is optional within schema version 1;
   `ws policy check` already ignores keys it does not use.
5. Without an `llm` key, only `local` endpoints may receive the project's context. A
   `remote` endpoint is used for a project only after the operator names it in that
   project's policy. That edit is the approval that the session pack's "not approved for
   cloud upload" asks for, and it changes the policy hash recorded in run evidence.
6. The agent host enforces this before every request: the session's bound project
   against the endpoint name. A disallowed endpoint is not called. Switching a running
   session to a disallowed model is refused, not warned about. Sub-agents inherit the
   session's project and are checked the same way.
7. An external agent CLI used as a driver (ADR-0019) talks to its vendor directly, so the
   host cannot see its traffic. It counts as a `remote` endpoint named after that driver,
   and needs the same explicit allowlist entry.
8. Each request records the endpoint name, model ID, and token counts with the agent's
   usage, never the prompt or completion content.

Allowing an endpoint does not make client data shareable. The anonymisation rule in
`AGENTS.md` still applies. The allowlist records that the operator accepts this vendor
receiving this project's working context.

## Consequences

### Positive
- Where a project's code and context may go is explicit, per project, reviewable, and
  checked on every request, not decided by a UI default.
- New vendors, routers, and local model servers need configuration only.
- Comparing models on one task (ADR-0015) stays inside each project's allowlist.

### Negative
- Default deny means the first agent session on a project fails until the operator edits
  its policy or runs a local model. That is deliberate, and it is still friction.
- Deriving locality from the URL treats a trusted self-hosted server on the LAN as
  `remote`. It has to be allowlisted by name like any vendor.
- "Compatible" APIs differ in detail. Capability overrides and per-endpoint quirks are
  maintained by hand.
- Enforcement is only as strong as the agent host. A tool run outside it is not covered.

### Neutral
- The policy schema version stays at 1. An older `ws` ignores the new key, and enforcement
  lives in the agent host either way.

## Alternatives considered

| Option | Why rejected |
|---|---|
| One adapter per vendor | Code and a release for every vendor that only changes a base URL, while the protocols are few. |
| Allow every endpoint, warn in the UI | A warning is not a rule. It is dismissed once and then forgotten, while the code has already left. |
| Endpoint list in the context repository | Endpoints and credential references are per machine. The context repo is shared with a team, for whom one person's local server URL means nothing. |
| A registry column for allowed endpoints | Egress permission is operator policy, which ADR-0014 keeps in `.local/`. Positional registry columns are costly to add (ADR-0018). |
| Declared locality per endpoint | A configuration file could call any host `local`, and that one word would switch off default deny. |

## Follow-up

- [ ] `.agents/templates/autonomy-policy.json` shows an `llm` example with synthetic names
- [ ] Endpoint configuration template with credential references only
- [ ] Agent-host test: a disallowed endpoint is never called, also after a mid-session model switch
