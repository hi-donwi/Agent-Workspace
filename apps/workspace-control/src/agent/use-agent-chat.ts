import { useCallback, useRef, useState } from 'react';
import { AgentApi, AgentUnavailableError } from './agent-api';

export interface ChatTool { name: string; result?: string }
export interface ChatTurn { id: string; role: 'user' | 'assistant'; content: string; tools: ChatTool[] }

let counter = 0;
const nextId = () => `turn-${Date.now()}-${++counter}`;
const message = (error: unknown) => error instanceof Error ? error.message : 'The request could not be completed.';

export interface AgentChat {
  turns: ChatTurn[];
  streaming: boolean;
  error: string;
  send: (content: string, options: { provider: string; model: string; project?: string }) => void;
  stop: () => void;
  clear: () => void;
}

/** Chat turns against the agent host, reading its streaming line protocol. */
export function useAgentChat(api: AgentApi): AgentChat {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState('');
  const abort = useRef<AbortController | null>(null);

  const replaceLast = (change: (assistant: ChatTurn) => ChatTurn) => setTurns(previous => {
    const last = previous[previous.length - 1];
    if (last?.role !== 'assistant') return previous;
    return [...previous.slice(0, -1), change(last)];
  });

  const send = useCallback((content: string, options: { provider: string; model: string; project?: string }) => {
    const text = content.trim();
    if (!text || streaming) return;
    setError('');
    const userTurn: ChatTurn = { id: nextId(), role: 'user', content: text, tools: [] };
    const assistantTurn: ChatTurn = { id: nextId(), role: 'assistant', content: '', tools: [] };
    const history = [...turns, userTurn];
    setTurns([...history, assistantTurn]);
    setStreaming(true);

    const controller = new AbortController();
    abort.current = controller;
    let full = '';
    const tools: ChatTool[] = [];

    void api.chat(
      { messages: history.map(turn => ({ role: turn.role, content: turn.content })), provider: options.provider, model: options.model, ...(options.project ? { project: options.project } : {}) },
      event => {
        if (event.type === 'text') { full += event.text; replaceLast(last => ({ ...last, content: full })); }
        else if (event.type === 'tool-call') { tools.push({ name: event.name }); replaceLast(last => ({ ...last, tools: [...tools] })); }
        else if (event.type === 'tool-result') { const current = tools[tools.length - 1]; if (current) current.result = event.result; replaceLast(last => ({ ...last, tools: [...tools] })); }
        else if (event.type === 'error') setError(event.message);
      },
      controller.signal,
    ).catch(cause => {
      if ((cause as Error).name === 'AbortError') return;
      setError(cause instanceof AgentUnavailableError ? cause.message : message(cause));
      setTurns(previous => {
        const last = previous[previous.length - 1];
        return last?.role === 'assistant' && !last.content ? previous.slice(0, -1) : previous;
      });
    }).finally(() => { setStreaming(false); abort.current = null; });
  }, [api, turns, streaming]);

  const stop = useCallback(() => { abort.current?.abort(); setStreaming(false); }, []);
  const clear = useCallback(() => { setTurns([]); setError(''); }, []);

  return { turns, streaming, error, send, stop, clear };
}
