import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const workspaceRoot = process.env.SMOKE_WORKSPACE
  || path.resolve(here, '..', 'test-results', 'smoke-workspace');
const runId = `${process.pid}-${Date.now()}`;
const projects = {
  plan: `smoke-plan-${runId}`,
  search: `smoke-search-${runId}`,
  learning: `smoke-learning-${runId}`,
  turn: `smoke-turn-${runId}`,
};
const token = 'smoke-admin-token';

function answerDialogs(page, answers) {
  const queue = [...answers];
  page.on('dialog', async dialog => {
    if (dialog.type() === 'prompt') {
      await dialog.accept(queue.shift() || '');
      return;
    }
    await dialog.accept();
  });
}

async function editorValue(page) {
  return page.evaluate(() => {
    const editor = window.agenticMonacoEditor;
    return editor ? editor.getValue() : document.querySelector('#editor').value;
  });
}

async function setEditorValue(page, value) {
  await page.evaluate(value => {
    const editor = window.agenticMonacoEditor;
    if (editor) {
      editor.setValue(value);
      return;
    }
    const textarea = document.querySelector('#editor');
    textarea.value = value;
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  }, value);
}

test.beforeAll(() => {
  // Do not remove the workspace root: the running API keeps its project
  // database there, and Windows refuses to delete open files.
  for (const project of Object.values(projects)) {
    fs.mkdirSync(path.join(workspaceRoot, project), { recursive: true });
  }
  fs.writeFileSync(
    path.join(workspaceRoot, projects.search, 'app.py'),
    'def smoke_feature():\n    return 42\n',
    'utf8',
  );
  fs.writeFileSync(
    path.join(workspaceRoot, projects.turn, 'app.py'),
    'value = 1\n',
    'utf8',
  );
});

// The workspace is unique per run and lives under the OS temp directory. Leave
// it for the runner: SQLite may still hold its files open on Windows.

test('Chat creates and displays a bounded project plan', async ({ page }) => {
  await page.goto('/');
  await page.locator('#token').fill(token);
  await page.locator('#project').fill(projects.plan);
  answerDialogs(page, ['Build a smoke-tested project']);

  await page.getByRole('button', { name: /Plan project/ }).click();

  const plan = page.locator('.msg').filter({ hasText: 'Project plan' });
  await expect(plan).toBeVisible();
  await expect(plan).toContainText('architect');
  await expect(plan).toContainText('coder');
  await expect(plan).toContainText('reviewer');
});

test('Studio indexes, searches, and opens a code hit', async ({ page }) => {
  await page.goto('/studio');
  await page.locator('#token').fill(token);
  await page.locator('#project').fill(projects.search);

  await page.locator('#refresh').click();
  await page.locator('#reindex').click();
  await expect(page.locator('#status')).toContainText('Indexed 1 files');

  await page.locator('#searchQuery').fill('smoke_feature');
  await page.locator('#search').click();
  const hit = page.locator('.search-hit').first();
  await expect(hit).toContainText('app.py:1');
  await hit.click();
  await expect(page.locator('#path')).toHaveValue('app.py');
});

test('Control page reports worker actions without page errors', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/control');
  await page.locator('#token').fill(token);

  await page.locator('#pause').click();
  await expect(page.locator('#status')).toContainText('pause requested');
  await page.locator('#resume').click();
  await expect(page.locator('#status')).toContainText('resume requested');

  expect(errors).toEqual([]);
});

test('Studio captures local feedback and records an evaluation', async ({ page }) => {
  await page.goto('/studio');
  await page.locator('#token').fill(token);
  await page.locator('#project').fill(projects.learning);
  await page.locator('details.learning summary').click();

  await setEditorValue(page, 'def accepted():\n    return 42');

  answerDialogs(page, ['Implement the accepted smoke feature']);
  await page.locator('#feedback').click();
  await expect(page.locator('#learningStatus')).toContainText('Stored example');
  page.removeAllListeners('dialog');

  answerDialogs(page, ['smoke-v1', '9', '10', '8']);
  await page.locator('#evaluation').click();
  await expect(page.locator('#learningStatus')).toContainText('approved');

  await page.locator('#learning').click();
  await expect(page.locator('#learningStatus')).toContainText('Feedback examples: 1');
});

test('Studio saves an approved edit and undoes the whole AI turn', async ({ page }) => {
  await page.goto('/studio');
  await page.locator('#token').fill(token);
  await page.locator('#project').fill(projects.turn);
  await page.locator('#path').fill('app.py');
  await page.locator('#open').click();
  await expect.poll(() => editorValue(page)).toBe('value = 1\n');

  await setEditorValue(page, 'value = 2\n');
  await page.locator('#diff').click();
  await expect(page.locator('#save')).toBeEnabled();

  answerDialogs(page, []);
  await page.locator('#save').click();
  await expect(page.locator('#status')).toContainText('Saved app.py');
  page.removeAllListeners('dialog');

  answerDialogs(page, []);
  await page.locator('#undoturn').click();
  await expect(page.locator('#status')).toContainText('Reverted 1 file');
  await expect.poll(() => editorValue(page)).toBe('value = 1\n');
});

test('Studio runs a command only after explicit approval', async ({ page }) => {
  await page.goto('/studio');
  await page.locator('#token').fill(token);
  await page.locator('#project').fill(projects.turn);

  answerDialogs(page, [`node -e "console.log('smoke-command-ok')"`]);
  await page.locator('#runcommand').click();
  await expect(page.locator('#changes')).toContainText('smoke-command-ok');
  await expect(page.locator('#status')).toContainText('Command succeeded');
});
