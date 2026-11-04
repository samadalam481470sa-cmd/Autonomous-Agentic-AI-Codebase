import { test, expect } from '@playwright/test';

const token = process.env.BUNDLE_TOKEN || 'bundle-smoke-token';
const baseURL = process.env.BUNDLE_URL || 'http://127.0.0.1:8131';

test('downloaded bundle serves the dashboard, editor, and control page', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));

  for (const asset of [
    '/assets/monaco-entry.js',
    '/assets/monaco-entry.css',
    '/assets/editor.worker.js',
    '/assets/ts.worker.js',
    '/assets/MONACO_LICENSE.txt',
  ]) {
    const response = await page.request.get(`${baseURL}${asset}`);
    expect(response.ok(), asset).toBe(true);
    expect((await response.body()).byteLength, asset).toBeGreaterThan(0);
  }

  await page.goto('/dashboard');
  await page.getByLabel('Administrator token').fill(token);
  await page.getByLabel('Project').fill('bundle-smoke');
  await page.getByRole('button', { name: 'Unlock workspace' }).click();
  await expect(page.locator('.status-text')).toContainText('Unlocked bundle-smoke');
  await expect(page.locator('.rail-button[title="Settings"]')).toBeVisible();

  await page.goto('/studio');
  await page.locator('#token').fill(token);
  await page.locator('#project').fill('bundle-smoke');
  await page.locator('#refresh').click();
  await page.locator('#reindex').click();
  await expect(page.locator('#status')).toContainText('Indexed 1 files');
  await expect.poll(
    () => page.evaluate(() => Boolean(window.agenticMonacoEditor)),
    { timeout: 20_000 },
  ).toBe(true);

  await page.goto('/control');
  await page.locator('#token').fill(token);
  await page.locator('#pause').click();
  await expect(page.locator('#status')).toContainText('pause requested');

  expect(errors).toEqual([]);
});
