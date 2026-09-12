# Engineering Workspace

Development standards, AI agent context, and team memory — for whichever organisation
owns this clone. The owner is declared in [`workspace.conf`](workspace.conf); nothing else
in this repository names a company.

This repo is **not** product code. It holds *how* we build product — so that every
developer and every AI agent on the team works to the same rules, context, and quality bar,
across projects and across time.

---

## Start here

**Joining an organisation that already uses this workspace:**

```bash
git clone <workspace-remote> workspace && cd workspace
.agents/bin/ws context clone <context-remote>   # your organisation's memory and registry
.agents/bin/ws bootstrap                        # clone every registered product repo
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
| [`.agents/skills/`](.agents/skills/) | Agent skills for those packs |
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
ws route "add order transaction summary endpoint"  # which skill applies
ws run <project-key> "task title"                       # create a run
ws log <project-key> "milestone"                        # append to the project log
ws sync                                                  # pull workspace, report repos
ws new <key> <folder> [remote]                           # register a new product repo
ws link <key>                                            # pointer + commit guard
ws where                                                 # print the workspace root
ws skills                                                # regenerate index.json
ws doctor                                                # workspace health check
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
