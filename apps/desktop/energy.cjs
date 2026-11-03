'use strict';
/**
 * Always-on preference for the local worker. Pure helpers plus a small JSON
 * preference file, so the behaviour is testable without Electron.
 *
 * The worker only runs while this computer is powered on. "Always on" means it
 * starts with the app, keeps using the local model (and GPU when llama.cpp is
 * configured for it) and is stopped by the Stop control or by turning the
 * machine off. No cloud service is contacted.
 */
const fs = require('node:fs');
const path = require('node:path');

const WORKER_ENV = Object.freeze({
  AGENT_WORKER_ENABLED: '1',
  AGENT_AUTONOMY: '1',
  AGENT_HOST_TOOLCHAIN: '1',
  AGENT_WORKER_POLICY: 'always'
});

function normalize(value) {
  return { enabled: value === true };
}

function workerEnv({ enabled = false, baseEnv = process.env } = {}) {
  const env = { ...baseEnv };
  if (enabled) {
    Object.assign(env, WORKER_ENV);
  } else {
    env.AGENT_WORKER_ENABLED = '0';
  }
  return env;
}

function loginItemOptions(platform) {
  return {
    openAtLogin: true,
    openAsHidden: platform === 'darwin',
    args: ['--always-on']
  };
}

function preferencePath(userData) {
  if (typeof userData !== 'string' || !userData) {
    throw new TypeError('A user data directory is required');
  }
  return path.join(userData, 'always-on.json');
}

function loadPreference(file) {
  try {
    const raw = JSON.parse(fs.readFileSync(file, 'utf8'));
    return normalize(raw.enabled);
  } catch (_) {
    return { enabled: false };
  }
}

function savePreference(file, enabled) {
  const value = normalize(enabled);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify({
    enabled: value.enabled,
    updatedAt: new Date().toISOString()
  }, null, 2), { mode: 0o600 });
  return value;
}

module.exports = {
  WORKER_ENV, normalize, workerEnv, loginItemOptions,
  preferencePath, loadPreference, savePreference
};
