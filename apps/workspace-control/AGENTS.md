# Workspace control UI

This application belongs to the framework. Do not copy a companion application,
product code, client records, or project memory into this directory.

Use the published `uidl-runtime` npm package with React and strict TypeScript.
Pages and task forms are generated UIDL documents, parsed by `DocumentSchema`.
The React shell owns navigation, theme preference, and the accessible native dialog.
Read through `WorkspaceApi`'s `DataAdapter` seam. Writes use its explicit host command
methods with task revisions. Unknown commands and adapter mutations fail closed.

UIDL 0.1.4 details: node events contain arrays of actions; input changes bind to
`event`; action payloads read document state with `$expr: { path: 'state.…' }`.
Render-time props use `$bind: 'state.…'`. Keep these semantics distinct.

Design tokens live in `src/styles.css`: neutral surfaces, teal accent, light/dark
palettes, system fonts, 4/8/12/16/24/32 spacing, and 8/12/16 radii. Keep labels,
visible focus, error/empty/loading states, and reduced-motion support. Navigation
and theme selection must remain usable at 320px and short viewport heights.

Verify with `npm run build` and `npm test`. Browser tests run the production build
and real Python API against disposable synthetic context. Never test mutations on
the operator's real projects. Changes to Python behavior also require the root
Python tests and CLI suite.
