# {{ORG}} — workspace context

This repository is one organisation's **context**: what it is building, for whom, and
where each piece stands. It is mounted at `context/` inside the engineering workspace and
is ignored by the workspace's git, so nothing here can reach the shared framework.

```
context/
├── registry.tsv          ← product repos: key, folder, remote, description
├── memory/projects/<key>/  project.md · active.md · decisions.md · log.md
├── runs/<key>/<run>/       brief · plan · progress · decisions · evidence · handoff
├── skills/<name>/          domain skills specific to this organisation
└── docs/                   client ADRs, proposals, kick-off notes
```

## Rules

1. **Never store secrets, credentials, or personal data here.** This repo is shared with
   the whole team. Client documents and dumps belong in `.local/`, which is ignored.
2. **Memory is a handoff aid, not a source of truth.** If memory and the code disagree,
   the code is right and the memory is stale.
3. **`active.md` is a routing hint.** The authoritative state of a task is its run.
4. **Shared files are patched additively.** `log.md` and `registry.tsv` merge by union —
   append through `ws log` rather than editing by hand. `index.md` and `decisions.md`
   conflict on purpose; read both sides.
5. **Convert relative dates to absolute.** "Last week" means nothing in November.

The full contract is in the workspace's `AGENTS.md`.
