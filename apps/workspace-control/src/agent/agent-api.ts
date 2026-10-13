/**
 * Client for the agent host's `/api/agent/*` surface (Agent-Workspace ADR-0019 §4).
 *
 * In agent mode the host serves this desk and prints the URL with its own token, so the
 * page's `?token=` authenticates every call here. When no host is present (the plain
 * `ws web` desk), `/api/agent/*` does not exist and every call reports `AgentUnavailableError`
 * so the panel can degrade instead of showing a broken screen.
 */

export interface AgentProvider {
  id: string;
  name: string;
  models: string[];
  locality: string;
}
export interface AgentProviders {
  providers: AgentProvider[];
  defaultProvider: string;
  defaultModel: string;
}
export interface AgentProject {
  key: string;
  client: string;
  folder: string;
  allowedEndpoints: string[] | null;
}
export interface AgentWorkspace {
  root: string;
  projects: string;
  tree: string;
}
export interface AgentConfig {
  defaultProvider: string;
  defaultModel: string;
  providers: Record<string, { apiKey: string; baseUrl?: string } | undefined>;
  [key: string]: unknown;
}
export interface ApprovalRequest {
  id: string;
  project: string;
  headSha: string;
  action: string;
  inputHash: string;
  policyHash: string;
  requestedAt: string;
  expiresAt: string;
}
export interface CodingSession {
  id: string;
  project: string;
  worktree: string;
  branch: string;
  startedAt: string;
}
export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

/** One event from the host's chat line protocol (`server/stream-protocol.ts`). */
export type ChatEvent =
  | { type: 'text'; text: string }
  | { type: 'tool-call'; name: string; args: Record<string, unknown> }
  | { type: 'tool-result'; result: string }
  | { type: 'error'; message: string }
  | { type: 'done' };

export class AgentUnavailableError extends Error {
  constructor() { super('The agent host is not running on this origin.'); }
}

export function agentToken(): string {
  return new URL(location.href).searchParams.get('token') ?? '';
}

export class AgentApi {
  constructor(private token: string) {}

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`/api/agent/${path}`, {
        ...options, cache: 'no-store',
        headers: { Authorization: `Bearer ${this.token}`, 'Content-Type': 'application/json', ...options.headers },
      });
    } catch {
      throw new AgentUnavailableError();
    }
    if (response.status === 404 || response.status === 501) throw new AgentUnavailableError();
    // A desk served without a host answers with the SPA's index.html, not JSON; treat any
    // non-JSON reply as "no agent host" so the panel degrades instead of trusting a shape.
    if (!response.headers.get('content-type')?.includes('application/json')) throw new AgentUnavailableError();
    const data = await response.json().catch(() => ({})) as T & { error?: string };
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
    return data;
  }

  providers(): Promise<AgentProviders> { return this.request('providers'); }
  projects(): Promise<{ projects: AgentProject[] }> { return this.request('projects'); }
  workspace(): Promise<AgentWorkspace> { return this.request('workspace'); }
  config(): Promise<AgentConfig> { return this.request('config'); }
  saveConfig(body: Partial<AgentConfig>): Promise<{ ok: boolean }> {
    return this.request('config', { method: 'POST', body: JSON.stringify(body) });
  }

  approvals(project: string, signal?: AbortSignal): Promise<{ pending: ApprovalRequest[] }> {
    return this.request(`approvals?project=${encodeURIComponent(project)}`, { signal });
  }
  decide(project: string, id: string, decision: 'approved' | 'denied'): Promise<{ ok: boolean }> {
    return this.request('approvals/decide', { method: 'POST', body: JSON.stringify({ project, id, decision }) });
  }

  codingSession(project: string, signal?: AbortSignal): Promise<{ session: CodingSession | null }> {
    return this.request(`coding-sessions/${encodeURIComponent(project)}`, { signal });
  }
  startSession(project: string): Promise<{ session: CodingSession }> {
    return this.request(`coding-sessions/${encodeURIComponent(project)}/start`, { method: 'POST' });
  }
  stopSession(project: string): Promise<{ stopped: boolean }> {
    return this.request(`coding-sessions/${encodeURIComponent(project)}/stop`, { method: 'POST' });
  }

  /** POST a chat turn and read the host's line protocol until the body ends. */
  async chat(
    body: { messages: ChatMessage[]; provider: string; model: string; project?: string },
    onEvent: (event: ChatEvent) => void,
    signal: AbortSignal,
  ): Promise<void> {
    let response: Response;
    try {
      response = await fetch('/api/agent/chat', {
        method: 'POST', signal,
        headers: { Authorization: `Bearer ${this.token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    } catch (error) {
      if ((error as Error).name === 'AbortError') return;
      throw new AgentUnavailableError();
    }
    if (response.status === 404 || response.status === 501) throw new AgentUnavailableError();
    if (!response.ok) {
      const data = await response.json().catch(() => ({})) as { error?: string };
      throw new Error(data.error || `Request failed (${response.status}).`);
    }
    const reader = response.body?.getReader();
    if (!reader) throw new Error('The host returned no response body.');

    const decoder = new TextDecoder();
    let buffered = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffered += decoder.decode(value, { stream: true });
      const lines = buffered.split('\n');
      buffered = lines.pop() ?? '';
      for (const line of lines) {
        if (!line.trim()) continue;
        const type = line[0];
        const payload = line.slice(2);
        try {
          if (type === '0') onEvent({ type: 'text', text: JSON.parse(payload) as string });
          else if (type === '9') {
            const call = JSON.parse(payload) as { toolName: string; args: Record<string, unknown> };
            onEvent({ type: 'tool-call', name: call.toolName, args: call.args });
          } else if (type === 'a') {
            const result = JSON.parse(payload) as { result: unknown };
            onEvent({ type: 'tool-result', result: typeof result.result === 'string' ? result.result : JSON.stringify(result.result) });
          } else if (type === 'e') onEvent({ type: 'error', message: JSON.parse(payload) as string });
          else if (type === 'd') onEvent({ type: 'done' });
        } catch {
          // Skip a line the protocol did not produce a full JSON payload for.
        }
      }
    }
  }
}
