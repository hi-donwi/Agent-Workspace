# projects/

Every folder here is an **independent git repository** with its own remote.
The `workspace` repo ignores all of them via `/projects/*` in `.gitignore`.

The only thing this repo tracks is `registry.tsv` — a map of key → folder → remote.

## Why not submodules

A submodule would force the workspace repo to hold a commit pointer into a client-owned
repo. That mixes ownership, adds a step to every clone and every pull, and fills this
repo's history with meaningless pointer bumps. The registry plus `ws bootstrap` gives the
same benefit — one command to set up a new machine — without that coupling.

## Adding a project

```bash
ws new <key> <folder> [remote-url]
```

This will:
1. append a row to `registry.tsv`;
2. clone the remote (or `git init` if there is no remote yet);
3. create `context/memory/projects/<key>/` from templates;
4. run `ws link <key>`.

## Setting up a new machine

```bash
ws bootstrap
```

Clones every row in `registry.tsv` that has a remote and is not already on disk.

## Verifying isolation

```bash
ws doctor
```

Confirms no product repo has leaked into the the workspace's git index, and that every product repo
really has its own `.git`.
