import { useEffect, useRef, useState } from 'react';
import { ApiError, api, streamChat } from '../api';
import type { AskResponse, ChatMessage, Citation } from '../types';
import { BotIcon, SendIcon, SparkIcon } from '../icons';
import AgentsPanel from './AgentsPanel';

type Tab = 'chat' | 'ask' | 'agents';

interface Props {
  project: string;
  tab: Tab;
  onTab: (tab: Tab) => void;
  onOpenFile: (path: string, line?: number) => void;
  onLocked: () => void;
  notify: (message: string) => void;
}

export default function AssistantPanel({ project, tab, onTab, onOpenFile, onLocked, notify }: Props) {
  return (
    <aside className="assistant" aria-label="AI assistant">
      <div className="assistant-head">
        <span className="assistant-title">
          <BotIcon size={15} /> Assistant
        </span>
        <div className="assistant-tabs" role="tablist" aria-label="Assistant modes">
          {(['chat', 'ask', 'agents'] as Tab[]).map((item) => (
            <button
              key={item}
              role="tab"
              aria-selected={tab === item}
              className={tab === item ? 'active' : ''}
              onClick={() => onTab(item)}
            >
              {item === 'chat' ? 'Chat' : item === 'ask' ? 'Ask code' : 'Agents'}
            </button>
          ))}
        </div>
      </div>
      <div className="assistant-body">
        {tab === 'chat' && <ChatPane project={project} onLocked={onLocked} notify={notify} />}
        {tab === 'ask' && (
          <AskPane project={project} onLocked={onLocked} onOpenFile={onOpenFile} notify={notify} />
        )}
        {tab === 'agents' && <AgentsPanel project={project} onLocked={onLocked} notify={notify} />}
      </div>
    </aside>
  );
}

function ChatPane({
  project,
  onLocked,
  notify,
}: {
  project: string;
  onLocked: () => void;
  notify: (message: string) => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setMessages([]);
    setError(null);
    (async () => {
      try {
        const data = await api.history(project);
        if (!cancelled) setMessages(data.messages.slice(-30));
      } catch (caught) {
        if (caught instanceof ApiError && (caught.status === 401 || caught.status === 403)) {
          onLocked();
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [project, onLocked]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput('');
    setError(null);
    setBusy(true);
    setMessages((previous) => [
      ...previous,
      { role: 'user', content: text },
      { role: 'assistant', content: '' },
    ]);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamChat(
        project,
        text,
        (delta) =>
          setMessages((previous) =>
            previous.map((message, index) =>
              index === previous.length - 1 ? { ...message, content: message.content + delta } : message,
            ),
          ),
        controller.signal,
      );
      notify('Assistant response complete');
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === 'AbortError') {
        setMessages((previous) =>
          previous.map((message, index) =>
            index === previous.length - 1 && !message.content
              ? { ...message, content: '[stopped]' }
              : message,
          ),
        );
      } else if (caught instanceof ApiError && (caught.status === 401 || caught.status === 403)) {
        onLocked();
      } else {
        setError(caught instanceof Error ? caught.message : 'Chat failed');
        setMessages((previous) =>
          previous.map((message, index) =>
            index === previous.length - 1 && !message.content
              ? { ...message, content: '[no response]' }
              : message,
          ),
        );
      }
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  }

  return (
    <div className="chat">
      <div className="chat-log" ref={logRef}>
        {messages.length === 0 && (
          <div className="chat-empty">
            <SparkIcon size={18} />
            <p>Ask for a feature, a refactor or an explanation. Retrieval grounds answers in this project.</p>
            <p className="muted small">{project} · results never leave your configured model endpoint.</p>
          </div>
        )}
        {messages.map((message, index) => (
          <article key={`${message.role}-${index}`} className={`bubble ${message.role}`}>
            {message.content || (busy && index === messages.length - 1 ? '…' : '')}
          </article>
        ))}
      </div>
      {error && <p className="error">{error}</p>}
      <div className="composer">
        <textarea
          value={input}
          rows={2}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Ask the assistant…"
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              void send();
            }
          }}
        />
        <div className="composer-row">
          <button
            className="ghost"
            onClick={() => abortRef.current?.abort()}
            disabled={!busy}
            title="Stop generating"
          >
            Stop
          </button>
          <button className="primary" onClick={() => void send()} disabled={busy || !input.trim()}>
            <SendIcon size={14} /> Send
          </button>
        </div>
      </div>
    </div>
  );
}

function AskPane({
  project,
  onLocked,
  onOpenFile,
  notify,
}: {
  project: string;
  onLocked: () => void;
  onOpenFile: (path: string, line?: number) => void;
  notify: (message: string) => void;
}) {
  const [query, setQuery] = useState('');
  const [result, setResult] = useState<AskResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [votes, setVotes] = useState<Record<string, 'up' | 'down'>>({});
  const [answerVote, setAnswerVote] = useState<'up' | 'down' | null>(null);

  async function submit() {
    const text = query.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    try {
      const data = await api.ask(project, text);
      setResult(data);
      setAnswerVote(null);
      notify(`Answer grounded in ${data.retrieval.results} excerpts`);
    } catch (caught) {
      if (caught instanceof ApiError && (caught.status === 401 || caught.status === 403)) {
        onLocked();
        return;
      }
      setError(caught instanceof Error ? caught.message : 'Codebase question failed');
    } finally {
      setBusy(false);
    }
  }

  async function rateAnswer(rating: 'up' | 'down') {
    if (!result?.interaction_id) return;
    try {
      await api.rateInteraction(project, result.interaction_id, rating);
      setAnswerVote(rating);
      notify(`Answer feedback stored · ${rating === 'up' ? 'accepted' : 'rejected'}`);
    } catch (caught) {
      if (caught instanceof ApiError && (caught.status === 401 || caught.status === 403)) {
        onLocked();
        return;
      }
      setError(caught instanceof Error ? caught.message : 'Answer feedback failed');
    }
  }

  async function vote(citation: Citation, rating: 'up' | 'down') {
    const key = `${citation.path}:${citation.line}`;
    try {
      const data = await api.feedback(project, query, citation.path, citation.line, rating);
      setVotes((previous) => ({ ...previous, [key]: rating }));
      notify(`Feedback learned: ${data.ranking.positive} up / ${data.ranking.negative} down`);
    } catch (caught) {
      if (caught instanceof ApiError && (caught.status === 401 || caught.status === 403)) {
        onLocked();
        return;
      }
      setError(caught instanceof Error ? caught.message : 'Feedback failed');
    }
  }

  return (
    <div className="ask">
      <div className="ask-form">
        <textarea
          value={query}
          rows={2}
          maxLength={500}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Where is billing calculated, and what tests cover it?"
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              void submit();
            }
          }}
        />
        <button className="primary" onClick={() => void submit()} disabled={busy || !query.trim()}>
          <SparkIcon size={14} /> Ask
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {!result && !error && (
        <p className="muted small">
          Answers cite indexed files and are screened for leaked secrets before the model sees them.
        </p>
      )}
      {result && (
        <div className="answer">
          {result.safety && (result.safety.secrets > 0 || result.safety.injection > 0) && (
            <p className={`safety ${result.safety.risk}`}>
              Safety: {result.safety.secrets} secret(s) redacted · {result.safety.injection} injection
              flag(s)
            </p>
          )}
          <article className="bubble assistant">{result.answer}</article>
          {result.interaction_id && (
            <div className="answer-learning">
              <span className="muted small">Train the local reranker:</span>
              <button
                className={`vote ${answerVote === 'up' ? 'active' : ''}`}
                onClick={() => void rateAnswer('up')}
                title="Accept this answer for learning"
              >
                👍
              </button>
              <button
                className={`vote ${answerVote === 'down' ? 'active' : ''}`}
                onClick={() => void rateAnswer('down')}
                title="Reject this answer for learning"
              >
                👎
              </button>
            </div>
          )}
          <h3 className="section-title">Citations</h3>
          {result.citations.length === 0 && <p className="muted small">No citations returned.</p>}
          {result.citations.map((citation) => {
            const key = `${citation.path}:${citation.line}`;
            return (
              <div className="citation" key={key}>
                <button className="link" onClick={() => onOpenFile(citation.path, citation.line)}>
                  {citation.path}:{citation.line}
                </button>
                <span className="run-meta">
                  {citation.redactions ? `redacted ${citation.redactions} · ` : ''}
                  {citation.injection_risk ?? 'none'}
                </span>
                <button
                  className={`vote ${votes[key] === 'up' ? 'active' : ''}`}
                  onClick={() => void vote(citation, 'up')}
                  title="Relevant"
                  aria-label={`Mark ${key} relevant`}
                >
                  👍
                </button>
                <button
                  className={`vote ${votes[key] === 'down' ? 'active' : ''}`}
                  onClick={() => void vote(citation, 'down')}
                  title="Not relevant"
                  aria-label={`Mark ${key} not relevant`}
                >
                  👎
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
