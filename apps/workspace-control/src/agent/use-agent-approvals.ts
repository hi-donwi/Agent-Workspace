import { useCallback, useEffect, useMemo, useState } from 'react';
import { AgentApi, AgentUnavailableError, type ApprovalRequest, type CodingSession } from './agent-api';

const message = (error: unknown) => error instanceof Error ? error.message : 'The request could not be completed.';

export interface AgentApprovals {
  pending: ApprovalRequest[];
  loading: boolean;
  error: string;
  busy: string;
  decide: (id: string, decision: 'approved' | 'denied') => void;
  refresh: () => void;
}

/** Pending local approvals for the selected project (ADR-0020). */
export function useAgentApprovals(api: AgentApi, project: string): AgentApprovals {
  const [pending, setPending] = useState<ApprovalRequest[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [revision, setRevision] = useState(0);

  const refresh = useCallback(() => setRevision(value => value + 1), []);

  useEffect(() => {
    if (!project) { setPending([]); return; }
    const controller = new AbortController();
    setLoading(true); setError('');
    api.approvals(project, controller.signal)
      .then(result => { if (!controller.signal.aborted) setPending(result.pending); })
      .catch(cause => {
        if (controller.signal.aborted || cause instanceof AgentUnavailableError) return;
        setError(message(cause));
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [api, project, revision]);

  const decide = useCallback((id: string, decision: 'approved' | 'denied') => {
    setBusy(id); setError('');
    api.decide(project, id, decision)
      .then(refresh)
      .catch(cause => setError(message(cause)))
      .finally(() => setBusy(''));
  }, [api, project, refresh]);

  return useMemo(() => ({ pending, loading, error, busy, decide, refresh }), [pending, loading, error, busy, decide, refresh]);
}

export interface AgentSession {
  session: CodingSession | null;
  loading: boolean;
  error: string;
  busy: boolean;
  start: () => void;
  stop: () => void;
  refresh: () => void;
}

/** The project's active coding session: its worktree is where mutating tools act. */
export function useAgentSession(api: AgentApi, project: string): AgentSession {
  const [session, setSession] = useState<CodingSession | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);

  const refresh = useCallback(() => setRevision(value => value + 1), []);

  useEffect(() => {
    if (!project) { setSession(null); return; }
    const controller = new AbortController();
    setLoading(true); setError('');
    api.codingSession(project, controller.signal)
      .then(result => { if (!controller.signal.aborted) setSession(result.session); })
      .catch(cause => {
        if (controller.signal.aborted || cause instanceof AgentUnavailableError) return;
        setError(message(cause));
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [api, project, revision]);

  const act = useCallback((action: 'start' | 'stop') => {
    setBusy(true); setError('');
    const call = action === 'start' ? api.startSession(project) : api.stopSession(project);
    call.then(refresh).catch(cause => setError(message(cause))).finally(() => setBusy(false));
  }, [api, project, refresh]);

  return useMemo(() => ({
    session, loading, error, busy,
    start: () => act('start'), stop: () => act('stop'), refresh,
  }), [session, loading, error, busy, act, refresh]);
}
