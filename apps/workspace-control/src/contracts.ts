export const statuses = ['backlog', 'ready', 'in_progress', 'review', 'done'] as const;
export type Status = typeof statuses[number];
export const statusLabels: Record<Status, string> = { backlog: 'Backlog', ready: 'Ready', in_progress: 'In progress', review: 'Review', done: 'Done' };
export const views = ['overview', 'projects', 'clients', 'board', 'backlog', 'search', 'plans', 'runs', 'context', 'activity', 'health', 'settings'] as const;
export type View = typeof views[number];
export const viewLabels: Record<View, string> = { overview: 'Overview', projects: 'Projects', clients: 'Clients', board: 'Task board', backlog: 'Backlog', search: 'Search', plans: 'Plans', runs: 'Runs', context: 'Context', activity: 'Activity', health: 'Health', settings: 'Settings' };
export const projectViews: View[] = ['board', 'backlog', 'search', 'runs', 'context', 'activity'];
export interface Project { key: string; client: string; group: string; folder: string; description: string }
export interface SourceFile { path: string; content: string; bytes?: number }
export interface RelatedRef { ref: string; resolved: boolean; file?: SourceFile }
export interface Task {
  id: string; project: string; title: string; status: Status; priority: string; owner: string;
  labels: string[]; blocked: boolean; blocked_reason: string; updated_at: string;
}
export interface TaskDetail extends Task {
  body: string; revision: string; acceptance_criteria: string[];
  related_plans: RelatedRef[]; related_runs: RelatedRef[];
  git_links: { project: string; sha: string }[];
}
export interface Commit { sha: string; subject: string; author: string; date: string }
export interface Board { columns: Record<Status, Task[]>; wip_limits: Partial<Record<Status, number>>; wip_warnings: string[]; legacy_candidates: { path: string }[] }
export interface Search { total: number; results: { task: Task; snippet: string }[]; freshness: { scanned_at: string; scanned_tasks: number } }
export interface Overview { counts: { projects: number; clients: number; tasks: number; blocked_tasks: number }; clients: { key: string; projects: Project[] }[]; context_local: boolean }
export interface Clients { clients: { key: string; summary: string; projects: Project[] }[] }
export interface Plans { plans: { title: string; project: string; run: string; body: string; updated: string }[] }
export interface Runs { runs: { id: string; handoff: string; updated: string }[] }
export interface Health { ok: boolean; checks: { id: string; ok: boolean; detail: string }[] }
export interface Settings { identity: Record<string, string>; runtime: string; root_name: string; context_local: boolean; loopback: boolean }
export interface Activity {
  month: string; active_clocks: Record<string, { actor: string; tool: string; start: string; note: string } | null>;
  hours: { human_total: number; agent_total: number; days: { day: string; human_hours: number; agent_hours: number; human_sessions: number; agent_sessions: number }[] };
  usage: { available: boolean; total_sessions: number; input_tokens: number; output_tokens: number; by_tool: Record<string, number>; days: { day: string; sessions: number; input_tokens: number; output_tokens: number }[] };
}
export interface Filters { q: string; status: string; priority: string; label: string; owner: string; blocked: string }
export const emptyFilters: Filters = { q: '', status: '', priority: '', label: '', owner: '', blocked: '' };
export interface PageData {
  overview?: Overview; clients?: Clients; board?: Board; search?: Search; plans?: Plans; runs?: Runs;
  context?: { files: SourceFile[] }; activity?: Activity; health?: Health; settings?: Settings;
}
