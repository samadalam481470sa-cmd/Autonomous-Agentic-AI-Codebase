'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, 'package.json'), 'utf8'));

test('desktop packaging declares Windows, macOS and Linux targets', () => {
  assert.match(pkg.scripts['package:win'], /--win nsis/);
  assert.match(pkg.scripts['package:mac'], /--mac dmg/);
  assert.match(pkg.scripts['package:linux'], /--linux AppImage/);
  assert.equal(pkg.build.win.target, 'nsis');
  assert.equal(pkg.build.mac.target, 'dmg');
  assert.equal(pkg.build.linux.target, 'AppImage');
});

test('macOS declares local microphone access instead of failing at runtime', () => {
  const description = pkg.build.mac.extendInfo?.NSMicrophoneUsageDescription;
  assert.equal(typeof description, 'string');
  assert.match(description, /local/i);
  assert.match(description, /whisper/i);
});

test('the backend and reviewed model policy are packaged on every platform', () => {
  const resources = pkg.build.extraResources;
  assert.ok(Array.isArray(resources));
  assert.ok(resources.some(item => item.from === '../../dist/backend' && item.to === 'backend'));
  assert.ok(resources.some(item => item.from === '../../security/model-policy.json' && item.to === 'model-policy.json'));
  for (const file of ['main.cjs', 'preload.cjs', 'setup.html', 'model-license.cjs']) {
    assert.ok(pkg.build.files.includes(file), file);
  }
});
