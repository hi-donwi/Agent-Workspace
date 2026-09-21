import { useEffect, useMemo, useRef, useState } from 'react';
import { createDocumentState, Icon, UIDocumentRenderer } from 'uidl-runtime';
import { projectViews, viewLabels, type View } from './contracts';
import { pageDocument } from './documents/pages';
import { editorDocument } from './documents/task-editor';
import { useWorkspace } from './use-workspace';
import { useTheme } from './use-theme';
import { registry, RenderBoundary, TaskDialog } from './ui';

const navigation: { title: string; items: { view: View; icon: string }[] }[] = [
  { title: 'WORKSPACE', items: [{ view: 'overview', icon: 'squares' }, { view: 'projects', icon: 'folder' }, { view: 'clients', icon: 'users' }] },
  { title: 'DELIVERY', items: [{ view: 'board', icon: 'view-columns' }, { view: 'backlog', icon: 'queue-list' }, { view: 'search', icon: 'search' }] },
  { title: 'KNOWLEDGE', items: [{ view: 'plans', icon: 'document-text' }, { view: 'runs', icon: 'play' }, { view: 'context', icon: 'book-open' }, { view: 'activity', icon: 'clock' }] },
  { title: 'SYSTEM', items: [{ view: 'health', icon: 'heart' }, { view: 'settings', icon: 'cog' }] },
];
const descriptions: Record<View, string> = {
  overview: 'Everything you need to keep work moving.', projects: 'One place for every project in your workspace.', clients: 'Projects organized around the people you build for.',
  board: 'From the first idea to the final review.', backlog: 'Make room for what comes next.', search: 'Find the right task, within the right project.',
  plans: 'Decisions and next steps, ready to pick up.', runs: 'Follow the work from one session to the next.', context: 'The shared knowledge behind your project.',
  activity: 'Understand where time and effort go.', health: 'A quick check of your local workspace.', settings: 'Make this workspace feel like yours.',
};

export function App() {
  const ws = useWorkspace();
  const theme = useTheme();
  const [menuOpen, setMenuOpen] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const workspaceTree = useMemo(() => {
    const clients = new Map<string, Map<string, typeof ws.projects>>();
    for (const project of ws.projects) {
      const groups = clients.get(project.client) ?? new Map<string, typeof ws.projects>();
      const group = project.group === '-' ? 'Projects' : project.group;
      groups.set(group, [...(groups.get(group) ?? []), project]);
      clients.set(project.client, groups);
    }
    return Array.from(clients.entries()).sort(([a], [b]) => a.localeCompare(b)).map(([client, groups]) => ({
      client,
      groups: Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b)).map(([group, projects]) => ({
        group,
        projects: [...projects].sort((a, b) => a.key.localeCompare(b.key)),
      })),
    }));
  }, [ws.projects]);
  const doc = useMemo(() => pageDocument(ws.view, ws.data, ws.projects, ws.project, ws.filters, ws.month, ws.clock), [ws.view, ws.data, ws.projects, ws.project, ws.filters, ws.month, ws.clock]);
  const pageState = useMemo(() => createDocumentState(doc.state), [doc]);
  const pageKey = useMemo(() => JSON.stringify([ws.view, ws.project, ws.revision, ws.filters, ws.month, ws.clock]), [ws.view, ws.project, ws.revision, ws.filters, ws.month, ws.clock]);
  const editorDoc = useMemo(() => ws.editor ? editorDocument(ws.editor.task, ws.editor.commits) : null, [ws.editor]);
  // Keep unsaved form fields while commit evidence changes independently.
  const editorState = useMemo(() => createDocumentState(editorDoc?.state), [ws.editor?.task?.id, Boolean(ws.editor)]);
  useEffect(() => { setMenuOpen(false); headingRef.current?.focus(); document.title = `${viewLabels[ws.view]} · Workspace Control`; }, [ws.view, ws.project]);
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === 'k') { event.preventDefault(); ws.navigate('search'); }
      if (event.key === 'Escape') setMenuOpen(false);
    };
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, [ws.navigate]);
  const renderOptions = { registry, dataAdapter: ws.api, commandHandler: ws.handleCommand };
  return <div className="app-shell">
    <a className="skip-link" href="#main-content" onClick={event => { event.preventDefault(); headingRef.current?.focus(); }}>Skip to content</a>
    {menuOpen && <button className="menu-scrim" aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}
    <aside id="workspace-sidebar" className={`sidebar${menuOpen ? ' is-open' : ''}`} aria-label="Workspace sidebar">
      <a className="brand" href="#view=overview"><span className="brand-mark">w<span>.</span></span><span>Workspace<span className="brand-subtitle">CONTROL DESK</span></span></a>
      <div className="workspace-explorer" aria-label="Workspace explorer">
        <div className="explorer-heading"><span>Workspace explorer</span><span>{ws.projects.length}</span></div>
        {workspaceTree.map(({ client, groups }) => <details key={client} open className="tree-client">
          <summary><Icon name="folder" className="shell-icon" />{client}</summary>
          {groups.map(({ group, projects }) => <details key={`${client}-${group}`} open className="tree-group">
            <summary>{group}<span>{projects.length}</span></summary>
            <div className="tree-projects">{projects.map(project => <button key={project.key} className={`tree-project${ws.project === project.key ? ' active' : ''}`} aria-current={ws.project === project.key ? 'page' : undefined} onClick={() => ws.navigate(projectViews.includes(ws.view) ? ws.view : 'board', project.key)} title={project.description || project.folder}>{project.key}</button>)}</div>
          </details>)}
        </details>)}
      </div>
      <nav aria-label="Main navigation">{navigation.map(group => <div className="nav-group" key={group.title}><p className="nav-label">{group.title}</p>{group.items.map(item => <button key={item.view} className={`nav-item${ws.view === item.view ? ' active' : ''}`} aria-current={ws.view === item.view ? 'page' : undefined} onClick={() => ws.navigate(item.view)}><Icon name={item.icon} className="shell-icon" /><span>{viewLabels[item.view]}</span>{item.view === 'search' && <kbd aria-hidden="true">⌘ K</kbd>}</button>)}</div>)}</nav>
      <div className="sidebar-footer"><div className="theme-switch" role="group" aria-label="Color theme">{(['light', 'dark', 'system'] as const).map(mode => <button key={mode} aria-pressed={theme.preference === mode} onClick={() => theme.changeTheme(mode)}>{mode[0].toUpperCase() + mode.slice(1)}</button>)}</div><p className="local-label"><span /> Local workspace <span className="version">v0.1</span></p></div>
    </aside>
    <div className="main-shell">
      <header className="topbar"><div className="row"><button className="icon-button menu-toggle" aria-label="Open navigation" aria-expanded={menuOpen} aria-controls="workspace-sidebar" onClick={() => setMenuOpen(value => !value)}><Icon name="menu" className="shell-icon" /></button><span className="breadcrumb">Workspace <span>/</span> <strong>{viewLabels[ws.view]}</strong></span></div><div className="row"><span className="connection"><span /> Loopback</span><button className="icon-button" aria-label="Refresh workspace" onClick={ws.refresh} disabled={ws.loading || ws.busy}><Icon name="refresh" className="shell-icon" /></button></div></header>
      <main id="main-content">
        <div className="page-heading"><div><div className="eyebrow">{projectViews.includes(ws.view) && ws.project ? ws.project : 'YOUR WORKSPACE, IN FOCUS'}</div><h1 ref={headingRef} tabIndex={-1}>{viewLabels[ws.view]}</h1><p className="muted">{descriptions[ws.view]}</p></div><span className="page-date">{new Date().toLocaleDateString('en', { weekday: 'short', month: 'short', day: 'numeric' })}</span></div>
        {theme.warning && <p className="notice warning" role="status">{theme.warning}</p>}
        {ws.notice && !ws.editor && <p className="notice success" role="status">{ws.notice}</p>}
        {ws.error && !ws.editor && <div className="notice error" role="alert">{ws.error} <button className="text-button" onClick={ws.refresh}>Retry</button></div>}
        {ws.loading ? <div className="loading-state" role="status"><span className="loading-dot" /> Loading workspace…<div className="skeleton-grid"><div /><div /><div /></div></div> : <fieldset className="content-fieldset" disabled={ws.busy} aria-busy={ws.busy}><RenderBoundary key={pageKey}><UIDocumentRenderer {...renderOptions} document={doc} stateStore={pageState.getState()} /></RenderBoundary></fieldset>}
        <footer className="page-footer"><span>Agent Workspace</span><span>Built for thoughtful work.</span></footer>
      </main>
    </div>
    {ws.editor && editorDoc && <TaskDialog returnFocus={ws.openerRef.current} onClose={ws.closeEditor} title={ws.editor.task ? 'Edit task' : 'New task'} busy={ws.busy}>
      {ws.error && <p className="notice error" role="alert">{ws.error}</p>}
      {ws.notice && <p className="notice success" role="status">{ws.notice}</p>}
      <fieldset className="content-fieldset" disabled={ws.busy} aria-busy={ws.busy}><UIDocumentRenderer {...renderOptions} document={editorDoc} stateStore={editorState.getState()} /></fieldset>
    </TaskDialog>}
  </div>;
}
