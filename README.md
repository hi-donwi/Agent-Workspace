# Agent Workspace

[![doctor](https://github.com/hi-donwi/Agent-Workspace/actions/workflows/doctor.yml/badge.svg)](https://github.com/hi-donwi/Agent-Workspace/actions/workflows/doctor.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**A shared working contract, binding standards, and durable memory for teams where AI
agents and developers work on the same code.**

Every agent — Claude Code, Cursor, Copilot, Codex, Gemini CLI — reads the same rules from
the same place. Every session that ends leaves behind enough for the next person or agent
to continue. Nothing internal leaks into a client's repository, and nothing of one
organisation's leaks into this one.

## The problem it solves

Agents lose context when a session ends. Developers switch tools. Standards written inside
a product repo diverge the moment there is a second product. And a codebase shared with a
client is the wrong place for your own engineering notes.

This repository is the *how*, kept separate from the *what*:

- **Standards** an agent must follow, in packs you switch on per stack
- **Skills** — task-shaped instructions an agent reads before starting, pulled from
  [Agent-Skills](https://github.com/hi-donwi/Agent-Skills) a pack at a time
- **Memory and runs** — what happened, what is in flight, what the next session needs
- **Two clocks** — human hours and agent hours, recorded separately and never summed
- **A CLI (`ws`)** that wires the repositories together and checks they stay separate

Nothing here names an organisation. Clone it, run `ws init`, and it is yours.

---

## Start here

**Joining an organisation that already uses this workspace:**

```bash
git clone <workspace-remote> workspace && cd workspace
cp workspace.conf.example workspace.conf        # then set org_name and context_remote
.agents/bin/ws bootstrap                        # skills, context, and every product repo
.agents/bin/ws ide                              # copy the shared editor defaults
.agents/bin/ws doctor                           # check isolation, ignores, toolchain
```

**Adopting the workspace for a new organisation, team, or client:**

```bash
git clone <workspace-remote> workspace && cd workspace
.agents/bin/ws init            # name the organisation; writes workspace.conf
.agents/bin/ws context init    # create an empty context repository for it
.agents/bin/ws doctor
```

Nothing but `workspace.conf` names a company, so the second form starts clean — no other
organisation's projects, memory, or clients come with it.

Clone it wherever you like — nothing tracked here assumes a path, and `ws where` resolves
the root from anywhere.

Then **open your editor at that root** — not at `projects/<x>`. The reason is in
[AGENTS.md §2](AGENTS.md).

Full first-day onboarding: [`docs/onboarding.md`](docs/onboarding.md).

---

## Map

Three repositories share one directory. Full explanation in [AGENTS.md §1](AGENTS.md).

**1. Framework — this repository, shared across organisations**

| Path | Contents |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Working contract for agents + developers. **Read this first.** |
| [`workspace.conf`](workspace.conf) | The only file that names an organisation |
| [`.agents/standards/`](.agents/standards/) | Binding standards, in packs (`core`, `java`) |
| `.agents/skills.manifest` | Which skills to pull, and from where |
| [`.agents/templates/`](.agents/templates/) | Templates: ADR, run, memory, endpoint spec |
| [`.agents/bin/ws`](.agents/bin/ws) | Workspace CLI |
| [`docs/adr/`](docs/adr/) | Decisions about the workspace mechanism itself |

**2. Context — a separate repo per organisation, ignored here**

| Path | Contents |
|---|---|
| `context/registry.tsv` | Which product repos this organisation has |
| `context/memory/projects/` | Cross-session memory, per project |
| `context/runs/` | Per-task working memory |
| `context/skills/` | This organisation's domain skills |
| `context/docs/` | Client ADRs, proposals, kick-off notes |

**3. Product — the client's repos, ignored here**

| Path | Contents |
|---|---|
| `projects/<group>/<repo>/` | Product code — separate git repos with their own remotes |
| `.local/` | Client documents & scratch — **ignored, never pushed** |

---

## Why this structure

Three problems it solves:

**1. Standards do not leak into client repos.** Product repos are often hosted by the
client. The workspace's standards, memory, and skills do not belong there.
Here they have one home, one history, one owner.

**2. One project is not the only project, and one organisation is not the only
organisation.** Standards rewritten per repo diverge immediately. Written here once, they
apply to every project — and, because nothing but `workspace.conf` names a company, to
every team or client that adopts the workspace later.

**3. Agents change; context persists.** Sessions hit quota, developers switch tools, people
take leave. `context/memory/` and `context/runs/` let another person or agent pick the work
up without redoing the investigation.

---

## Active projects

This repository does not list them. Projects, their clients, and their memory belong to
whoever owns the clone and live in the context repository — `context/registry.tsv` and
`context/memory/projects/`. Run `ws list` to see them.

---

## Common commands

```bash
ws route "add an order summary endpoint"   # which skill applies to this task
ws skills available                        # what the skills repository offers
ws skills add code-review                  # take one, pinned to a commit
ws run <project-key> "task title"          # start a run (multi-session work)
ws log <project-key> "milestone"           # append to the project log
ws clock in <project-key> "what you'll do" # human hours
ws agent in <project-key> "what it'll do"  # agent hours, counted separately
ws hours --month 2026-09                   # both, side by side
ws sync                                    # pull workspace, report repo state
ws new <key> <folder> [remote]             # register a new product repo
ws link <key>                              # pointer + commit guard in a client repo
ws doctor                                  # health check: isolation, portability, drift
```

Add to `PATH` once, from inside your clone:

```bash
echo "export PATH=\"$PWD/.agents/bin:\$PATH\"" >> ~/.zshrc && source ~/.zshrc
```

---

## Language

Everything written here — documentation, code, comments, commit messages, identifiers — is
in **English**. An organisation whose domain carries statutory or regulated vocabulary with
no precise English equivalent may keep those terms as-is; that glossary then lives in its own
context repository (`context/skills/<domain>/SKILL.md`), never here.

---

## Rules most often broken

1. Opening the editor at `projects/<x>` → standards do not load. Open the root.
2. Putting client documents outside `.local/` → risk of pushing them. Always `.local/`.
3. Committing in `projects/<x>` thinking it is this repo → that is the client repo.
4. Deviating from a standard without an ADR → write the ADR, don't bury it in one file.
5. Running `git clean -ffxd` at the root → **deletes the product repo and any unpushed
   commit in it**. Plain `-xdf` is safe; `-ff` is not. See [AGENTS.md §2](AGENTS.md).
