# ADR-0020: Local approval record for actions that stay on this machine

- **Date:** 2026-10-02
- **Status:** Accepted
- **Deciders:** Workspace maintainer
- **Project:** workspace

## Context

ADR-0014 classifies an agent action as `read`, `change`, or `approval-required`.
ADR-0017 says a classification is not an approval, and lists what any approval
integration must provide before it is built:

1. an authenticated human or group identity;
2. an immutable request ID bound to the exact project, revision, action, and policy hash;
3. an auditable timestamp and an expiration or revocation rule;
4. a verification mechanism independent of the product checkout;
5. least-privilege delivery to the executor, with no reusable secret in prompts or logs.

The agent host of ADR-0019 will reach `approval-required` many times in one session, and
most of those actions never leave the machine: install a dependency into the worktree,
run a command that needs the network, delete a directory, commit to the agent's branch.
Blocking all of them makes an agent useless. Accepting an environment variable, a chat
message, or a model's claim as approval is the bypass ADR-0017 rules out.

## Decision

The framework provides a local approval record, limited to actions whose effect stays on
this machine: the session's worktree, the local context repository, and local processes.
Actions that leave the machine or change a shared system stay outside it: push, merge,
deploy, release, credential or IAM changes, and production access. ADR-0017 still
governs those, through protected branches and environments.

How each ADR-0017 requirement is met:

1. **Identity.** The approver is the operator holding the desk's session cookie on
   loopback (ADR-0019). That is the OS user who started `ws web`, recorded as the human
   ID that `ws` already uses for clocks. Agent processes never receive the cookie or the
   internal control token.
2. **Binding.** A request has a random ID. It names the project key, agent session ID,
   worktree path, the worktree's `HEAD` commit, the action label, a SHA-256 of the exact
   tool input (the argument vector or the patch), and a SHA-256 of the policy file that
   classified it.
3. **Time and revocation.** A request records when it was made, decided, and expires.
   The default expiry is 15 minutes. An approval is single-use. Stopping the session
   voids every pending request.
4. **Independent verification.** Immediately before execution, the agent host recomputes
   `HEAD`, the input hash, and the policy hash. Any mismatch voids the approval. Records
   are append-only JSONL under `.local/agent/approvals/<project-key>/<YYYY-MM>.jsonl`,
   mode `0600`. The path check that ADR-0014 applies to policies applies here, so the
   records cannot live inside a product checkout.
5. **Least privilege.** The executor consumes the approval. The model sees only
   `approved` or `denied`, and never an ID it could replay. The run's `evidence.md` gets a
   summary (request ID, action, decision, times) without the tool input, which may hold
   client data.

The only decisions are **approve once** and **deny**. There is no "always allow". A
standing permission is a change to the operator policy of ADR-0014: an explicit,
reviewable file edit that changes the policy hash, and with it every later request.

## Consequences

### Positive
- Agents can progress through local risky steps with a human in the loop, without any
  path that lets a model, a checkout, or an environment flag approve itself.
- Every approval is reconstructable: who, what exact input, at which revision, under
  which policy.
- Remote and irreversible actions keep the stronger boundary of ADR-0017.

### Negative
- It assumes one operator per machine. It is not a group identity and does not satisfy a
  four-eyes rule.
- Anyone who obtains the session cookie can approve as the operator. The cookie is the
  credential, so loopback binding and `SameSite=Strict` are load-bearing.
- The records are evidence, not a tamper-proof log: the OS user can edit them.
- Single-use approvals cause approval fatigue on long tasks. The intended fix is a
  narrower policy, not a wider approval.

### Neutral
- `ws policy check` is unchanged. This ADR adds the step that follows its
  `approval-required` result.

## Alternatives considered

| Option | Why rejected |
|---|---|
| Environment flag or CLI switch | ADR-0017 rejects it: anything that can start the agent can set it. |
| Approval typed into the chat | The transcript is model-visible and model-writable. A prompt injection can produce the same text. |
| "Always allow this command" stored by the UI | A standing permission hidden in UI state, invisible to policy review and to the policy hash. |
| OS-native confirmation dialogs | Platform-specific, not testable in CI, and they carry no binding to revision or input hash. |
| Protected environments for local actions too | A remote round trip for each local edit, and it needs the remote identity provider ADR-0017 deferred choosing. |

## Follow-up

- [ ] Record schema and fixture with synthetic projects only
- [ ] Agent-host test: an approval is void after `HEAD`, input, or policy changes
- [ ] Desk approval inbox shows action, exact input, worktree, revision, and expiry
