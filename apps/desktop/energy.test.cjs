'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const {
  WORKER_ENV, normalize, workerEnv, loginItemOptions,
  preferencePath, loadPreference, savePreference
} = require('./energy.cjs');

test('enabling the worker sets local-only autonomous execution flags', () => {
  const env = workerEnv({ enabled: true, baseEnv: { PATH: '/usr/bin', KEEP: 'yes' } });
  assert.equal(env.AGENT_WORKER_ENABLED, '1');
  assert.equal(env.AGENT_AUTONOMY, '1');
  assert.equal(env.AGENT_HOST_TOOLCHAIN, '1');
  assert.equal(env.AGENT_WORKER_POLICY, 'always');
  assert.equal(env.PATH, '/usr/bin');
  assert.equal(env.KEEP, 'yes');
  assert.deepEqual(Object.keys(WORKER_ENV).sort(), Object.keys(WORKER_ENV).sort());
});

test('disabling leaves autonomy and host execution off', () => {
  const env = workerEnv({ enabled: false, baseEnv: {} });
  assert.equal(env.AGENT_WORKER_ENABLED, '0');
  assert.equal(env.AGENT_AUTONOMY, undefined);
  assert.equal(env.AGENT_HOST_TOOLCHAIN, undefined);
});

test('only an explicit boolean true enables background work', () => {
  assert.deepEqual(normalize(true), { enabled: true });
  for (const value of [false, 'true', 1, null, undefined]) {
    assert.deepEqual(normalize(value), { enabled: false });
  }
});

test('login item options start the app hidden on macOS', () => {
  assert.equal(loginItemOptions('darwin').openAsHidden, true);
  assert.equal(loginItemOptions('linux').openAsHidden, false);
  assert.equal(loginItemOptions('win32').openAtLogin, true);
  assert.deepEqual(loginItemOptions('linux').args, ['--always-on']);
});

test('preference round-trips in a private file', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'agentic-energy-'));
  const file = preferencePath(dir);
  assert.deepEqual(loadPreference(file), { enabled: false });
  assert.deepEqual(savePreference(file, true), { enabled: true });
  assert.deepEqual(loadPreference(file), { enabled: true });
  if (process.platform !== 'win32') {
    const mode = fs.statSync(file).mode & 0o777;
    assert.equal(mode, 0o600);
  }
  assert.deepEqual(savePreference(file, 'yes'), { enabled: false });
  fs.rmSync(dir, { recursive: true, force: true });
});

test('an invalid preference file fails closed', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'agentic-energy-'));
  const file = path.join(dir, 'always-on.json');
  fs.writeFileSync(file, '{not json');
  assert.deepEqual(loadPreference(file), { enabled: false });
  fs.rmSync(dir, { recursive: true, force: true });
});

test('a preference path requires a directory', () => {
  assert.throws(() => preferencePath(''), TypeError);
});
