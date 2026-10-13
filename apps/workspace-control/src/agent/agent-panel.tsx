import { useMemo, useState } from 'react';
import { AgentApi, agentToken } from './agent-api';
import { useAgentApprovals, useAgentSession } from './use-agent-approvals';
import { useAgentChat } from './use-agent-chat';
import { useAgentConnection } from './use-agent-connection';
import { ApprovalsSection } from './approvals-section';
import { ChatSection } from './chat-section';
import { ConfigSection } from './config-section';
import { SessionsSection } from './sessions-section';
import './agent-panel.css';

type Tab = 'chat' | 'approvals' | 'sessions' | 'config';

export function AgentPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const api = useMemo(() => new AgentApi(agentToken()), []);
  const connection = useAgentConnection(api);
  const chat = useAgentChat(api);
  const approvals = useAgentApprovals(api, connection.project);
  const session = useAgentSession(api, connection.project);
  const [tab, setTab] = useState<Tab>('chat');

  const tabs: { id: Tab; label: string; badge: number }[] = [
    { id: 'chat', label: 'Chat', badge: 0 },
    { id: 'approvals', label: 'Approvals', badge: approvals.pending.length },
    { id: 'sessions', label: 'Sessions', badge: session.session ? 1 : 0 },
    { id: 'config', label: 'Config', badge: 0 },
  ];

  return <aside id="agent-panel" className={`agent-panel${open ? ' is-open' : ''}`} aria-label="Agent panel" aria-hidden={!open} inert={!open}>
    <header className="agent-head">
      <div>
        <p className="eyebrow">Agent host</p>
        <h2>Agent</h2>
      </div>
      <button type="button" className="text-button" onClick={onClose}>Close</button>
    </header>

    {connection.available === null && <p className="muted agent-empty">Connecting to the agent host...</p>}

    {connection.available === false && <div className="empty-state">
      <h3>The agent host is not running</h3>
      <p className="muted">Start it with <code>ws web --agent</code> and open the URL it prints. The desk alone is read-only.</p>
    </div>}

    {connection.available === true && <>
      <div className="agent-tabs" role="tablist" aria-label="Agent sections">
        {tabs.map(item => <button key={item.id} role="tab" type="button" id={`agent-tab-${item.id}`} aria-controls="agent-tabpanel" aria-selected={tab === item.id} className={`agent-tab${tab === item.id ? ' is-active' : ''}`} onClick={() => setTab(item.id)}>
          {item.label}{item.badge > 0 && <span className="agent-badge">{item.badge}</span>}
        </button>)}
      </div>
      {connection.error && <p className="notice error" role="alert">{connection.error}</p>}
      <div className="agent-body" id="agent-tabpanel" role="tabpanel" aria-label={tabs.find(item => item.id === tab)?.label}>
        {tab === 'chat' && <ChatSection connection={connection} chat={chat} />}
        {tab === 'approvals' && <ApprovalsSection connection={connection} approvals={approvals} />}
        {tab === 'sessions' && <SessionsSection connection={connection} session={session} />}
        {tab === 'config' && <ConfigSection connection={connection} api={api} />}
      </div>
      <footer className="agent-foot">
        <span className="mono muted">{connection.workspace?.root ?? ''}</span>
        <span className="small muted">{connection.provider}/{connection.model}</span>
      </footer>
    </>}
  </aside>;
}
