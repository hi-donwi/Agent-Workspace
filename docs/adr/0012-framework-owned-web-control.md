# ADR-0012: Framework-owned web control using the published UIDL runtime

- **Date:** 2026-09-21
- **Status:** Accepted
- **Deciders:** Workspace maintainer (requested npm UIDL redesign)
- **Project:** workspace

## Context

The local web control API belongs to the framework, but its default UI previously
depended on a built companion in an independent product checkout. That makes
setup dependent on an unrelated checkout and obscures which repository owns the
control desk. The requested redesign explicitly requires the npm UIDL runtime
and light/dark support.

## Decision

The framework owns `apps/workspace-control`. It consumes the published
`uidl-runtime` package through a locked npm installation. React hosts navigation,
theme preference, and native dialog behavior; validated UIDL documents render
page content and task forms. Read operations use a DataAdapter; host commands
allow only the existing API workflows. Production builds are served by the
stdlib Python server on loopback, with same-origin browser access and the
existing process bearer token.

Build discovery prefers an explicit `WS_UIDL_DIST`, then the framework build,
then legacy companion builds. The zero-dependency vanilla fallback remains.
This does not change the three-repository ownership rule: runtime library code
is an installed dependency, never copied from a product checkout.

## Consequences

- A workspace can build its UI without cloning the runtime source repository.
- UI changes and API compatibility tests live together in the framework.
- Node and Chromium are required to build and browser-test the modern UI;
  Python-only CLI and fallback usage remain available.
- The pinned npm runtime and legacy companion may evolve independently.
- The web desk is a same-origin loopback application. Development uses a local
  Vite proxy; arbitrary cross-origin companion access is deliberately closed.
- The TypeScript web standards apply to the new app. The stdlib backend keeps
  its existing local API contract; this change does not introduce hosted REST
  service infrastructure or a second database.

## Alternatives considered

| Option | Why rejected |
|---|---|
| Edit the runtime companion | Keeps setup and framework UI ownership in an independent product repo. |
| Copy the companion into the framework | Violates repository ownership boundaries. |
| Rewrite the vanilla UI alone | Does not meet the requested npm UIDL requirement. |
| Replace the Python server with a Node service | Adds runtime migration without helping the requested UI workflows. |

## Verification

The build typechecks, then bundles. Playwright drives the real Python API using
synthetic context and checks navigation, task mutations, evidence, search,
clocks, error states, responsive layouts, and accessibility in both themes.
Python regressions protect build discovery, effective runtime reporting, month
validation, and clock ownership.
