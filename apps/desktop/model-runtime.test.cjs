'use strict';
const assert = require('node:assert/strict');
const test = require('node:test');
const { EventEmitter } = require('node:events');
const { PassThrough } = require('node:stream');
const { startLocalModel, observedOffload, waitForReady, terminate } = require('./model-runtime.cjs');

function fakeProcess(exitCode = null) {
  const child = new EventEmitter();
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.exitCode = exitCode;
  child.signalCode = null;
  child.killed = false;
  child.kill = signal => {
    child.killed = true;
    child.signalCode = signal || 'SIGTERM';
    child.emit('close', exitCode, child.signalCode);
    return true;
  };
  return child;
}

test('recognizes only observed GPU layer offload, not merely device names', () => {
  assert.equal(observedOffload('CUDA0: RTX 4090'), null);
  assert.equal(observedOffload('llama_model_load: offloaded 33/33 layers to GPU'), true);
  assert.equal(observedOffload('offloaded 0/33 layers to GPU'), false);
});

test('launches with the selected local GPU and loopback binding', async () => {
  const child = fakeProcess();
  const calls = [];
  let checks = 0;
  const started = await startLocalModel({
    engine: '/local/llama-server', model: '/local/coder.gguf',
    inspect: async () => ({ gpuAvailable: true, gpu: ['CUDA0: RTX'] }),
    probe: async () => ++checks !== 1,
    spawnProcess: (exe, args, options) => {
      calls.push({ exe, args, options });
      process.nextTick(() => child.stderr.write('offloaded 30/33 layers to GPU\n'));
      return child;
    }
  });
  assert.equal(started.mode, 'gpu');
  assert.equal(started.offloadedLayers, 'auto');
  assert.equal(started.process, child);
  assert.deepEqual(calls[0].args.slice(0, 6),
    ['-m', '/local/coder.gguf', '--host', '127.0.0.1', '--port', '9931']);
  assert.equal(calls[0].options.shell, false);
  assert.equal(calls[0].args[calls[0].args.indexOf('-ngl') + 1], 'auto');
  await terminate(child);
  assert.equal(child.killed, true);
});

test('retries on CPU only in auto mode after GPU startup failure', async () => {
  const children = [fakeProcess(1), fakeProcess()];
  const args = [];
  let probes = 0;
  const result = await startLocalModel({
    engine: 'llama-server', model: 'coder.gguf',
    inspect: async () => ({ gpuAvailable: true, gpu: ['Vulkan0: AMD'] }),
    probe: async () => ++probes > 1,
    spawnProcess: (exe, argv) => {
      args.push(argv);
      return children[args.length - 1];
    }
  });
  assert.equal(args.length, 2);
  assert.equal(args[0][args[0].indexOf('-ngl') + 1], 'auto');
  assert.equal(args[1][args[1].indexOf('-ngl') + 1], '0');
  assert.equal(result.mode, 'cpu-fallback');
  assert.equal(result.gpuConfirmed, false);
  await terminate(result.process);
});

test('manual mode never silently falls back to CPU', async () => {
  let launches = 0;
  await assert.rejects(startLocalModel({
    engine: 'server', model: 'model.gguf', mode: 'manual', layers: 25,
    inspect: async () => ({ gpuAvailable: true, gpu: ['CUDA0'] }),
    probe: async () => false,
    spawnProcess: () => { launches++; return fakeProcess(1); }
  }), /exited before readiness/);
  assert.equal(launches, 1);
});

test('refuses an already occupied local port', async () => {
  let launched = false;
  await assert.rejects(startLocalModel({
    engine: 'server', model: 'model.gguf',
    probe: async () => true,
    inspect: async () => { throw new Error('Should not inspect'); },
    spawnProcess: () => { launched = true; }
  }), /already occupied/);
  assert.equal(launched, false);
});

test('CPU-only engine always starts with zero GPU layers', async () => {
  let requestedLayers;
  let probes = 0;
  const result = await startLocalModel({
    engine: 'server', model: 'model.gguf',
    inspect: async () => ({ gpuAvailable: false, gpu: [] }),
    probe: async () => ++probes > 1,
    spawnProcess: (exe, argv) => {
      requestedLayers = argv[argv.indexOf('-ngl') + 1];
      return fakeProcess();
    }
  });
  assert.equal(requestedLayers, '0');
  assert.equal(result.mode, 'cpu');
  assert.equal(result.gpuConfirmed, false);
  await terminate(result.process);
});

test('reports a process failure before an unrelated service can claim readiness', async () => {
  await assert.rejects(waitForReady(fakeProcess(1), 'http://127.0.0.1:9931', {
    probe: async () => true
  }), /exited before readiness/);
});
