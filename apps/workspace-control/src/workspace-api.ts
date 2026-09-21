import type { DataAdapter, Mutation, Query, QueryResult } from 'uidl-runtime';
import type { Commit, Filters, PageData, Project, TaskDetail, View } from './contracts';

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

const disabled = (): never => { throw new Error('Use an explicitly permitted workspace command.'); };

/** Read-only UIDL adapter. Writes are exposed only through the host command service. */
export class WorkspaceApi implements DataAdapter {
  constructor(private token: string) {}

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const response = await fetch(`/api/${path}`, {
      ...options, cache: 'no-store',
      headers: { Authorization: `Bearer ${this.token}`, 'Content-Type': 'application/json' },
    });
    const data = await response.json() as T & { error?: string };
    if (!response.ok) {
      const message = response.status === 401 ? 'Your connection token has expired. Reopen the URL printed by ws web.'
        : response.status === 409 ? 'This record changed or the session is already active. Refresh before trying again.'
        : data.error || `Request failed (${response.status}).`;
      throw new ApiError(message, response.status);
    }
    return data;
  }

  async report<T>(name: string, params: Record<string, unknown>, signal?: AbortSignal): Promise<T> {
    const global = ['overview', 'projects', 'clients', 'plans', 'health', 'settings'];
    const scoped = ['board', 'search', 'context', 'runs', 'activity', 'commits'];
    const query = new URLSearchParams();
    for (const key of ['q', 'status', 'priority', 'label', 'owner', 'blocked', 'month']) {
      if (typeof params[key] === 'string' && params[key]) query.set(key, params[key] as string);
    }
    let path: string;
    if (global.includes(name)) path = name;
    else if (scoped.includes(name) && typeof params.project === 'string' && params.project) {
      path = `projects/${encodeURIComponent(params.project)}/${name}`;
    } else throw new Error('Unknown workspace report or missing project.');
    return this.request<T>(`${path}?${query}`, { signal });
  }

  async query<T>(query: Query, signal?: AbortSignal): Promise<QueryResult<T>> {
    const result = await this.report<{ projects: T[] }>(query.collection, {}, signal);
    if (query.collection !== 'projects') throw new Error('This collection must be read as a report.');
    return { rows: result.projects, total: result.projects.length, page: 1, pageSize: result.projects.length };
  }
  async get<T>(_collection: string, _id: string): Promise<{ record: T; meta: { version: number } } | undefined> { return disabled(); }
  async create<T>(_mutation: Mutation): Promise<{ record: T; meta: { version: number } }> { return disabled(); }
  async update<T>(_mutation: Mutation): Promise<{ record: T; meta: { version: number } }> { return disabled(); }
  async remove(): Promise<void> { disabled(); }
  async transition<T>(_mutation: Mutation & { transition: string }): Promise<{ record: T; meta: { version: number } }> { return disabled(); }

  async load(view: View, project: string, filters: Filters, month: string, signal: AbortSignal): Promise<PageData> {
    if (view === 'projects') return {};
    const report = view === 'backlog' ? 'board' : view;
    if (['board', 'search', 'context', 'runs', 'activity'].includes(report) && !project) return {};
    return { [report]: await this.report(report, { ...filters, project, month }, signal) };
  }
  async projects(signal: AbortSignal): Promise<Project[]> { return (await this.query<Project>({ collection: 'projects' }, signal)).rows; }
  task(project: string, id: string): Promise<{ task: TaskDetail }> { return this.request(this.taskPath(project, id)); }
  commits(project: string): Promise<{ commits: Commit[] }> { return this.report('commits', { project }); }
  private taskPath(project: string, id?: string): string {
    return `projects/${encodeURIComponent(project)}/tasks${id ? `/${encodeURIComponent(id)}` : ''}`;
  }
  saveTask(project: string, id: string | undefined, payload: Record<string, unknown>): Promise<{ task: TaskDetail }> {
    return this.request(this.taskPath(project, id), { method: id ? 'PUT' : 'POST', body: JSON.stringify(payload) });
  }
  link(project: string, task: TaskDetail, sha: string, remove = false): Promise<{ task: TaskDetail }> {
    return this.request(`${this.taskPath(project, task.id)}/git-links${remove ? `/${encodeURIComponent(sha)}` : ''}`, {
      method: remove ? 'DELETE' : 'POST', body: JSON.stringify({ sha, expected_revision: task.revision }),
    });
  }
  clock(project: string, payload: Record<string, unknown>): Promise<unknown> {
    return this.request(`projects/${encodeURIComponent(project)}/clock`, { method: 'POST', body: JSON.stringify(payload) });
  }
}
