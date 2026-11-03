import { useCallback, useEffect, useState } from 'react';
import { ApiError, api } from '../api';
import type { AgentRun } from '../types';
import { PlayIcon, PlusIcon, RefreshIcon } from '../icons';

interface Props {
  project: string;
  notify: (message: string) => void;
  onLocked: () => void;
}

export default function AgentsPanel({ project, notify, onLocked }: Props) {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [goal, setGoal] = useState('');
  const [mode, setMode] = useState<'build' | 'plan'>('build');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function fail(caught: unknown) {
    if (caught instanceof ApiError && (caught.status === 401 || caught.status === 403)) {
      onLocked();
      return;
    }
    setError(caught instanceof Error ? caught.message : 'Agent request failed');
  }

  const refresh = useCallback(async () => {
    try {
      const data = await api.runs(project);
      setRuns(data.runs);
      setSelectedId((current) => current ?? data.runs[0]?.id ?? null);
    } catch (caught) {
      fail(caught);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, onLocked]);

  useEffect(() => {
    setRuns([]);
    setSelectedId(null);
    void refresh();
  }, [refresh]);

  const selected = runs.find((run) => run.id === selectedId) ?? null;

  async function create() {
    const text = goal.trim();
    if (text.length < 8) {
      setError('Describe the goal in at least 8 characters.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const run = await api.createRun(project, text, mode);
      setRuns((previous) => [run, ...previous.filter((item) => item.id !== run.id)]);
      setSelectedId(run.id);
      setGoal('');
      notify(`Agent run created with ${run.steps.length} specialist steps`);
    } catch (caught) {
      fail(caught);
    } finally {
      setBusy(false);
    }
  }

  async function advance() {
    if (!selectedId) return;
    setBusy(true);
    setError(null);
    try {
      const run = await api.advanceRun(selectedId);
      setRuns((previous) => previous.map((item) => (item.id === run.id ? run : item)));
      notify(`Step complete: ${run.progress.completed}/${run.progress.total} · ${run.status}`);
    } catch (caught) {
      fail(caught);
      try {
        const fresh = await api.run(selectedId);
        setRuns((previous) => previous.map((item) => (item.id === fresh.id ? fresh : item)));
      } catch {
        // The original error is already shown.
      }
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!selectedId) return;
    setBusy(true);
    setError(null);
    try {
      const run = await api.cancelRun(selectedId);
      setRuns((previous) => previous.map((item) => (item.id === run.id ? run : item)));
      notify('Run cancelled');
    } catch (caught) {
      fail(caught);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="agents">
      <div className="run-form">
        <label className="field">
          <span>Goal</span>
          <textarea
            value={goal}
            rows={3}
            maxLength={4000}
            onChange={(event) => setGoal(event.target.value)}
            placeholder="Describe the feature, bug or review you want planned and implemented…"
          />
        </label>
        <div className="run-form-row">
          <select value={mode} onChange={(event) => setMode(event.target.value as 'build' | 'plan')}>
            <option value="build">Build · 5 specialists</option>
            <option value="plan">Plan · architect + reviewer</option>
          </select>
          <button className="primary" onClick={() => void create()} disabled={busy}>
            <PlusIcon size={14} /> Create run
          </button>
        </div>
        <p className="muted small">
          Runs are bounded, stored locally, and never write files or execute commands. Each step
          needs an explicit operator action.
        </p>
        {error && <p className="error">{error}</p>}
      </div>

      <div className="run-list-head">
        <span>Runs</span>
        <button className="ghost icon" onClick={() => void refresh()} title="Refresh runs">
          <RefreshIcon size={14} />
        </button>
      </div>
      <div className="run-list">
        {runs.length === 0 ? (
          <p className="muted small">No runs for {project} yet.</p>
        ) : (
          runs.map((run) => (
            <button
              key={run.id}
              className={`run-item ${selectedId === run.id ? 'active' : ''}`}
              onClick={() => setSelectedId(run.id)}
            >
              <span className={`badge ${run.status}`}>{run.status}</span>
              <span className="run-goal">{run.goal}</span>
              <span className="run-meta">
                {run.mode} · {run.progress.completed}/{run.progress.total}
              </span>
            </button>
          ))
        )}
      </div>

      {selected && (
        <div className="run-detail">
          <div className="run-detail-head">
            <div>
              <strong>{selected.goal}</strong>
              <div className="run-meta">
                <span className={`badge ${selected.status}`}>{selected.status}</span> {selected.mode}{' '}
                · {selected.progress.completed}/{selected.progress.total} steps
              </div>
            </div>
            <div className="run-actions">
              <button
                className="primary"
                onClick={() => void advance()}
                disabled={busy || selected.status === 'completed' || selected.status === 'cancelled'}
              >
                <PlayIcon size={14} /> Advance
              </button>
              <button
                className="ghost"
                onClick={() => void cancel()}
                disabled={busy || selected.status === 'completed' || selected.status === 'cancelled'}
              >
                Cancel
              </button>
            </div>
          </div>
          <div className="progress" aria-label="Run progress">
            <div
              style={{
                width: `${
                  selected.progress.total
                    ? (selected.progress.completed / selected.progress.total) * 100
                    : 0
                }%`,
              }}
            />
          </div>
          {selected.steps.map((step) => (
            <details className="step" key={step.id}>
              <summary>
                <span className={`badge ${step.status}`}>{step.status}</span>
                <strong>{step.role}</strong>
                <span className="run-meta">step {step.seq + 1}</span>
              </summary>
              <p className="step-instruction">{step.instruction}</p>
              {step.error && <p className="error">{step.error}</p>}
              {step.output ? (
                <pre className="step-output">{step.output}</pre>
              ) : (
                <p className="muted small">No output yet.</p>
              )}
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
