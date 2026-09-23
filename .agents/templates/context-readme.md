# Workspace context

This repository is one organisation's **context**: what it is building, for whom, and
where each piece stands. It is mounted at `context/` inside the engineering workspace and
is ignored by the workspace's git, so nothing here can reach the shared framework.

```
context/
├── registry.tsv            ← projects: key, CLIENT, folder, remote, description
├── clients/<client>/       ← what is true for every project of one client
│   ├── client.md             who they are, contract, stakeholders
│   ├── decisions.md          decisions that hold across all their projects
│   ├── skills/<domain>/      their domain glossary and business rules
│   └── docs/                 their proposals, kick-off notes, client-specific ADRs
├── memory/projects/<key>/  ← per-project state (flat — a key is unique across clients)
├── runs/<key>/<run>/       ← per-task working memory (flat, same reason)
└── works/{human,agent}/<key>/  hours (flat; reports can group --client)
```

## Client vs. project

A client may have several projects. `clients/<client>/` holds what is true regardless of
which project it is — namespace, domain glossary, stakeholders. `memory/projects/<key>/`
holds what is true of one project only. Project keys stay flat, never nested under a
client: a key is unique workspace-wide, and a project can change client without moving
directory trees. `registry.tsv`'s `client` column is the link between the two.

Create a client with: `ws client new <key>`. Register a project against it with:
`ws new <project-key> <folder> --client <client-key>`.

## Rules

1. **Never store secrets, credentials, or personal data here.** This repo is shared with
   the whole team. Client documents and dumps belong in `.local/`, which is ignored.
2. **Memory is a handoff aid, not a source of truth.** If memory and the code disagree,
   the code is right and the memory is stale.
3. **`active.md` is a routing hint.** The authoritative state of a task is its run.
4. **A decision belongs to a client only once a second project confirms it.** One project
   cannot tell a project-specific choice from a client-wide one.
5. **Shared files are patched additively.** `log.md`, `registry.tsv`, and `works/**/*.jsonl`
   merge by union — append through `ws log` / `ws clock` rather than editing by hand.
   `index.md` and each `decisions.md` conflict on purpose; read both sides.
6. **Convert relative dates to absolute.** "Last week" means nothing in November.

The full contract is in the workspace's `AGENTS.md`.
