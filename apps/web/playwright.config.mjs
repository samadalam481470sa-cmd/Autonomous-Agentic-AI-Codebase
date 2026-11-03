import { defineConfig } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..', '..');
const workspace = process.env.SMOKE_WORKSPACE || path.join(os.tmpdir(), 'agentic-ai-smoke');
const venvPython = process.platform === 'win32'
  ? path.join(root, '.venv', 'Scripts', 'python.exe')
  : path.join(root, '.venv', 'bin', 'python');
const python = process.env.PYTHON || (fs.existsSync(venvPython) ? venvPython : 'python');

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: 'line',
  use: {
    baseURL: 'http://127.0.0.1:8765',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: `"${python}" -m uvicorn services.api.main:app --host 127.0.0.1 --port 8765`,
    cwd: root,
    url: 'http://127.0.0.1:8765/health',
    timeout: 120_000,
    reuseExistingServer: false,
    env: {
      ...process.env,
      WORKSPACE_ROOT: workspace,
      AGENT_ADMIN_TOKEN: 'smoke-admin-token',
      PROJECT_DB_PATH: path.join(workspace, 'projects.sqlite3'),
    },
  },
});
