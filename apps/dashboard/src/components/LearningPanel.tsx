import { useCallback, useEffect, useState } from 'react';
import { ApiError, api } from '../api';
import type { GpuTrainingStatus, LearningStatus } from '../types';
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
  const [gpu, setGpu] = useState<GpuTrainingStatus | null>(null);
  const [consent, setConsent] = useState(false);
  const [gpuForm, setGpuForm] = useState({
    model_dir: '',
    model_id: '',
    model_license: '',
  });
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
      const [next, nextGpu] = await Promise.all([
        api.learningStatus(project),
        api.gpuTrainingStatus(project),
      ]);
      setStatus(next);
      setGpu(nextGpu);
      setGpuForm((current) =>
        current.model_dir || current.model_id || current.model_license
          ? current
          : {
              model_dir: nextGpu.config.model_dir,
              model_id: nextGpu.config.model_id,
              model_license: nextGpu.config.model_license,
            },
      );
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

            {gpu && (
              <section className="device-card gpu-training-card">
                <header>
                  <SparkIcon size={14} />
                  <span>GPU weight training</span>
                  <span className={`pill ${gpu.running ? 'ok' : gpu.active_adapter ? 'ok' : 'unknown'}`}>
                    {gpu.running ? 'training' : gpu.active_adapter ? 'adapter active' : 'not active'}
                  </span>
                </header>
                <dl className="device-list">
                  <div>
                    <dt>Accepted answers</dt>
                    <dd>
                      {gpu.approved_examples} / {gpu.required_examples}
                    </dd>
                  </div>
                  <div>
                    <dt>GPU</dt>
                    <dd>{gpu.gpu.detected ? gpu.gpu.vendor ?? 'detected' : 'not detected'}</dd>
                  </div>
                  <div>
                    <dt>Last run</dt>
                    <dd>{gpu.last_run?.state ?? 'never'}</dd>
                  </div>
                  <div>
                    <dt>Adapter</dt>
                    <dd>{gpu.active_adapter?.active.slice(0, 12) ?? 'none'}</dd>
                  </div>
                </dl>
                <div className="learning-form">
                  <label>
                    Local Hugging Face model directory
                    <input
                      value={gpuForm.model_dir}
                      onChange={(event) =>
                        setGpuForm({ ...gpuForm, model_dir: event.target.value })
                      }
                      placeholder="/models/Qwen2.5-Coder-7B-Instruct"
                    />
                  </label>
                  <label>
                    Reviewed model id
                    <input
                      value={gpuForm.model_id}
                      onChange={(event) =>
                        setGpuForm({ ...gpuForm, model_id: event.target.value })
                      }
                      placeholder="Qwen/Qwen2.5-Coder-7B-Instruct"
                    />
                  </label>
                  <label>
                    Reviewed license
                    <input
                      value={gpuForm.model_license}
                      onChange={(event) =>
                        setGpuForm({ ...gpuForm, model_license: event.target.value })
                      }
                      placeholder="Apache-2.0"
                    />
                  </label>
                </div>
                <label className="learning-consent">
                  <input
                    type="checkbox"
                    checked={consent}
                    onChange={(event) => setConsent(event.target.checked)}
                  />
                  I consent to local GPU training on these accepted answers.
                </label>
                <div className="device-actions">
                  <button
                    className="ghost"
                    onClick={() =>
                      void run('GPU training', () =>
                        api.startGpuTraining(project, {
                          consent,
                          ...gpuForm,
                        }),
                      )
                    }
                    disabled={!consent || busy !== null || gpu.running || !gpu.enabled}
                  >
                    Train weights
                  </button>
                  <button
                    className="ghost"
                    onClick={() =>
                      void run('Adapter rollback', () => api.rollbackGpuTraining(project))
                    }
                    disabled={busy !== null || gpu.running || !gpu.active_adapter}
                  >
                    Roll back adapter
                  </button>
                </div>
                {gpu.last_run?.result && (
                  <p className="muted small">
                    {gpu.last_run.result.promoted ? 'Promoted' : 'Not promoted'} · baseline{' '}
                    {gpu.last_run.result.baseline_loss?.toFixed(4) ?? '—'} · candidate{' '}
                    {gpu.last_run.result.candidate_loss?.toFixed(4) ?? '—'}
                  </p>
                )}
                {gpu.reasons.length > 0 && (
                  <p className="muted small">{gpu.reasons.join(' ')}</p>
                )}
                <p className="muted small">{gpu.note}</p>
              </section>
            )}
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
