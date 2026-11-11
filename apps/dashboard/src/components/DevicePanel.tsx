import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, api } from '../api';
import type { DeviceStatus } from '../types';
import { BoltIcon, DeviceIcon, RefreshIcon, ThermometerIcon } from '../icons';

function formatDuration(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m`;
  return `${seconds}s`;
}

function value(text: number | null | undefined, suffix = ''): string {
  return text === null || text === undefined ? '—' : `${text}${suffix}`;
}

export default function DevicePanel({
  notify,
  onLocked,
}: {
  notify: (message: string) => void;
  onLocked: () => void;
}) {
  const [status, setStatus] = useState<DeviceStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fail = useCallback(
    (problem: unknown) => {
      if (problem instanceof ApiError && (problem.status === 401 || problem.status === 403)) {
        onLocked();
        return;
      }
      setError(problem instanceof Error ? problem.message : 'Device request failed');
    },
    [onLocked],
  );

  const load = useCallback(async () => {
    try {
      const next = await api.device();
      setStatus(next);
      setError(null);
    } catch (problem) {
      fail(problem);
    }
  }, [fail]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, [load]);

  async function toggleKeepAwake() {
    if (!status) return;
    setBusy(true);
    try {
      const next = await api.setKeepAwake(!status.keep_awake.active);
      setStatus(next);
      notify(
        next.keep_awake.active
          ? `Keep-awake on · ${next.keep_awake.backend ?? 'system'}`
          : 'Keep-awake released',
      );
    } catch (problem) {
      fail(problem);
    } finally {
      setBusy(false);
    }
  }

  async function copyEnvironment() {
    if (!status) return;
    if (!navigator.clipboard) {
      notify('Clipboard is not available in this browser');
      return;
    }
    const snippet = Object.entries(status.recommendation.env)
      .map(([key, entry]) => `export ${key}=${entry}`)
      .join('\n');
    try {
      await navigator.clipboard.writeText(snippet);
      notify('Model environment copied');
    } catch {
      notify('Clipboard write was blocked');
    }
  }

  const thermal = status?.thermal;
  const heatPercent =
    thermal && thermal.max_c !== null
      ? Math.min(100, Math.round((thermal.max_c / thermal.thresholds.critical) * 100))
      : 0;

  const spark = useMemo(() => {
    const history = status?.thermal.history ?? [];
    if (history.length < 2) return '';
    const values = history.map((point) => point.c);
    const low = Math.min(...values);
    const high = Math.max(...values);
    const span = Math.max(1, high - low);
    return values
      .map(
        (entry, index) =>
          `${(index / (values.length - 1)) * 100},${40 - ((entry - low) / span) * 34}`,
      )
      .join(' ');
  }, [status?.thermal.history]);

  if (!status) {
    return (
      <div className="page device-page">
        <p className="muted">{error ?? 'Reading device sensors…'}</p>
      </div>
    );
  }

  const stateClass = thermal?.state ?? 'unknown';

  return (
    <div className="page device-page">
      <div className="page-head">
        <div>
          <h1>
            <DeviceIcon size={18} /> Device runtime
          </h1>
          <p className="muted">
            Local hardware, thermal limits and sleep control. Nothing leaves this machine.
          </p>
        </div>
        <div className="device-actions">
          <button className="ghost" onClick={() => void load()} title="Refresh device report">
            <RefreshIcon size={14} /> Refresh
          </button>
          <button
            className={`toggle ${status.keep_awake.active ? 'on' : ''}`}
            onClick={() => void toggleKeepAwake()}
            disabled={busy}
            aria-pressed={status.keep_awake.active}
          >
            <BoltIcon size={14} />
            {status.keep_awake.active ? 'Keep awake on' : 'Keep awake off'}
          </button>
        </div>
      </div>

      {error && <p className="device-error">{error}</p>}

      <div className="device-grid">
        <section className={`device-card thermal-card ${stateClass}`}>
          <header>
            <ThermometerIcon size={15} />
            <span>Thermal governor</span>
            <span className={`pill ${stateClass}`}>{thermal?.state}</span>
          </header>
          <div className="thermal-readout">
            <strong>
              {thermal?.max_c ?? '—'}
              <small>°C</small>
            </strong>
            <div>
              <p className="muted small">
                EWMA {value(thermal?.ewma_c, '°C')} · slope {value(thermal?.slope_c_per_min, '°C/min')}
              </p>
              <p className="muted small">
                Predicted {value(thermal?.predicted_c, '°C')} · duty{' '}
                {Math.round((thermal?.duty_cycle ?? 0) * 100)}%
              </p>
            </div>
          </div>
          <div className="meter" aria-hidden="true">
            <div className={`meter-fill ${stateClass}`} style={{ width: `${heatPercent}%` }} />
          </div>
          <p className="small">
            {thermal?.admission.allowed
              ? 'Heavy work allowed'
              : `Paused: ${thermal?.admission.reason}`}
          </p>
          <p className="muted small">{thermal?.note}</p>
          {spark && (
            <svg
              className="sparkline"
              viewBox="0 0 100 40"
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <polyline points={spark} />
            </svg>
          )}
          <div className="sensor-row">
            {thermal && thermal.sensors.length > 0 ? (
              thermal.sensors.map((sensor) => (
                <span className="sensor" key={sensor.label}>
                  {sensor.label} · {sensor.celsius}°C
                </span>
              ))
            ) : (
              <span className="muted small">No sensors exposed; monitor-only mode.</span>
            )}
          </div>
          <p className="muted small">
            Pause at {thermal?.thresholds.hot}°C · critical {thermal?.thresholds.critical}°C ·
            resume {thermal?.thresholds.resume}°C
          </p>
        </section>

        <section className="device-card">
          <header>
            <DeviceIcon size={15} />
            <span>Compute</span>
          </header>
          <dl className="device-list">
            <div>
              <dt>CPU</dt>
              <dd>{status.cpu.model || 'Unknown'}</dd>
            </div>
            <div>
              <dt>Cores</dt>
              <dd>
                {value(status.cpu.logical_cores)} logical
                {status.cpu.physical_cores ? ` · ${status.cpu.physical_cores} physical` : ''}
              </dd>
            </div>
            <div>
              <dt>Memory</dt>
              <dd>
                {value(status.memory.total_mb, ' MB')}
                {status.memory.used_percent !== null ? ` · ${status.memory.used_percent}% used` : ''}
              </dd>
            </div>
            <div>
              <dt>Disk</dt>
              <dd>
                {status.disk
                  ? `${status.disk.free_gb} GB free of ${status.disk.total_gb} GB`
                  : 'Unknown'}
              </dd>
            </div>
            <div>
              <dt>Battery</dt>
              <dd>
                {status.battery
                  ? `${status.battery.percent ?? '—'}% · ${
                      status.battery.plugged ? 'plugged in' : status.battery.status
                    }`
                  : 'No battery detected'}
              </dd>
            </div>
          </dl>
          {status.gpus.length > 0 ? (
            status.gpus.map((gpu) => (
              <div className="gpu" key={gpu.name}>
                <strong>{gpu.name}</strong>
                <p className="muted small">
                  {gpu.vendor} ·{' '}
                  {gpu.vram_mb ? `${gpu.vram_mb} MB VRAM` : 'unified or unknown memory'}
                  {gpu.temp_c !== null ? ` · ${gpu.temp_c}°C` : ''}
                </p>
              </div>
            ))
          ) : (
            <p className="muted small">
              No discrete GPU detected. CPU inference works with a small quantized model.
            </p>
          )}
        </section>

        <section className="device-card">
          <header>
            <BoltIcon size={15} />
            <span>Local inference</span>
          </header>
          <dl className="device-list">
            <div>
              <dt>Recommended</dt>
              <dd>{status.recommendation.name}</dd>
            </div>
            <div>
              <dt>Context</dt>
              <dd>
                {status.recommendation.context_tokens} tokens · GPU layers{' '}
                {status.recommendation.gpu_layers}
              </dd>
            </div>
          </dl>
          <p className="muted small">{status.recommendation.reason}</p>
          <pre className="device-code">{status.recommendation.pull_command}</pre>
          <button className="ghost" onClick={() => void copyEnvironment()}>
            Copy model environment
          </button>
          <div className="backend-list">
            {status.backends.map((backend) => (
              <div className="backend" key={`${backend.name}:${backend.url}`}>
                <span className={`status-dot ${backend.status === 'ready' ? 'ok' : 'idle'}`} />
                <span>{backend.name}</span>
                <span className="muted small">{backend.url}</span>
                <span className={`pill ${backend.status === 'ready' ? 'ok' : ''}`}>
                  {backend.status}
                </span>
                {backend.models.length > 0 && (
                  <span className="muted small">{backend.models.join(', ')}</span>
                )}
              </div>
            ))}
          </div>
        </section>

        <section className="device-card">
          <header>
            <BoltIcon size={15} />
            <span>Long session</span>
            <span className={`pill ${status.keep_awake.active ? 'ok' : ''}`}>
              {status.keep_awake.active ? 'held awake' : 'normal sleep'}
            </span>
          </header>
          <dl className="device-list">
            <div>
              <dt>Uptime</dt>
              <dd>{formatDuration(status.session.uptime_seconds)}</dd>
            </div>
            <div>
              <dt>Kept awake</dt>
              <dd>
                {formatDuration(status.session.keep_awake_seconds)} of{' '}
                {status.session.max_hours}h budget
              </dd>
            </div>
            <div>
              <dt>Backend</dt>
              <dd>
                {status.keep_awake.backend ??
                  (status.keep_awake.supported ? 'available' : 'unsupported')}
              </dd>
            </div>
            <div>
              <dt>Expires</dt>
              <dd>
                {status.keep_awake.expires_at
                  ? new Date(status.keep_awake.expires_at * 1000).toLocaleTimeString()
                  : '—'}
              </dd>
            </div>
          </dl>
          <p className="muted small">
            {status.keep_awake.note ||
              'Keep-awake is released automatically above the critical temperature.'}
          </p>
          <p className="muted small">
            Downloadable build: run <code>python scripts/package_local.py</code> to produce a zip
            with Linux, macOS and Windows launchers.
          </p>
        </section>
      </div>

      <p className="muted small device-footnote">{status.privacy}</p>
    </div>
  );
}
