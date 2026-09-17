# The context repository

`context/` is the second of the three repositories that share a working directory. It is
**not** in this repository — it cannot be, which is why this page exists instead of a
`context/README.md` next to [`projects/README.md`](../projects/README.md).

It holds one access boundary's answer to: *what are we building, for whom, and where does it
stand?* The framework holds the *how*, and stays the same for everyone. The product repos
hold the code, and belong to the client.

```
context/
├── registry.tsv              projects: key, CLIENT, folder, remote, description
├── clients/<client>/         what holds across every one of one client's projects
│   ├── client.md               who they are, contract, stakeholders
│   ├── decisions.md            decisions that apply to all their projects
│   ├── skills/<domain>/        their domain glossary and business rules
│   └── docs/                   their proposals, kick-off notes, client-specific ADRs
├── memory/projects/<key>/    project.md · active.md · decisions.md · log.md (flat)
├── runs/<key>/<run>/         brief · plan · progress · decisions · evidence · handoff
├── skills/<name>/            domain skills shared across every client
├── works/{human,agent}/<key>/  hours; reports can group `--client`
└── docs/adr/                 decisions about this workspace itself
```

## Client vs. project

A **client** may have several **projects** — a REST API and its later mobile companion,
say. `clients/<client-key>/` holds what is true regardless of which project it is: the
namespace, the domain glossary, the stakeholder list. `memory/projects/<key>/` holds what
is true of one project only.

Project keys stay **flat**, never nested under their client
(`memory/clients/<c>/projects/<key>/`) — a key is unique workspace-wide, a project can
change client without moving four directory trees, and `runs/` and `works/` already assume
a flat key.

```bash
ws client new <key>                            # scaffold clients/<key>/
ws new <project-key> <folder> --client <key>    # register a project against it — required
ws client list                                  # every client and its project keys
ws hours --client <key>                         # billable hours across all their projects
```

**`--client` is required, not optional.** `ws new` refuses to register a project without
one, and `ws doctor` fails on any existing project that has none, or that names a client
directory that does not exist. Genuinely client-less work still needs a client —
`ws client new internal` — rather than becoming an exception the tooling has to special-case.

A decision belongs in `clients/<key>/decisions.md` only once a **second** project confirms
it is genuinely client-wide — one project cannot tell a client-wide fact from a
project-specific one wearing a client's name. Full reasoning:
[ADR-0009](adr/0009-client-grouping-in-context.md).

## Access boundaries

A context repository is an **access boundary**. Everyone who can clone it can read every
file in it and, unless history is rewritten, every file that was ever committed to it.
`clients/<client>/`, `groups.tsv`, and `context_scope` organize context and pack assembly;
they do not create access control.

Use this rule before adding a project, client, group, run, or memory file:

```text
Can every reader of this context repo read this artifact and its history?
```

If the answer is no, use another context repository and usually another workspace clone.
Common layouts are:

```text
# One owner or team can read all material in this clone.
workspaces/personal/
├── context/   # personal work
└── projects/personal/...

# Only the project team can read this context.
workspaces/backend-api/
├── context/   # backend-api project-only context
└── projects/example-org/client-a/backend-api/
```

Create broader context repositories only when their audience is genuinely broader. For
example, `context-client-alpha` is appropriate only if every reader may see every
project and group fact for that client. A project-only contributor should get a
project-only context repo, not a folder inside a broader client repo.

Full reasoning: [ADR-0010](adr/0010-context-repositories-follow-access-boundaries.md).

Access is not attention. An agent opened at the workspace root can still *see*
every client in that clone. Bind the session (`ws session bind <project-key>`)
so it loads only that pack. [ADR-0011](adr/0011-attention-isolation-is-not-access-isolation.md).

When one clone temporarily holds both personal/public work and paying-client rows, leave
`context_remote` empty and set `personal_clients` in `workspace.conf`. Do not attach a
remote until the tree is one audience:

```bash
ws context split --personal donwi
# mixed history → .local/archives/context-mixed-* (keep local, never push)
# donwi copy     → .local/contexts/donwi
# org copy       → .local/contexts/org
# optional: ws context split --personal donwi --apply org
```

## Why it is a separate repository

Three kinds of material, three owners, three audiences:

| | Owner | Audience | Example |
|---|---|---|---|
| Framework | whoever maintains the workspace | anyone, possibly public | "every collection paginates" |
| **Context** | **one organisation** | **that organisation only** | "this client's billing module is blocked on their namespace decision" |
| Product | usually the client | whoever the client allows | the code |

Context cannot live in the framework: the framework is shared and may be published, and a
client's name, scope, and glossary have no business there. It cannot live in a product repo
either: that repository belongs to the client, and your own delivery notes, estimates, and
cross-project memory are not theirs to read. There is no third place, so it gets its own
repository — mounted at `context/` and ignored by the framework, exactly as product repos
already were.

The word "organisation" here means "the audience allowed to read this context repo". It
may be a whole company, one client team, one project team, or one person's own public work.
When those audiences differ, create separate context repositories.

The full reasoning, and the five alternatives rejected, is in
[ADR-0006](adr/0006-framework-context-product-split.md).

## Visibility — the one mistake that matters

**A context repository must be private.** It names clients, records contract scope, may
carry a regulated domain glossary, and holds the hours behind invoices. Published, that is
a disclosure, not an untidy repository.

`ws doctor` checks this on every run and **fails** if the context remote can be read
without credentials:

```
x CONTEXT REPO IS PUBLIC - it can be read without credentials
```

The check needs no host API: it strips the credential helpers and tries an anonymous
`git ls-remote`. A network failure looks the same as "private", so the check can miss a
problem but never invents one — treat a pass as reassurance, not proof, and confirm the
setting in the host's UI when you first create the repository.

## Creating one

```bash
ws init                      # names the organisation, writes workspace.conf
ws context init              # scaffolds context/ and git init
```

For a team/shared context, give it a **private** remote and record it, so teammates get it
automatically:

```bash
git -C context remote add origin <private-remote>
git -C context push -u origin main
# then in workspace.conf:  context_remote = <private-remote>
```

For a personal or private-local project, a context repository with **no remote** is allowed.
`ws doctor` treats it as local-only rather than public or shared. Do not use a no-remote
context for team handoffs, billable shared hours, or anything another machine must recover.

## Joining an organisation that has one

```bash
ws context clone <private-remote>
```

`ws bootstrap` does this for you when `workspace.conf` names a `context_remote`, before it
clones the product repos.

## What goes in, and what never does

| Goes in | Never |
|---|---|
| Project memory, runs, handoffs | Credentials, tokens, private keys |
| The product registry, and each client's own folder | Client documents and data dumps — those go in `.local/`, git-ignored |
| Domain skills and glossaries | Anything a client has not agreed you may keep |
| Client ADRs, proposals, kick-off notes | Personal data beyond what delivery needs |
| Human and agent hours | Large logs or generated output |

`.local/` at the workspace root exists for the material that is too sensitive even for
this repository: signed PDFs, database dumps, screenshots with real records. It is
git-ignored and never pushed anywhere.

## Concurrency

Several people and agents write here at once. `context/.gitattributes` — tracked **inside
this repository**, not the framework's, because a merge attribute only ever governs merges
run in the repository that carries it — gives the append-only files the union merge driver,
so concurrent entries both survive:

- `memory/projects/*/log.md` and `registry.tsv` — merge by union
- `works/**/*.jsonl` — merge by union
- `memory/projects/index.md`, each project's `decisions.md`, and each
  `clients/<c>/decisions.md` — **conflict on purpose**; a clash there means two people
  changed the same fact and someone should read both sides

`ws context init` writes this file for you. If your context repository predates that (any
context repository created before this note was added never had working union merge at
all, however long ago its `AGENTS.md` claimed otherwise), copy it from
`.agents/templates/context-gitattributes` in the workspace and commit it once.

The per-file rules are tabulated in [`AGENTS.md`](../AGENTS.md) under *Working in
parallel*.

## Starting over for another organisation

Nothing in the framework names a company, so adopting it elsewhere is:

```bash
git clone <workspace-remote> workspace && cd workspace
ws init && ws context init
```

The standards and skills arrive; no other organisation's projects, clients, or memory
come with them.
