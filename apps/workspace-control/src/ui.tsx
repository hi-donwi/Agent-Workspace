import { Component, useEffect, useRef, type ReactNode } from 'react';
import { createRegistry, defaultRegistry } from 'uidl-runtime';

export const registry = createRegistry();
for (const manifest of defaultRegistry.list()) registry.register(manifest);
registry.register({
  type: 'WorkspaceDisclosure', category: 'data', acceptsChildren: false,
  component: ({ title, content }) => <details className="document-disclosure"><summary>{String(title)}</summary><pre>{String(content)}</pre></details>,
});

export function TaskDialog({ children, onClose, title, busy, returnFocus }: { children: ReactNode; onClose: () => void; title: string; busy: boolean; returnFocus: HTMLElement | null }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    const previous = returnFocus;
    dialog?.showModal();
    return () => { dialog?.close(); previous?.focus(); };
  }, []);
  return <dialog ref={ref} className="task-dialog" aria-labelledby="task-dialog-title" onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className="dialog-header"><div><p className="eyebrow">TASK DETAILS</p><h2 id="task-dialog-title">{title}</h2></div><button className="icon-button" aria-label="Close task" onClick={onClose} disabled={busy}>×</button></div>
    {children}
  </dialog>;
}

export class RenderBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed ? <div className="notice error" role="alert">This page could not be rendered. <button className="text-button" onClick={() => location.reload()}>Reload workspace</button></div> : this.props.children;
  }
}
