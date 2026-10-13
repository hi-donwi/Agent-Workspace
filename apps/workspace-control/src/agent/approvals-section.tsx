import type { AgentApprovals } from './use-agent-approvals';
import type { AgentConnection } from './use-agent-connection';

const shortSha = (value: string) => value.slice(0, 8);
const timeLeft = (expiresAt: string) => {
  const seconds = Math.round((new Date(expiresAt).getTime() - Date.now()) / 1000);
  if (Number.isNaN(seconds)) return 'unknown';
  if (seconds <= 0) return 'expired';
  if (seconds < 60) return `${seconds}s`;
  return `${Math.round(seconds / 60)}m`;
};

export function ApprovalsSection({ connection, approvals }: { connection: AgentConnection; approvals: AgentApprovals }) {
  if (!connection.project) {
    return <div className="agent-section">
      <p className="muted agent-empty">Select a project to see its pending approvals.</p>
    </div>;
  }

  return <div className="agent-section">
    <div className="spread">
      <span className="agent-scope-label">Pending in {connection.project}</span>
      <button type="button" className="text-button" onClick={approvals.refresh} disabled={approvals.loading}>Refresh</button>
    </div>
    {approvals.error && <p className="notice error" role="alert">{approvals.error}</p>}
    {approvals.loading && approvals.pending.length === 0
      ? <p className="muted agent-empty">Loading approvals...</p>
      : approvals.pending.length === 0
        ? <p className="muted agent-empty">No approvals are waiting. Gated actions ask here before they run.</p>
        : <ul className="agent-list">
          {approvals.pending.map(request => <li key={request.id} className="agent-card">
            <div className="spread">
              <span className="agent-card-title">{request.action}</span>
              <span className="status status-warning">expires in {timeLeft(request.expiresAt)}</span>
            </div>
            <p className="mono muted">head {shortSha(request.headSha)} | input {shortSha(request.inputHash)} | policy {shortSha(request.policyHash)}</p>
            <div className="row agent-card-actions">
              <button type="button" className="button primary" disabled={approvals.busy === request.id} onClick={() => approvals.decide(request.id, 'approved')}>Approve</button>
              <button type="button" className="button" disabled={approvals.busy === request.id} onClick={() => approvals.decide(request.id, 'denied')}>Deny</button>
            </div>
          </li>)}
        </ul>}
  </div>;
}
