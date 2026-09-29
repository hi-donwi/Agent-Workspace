# GEMINI.md

Gemini CLI and Antigravity read this file. The working contract for every agent is
[`AGENTS.md`](AGENTS.md) at this root: read it before any task.

<!-- hard-rules:begin -->
## Hard rules - read these even if you read nothing else

1. **This framework repository is public.** Never put a client, group, project key,
   organisation name, client document, credential, or absolute path from your machine
   into a tracked file here or into a commit message. Product documents go in the
   product repo; plans, notes, and evidence go in `context/`.
2. **Commit only where and when the user asked; never push unless asked.** Never bypass
   hooks with `--no-verify`: the framework's guard hooks refuse any commit or push that
   names a client.
3. **Three repositories, three owners.** The framework (this folder), `context/`, and
   each repo under `projects/` are separate git repositories. Nothing from `context/` or
   `projects/` enters the framework; nothing from the framework or `context/` enters a
   product repo.
4. **Bind before you read project material:** `ws session bind <project-key>`, then load
   only the files that `.local/sessions/<session>/CONTEXT.md` lists.
5. **Runs come only from `ws run <project-key> "title"`** (`workspace` for work on this
   framework). Never hand-make a run folder, and never key one by client or group.
6. **Say who you are.** Every shell that runs `ws` exports `WS_AGENT=<your tool>` and
   `WS_SESSION_ID=<unique id>`; otherwise your work is logged as `dev` on a shared
   `default` session.
7. **English** in every file and every commit message.

The full contract is `AGENTS.md`. Where it and this list differ, this list wins.
<!-- hard-rules:end -->
