'use strict';
/**
 * Local inference process supervision. Runs a user-selected llama.cpp executable
 * on this computer only, binds it to loopback, and never contacts a cloud model.
 */
const http = require('node:http');
const { spawn } = require('node:child_process');
const { inspectEngine, selectOffload } = require('./hardware.cjs');

const MODEL_URL = 'http://127.0.0.1:9931/v1/models';
const GATEWAY_URL = 'http://127.0.0.1:8088/health';

function probeHttp(url, timeoutMs = 1300) {
  return new Promise(resolve => {
    const request = http.get(url, { timeout: timeoutMs }, response => {
      response.resume();
      resolve(response.statusCode === 200);
    });
    request.on('error', () => resolve(false));
    request.on('timeout', () => { request.destroy(); resolve(false); });
  });
}

function captureLogs(processHandle) {
  let tail = '';
  for (const stream of [processHandle.stdout, processHandle.stderr]) {
    if (stream && typeof stream.on === 'function') {
      stream.on('data', chunk => { tail = (tail + String(chunk)).slice(-12000); });
    }
  }
  return () => tail;
}

function observedOffload(logs) {
  const match = String(logs).match(/offloaded\s+(\d+)\s*\/\s*\d+\s+layers?\s+to\s+GPU/i);
  return match ? Number(match[1]) > 0 : null;
}

async function terminate(processHandle, timeoutMs = 1500) {
  if (!processHandle || processHandle.exitCode !== null ||
      processHandle.signalCode != null || processHandle.killed) return;
  await new Promise(resolve => {
    let finished = false;
    let timer;
    const done = () => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      processHandle.removeListener('close', done);
      resolve();
    };
    processHandle.once('close', done);
    timer = setTimeout(() => {
      try { processHandle.kill('SIGKILL'); } catch (_) {}
      done();
    }, timeoutMs);
    timer.unref?.();
    try { processHandle.kill(); } catch (_) { done(); }
  });
}

async function waitForReady(processHandle, url, {
  probe = probeHttp,
  sleep = ms => new Promise(resolve => setTimeout(resolve, ms)),
  timeoutMs = 120000
} = {}) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (processHandle.startError || processHandle.exitCode !== null ||
        processHandle.signalCode != null || processHandle.killed) {
      throw new Error('Local inference process exited before readiness');
    }
    if (await probe(url)) return;
    await sleep(350);
  }
  throw new Error('Local inference server did not become ready before the timeout');
}

async function startLocalModel({
  engine, model, mode = 'auto', layers = 0, probe = probeHttp,
  inspect = inspectEngine, spawnProcess = spawn,
  sleep, timeoutMs = 120000
}) {
  if (typeof engine !== 'string' || !engine || typeof model !== 'string' || !model) {
    throw new TypeError('Local executable and GGUF model paths are required');
  }
  if (await probe(MODEL_URL)) {
    throw new Error('Port 9931 is already occupied; refusing to attach to an unknown service');
  }

  const devices = await inspect(engine);
  const selected = selectOffload(mode, devices, layers);
  const launch = async gpuLayers => {
    const args = ['-m', model, '--host', '127.0.0.1', '--port', '9931',
      '-c', '4096', '-ngl', gpuLayers, '--jinja', '--alias', 'local-model'];
    const processHandle = spawnProcess(engine, args, {
      windowsHide: true, shell: false, stdio: ['ignore', 'pipe', 'pipe']
    });
    const readLogs = captureLogs(processHandle);
    processHandle.on('error', error => {
      processHandle.startError = error.message || 'Unable to launch local engine';
    });
    try {
      await waitForReady(processHandle, MODEL_URL, { probe, sleep, timeoutMs });
      return { process: processHandle, gpuConfirmed: observedOffload(readLogs()) };
    } catch (error) {
      await terminate(processHandle);
      throw error;
    }
  };

  let result;
  let effectiveMode = selected.mode;
  let effectiveLayers = selected.layers;
  try {
    result = await launch(selected.layers);
  } catch (error) {
    if (mode !== 'auto' || selected.mode !== 'gpu') throw error;
    // A GPU startup failure should not prevent owners of CPU-capable machines
    // from running the model. Do not silently override explicit manual mode.
    result = await launch('0');
    effectiveMode = 'cpu-fallback';
    effectiveLayers = '0';
  }
  return {
    process: result.process,
    mode: effectiveMode,
    offloadedLayers: effectiveLayers,
    gpuDetected: !!devices.gpuAvailable,
    gpuConfirmed: effectiveMode === 'gpu' ? result.gpuConfirmed : false,
    deviceDescriptions: devices.gpu || []
  };
}

module.exports = {
  MODEL_URL, GATEWAY_URL, probeHttp, captureLogs, observedOffload,
  terminate, waitForReady, startLocalModel
};
