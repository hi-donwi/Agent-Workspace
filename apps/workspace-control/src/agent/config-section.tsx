import { useEffect, useState } from 'react';
import { AgentApi } from './agent-api';
import type { AgentConnection } from './use-agent-connection';

interface KeyDraft { apiKey: string; baseUrl: string }

export function ConfigSection({ connection, api }: { connection: AgentConnection; api: AgentApi }) {
  const [provider, setProvider] = useState('');
  const [model, setModel] = useState('');
  const [keys, setKeys] = useState<Record<string, KeyDraft>>({});
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<{ kind: 'ok' | 'error'; message: string } | null>(null);

  useEffect(() => {
    const config = connection.config;
    if (!config) return;
    setProvider(config.defaultProvider);
    setModel(config.defaultModel);
    const drafts: Record<string, KeyDraft> = {};
    for (const item of connection.providers) drafts[item.id] = { apiKey: '', baseUrl: config.providers?.[item.id]?.baseUrl ?? '' };
    setKeys(drafts);
  }, [connection.config, connection.providers]);

  const models = connection.providers.find(item => item.id === provider)?.models ?? [];

  const save = () => {
    setSaving(true); setStatus(null);
    const providers: Record<string, { apiKey: string; baseUrl?: string }> = {};
    for (const [id, draft] of Object.entries(keys)) {
      const apiKey = draft.apiKey.trim();
      if (!apiKey || apiKey.includes('...')) continue;
      const baseUrl = draft.baseUrl.trim();
      providers[id] = baseUrl ? { apiKey, baseUrl } : { apiKey };
    }
    api.saveConfig({ defaultProvider: provider, defaultModel: model, providers })
      .then(() => { setStatus({ kind: 'ok', message: 'Saved. New keys are stored at ~/.agent-control/config.json.' }); connection.refresh(); })
      .catch(error => setStatus({ kind: 'error', message: error instanceof Error ? error.message : 'The configuration could not be saved.' }))
      .finally(() => setSaving(false));
  };

  return <div className="agent-section">
    <div className="form-grid">
      <label className="agent-field">
        Default provider
        <select className="field" value={provider} onChange={event => setProvider(event.target.value)}>
          {connection.providers.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
      <label className="agent-field">
        Default model
        <input className="field" list="agent-models" value={model} onChange={event => setModel(event.target.value)} />
        <datalist id="agent-models">{models.map(item => <option key={item} value={item} />)}</datalist>
      </label>
    </div>
    <div className="agent-keys">
      {connection.providers.map(item => <div key={item.id} className="agent-field">
        <span className="agent-scope-label">{item.name} key <span className="muted small">({item.locality})</span></span>
        <input className="field" type="password" autoComplete="off" placeholder="leave blank to keep the stored key" value={keys[item.id]?.apiKey ?? ''} onChange={event => setKeys(current => ({ ...current, [item.id]: { apiKey: event.target.value, baseUrl: current[item.id]?.baseUrl ?? '' } }))} />
        <input className="field" placeholder="base URL (optional)" value={keys[item.id]?.baseUrl ?? ''} onChange={event => setKeys(current => ({ ...current, [item.id]: { apiKey: current[item.id]?.apiKey ?? '', baseUrl: event.target.value } }))} />
      </div>)}
    </div>
    {status && <p className={`notice ${status.kind === 'ok' ? 'success' : 'error'}`} role={status.kind === 'error' ? 'alert' : undefined}>{status.message}</p>}
    <div className="row agent-card-actions">
      <button type="button" className="button primary" disabled={saving} onClick={save}>Save configuration</button>
    </div>
  </div>;
}
