import { useCallback, useEffect, useState } from 'react';
import { ApiError, api } from '../api';
import type { SecurityPosture } from '../types';
import { RefreshIcon, ShieldIcon } from '../icons';

interface Props {
  notify: (message: string) => void;
  onLocked: () => void;
}

export default function SecurityPanel({ notify, onLocked }: Props) {
  const [posture, setPosture] = useState<SecurityPosture | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const data = await api.security();
      setPosture(data);
      setError(null);
    } catch (caught) {
      if (caught instanceof ApiError && (caught.status === 401 || caught.status === 403)) {
        onLocked();
        return;
      }
      setError(caught instanceof Error ? caught.message : 'Could not load security posture');
    } finally {
      setBusy(false);
    }
  }, [onLocked]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>
            <ShieldIcon size={18} /> Security posture
          </h1>
          <p className="muted">
            Authentication, lockouts, limits and the local audit trail. Values are read from the
            running service; no secrets are exposed.
          </p>
        </div>
        <button
          className="ghost"
          onClick={() => {
            void load();
            notify('Security posture refreshed');
          }}
          disabled={busy}
        >
          <RefreshIcon size={14} /> Refresh
        </button>
      </div>

      {error && <p className="error">{error}</p>}
      {!posture && !error && <p className="muted">Loading…</p>}

      {posture && (
        <>
          <div className="posture-grid">
            <article className="posture">
              <h2>Administrator token</h2>
              <p className="posture-value">
                {posture.token_configured ? 'Configured' : 'Missing'}
                <span className="pill">{posture.token_strength}</span>
              </p>
              <p className="muted mono">
                fingerprint {posture.token_fingerprint ?? '—'}
              </p>
            </article>
            <article className="posture">
              <h2>Two-factor</h2>
              <p className="posture-value">
                {posture.mfa_enabled ? 'Enabled' : 'Not enabled'}
                <span className={`pill ${posture.mfa_enabled ? 'ok' : ''}`}>
                  {posture.mfa_enabled ? 'TOTP' : 'optional'}
                </span>
              </p>
              <p className="muted">{posture.mfa_algorithm}</p>
            </article>
            <article className="posture">
              <h2>Brute-force defence</h2>
              <p className="posture-value">
                {posture.max_auth_failures} failures / {posture.failure_window_seconds}s
              </p>
              <p className="muted">
                Lockout {posture.lockout_base_seconds}–{posture.lockout_cap_seconds}s · locked
                addresses now: {posture.locked_addresses}
              </p>
            </article>
            <article className="posture">
              <h2>Request limits</h2>
              <p className="posture-value">{posture.general_rate_limit_per_minute} req/min</p>
              <p className="muted">
                Body cap {(posture.max_body_bytes / (1024 * 1024)).toFixed(1)} MiB · client{' '}
                {posture.client ?? 'unknown'}
              </p>
            </article>
          </div>

          <h2 className="section-title">Recent audit events</h2>
          <div className="audit">
            {posture.recent_audit.length === 0 ? (
              <p className="muted">No audit events recorded yet.</p>
            ) : (
              posture.recent_audit.map((entry) => (
                <div className="audit-row" key={`${entry.request_id}:${entry.created_at}:${entry.event}`}>
                  <span className="mono muted">
                    {new Date(entry.created_at * 1000).toLocaleString()}
                  </span>
                  <span className={`badge ${entry.event.startsWith('auth') ? 'blocked' : ''}`}>
                    {entry.event}
                  </span>
                  <span className="audit-detail">{entry.detail || '—'}</span>
                </div>
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}
