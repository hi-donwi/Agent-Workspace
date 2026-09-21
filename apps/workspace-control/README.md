# Workspace Control

The framework's local control desk, built with React, strict TypeScript, and the
published [`uidl-runtime`](https://www.npmjs.com/package/uidl-runtime) package pinned
to 0.1.4. The shell hosts validated UIDL documents for all page content and task forms.

## Run

From the workspace root, using Node 22.12 or newer:

```sh
npm --prefix apps/workspace-control ci
npm --prefix apps/workspace-control run build
.agents/bin/ws web --port 8765
```

Open the printed URL. The Python server serves `dist/`, injects its process token,
and supplies the same-origin API. Light, Dark, and System are available in the
sidebar; theme preference is saved in browser storage. The token is never saved
in browser storage. Restarting the server invalidates old token URLs.

Build lookup order: `WS_UIDL_DIST`, this application's `dist/`, a legacy companion
under `projects/**/apps/workspace-control/dist`, then the vanilla fallback.
`ws web --runtime vanilla` explicitly selects the fallback.

## Features

- Overview, project/client navigation, and project-scoped board/backlog/search.
- Create/edit tasks, status and priority, ownership, labels, acceptance criteria,
  blocked reason, related plans/runs, and linking/unlinking verified Git commits.
- WIP warnings and visibility of legacy task files requiring conversion.
- Plans, runs, full available context/handoffs, workspace health and configuration.
- Monthly human/agent hours, active sessions, clock in/out, and optional token usage.
- Responsive navigation, keyboard shortcuts (`Ctrl/Cmd+K`), accessible task dialogs,
  persisted theme selection, and error/revision-conflict feedback.

Task status changes use the editor. Configuration is read-only and edited in
`workspace.conf`. Clock-out requires the original actor/tool/session and project;
it never chooses another person's session. Usage availability depends on the
operator's configured usage source. Health checks cover the registry, context
remote configuration, and checkout existence; `ws doctor` remains the deeper audit.

## Develop and verify

```sh
# Terminal 1, at the workspace root:
.agents/bin/ws web --port 8765

# Terminal 2:
cd apps/workspace-control
npm run dev
# Open the Vite URL with ?token=<token printed by ws web>.

npm run build
npx playwright install chromium
npm test
```

`WS_WEB_URL` can point the development proxy at another loopback port. The tests
start their own API on port 18765 with a disposable synthetic workspace; stop any
other process using that port first. Screenshots and failure traces are ignored
under `test-results/`. The root Python and CLI suites remain independent of Node.

The production server rejects non-loopback binding, foreign Host/Origin headers,
cross-site requests, and API calls without the process bearer token. It sends no
cross-origin access grant. This is a local operator application, not a hosted
multi-user authorization service.
