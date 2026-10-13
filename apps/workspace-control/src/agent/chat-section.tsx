import { useState, type FormEvent } from 'react';
import type { AgentChat } from './use-agent-chat';
import type { AgentConnection } from './use-agent-connection';

const preview = (value: string) => value.length > 160 ? `${value.slice(0, 160)}...` : value;

export function ChatSection({ connection, chat }: { connection: AgentConnection; chat: AgentChat }) {
  const [draft, setDraft] = useState('');
  const canSend = Boolean(draft.trim()) && Boolean(connection.provider) && Boolean(connection.model) && !chat.streaming;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!canSend) return;
    const content = draft;
    setDraft('');
    chat.send(content, {
      provider: connection.provider,
      model: connection.model,
      ...(connection.project ? { project: connection.project } : {}),
    });
  };

  return <div className="agent-section agent-chat">
    <div className="agent-scope">
      <span className="agent-scope-label">Chat bound to</span>
      <select className="field" aria-label="Project this chat works with" value={connection.project} onChange={event => connection.setProject(event.target.value)}>
        <option value="">No project (framework only)</option>
        {connection.projects.map(project => <option key={project.key} value={project.key}>{project.key}</option>)}
      </select>
    </div>
    <div className="agent-log" role="log" aria-live="polite" aria-label="Conversation">
      {chat.turns.length === 0
        ? <p className="muted agent-empty">Ask the agent to read, search, or change the selected project. Tools act in a coding session's worktree, never the primary checkout.</p>
        : chat.turns.map(turn => <article key={turn.id} className={`agent-turn agent-turn-${turn.role}`}>
          <p className="agent-role">{turn.role === 'user' ? 'You' : 'Agent'}</p>
          <p className="agent-text">{turn.content || (chat.streaming ? 'Thinking...' : '')}</p>
          {turn.tools.length > 0 && <ul className="agent-tools">
            {turn.tools.map((tool, index) => <li key={`${tool.name}-${index}`}><code>{tool.name}</code>{tool.result ? <span className="muted"> {preview(tool.result)}</span> : <span className="muted"> running...</span>}</li>)}
          </ul>}
        </article>)}
    </div>
    {chat.error && <p className="notice error" role="alert">{chat.error}</p>}
    <form className="agent-composer" onSubmit={submit}>
      <textarea className="field agent-prompt" aria-label="Message the agent" rows={2} value={draft} placeholder="Message the agent..." onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) submit(event); }} />
      <div className="agent-composer-actions">
        <button type="button" className="text-button" onClick={chat.clear} disabled={chat.streaming || chat.turns.length === 0}>Clear</button>
        {chat.streaming
          ? <button type="button" className="button" onClick={chat.stop}>Stop</button>
          : <button type="submit" className="button primary" disabled={!canSend}>Send</button>}
      </div>
    </form>
  </div>;
}
