import type {
  AgentRun,
  AskResponse,
  FileRead,
  HistoryResponse,
  IndexReport,
  IndexStats,
  SearchResult,
  SecurityPosture,
} from './types';

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

let credentials = { token: '', totp: '' };

export function setCredentials(next: { token: string; totp: string }): void {
  credentials = { token: next.token.trim(), totp: next.totp.trim() };
}

export function hasCredentials(): boolean {
  return credentials.token.length > 0;
}

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { ...(extra ?? {}) };
  if (credentials.token) headers.Authorization = `Bearer ${credentials.token}`;
  if (credentials.totp) headers['X-Agent-TOTP'] = credentials.totp;
  return headers;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: authHeaders({
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...((init.headers as Record<string, string> | undefined) ?? {}),
    }),
  });
  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text.slice(0, 300) };
    }
  }
  if (!response.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    throw new ApiError(
      response.status,
      typeof detail === 'string' ? detail : `Request failed with HTTP ${response.status}`,
    );
  }
  return data as T;
}

export const api = {
  security: () => request<SecurityPosture>('/api/security/status'),
  files: (project: string) =>
    request<{ files: string[] }>(`/api/studio/files/${encodeURIComponent(project)}`),
  readFile: (project: string, path: string) =>
    request<FileRead>('/api/studio/read', {
      method: 'POST',
      body: JSON.stringify({ project, path }),
    }),
  history: (project: string) =>
    request<HistoryResponse>(`/api/projects/${encodeURIComponent(project)}/history`),
  chat: (project: string, message: string) =>
    request<{ answer: string }>('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ project, message }),
    }),
  search: (project: string, query: string, limit = 12) =>
    request<{ results: SearchResult[] }>('/api/ai/search', {
      method: 'POST',
      body: JSON.stringify({ project, query, limit, mode: 'hybrid' }),
    }),
  ask: (project: string, question: string) =>
    request<AskResponse>('/api/ai/ask', {
      method: 'POST',
      body: JSON.stringify({ project, question }),
    }),
  index: (project: string) =>
    request<IndexReport>('/api/ai/index/refresh', {
      method: 'POST',
      body: JSON.stringify({ project, max_files: 5000 }),
    }),
  indexStats: (project: string) =>
    request<IndexStats>(`/api/ai/${encodeURIComponent(project)}/stats`),
  feedback: (project: string, query: string, path: string, line: number, rating: 'up' | 'down') =>
    request<{ ranking: { positive: number; negative: number; paths: number } }>(
      '/api/ai/feedback',
      {
        method: 'POST',
        body: JSON.stringify({ project, query, path, line, rating }),
      },
    ),
  roles: () =>
    request<{ roles: { name: string; instruction: string }[]; max_steps: number }>(
      '/api/agents/roles',
    ),
  runs: (project: string) =>
    request<{ runs: AgentRun[] }>(`/api/agents/runs?project=${encodeURIComponent(project)}`),
  run: (runId: string) => request<AgentRun>(`/api/agents/runs/${runId}`),
  createRun: (project: string, goal: string, mode: 'build' | 'plan') =>
    request<AgentRun>('/api/agents/runs', {
      method: 'POST',
      body: JSON.stringify({ project, goal, mode }),
    }),
  advanceRun: (runId: string) =>
    request<AgentRun>(`/api/agents/runs/${runId}/advance`, { method: 'POST' }),
  cancelRun: (runId: string) =>
    request<AgentRun>(`/api/agents/runs/${runId}/cancel`, { method: 'POST' }),
};

/**
 * Prefer the local SSE endpoint; fall back to the regular chat route when
 * streaming is disabled on the server. Both paths send the same credentials.
 */
export async function streamChat(
  project: string,
  message: string,
  onDelta: (text: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ project, message }),
    signal,
  });

  if (!response.ok || !response.body) {
    let detail = `HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === 'string') detail = payload.detail;
    } catch {
      // Keep the status-based message when the body is not JSON.
    }
    if (response.status === 409 || response.status === 503) {
      const fallback = await api.chat(project, message);
      onDelta(fallback.answer);
      return;
    }
    throw new ApiError(response.status, detail);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = '';
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      pending += decoder.decode(value, { stream: true }).replace(/\r/g, '');
      let boundary = pending.indexOf('\n\n');
      while (boundary >= 0) {
        const raw = pending.slice(0, boundary);
        pending = pending.slice(boundary + 2);
        const lines = raw.split('\n');
        const eventLine = lines.find((line) => line.startsWith('event:'));
        const data = lines
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trimStart())
          .join('\n');
        if (eventLine && data) {
          const kind = eventLine.slice(6).trim();
          const payload = JSON.parse(data) as { text?: unknown; message?: unknown };
          if (kind === 'delta' && typeof payload.text === 'string') onDelta(payload.text);
          if (kind === 'error') {
            throw new ApiError(
              502,
              typeof payload.message === 'string' ? payload.message : 'Stream failed',
            );
          }
        }
        boundary = pending.indexOf('\n\n');
      }
    }
  } finally {
    reader.releaseLock();
  }
}
