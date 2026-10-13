import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AgentApi, AgentUnavailableError, type AgentConfig, type AgentProject, type AgentProvider, type AgentWorkspace } from './agent-api';

export interface AgentConnection {
  available: boolean | null;
  loading: boolean;
  error: string;
  providers: AgentProvider[];
  provider: string;
  setProvider: (id: string) => void;
  model: string;
  setModel: (id: string) => void;
  projects: AgentProject[];
  project: string;
  setProject: (key: string) => void;
  config: AgentConfig | null;
  workspace: AgentWorkspace | null;
  refresh: () => void;
}

const message = (error: unknown) => error instanceof Error ? error.message : 'The request could not be completed.';

/** Connection to the agent host: is it there, and what can it run? */
export function useAgentConnection(api: AgentApi): AgentConnection {
  const [available, setAvailable] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [providers, setProviders] = useState<AgentProvider[]>([]);
  const [provider, setProviderState] = useState('');
  const [model, setModel] = useState('');
  const [projects, setProjects] = useState<AgentProject[]>([]);
  const [project, setProject] = useState('');
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [workspace, setWorkspace] = useState<AgentWorkspace | null>(null);
  const [revision, setRevision] = useState(0);
  const defaulted = useRef(false);

  const refresh = useCallback(() => setRevision(value => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    void (async () => {
      try {
        const catalog = await api.providers();
        if (controller.signal.aborted) return;
        if (!Array.isArray(catalog?.providers) || catalog.providers.length === 0) { setAvailable(false); return; }
        setProviders(catalog.providers);
        setAvailable(true);
        if (!defaulted.current) {
          defaulted.current = true;
          const first = catalog.providers.find(p => p.id === catalog.defaultProvider) ?? catalog.providers[0];
          setProviderState(first?.id ?? '');
          setModel(catalog.defaultModel || first?.models[0] || '');
        }
        const [projectList, hostConfig, workspaceInfo] = await Promise.all([
          api.projects().catch(() => ({ projects: [] as AgentProject[] })),
          api.config().catch(() => null),
          api.workspace().catch(() => null),
        ]);
        if (controller.signal.aborted) return;
        setProjects(projectList.projects);
        setConfig(hostConfig);
        setWorkspace(workspaceInfo);
      } catch (cause) {
        if (controller.signal.aborted) return;
        if (cause instanceof AgentUnavailableError) { setAvailable(false); return; }
        setError(message(cause));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    })();
    return () => controller.abort();
  }, [api, revision]);

  const setProvider = useCallback((id: string) => {
    setProviderState(id);
    const chosen = providers.find(p => p.id === id);
    setModel(chosen?.models[0] ?? '');
  }, [providers]);

  return useMemo(() => ({
    available, loading, error, providers, provider, setProvider, model, setModel,
    projects, project, setProject, config, workspace, refresh,
  }), [available, loading, error, providers, provider, setProvider, model, projects, project, config, workspace, refresh]);
}
