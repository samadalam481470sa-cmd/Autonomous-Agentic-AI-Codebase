import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const workspaceRoot = process.env.SMOKE_WORKSPACE || path.join(os.tmpdir(), 'agentic-ai-smoke');
const runId = `${process.pid}-${Date.now()}`;
const projects = {
  plan: `smoke-plan-${runId}`,
  search: `smoke-search-${runId}`,
  learning: `smoke-learning-${runId}`,
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
});

test.afterAll(() => {
  for (const project of Object.values(projects)) {
    fs.rmSync(path.join(workspaceRoot, project), { recursive: true, force: true });
  }
});

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

test('Studio captures local feedback and records an evaluation', async ({ page }) => {
  await page.goto('/studio');
  await page.locator('#token').fill(token);
  await page.locator('#project').fill(projects.learning);
  await page.locator('details.learning summary').click();

  await page.evaluate(() => {
    const editor = document.querySelector('#editor');
    editor.value = 'def accepted():\n    return 42';
    editor.dispatchEvent(new Event('input', { bubbles: true }));
  });

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
