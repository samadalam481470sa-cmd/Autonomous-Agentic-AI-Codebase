'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const { classifyDevices, inspectEngine, selectOffload } = require('./hardware.cjs');

test('CUDA and Vulkan local devices trigger auto-offload', () => {
  const cuda = classifyDevices('Available devices:\n  CUDA0: NVIDIA GeForce RTX 4090 (24000 MiB)\n  CPU: x86_64');
  assert.equal(cuda.gpuAvailable, true);
  assert.equal(selectOffload('auto', cuda).layers, 'auto');
  assert.equal(classifyDevices('Vulkan0: AMD Radeon').gpuAvailable, true);
  assert.equal(classifyDevices('Metal: Apple M3 Max').gpuAvailable, true);
});

test('CPU-only and unknown hardware use CPU instead of claiming GPU', () => {
  for (const value of ['', 'CPU: Intel i7', 'No GPU support in this build']) {
    const result = classifyDevices(value);
    assert.equal(result.gpuAvailable, false);
    assert.deepEqual(selectOffload('auto', result), {layers: '0', mode: 'cpu'});
  }
});

test('explicit CPU selection wins, even if accelerator is available', () => {
  const devices = classifyDevices('CUDA0: RTX');
  assert.equal(selectOffload('cpu', devices).layers, '0');
  assert.equal(selectOffload('manual', devices, 12).layers, '12');
  assert.throws(() => selectOffload('manual', devices, -1), TypeError);
  assert.throws(() => selectOffload('manual', devices, NaN), TypeError);
  assert.throws(() => selectOffload('unknown', devices), TypeError);
});

test('probes selected engine without invoking a shell', async () => {
  const calls = [];
  const fake = (exe, args, opts, done) => {
    calls.push([exe,args,opts]);
    done(null, 'CUDA0: NVIDIA RTX 4070\nCPU: AMD', '');
  };
  const response = await inspectEngine('/local/llama-server', fake);
  assert.equal(response.gpuAvailable, true);
  assert.deepEqual(calls[0][1], ['--list-devices']);
  assert.equal(calls[0][2].windowsHide, true);
});
test('failed engine probe never asserts GPU', async () => {
  const fake = (exe, args, opts, done) => done(new Error('unavailable'), '', '');
  const result = await inspectEngine('missing', fake);
  assert.equal(result.gpuAvailable, false);
  assert.equal(selectOffload('auto', result).layers, '0');
});
