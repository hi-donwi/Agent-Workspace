import { DocumentSchema, type UIDLNode } from 'uidl-runtime';
import { emptyFilters, statusLabels, statuses, viewLabels, type Filters, type PageData, type Project, type Task, type View } from '../contracts';
import { badge, bind, box, button, command, disclosure, empty, field, node, options, section, stat, text } from './primitives';

const openProject = (key: string) => command('project.open', { project: key });
const openTask = (id: string) => command('task.open', { id });

function projectCard(project: Project): UIDLNode {
  return box(`project-${project.key}`, 'project-card', [
    box(`${project.key}-top`, 'spread', [text(`${project.key}-avatar`, project.key.slice(0, 2).toUpperCase(), 'project-avatar'), badge(`${project.key}-client`, project.client)]),
    button(`${project.key}-open`, project.key, openProject(project.key), 'text-button project-title'),
    text(`${project.key}-desc`, project.description || 'No project description yet.', 'muted clamp'),
    box(`${project.key}-footer`, 'spread card-footer', [text(`${project.key}-group`, project.group === '-' ? 'Independent project' : project.group, 'muted small'), text(`${project.key}-arrow`, '↗', 'muted')]),
  ]);
}

function taskCard(task: Task, compact = false): UIDLNode {
  return box(`task-${task.id}`, compact ? 'task-row' : 'task-card', [
    box(`${task.id}-meta`, 'spread', [text(`${task.id}-id`, task.id.replace('task_', '').slice(0, 12).toUpperCase(), 'mono muted small'), badge(`${task.id}-priority`, task.priority, task.priority === 'urgent' || task.priority === 'high' ? 'warning' : 'neutral')]),
    button(`${task.id}-open`, task.title, openTask(task.id), 'text-button task-title'),
    ...(task.blocked ? [badge(`${task.id}-blocked`, `Blocked · ${task.blocked_reason}`, 'danger')] : []),
    box(`${task.id}-bottom`, 'spread task-bottom', [text(`${task.id}-owner`, task.owner || 'Unassigned', 'muted small'), text(`${task.id}-labels`, task.labels.join(' · '), 'small muted')]),
  ]);
}

function boardPage(data: PageData, backlog: boolean): UIDLNode[] {
  const board = data.board;
  if (!board) return [];
  const columns = backlog ? ['backlog'] as const : statuses;
  return [
    box('board-toolbar', 'spread', [text('board-help', backlog ? 'Shape the work before it moves into delivery.' : 'Open a task to update its status, owner, or evidence.', 'muted'), button('new-task', 'New task', command('task.new'), 'button primary', 'plus')]),
    ...board.wip_warnings.map((warning, index) => text(`warning-${index}`, warning, 'notice warning')),
    box('board-columns', backlog ? 'backlog-list' : 'board-grid', columns.map(status => box(`column-${status}`, 'board-column', [
      box(`${status}-heading`, 'spread column-heading', [text(`${status}-name`, statusLabels[status], '', 2), badge(`${status}-count`, `${board.columns[status].length}${board.wip_limits[status] ? ` / ${board.wip_limits[status]}` : ''}`)]),
      ...board.columns[status].map(task => taskCard(task, backlog)),
      ...(board.columns[status].length ? [] : [empty(`${status}-empty`, 'Nothing here yet', 'Tasks will appear as work moves forward.')]),
    ]))),
    ...(board.legacy_candidates.length ? [section('legacy', 'Unstructured task files', [text('legacy-desc', 'These files need conversion to task frontmatter before they can appear on the board.', 'muted'), ...board.legacy_candidates.map((item, i) => text(`legacy-${i}`, item.path, 'mono small'))])] : []),
  ];
}

function searchPage(data: PageData): UIDLNode[] {
  return [
    node('search-form', 'Form', { className: 'panel stack' }, [
      box('search-main', 'search-main', [field('filters.q', 'Search tasks', 'TextField', { placeholder: 'Title, description, or task ID…', type: 'search' }), node('search-submit', 'Button', { label: 'Search', type: 'submit', className: 'button primary' })]),
      box('search-filters', 'filter-grid', [
        field('filters.status', 'Status', 'Select', { options: [{ value: '', label: 'All statuses' }, ...statuses.map(value => ({ value, label: statusLabels[value] }))] }),
        field('filters.priority', 'Priority', 'Select', { options: [{ value: '', label: 'All priorities' }, ...options(['low', 'normal', 'high', 'urgent'])] }),
        field('filters.owner', 'Owner', 'TextField', { placeholder: 'Any owner' }),
        field('filters.label', 'Label', 'TextField', { placeholder: 'Any label' }),
        field('filters.blocked', 'Blocked', 'Select', { options: [{ value: '', label: 'All tasks' }, { value: 'true', label: 'Blocked only' }, { value: 'false', label: 'Not blocked' }] }),
      ]),
    ], { onSubmit: command('search.apply', { filters: bind('filters') }) }),
    button('clear-search', 'Clear filters', command('search.apply', { filters: { ...emptyFilters } }), 'text-button'),
    text('search-count', `${data.search?.total ?? 0} matching tasks`, 'section-title', 2),
    ...(data.search?.results.length ? data.search.results.map(({ task, snippet }) => box(`result-${task.id}`, 'panel search-result', [taskCard(task, true), text(`${task.id}-snippet`, snippet, 'muted')])) : [empty('search-empty', 'No matching tasks', 'Try a different search or clear your filters.')]),
    ...(data.search ? [text('freshness', `Source refreshed ${new Date(data.search.freshness.scanned_at).toLocaleString()} · ${data.search.freshness.scanned_tasks} tasks scanned`, 'muted small')] : []),
  ];
}

function activityPage(data: PageData): UIDLNode[] {
  const activity = data.activity;
  if (!activity) return [];
  return [
    node('month-form', 'Form', { className: 'month-form' }, [field('month', 'Reporting month', 'TextField', { type: 'month', required: true }), node('month-submit', 'Button', { label: 'Apply month', type: 'submit', className: 'button' })], { onSubmit: command('month.apply', { month: bind('month') }) }),
    box('activity-stats', 'stats-grid', [stat('human-hours', 'Human hours', `${activity.hours.human_total.toFixed(2)}h`, 'Recorded human attention', true), stat('agent-hours', 'Agent hours', `${activity.hours.agent_total.toFixed(2)}h`, 'Overlapping agent time merged'), stat('input-tokens', 'Input tokens', activity.usage.input_tokens.toLocaleString(), activity.usage.available ? 'From the configured usage source' : 'Usage source unavailable'), stat('output-tokens', 'Output tokens', activity.usage.output_tokens.toLocaleString(), `${activity.usage.total_sessions} recorded sessions`)]),
    section('daily-hours', 'Daily activity', activity.hours.days.length ? activity.hours.days.map(day => box(`day-${day.day}`, 'data-row', [text(`${day.day}-date`, day.day, 'mono'), text(`${day.day}-human`, `${day.human_hours.toFixed(2)}h human · ${day.human_sessions} sessions`), text(`${day.day}-agent`, `${day.agent_hours.toFixed(2)}h agent · ${day.agent_sessions} sessions`)])) : [empty('hours-empty', 'No hours recorded this month', 'Completed clock sessions will appear here.')]),
    section('active-clocks', 'Active sessions', Object.entries(activity.active_clocks).flatMap(([kind, clock]) => clock ? [box(`clock-${kind}`, 'data-row', [badge(`clock-${kind}-badge`, kind, 'success'), text(`clock-${kind}-actor`, `${clock.actor} · ${clock.tool}`), text(`clock-${kind}-start`, `Since ${new Date(clock.start).toLocaleString()}`, 'muted'), text(`clock-${kind}-note`, clock.note, 'muted')])] : [text(`no-${kind}`, `No active ${kind} session`, 'muted')])),
    section('clock-controls', 'Record a work session', [
      text('clock-help', 'Human and agent time are recorded separately. Use the same actor, tool, and session when stopping a clock.', 'muted'),
      box('clock-fields', 'filter-grid', [field('clock.actor', 'Actor', 'TextField', { placeholder: 'Your name', required: true }), field('clock.kind', 'Clock type', 'Select', { options: options(['human', 'agent']) }), field('clock.tool', 'Tool', 'TextField', { required: true, pattern: '[a-zA-Z0-9_-]+' }), field('clock.session', 'Session', 'TextField'), field('clock.note', 'Work note', 'TextField')]),
      box('clock-buttons', 'row', [button('clock-in', 'Clock in', command('clock.in', { clock: bind('clock') }), 'button primary', 'play'), button('clock-out', 'Clock out', command('clock.out', { clock: bind('clock') }), 'button', 'pause')]),
    ]),
    section('usage', 'Usage by tool', Object.entries(activity.usage.by_tool).length ? Object.entries(activity.usage.by_tool).map(([tool, count]) => box(`usage-${tool}`, 'spread data-row', [text(`${tool}-name`, tool), text(`${tool}-sessions`, `${count} sessions`, 'muted')])) : [text('usage-empty', 'No tool usage recorded for this project and month.', 'muted')]),
  ];
}

export function pageDocument(view: View, data: PageData, projects: Project[], project: string, filters: Filters, month: string, clock: Record<string, string>) {
  let children: UIDLNode[] = [];
  if (view === 'overview' && data.overview) {
    const { counts, clients } = data.overview;
    children = [
      box('overview-intro', 'welcome-panel', [box('welcome-copy', 'stack welcome-copy', [badge('welcome-status', 'Your local workspace', 'success'), text('welcome-title', 'A clear view of your work.', '', 2), text('welcome-desc', 'Projects, delivery, and context — connected in one place.', 'muted'), button('welcome-action', 'Explore projects', command('view.open', { view: 'projects' }), 'button primary', 'arrow-right')]), box('welcome-art', 'workspace-art', [text('art-symbol', 'W', 'art-letter'), text('art-caption', 'WORKSPACE / CONTROL', 'mono small')], { 'aria-hidden': true })]),
      box('overview-stats', 'stats-grid', [stat('projects-stat', 'Projects', counts.projects, 'Across your workspace', true), stat('clients-stat', 'Clients', counts.clients, 'Organized by ownership'), stat('tasks-stat', 'Tasks', counts.tasks, 'Tracked in your context'), stat('blocked-stat', 'Blocked tasks', counts.blocked_tasks, counts.blocked_tasks ? 'Ready for your attention' : 'No blockers recorded')]),
      box('projects-heading', 'spread', [text('projects-heading-text', 'Your projects', 'section-title', 2), button('view-projects', 'View all projects', command('view.open', { view: 'projects' }), 'text-button', 'arrow-right')]),
      box('overview-projects', 'project-grid', projects.slice(0, 6).map(projectCard)),
      ...(!projects.length ? [empty('no-projects', 'Your workspace starts here', 'Register a project with ws new to see it here.')] : []),
      section('ownership', 'Workspace at a glance', clients.map(client => box(`client-${client.key}`, 'spread data-row', [text(`client-${client.key}-name`, client.key), text(`client-${client.key}-count`, `${client.projects.length} projects`, 'muted')]))),
    ];
  } else if (view === 'projects') children = [text('project-count', `${projects.length} project${projects.length === 1 ? '' : 's'} · Select a project to open its task board.`, 'muted'), ...(projects.length ? [box('all-projects', 'project-grid', projects.map(projectCard))] : [empty('projects-empty', 'No registered projects', 'Use ws new to register your first project.')])];
  else if (view === 'clients' && data.clients) children = data.clients.clients.length ? data.clients.clients.map(client => section(`client-${client.key}`, client.key, [text(`${client.key}-summary`, client.summary || 'No client summary yet.', 'pre-wrap muted'), box(`${client.key}-projects`, 'project-grid', client.projects.map(projectCard))])) : [empty('clients-empty', 'No clients yet', 'Use ws client new to add a client.')];
  else if (view === 'board' || view === 'backlog') children = boardPage(data, view === 'backlog');
  else if (view === 'search') children = searchPage(data);
  else if (view === 'activity') children = activityPage(data);
  else if (view === 'plans' && data.plans) children = data.plans.plans.length ? data.plans.plans.map((plan, i) => section(`plan-${i}`, plan.title, [text(`plan-${i}-meta`, `${plan.project} · ${new Date(plan.updated).toLocaleDateString()}`, 'muted small'), disclosure(`plan-${i}-body`, 'Read plan', plan.body)])) : [empty('plans-empty', 'No plans yet', 'Plans from workspace runs will appear here.')];
  else if (view === 'runs' && data.runs) children = data.runs.runs.length ? data.runs.runs.map((run, i) => section(`run-${i}`, run.id, [text(`run-${i}-updated`, new Date(run.updated).toLocaleString(), 'muted small'), text(`run-${i}-handoff`, run.handoff || 'No handoff written yet.', 'pre-wrap'), button(`run-${i}-context`, 'Read full handoffs', command('view.open', { view: 'context' }), 'text-button')])) : [empty('runs-empty', 'No runs yet', 'Create a run with ws run to capture the next piece of work.')];
  else if (view === 'context' && data.context) children = data.context.files.length ? data.context.files.map((file, i) => disclosure(`file-${i}`, file.path, file.content)) : [empty('context-empty', 'No context documents', 'Project memory and run handoffs will appear here.')];
  else if (view === 'health' && data.health) children = [box('health-summary', 'health-summary', [badge('health-badge', data.health.ok ? 'Checks passed' : 'Needs attention', data.health.ok ? 'success' : 'warning'), text('health-message', data.health.ok ? 'Your workspace is ready.' : 'Some workspace checks need attention.', '', 2), text('health-description', 'Local registry, context configuration, and project checkout checks.', 'muted')]), section('health-checks', 'Workspace checks', data.health.checks.map(check => box(`check-${check.id}`, 'data-row', [badge(`${check.id}-status`, check.ok ? 'Pass' : 'Check', check.ok ? 'success' : 'warning'), text(`${check.id}-name`, check.id.replaceAll('_', ' ')), text(`${check.id}-detail`, check.detail, 'muted')])))];
  else if (view === 'settings' && data.settings) children = [section('appearance', 'Appearance', [text('appearance-help', 'Choose Light, Dark, or System in the sidebar. Your choice is saved on this device.', 'muted')]), section('configuration', 'Workspace configuration', [...Object.entries(data.settings.identity).map(([key, value]) => box(`setting-${key}`, 'data-row', [text(`${key}-label`, key.replaceAll('_', ' ')), text(`${key}-value`, value || 'Not configured', 'mono muted')])), box('runtime-setting', 'data-row', [text('runtime-label', 'UI runtime'), text('runtime-value', `${data.settings.runtime} · npm uidl-runtime 0.1.4`, 'mono muted')]), text('settings-help', 'Configuration is read from workspace.conf. Update that file to change workspace settings.', 'muted small')])];
  if (['board', 'backlog', 'search', 'runs', 'context', 'activity'].includes(view) && !project) children = [empty('choose-project', 'Choose a project', 'Select a project from the sidebar to view its work.')];
  return DocumentSchema.parse({ version: '1.0', id: `workspace-${view}`, name: viewLabels[view], state: { filters: { ...filters }, month, clock: { ...clock } }, root: box('page', 'page-content', children) });
}
