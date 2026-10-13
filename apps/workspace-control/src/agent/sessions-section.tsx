import type { AgentSession } from './use-agent-approvals';
import type { AgentConnection } from './use-agent-connection';

export function SessionsSection({ connection, session }: { connection: AgentConnection; session: AgentSession }) {
  if (!connection.project) {
    return <div className="agent-section">
      <p className="muted agent-empty">Select a project to start or stop its coding session.</p>
    </div>;
  }

  return <div className="agent-section">
    <div className="spread">
      <span className="agent-scope-label">Coding session for {connection.project}</span>
      <button type="button" className="text-button" onClick={session.refresh} disabled={session.loading}>Refresh</button>
    </div>
    {session.error && <p className="notice error" role="alert">{session.error}</p>}
    {session.loading && session.session === null
      ? <p className="muted agent-empty">Loading session...</p>
      : session.session
        ? <div className="agent-card">
          <div className="spread">
            <span className="agent-card-title">{session.session.branch}</span>
            <span className="status status-success">active</span>
          </div>
          <p className="mono muted">worktree {session.session.worktree}</p>
          <p className="small muted">started {new Date(session.session.startedAt).toLocaleString()}</p>
          <div className="row agent-card-actions">
            <button type="button" className="button" disabled={session.busy} onClick={session.stop}>Stop session</button>
          </div>
        </div>
        : <div className="agent-card">
          <p className="muted agent-empty">No coding session. Mutating tools need one - their changes stay in its worktree, never the primary checkout.</p>
          <div className="row agent-card-actions">
            <button type="button" className="button primary" disabled={session.busy} onClick={session.start}>Start session</button>
          </div>
        </div>}
  </div>;
}
