import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CommandRequest } from 'uidl-runtime';
import { emptyFilters, views, type Commit, type Filters, type PageData, type Project, type TaskDetail, type View } from './contracts';
import { WorkspaceApi } from './workspace-api';

function routeFromHash() {
  const params = new URLSearchParams(location.hash.slice(1));
  const name = params.get('view') ?? 'overview';
  return { view: views.includes(name as View) ? name as View : 'overview' as View, project: params.get('project') ?? '' };
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid command payload.');
  return value as Record<string, unknown>;
}
const lines = (value: unknown) => String(value ?? '').split('\n').map(line => line.trim()).filter(Boolean);
const message = (error: unknown) => error instanceof Error ? error.message : 'The request could not be completed.';

export function useWorkspace() {
  const [route, setRoute] = useState(routeFromHash);
  const [projects, setProjects] = useState<Project[]>([]);
  const [data, setData] = useState<PageData>({});
  const [filters, setFilters] = useState<Filters>(() => ({ ...emptyFilters }));
  const [month, setMonth] = useState(() => new Date().toLocaleDateString('en-CA').slice(0, 7));
  const [clock, setClock] = useState({ actor: '', kind: 'human', tool: 'web-control', session: 'web', note: '' });
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const openerRef = useRef<HTMLElement | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [editor, setEditor] = useState<{ task: TaskDetail | null; commits: Commit[] } | null>(null);
  const api = useMemo(() => new WorkspaceApi(new URL(location.href).searchParams.get('token') ?? ''), []);
  const refresh = useCallback(() => setRevision(value => value + 1), []);
  const navigate = useCallback((view: View, project = route.project) => {
    location.hash = new URLSearchParams({ view, ...(project ? { project } : {}) }).toString();
  }, [route.project]);

  useEffect(() => {
    const onHash = () => { setRoute(routeFromHash()); setEditor(null); setError(''); setNotice(''); };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  useEffect(() => { setFilters({ ...emptyFilters }); }, [route.project]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    void Promise.all([api.projects(controller.signal), api.load(route.view, route.project, filters, month, controller.signal)])
      .then(([list, page]) => { if (!controller.signal.aborted) { setProjects(list); setData(page); } })
      .catch(error => { if (!controller.signal.aborted) { setData({}); setError(message(error)); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [api, route, filters, month, revision]);

  const handleCommand = async ({ name, payload = {} }: CommandRequest) => {
    if (busyRef.current) return;
    if (name === 'task.new' || name === 'task.open') openerRef.current = document.activeElement as HTMLElement | null;
    if (name === 'task.close') { setEditor(null); setError(''); return; }
    if (name === 'view.open') {
      if (!views.includes(payload.view as View)) throw new Error('Unknown view.');
      navigate(payload.view as View); return;
    }
    if (name === 'project.open') { navigate('board', String(payload.project)); return; }
    if (name === 'search.clear') { setFilters({ ...emptyFilters }); return; }
    if (name === 'search.apply') { setFilters({ ...emptyFilters, ...object(payload.filters) } as Filters); return; }
    if (name === 'month.apply') { setMonth(String(payload.month)); return; }
    if (name === 'task.new') { setError(''); setEditor({ task: null, commits: [] }); return; }
    busyRef.current = true; setBusy(true); setError(''); setNotice('');
    try {
      if (!route.project) throw new Error('Choose a project first.');
      if (name === 'task.open') {
        const { task } = await api.task(route.project, String(payload.id));
        // A missing checkout must not prevent editing a task's context document.
        let commits: Commit[] = [];
        try { commits = (await api.commits(route.project)).commits; }
        catch { setNotice('Commit history is unavailable for this checkout. Task editing is still available.'); }
        setEditor({ task, commits });
      } else if (name === 'task.save') {
        const form = object(payload.form);
        if (!String(form.title ?? '').trim()) throw new Error('A task title is required.');
        if (form.blocked && !String(form.blocked_reason ?? '').trim()) throw new Error('Enter a reason for blocking this task.');
        const saved = await api.saveTask(route.project, editor?.task?.id, {
          ...form, blocked_reason: form.blocked ? form.blocked_reason : '',
          labels: String(form.labels ?? '').split(',').map(label => label.trim()).filter(Boolean),
          acceptance_criteria: lines(form.acceptance_criteria), related_plans: lines(form.related_plans), related_runs: lines(form.related_runs),
          ...(editor?.task ? { expected_revision: editor.task.revision } : {}),
        });
        setEditor(null); setNotice(`Saved “${saved.task.title}”.`); refresh();
      } else if (name === 'git.add' || name === 'git.remove') {
        if (!editor?.task || !payload.sha) throw new Error('Choose a commit first.');
        const result = await api.link(route.project, editor.task, String(payload.sha), name === 'git.remove');
        setEditor({ ...editor, task: result.task }); setNotice('Git evidence updated.'); refresh();
      } else if (name === 'clock.in' || name === 'clock.out') {
        const values = object(payload.clock);
        if (!String(values.actor ?? '').trim()) throw new Error('Enter the actor for this clock session.');
        setClock(values as typeof clock);
        await api.clock(route.project, { ...values, action: name === 'clock.in' ? 'in' : 'out' });
        setNotice(name === 'clock.in' ? 'Clock started.' : 'Clock stopped and session recorded.'); refresh();
      } else throw new Error('This command is not permitted.');
    } catch (error) { setError(message(error)); }
    finally { busyRef.current = false; setBusy(false); }
  };
  return { ...route, projects, data, filters, month, clock, revision, loading, busy, error, notice, editor, api, navigate, refresh, handleCommand, openerRef, closeEditor: () => { setEditor(null); setError(''); } };
}
