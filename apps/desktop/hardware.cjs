'use strict';
/**
 * Local llama.cpp device negotiation. Never sends hardware data off-box.
 * An installed llama-server binary decides which compute backends actually
 * exist. OS GPU brand alone cannot prove the server supports acceleration.
 */
const { execFile } = require('node:child_process');

function classifyDevices(output) {
  const lines = String(output || '').split(/\r?\n/);
  const gpu = lines.filter(line =>
    /(?:^|[\s:|])(?:CUDA\d+|ROCm\d+|HIP\d+|Vulkan\d+|SYCL\d+|Metal\d*|GPU\s*\d*\s*:)/i.test(line) ||
    /(?:device\s*\d+[^\n]*\b(?:nvidia|radeon|apple\s*m\d+|intel\s*arc)\b)/i.test(line)
  ).map(line => line.trim().slice(0, 240));
  const cpu = lines.filter(line => /(?:^|[\s:|])CPU(?:\d+)?(?:\s|:|$)/i.test(line))
    .map(line => line.trim().slice(0, 240));
  return { gpu, cpu, gpuAvailable: gpu.length > 0, lines: lines.slice(0, 50) };
}

function inspectEngine(executable, run = execFile) {
  return new Promise(resolve => {
    run(executable, ['--list-devices'], {
      windowsHide: true, timeout: 12000, maxBuffer: 512 * 1024
    }, (err, stdout, stderr) => {
      const details = classifyDevices([stdout || '', stderr || ''].join('\n'));
      resolve({
        ...details,
        supported: !err || details.gpu.length > 0 || details.cpu.length > 0,
        error: err ? 'Unable to verify llama.cpp accelerator backends; CPU remains available.' : null
      });
    });
  });
}

function selectOffload(mode, devices, manualLayers = 0) {
  if (!['auto', 'cpu', 'manual'].includes(mode)) {
    throw new TypeError('Invalid hardware mode');
  }
  if (mode === 'cpu') return { layers: '0', mode: 'cpu' };
  if (mode === 'manual') {
    if (!Number.isInteger(manualLayers) || manualLayers < 0 || manualLayers > 999) {
      throw new TypeError('Manual layer count must be between 0 and 999');
    }
    return { layers: String(manualLayers), mode: manualLayers ? 'manual' : 'cpu' };
  }
  return devices && devices.gpuAvailable
    ? { layers: 'auto', mode: 'gpu' }
    : { layers: '0', mode: 'cpu' };
}

module.exports = { classifyDevices, inspectEngine, selectOffload };
