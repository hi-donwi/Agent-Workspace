import type { Action, UIDLNode } from 'uidl-runtime';

export function node(id: string, type: string, props: Record<string, unknown> = {}, children?: UIDLNode[], events?: Record<string, Action | Action[]>): UIDLNode {
  return { id, type, props, ...(children ? { children } : {}), ...(events ? { events: Object.fromEntries(Object.entries(events).map(([name, action]) => [name, Array.isArray(action) ? action : [action]])) } : {}) };
}
export const box = (id: string, className: string, children: UIDLNode[], props = {}) => node(id, 'Container', { className, ...props }, children);
export const text = (id: string, value: unknown, className = '', heading?: number) => node(id, 'Text', { value, className, ...(heading ? { heading } : {}) });
export const command = (name: string, payload: Record<string, unknown> = {}): Action => ({
  command: { name, payload: Object.fromEntries(Object.entries(payload).map(([key, value]) => [key,
    value && typeof value === 'object' && '$bind' in value && typeof value.$bind === 'string' && value.$bind.startsWith('state.')
      ? { $expr: { path: value.$bind } } : value,
  ])) },
});
export const bind = (path: string) => ({ $bind: `state.${path}` });
export const button = (id: string, label: string, action: Action, className = 'button', iconName?: string) => node(id, 'Button', { label, type: 'button', className, ...(iconName ? { iconName } : {}) }, undefined, { onClick: action });
export const badge = (id: string, label: string, color = 'neutral') => text(id, label, `status status-${color}`);
export const empty = (id: string, title: string, description: string) => box(id, 'empty-state', [text(`${id}-title`, title, '', 3), text(`${id}-desc`, description, 'muted')]);
export const section = (id: string, title: string, children: UIDLNode[]) => box(id, 'panel', [text(`${id}-title`, title, 'section-title', 2), ...children]);
export const stat = (id: string, label: string, value: string | number, note: string, accent = false) => box(id, `stat${accent ? ' stat-accent' : ''}`, [text(`${id}-label`, label, 'eyebrow'), text(`${id}-value`, value, 'stat-value'), text(`${id}-note`, note, 'muted')]);
export function field(path: string, label: string, type = 'TextField', props: Record<string, unknown> = {}): UIDLNode {
  return node(path, type, { label, value: bind(path), className: 'field', ...props }, undefined, {
    onChange: { setState: { path, value: { $bind: 'event' } } },
  });
}
export const options = (values: string[]) => values.map(value => ({ value, label: value.replaceAll('_', ' ') }));
export const disclosure = (id: string, title: string, content: string) => node(id, 'WorkspaceDisclosure', { title, content });
