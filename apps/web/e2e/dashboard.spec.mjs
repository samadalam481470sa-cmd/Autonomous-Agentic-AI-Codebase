import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const workspaceRoot = process.env.SMOKE_WORKSPACE
  || path.resolve(here, '..', 'test-results', 'smoke-workspace');
const token = 'smoke-admin-token';
const project = 'smoke-dashboard';

test.beforeAll(() => {
  fs.rmSync(path.join(workspaceRoot, project), { recursive: true, force: true });
  fs.mkdirSync(path.join(workspaceRoot, project), { recursive: true });
  fs.writeFileSync(
    path.join(workspaceRoot, project, 'app.py'),
    'def dashboard_feature():\n    return 42\n',
    'utf8',
  );
});

test('Dashboard unlocks, searches, navigates every view, and locks', async ({ page }) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));

  await page.goto('/dashboard');
  await page.getByLabel('Administrator token').fill(token);
  await page.getByLabel('Project').fill(project);
  await page.getByRole('button', { name: 'Unlock workspace' }).click();
  await expect(page.locator('.status-text')).toContainText(`Unlocked ${project}`);

  const explorerToggle = page.locator('.title-actions button').filter({ hasText: 'Explorer' });
  await explorerToggle.click();
  await expect(explorerToggle).toHaveAttribute('aria-pressed', 'false');
  await explorerToggle.click();
  await expect(explorerToggle).toHaveAttribute('aria-pressed', 'true');

  const assistantToggle = page.locator('.title-actions button').filter({ hasText: 'Assistant' });
  await assistantToggle.click();
  await expect(assistantToggle).toHaveAttribute('aria-pressed', 'false');
  await assistantToggle.click();
  await expect(assistantToggle).toHaveAttribute('aria-pressed', 'true');

  await page.locator('.title-actions button').filter({ hasText: 'Index' }).click();
  await expect(page.locator('.status-text')).toContainText('Indexed', { timeout: 20_000 });

  await page.locator('.rail-button[title="Search"]').click();
  await page.getByLabel('Search code').fill('dashboard_feature');
  await page.locator('.search-pane button.primary').click();
  await expect(page.locator('.search-results .result').first()).toContainText('app.py:1');
  await page.locator('.search-results .result').first().click();
  await expect(page.locator('.editor-meta')).toContainText('app.py');

  await page.getByRole('tab', { name: 'Ask code' }).click();
  await expect(page.getByRole('tab', { name: 'Ask code' })).toHaveAttribute('aria-selected', 'true');
  await page.getByRole('tab', { name: 'Agents' }).click();
  await expect(page.getByRole('tab', { name: 'Agents' })).toHaveAttribute('aria-selected', 'true');

  await page.locator('.rail-button[title="Settings"]').click();
  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible();
  await expect(page.getByLabel('Administrator token')).toHaveValue(token);

  await page.locator('.rail-button[title="Device runtime"]').click();
  await expect(page.getByRole('heading', { name: 'Device runtime' })).toBeVisible();
  await expect(page.locator('.device-page')).toContainText('Thermal governor', { timeout: 15_000 });
  await page.getByTitle('Refresh device report').click();

  await page.locator('.rail-button[title="Security"]').click();
  await expect(page.getByRole('heading', { name: 'Security posture' })).toBeVisible();
  await expect(page.locator('.posture').first()).toBeVisible();

  await page.keyboard.press('Control+k');
  const palette = page.getByRole('dialog', { name: 'Command palette' });
  await expect(palette).toBeVisible();
  await page.getByLabel('Search commands and files').fill('Device');
  await expect(palette.locator('.palette-item').first()).toContainText('Device runtime');
  await page.keyboard.press('Escape');
  await expect(palette).toBeHidden();

  await page.locator('.rail-button[title="Labs"]').click();
  await expect(page.getByRole('heading', { name: 'Labs' })).toBeVisible();
  await page.getByRole('tab', { name: 'Diagrams' }).click();
  await page.getByRole('button', { name: 'Generate diagram' }).click();
  await expect(page.locator('.diagram-frame img')).toBeVisible();
  await expect(page.locator('.diagram-stats')).toContainText('files shown');
  await page.getByRole('tab', { name: 'GitHub learning' }).click();
  await expect(page.getByRole('button', { name: 'Learn repository' })).toBeDisabled();
  await expect(page.locator('.labs-note')).toContainText('GITHUB_LEARNING');

  await page.getByTitle('Lock workspace').click();
  await expect(page.getByRole('button', { name: 'Unlock workspace' })).toBeVisible();
  expect(pageErrors).toEqual([]);
});
