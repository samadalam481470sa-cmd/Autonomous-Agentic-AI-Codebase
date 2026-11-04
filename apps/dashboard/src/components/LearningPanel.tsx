import { useCallback, useEffect, useState } from 'react';
import { ApiError, api } from '../api';
import type { LearningStatus } from '../types';
import { RefreshIcon, SparkIcon } from '../icons';

function number(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function metric(metrics: Record<string, unknown> | undefined, key: string): string {
  const value = metrics?.[key];
  return typeof value === 'number' ? value.toFixed(3) : '—';
}

export default function LearningPanel({
  project,
  notify,
  onLocked,
}: {
  project: string;
  notify: (message: string) => void;
  onLocked: () => void;
}) {
  const [status, setStatus] = useState<LearningStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fail = useCallback(
    (problem: unknown) => {
      if (problem instanceof ApiError && (problem.status === 401 || problem.status === 403)) {
        onLocked();
        return;
      }
      setError(problem instanceof Error ? problem.message : 'Learning request failed');
    },
    [onLocked],
  );

  const load = useCallback(async () => {
    try {
      setStatus(await api.learningStatus(project));
      setError(null);
    } catch (problem) {
      fail(problem);
    }
  }, [project, fail]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 8000);
    return () => window.clearInterval(timer);
  }, [load]);

  async function run(label: string, action: () => Promise<unknown>) {
    setBusy(label);
    setError(null);
    try {
      await action();
      notify(`${label} complete`);
      await load();
    } catch (problem) {
      fail(problem);
    } finally {
      setBusy(null);
    }
  }

  const runtime = status?.runtime;
  const info = status?.project;
  const active = info?.models.active ?? info?.model;
  const metrics = active?.metrics;
  const latest = info?.models.latest;

  return (
    <div className="page learning-page">
      <div className="page-head">
        <div>
          <h1>
            <SparkIcon size={18} /> Continuous learning
          </h1>
          <p className="muted">
            Local feedback becomes a versioned retrieval reranker. Candidates must beat the
            active model on a held-out split before promotion.
          </p>
        </div>
        <div className="device-actions">
          <button
            className="ghost"
            onClick={() => (runtime?.paused ? void run('Resume learning', api.learningStart) : void run('Pause learning', api.learningPause))}
            disabled={busy !== null}
          >
            {runtime?.paused ? 'Resume' : 'Pause'}
          </button>
          <button
            className="ghost"
            onClick={() => void run('Learning cycle', api.learningTick)}
            disabled={busy !== null}
          >
            <SparkIcon size={14} /> Learn now
          </button>
          <button
            className="ghost"
            onClick={() => void run('Training', () => api.learningTrain(project, true))}
            disabled={busy !== null}
          >
            Train current project
          </button>
          <button className="ghost" onClick={() => void load()} disabled={busy !== null}>
            <RefreshIcon size={14} /> Refresh
          </button>
        </div>
      </div>

      {error && <p className="device-error">{error}</p>}
      {!status && <p className="muted">Reading learner state…</p>}

      {status && (
        <>
          <div className="device-grid">
            <section className="device-card">
              <header>
                <SparkIcon size={14} />
                <span>Loop</span>
                <span className={`pill ${runtime?.thread_running ? 'ok' : 'unknown'}`}>
                  {runtime?.paused ? 'paused' : runtime?.thread_running ? 'running' : 'idle'}
                </span>
              </header>
              <dl className="device-list">
                <div>
                  <dt>Enabled</dt>
                  <dd>{runtime?.enabled ? 'yes' : 'no'}</dd>
                </div>
                <div>
                  <dt>Interval</dt>
                  <dd>{Math.round((runtime?.interval_seconds ?? 0) / 60)} min</dd>
                </div>
                <div>
                  <dt>Capture</dt>
                  <dd>{runtime?.capture ? 'redacted locally' : 'off'}</dd>
                </div>
                <div>
                  <dt>Projects</dt>
                  <dd>{status.projects.join(', ') || 'none'}</dd>
                </div>
              </dl>
              <p className="muted small">
                The loop indexes changed files and trains from new feedback. It yields to thermal
                and battery limits; it never edits files or executes commands.
              </p>
            </section>

            <section className="device-card">
              <header>
                <SparkIcon size={14} />
                <span>GPU & power</span>
                <span className={`pill ${status.gpu.detected ? 'ok' : 'unknown'}`}>
                  {status.gpu.detected ? status.gpu.vendor ?? 'gpu' : 'cpu only'}
                </span>
              </header>
              <dl className="device-list">
                <div>
                  <dt>GPU devices</dt>
                  <dd>{status.gpu.device_count || 'none detected'}</dd>
                </div>
                <div>
                  <dt>GPU temp</dt>
                  <dd>{status.gpu.max_temperature_c ?? 'unknown'} °C</dd>
                </div>
                <div>
                  <dt>GPU load</dt>
                  <dd>{status.gpu.max_utilization_percent ?? 'unknown'} %</dd>
                </div>
                <div>
                  <dt>Power</dt>
                  <dd>
                    {status.power.on_ac === null
                      ? 'unknown'
                      : status.power.on_ac
                        ? 'AC'
                        : `battery ${status.power.battery_percent ?? '?'}%`}
                  </dd>
                </div>
              </dl>
              <p className="muted small">
                Learning stays CPU-light so a 24/7 local model keeps the GPU. Optional AC-only and
                temperature gates are enforced before every cycle.
              </p>
            </section>

            <section className="device-card">
              <header>
                <SparkIcon size={14} />
                <span>Feedback</span>
                <span className="pill ok">{info?.capture ? 'capturing' : 'capture off'}</span>
              </header>
              <dl className="device-list">
                <div>
                  <dt>Interactions</dt>
                  <dd>{number(info?.interactions)}</dd>
                </div>
                <div>
                  <dt>Rated</dt>
                  <dd>
                    👍 {number(info?.positive)} · 👎 {number(info?.negative)}
                  </dd>
                </div>
                <div>
                  <dt>Path votes</dt>
                  <dd>
                    👍 {number(info?.feedback.positive)} · 👎 {number(info?.feedback.negative)}
                  </dd>
                </div>
                <div>
                  <dt>Active model</dt>
                  <dd>{active ? active.id.slice(0, 12) : 'not promoted yet'}</dd>
                </div>
              </dl>
              {latest && !latest.active && (
                <p className="muted small">
                  Latest candidate was not promoted: {latest.notes || 'no improvement'}.
                </p>
              )}
            </section>

            <section className="device-card">
              <header>
                <SparkIcon size={14} />
                <span>Model quality</span>
                <span className="pill ok">{active ? 'active' : 'baseline'}</span>
              </header>
              <dl className="device-list">
                <div>
                  <dt>Baseline NDCG@5</dt>
                  <dd>{metric(metrics, 'baseline_ndcg5')}</dd>
                </div>
                <div>
                  <dt>Candidate NDCG@5</dt>
                  <dd>{metric(metrics, 'candidate_ndcg5')}</dd>
                </div>
                <div>
                  <dt>Gain</dt>
                  <dd>{metric(metrics, 'gain')}</dd>
                </div>
                <div>
                  <dt>Holdout</dt>
                  <dd>{number(metrics?.holdout)} examples</dd>
                </div>
              </dl>
              <button
                className="ghost"
                onClick={() => void run('Rollback', () => api.learningRollback(project))}
                disabled={busy !== null || !active}
              >
                Roll back active model
              </button>
            </section>
          </div>

          <section className="learning-recent">
            <div className="page-head">
              <div>
                <h2>Recent interactions</h2>
                <p className="muted">
                  Rate answers to teach the reranker. Prompts and responses are redacted before
                  storage and never leave this machine.
                </p>
              </div>
            </div>
            {info?.interactions_recent.length === 0 && (
              <p className="muted small">No interactions captured yet. Ask the assistant or search code.</p>
            )}
            {info?.interactions_recent.map((interaction) => (
              <article className="learning-interaction" key={interaction.id}>
                <div className="learning-meta">
                  <span className="pill ok">{interaction.kind}</span>
                  <span className="muted small">
                    {new Date(interaction.created_at * 1000).toLocaleString()}
                    {interaction.redactions > 0 ? ` · ${interaction.redactions} redactions` : ''}
                  </span>
                </div>
                <p className="learning-prompt">{interaction.prompt || '(no prompt)'}</p>
                <p className="muted small learning-response">
                  {interaction.response || '(no response stored)'}
                </p>
                <div className="learning-votes">
                  <button
                    className={`vote ${interaction.rating === 'up' ? 'active' : ''}`}
                    onClick={() =>
                      void run('Accepted answer', () =>
                        api.rateInteraction(project, interaction.id, 'up'),
                      )
                    }
                    disabled={busy !== null}
                    title="Accept for learning"
                  >
                    👍
                  </button>
                  <button
                    className={`vote ${interaction.rating === 'down' ? 'active' : ''}`}
                    onClick={() =>
                      void run('Rejected answer', () =>
                        api.rateInteraction(project, interaction.id, 'down'),
                      )
                    }
                    disabled={busy !== null}
                    title="Reject for learning"
                  >
                    👎
                  </button>
                  {interaction.rating && (
                    <span className="muted small">stored as {interaction.rating}</span>
                  )}
                </div>
              </article>
            ))}
          </section>
        </>
      )}
    </div>
  );
}
