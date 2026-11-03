'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { checkModel, loadPolicy, policyPath, USES } = require('./model-license.cjs');

const QWEN = 'Qwen/Qwen2.5-Coder-7B-Instruct';
const LLAMA = 'meta-llama/Llama-3.1-8B-Instruct';

test('loads the shared reviewed registry and knows every permitted use', () => {
  const policy = loadPolicy();
  assert.ok(policy.models.length >= 4);
  assert.deepEqual(USES, ['inference', 'training', 'redistribution', 'shipping']);
  assert.match(policyPath(), /security[\\/]model-policy\.json$/);
  assert.match(policyPath({ packaged: true, resourcesPath: '/opt/app' }), /model-policy\.json$/);
});

test('Apache coding models are approved for inference and training', () => {
  assert.equal(checkModel({ modelId: QWEN, license: 'Apache-2.0' }).approved, true);
  assert.equal(
    checkModel({ modelId: 'qwen2.5-coder:7b', license: 'Apache-2.0', use: 'training' }).approved,
    true
  );
  const decision = checkModel({ modelId: QWEN, license: 'Apache-2.0', use: 'shipping' });
  assert.equal(decision.approved, true);
  assert.ok(decision.requirements.some(item => item.includes('Apache-2.0')));
});

test('custom Llama license trains but cannot ship weights', () => {
  assert.equal(
    checkModel({ modelId: LLAMA, license: 'Llama-3.1-Community', use: 'training' }).approved,
    true
  );
  const shipping = checkModel({ modelId: LLAMA, license: 'Llama-3.1-Community', use: 'shipping' });
  assert.equal(shipping.approved, false);
  assert.equal(shipping.status, 'restricted');
  assert.ok(shipping.requirements.some(item => item.includes('Built with Llama')));
});

test('unknown models, mismatched licenses, and bad uses fail closed', () => {
  assert.equal(checkModel({ modelId: 'unknown/model', license: 'MIT' }).approved, false);
  assert.equal(checkModel({ modelId: QWEN, license: 'MIT' }).status, 'mismatch');
  assert.equal(checkModel({ modelId: '', license: 'Apache-2.0' }).approved, false);
  assert.throws(() => checkModel({ modelId: QWEN, license: 'Apache-2.0', use: 'anything' }), TypeError);
});

test('malformed replacement policy is rejected, not silently trusted', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'agentic-policy-'));
  const file = path.join(directory, 'policy.json');
  fs.writeFileSync(file, JSON.stringify({ version: 1, models: 'not-an-array' }));
  try {
    assert.throws(() => loadPolicy(file), /malformed/);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
