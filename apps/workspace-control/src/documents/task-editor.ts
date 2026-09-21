import { DocumentSchema } from 'uidl-runtime';
import { statuses, statusLabels, type Commit, type TaskDetail } from '../contracts';
import { bind, box, button, command, disclosure, field, node, options, section, text } from './primitives';

export function editorDocument(task: TaskDetail | null, commits: Commit[]) {
  const form = {
    title: task?.title ?? '', status: task?.status ?? 'backlog', priority: task?.priority ?? 'normal',
    owner: task?.owner ?? 'unassigned', body: task?.body ?? '', labels: task?.labels.join(', ') ?? '',
    blocked: task?.blocked ?? false, blocked_reason: task?.blocked_reason ?? '',
    acceptance_criteria: task?.acceptance_criteria.join('\n') ?? '',
    related_plans: task?.related_plans.map(ref => ref.ref).join('\n') ?? '',
    related_runs: task?.related_runs.map(ref => ref.ref).join('\n') ?? '',
  };
  return DocumentSchema.parse({
    version: '1.0', id: `editor-${task?.id ?? 'new'}`, name: 'Task editor', state: { form, sha: '' },
    root: box('editor', 'stack', [
      node('task-form', 'Form', { className: 'stack' }, [
        field('form.title', 'Title', 'TextField', { required: true, maxLength: 240, placeholder: 'What needs to be done?', autoFocus: true }),
        box('task-properties', 'form-grid', [
          field('form.status', 'Status', 'Select', { options: statuses.map(value => ({ value, label: statusLabels[value] })) }),
          field('form.priority', 'Priority', 'Select', { options: options(['low', 'normal', 'high', 'urgent']) }),
          field('form.owner', 'Owner'), field('form.labels', 'Labels', 'TextField', { placeholder: 'Comma-separated labels' }),
        ]),
        field('form.body', 'Description', 'Textarea', { rows: 4, placeholder: 'Describe the work and any useful context.' }),
        field('form.acceptance_criteria', 'Acceptance criteria', 'Textarea', { rows: 3, placeholder: 'One criterion per line' }),
        node('form.blocked', 'Checkbox', { label: 'Blocked', checked: bind('form.blocked'), className: 'checkbox' }, undefined, { onChange: { setState: { path: 'form.blocked', value: { $bind: 'event' } } } }),
        field('form.blocked_reason', 'Blocked reason', 'TextField', { placeholder: 'Required when the task is blocked' }),
        box('task-references', 'form-grid', [field('form.related_plans', 'Related plan paths', 'Textarea', { rows: 2, placeholder: 'One context-relative path per line' }), field('form.related_runs', 'Related run paths', 'Textarea', { rows: 2, placeholder: 'One context-relative path per line' })]),
        box('editor-actions', 'row editor-actions', [node('save-task', 'Button', { label: task ? 'Save changes' : 'Create task', type: 'submit', className: 'button primary' }), button('cancel-task', 'Cancel', command('task.close'))]),
      ], { onSubmit: command('task.save', { form: bind('form') }) }),
      ...(task ? [section('git-evidence', 'Git evidence', [
        ...task.git_links.map((link, index) => box(`link-${index}`, 'spread data-row', [text(`link-${index}-sha`, `${link.project} @ ${link.sha.slice(0, 12)}`, 'mono small'), button(`remove-link-${index}`, `Remove ${link.sha.slice(0, 7)}`, command('git.remove', { sha: link.sha }), 'text-button danger')])),
        ...(!task.git_links.length ? [text('no-evidence', 'No commits linked yet.', 'muted')] : []),
        field('sha', 'Commit', 'Select', { options: [{ value: '', label: 'Choose a commit…' }, ...commits.map(commit => ({ value: commit.sha, label: `${commit.sha.slice(0, 7)} · ${commit.subject}` }))] }),
        button('add-evidence', 'Link commit', command('git.add', { sha: bind('sha') })),
      ]),
      ...[...task.related_plans, ...task.related_runs].map((ref, index) => disclosure(`reference-${index}`, ref.ref, ref.file?.content ?? 'Reference could not be resolved.'))] : []),
    ]),
  });
}
