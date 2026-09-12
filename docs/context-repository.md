# The context repository

`context/` is the second of the three repositories that share a working directory. It is
**not** in this repository — it cannot be, which is why this page exists instead of a
`context/README.md` next to [`projects/README.md`](../projects/README.md).

It holds one organisation's answer to: *what are we building, for whom, and where does it
stand?* The framework holds the *how*, and stays the same for everyone. The product repos
hold the code, and belong to the client.

```
context/
├── registry.tsv              which product repos this organisation has
├── memory/projects/<key>/    project.md · active.md · decisions.md · log.md
├── runs/<key>/<run>/         brief · plan · progress · decisions · evidence · handoff
├── skills/<name>/            this organisation's domain skills
├── works/                    human and agent hours, and the monthly rollup
└── docs/                     client ADRs, proposals, kick-off notes
```

## Why it is a separate repository

Three kinds of material, three owners, three audiences:

| | Owner | Audience | Example |
|---|---|---|---|
| Framework | whoever maintains the workspace | anyone, possibly public | "every collection paginates" |
| **Context** | **one organisation** | **that organisation only** | "this client's tender module has 29 endpoints, blocked on their namespace decision" |
| Product | usually the client | whoever the client allows | the code |

Context cannot live in the framework: the framework is shared and may be published, and a
client's name, scope, and glossary have no business there. It cannot live in a product repo
either: that repository belongs to the client, and your own delivery notes, estimates, and
cross-project memory are not theirs to read. There is no third place, so it gets its own
repository — mounted at `context/` and ignored by the framework, exactly as product repos
already were.

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

Then give it a **private** remote and record it, so teammates get it automatically:

```bash
git -C context remote add origin <private-remote>
git -C context push -u origin main
# then in workspace.conf:  context_remote = <private-remote>
```

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
| The product registry | Client documents and data dumps — those go in `.local/`, git-ignored |
| Domain skills and glossaries | Anything a client has not agreed you may keep |
| Client ADRs, proposals, kick-off notes | Personal data beyond what delivery needs |
| Human and agent hours | Large logs or generated output |

`.local/` at the workspace root exists for the material that is too sensitive even for
this repository: signed PDFs, database dumps, screenshots with real records. It is
git-ignored and never pushed anywhere.

## Concurrency

Several people and agents write here at once. `.gitattributes` gives the append-only files
the union merge driver, so concurrent entries both survive:

- `memory/projects/*/log.md` and `registry.tsv` — merge by union
- `works/**/*.jsonl` — merge by union
- `memory/projects/index.md` and `decisions.md` — **conflict on purpose**; a clash there
  means two people changed the same fact and someone should read both sides

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
