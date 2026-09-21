import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const open = async (page: Page, view = 'overview', project = 'workspace') => {
  await page.goto(`/?token=browser-test-token#view=${view}&project=${project}`);
  await expect(page.getByRole('status').filter({ hasText: 'Loading workspace' })).toHaveCount(0);
};
const nav = (page: Page, name: string) => page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name, exact: true });
const sidebar = (page: Page) => page.getByRole('complementary', { name: 'Workspace sidebar' });

test('HTTP boundary rejects foreign origins and hosts without disclosing the token', async ({ request }) => {
  const foreign = await request.get('/', { headers: { Origin: 'https://example.invalid' } });
  expect(foreign.status()).toBe(403);
  expect(await foreign.text()).not.toContain('browser-test-token');
  const rebound = await request.get('/', { headers: { Host: 'example.invalid:18765' } });
  expect(rebound.status()).toBe(403);
  expect(foreign.headers()['access-control-allow-origin']).toBeUndefined();
});

test('bare root boots the npm UI and every navigation view loads', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'A clear view of your work.' })).toBeVisible();
  await sidebar(page).getByRole('button', { name: 'workspace', exact: true }).click();
  const destinations = [
    ['Overview', 'A clear view of your work.'], ['Projects', '3 projects'], ['Clients', 'Example Studio'],
    ['Task board', 'Render board'], ['Backlog', 'Nothing here yet'], ['Search', 'matching tasks'],
    ['Plans', 'Delivery plan'], ['Runs', 'Continue browser validation'], ['Context', 'context/memory/projects/workspace'],
    ['Activity', 'Human hours'], ['Health', 'Your workspace is ready.'], ['Settings', 'npm uidl-runtime 0.1.4'],
  ];
  for (const [name, content] of destinations) {
    await nav(page, name).click();
    await expect(page.getByRole('heading', { name, exact: true, level: 1 })).toBeVisible();
    await expect(page.locator('main').getByText(content, { exact: false }).first()).toBeVisible();
  }
  expect(errors).toEqual([]);
});

test('workspace explorer shows client group project hierarchy', async ({ page }) => {
  await open(page, 'projects', '');
  await expect(sidebar(page).getByText('Workspace explorer')).toBeVisible();
  await expect(sidebar(page).getByText('example')).toBeVisible();
  await expect(sidebar(page).getByText('platform')).toBeVisible();
  await expect(sidebar(page).getByText('Projects').first()).toBeVisible();
  await sidebar(page).getByRole('button', { name: 'atlas', exact: true }).click();
  await expect(page).toHaveURL(/project=atlas/);
  await expect(page.getByRole('heading', { name: 'Task board', exact: true, level: 1 })).toBeVisible();
  await expect(sidebar(page).getByRole('button', { name: 'atlas', exact: true })).toHaveAttribute('aria-current', 'page');
});

test('task create, validation, edit, status, block, and git evidence persist', async ({ page }) => {
  await open(page, 'board');
  await page.getByRole('button', { name: 'New task', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await page.getByLabel('Title', { exact: true }).fill('Browser delivery task');
  await page.getByLabel('Status', { exact: true }).selectOption('ready');
  await page.getByLabel('Blocked', { exact: true }).check();
  await dialog.getByRole('button', { name: 'Create task' }).click();
  await expect(dialog.getByRole('alert')).toContainText('Enter a reason');
  await page.getByLabel('Blocked reason').fill('Waiting for design review');
  await page.getByLabel('Acceptance criteria').fill('Task is persisted\nEvidence can be linked');
  await page.getByLabel('Labels', { exact: true }).fill('ui, browser');
  await dialog.getByRole('button', { name: 'Create task' }).click();
  await expect(dialog).not.toBeVisible();
  await page.getByRole('button', { name: 'Browser delivery task', exact: true }).click();
  await expect(page.getByLabel('Blocked reason')).toHaveValue('Waiting for design review');
  await page.getByLabel('Status', { exact: true }).selectOption('in_progress');
  await page.getByLabel('Blocked', { exact: true }).uncheck();
  await dialog.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.locator('.board-column').filter({ has: page.getByRole('heading', { name: 'In progress', exact: true }) }).getByRole('button', { name: 'Browser delivery task' })).toBeVisible();
  await page.getByRole('button', { name: 'Browser delivery task', exact: true }).click();
  await page.getByLabel('Commit', { exact: true }).selectOption({ index: 1 });
  await dialog.getByRole('button', { name: 'Link commit' }).click();
  await expect(dialog.getByRole('button', { name: /^Remove / })).toBeVisible();
  await dialog.getByRole('button', { name: /^Remove / }).click();
  await expect(dialog.getByText('No commits linked yet.')).toBeVisible();
  await page.getByRole('button', { name: 'Close task' }).click();
  await page.reload();
  await expect(page.getByRole('button', { name: 'Browser delivery task', exact: true })).toBeVisible();
});

test('search filters, clear, and project isolation', async ({ page }) => {
  await open(page, 'search');
  await page.getByLabel('Search tasks').fill('Render');
  await page.getByRole('main').getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByText('1 matching tasks')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Render board', exact: true })).toBeVisible();
  await page.getByLabel('Status', { exact: true }).selectOption('done');
  await page.getByRole('main').getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByText('No matching tasks', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Clear filters' }).click();
  await expect(page.getByLabel('Search tasks')).toHaveValue('');
  await page.getByLabel('Active project').selectOption('studio');
  await expect(page.getByText('0 matching tasks')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Render board', exact: true })).toHaveCount(0);
});

test('clock in and out records activity; reporting month changes', async ({ page }) => {
  await open(page, 'activity');
  await page.getByLabel('Actor', { exact: true }).fill('browser-user');
  await page.getByLabel('Work note').fill('Verify local activity');
  await page.getByRole('button', { name: 'Clock in', exact: true }).click();
  await expect(page.getByText('Clock started.', { exact: true })).toBeVisible();
  await expect(page.getByText('browser-user · web-control', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Clock out', exact: true }).click();
  await expect(page.getByText('Clock stopped and session recorded.', { exact: true })).toBeVisible();
  await page.getByLabel('Reporting month').fill('2020-01');
  await page.getByRole('button', { name: 'Apply month' }).click();
  await expect(page.getByText('No hours recorded this month')).toBeVisible();
});

test('theme persists, system preference reacts, and both themes are accessible', async ({ page }) => {
  await open(page);
  for (const mode of ['Dark', 'Light']) {
    await page.getByRole('button', { name: mode, exact: true }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', mode.toLowerCase());
    await page.reload();
    await expect(page.getByRole('button', { name: mode, exact: true })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('heading', { name: 'A clear view of your work.' })).toBeVisible();
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
    expect(results.violations).toEqual([]);
    await page.screenshot({ path: `test-results/overview-${mode.toLowerCase()}.png`, fullPage: true });
  }
  await page.getByRole('button', { name: 'System', exact: true }).click();
  await page.emulateMedia({ colorScheme: 'dark' });
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.emulateMedia({ colorScheme: 'light' });
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
});

test('mobile layouts and keyboard task access', async ({ page }) => {
  for (const width of [320, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await open(page);
    await expect(page.getByRole('heading', { name: 'A clear view of your work.' })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await nav(page, 'Task board').click();
  await expect(page.getByRole('button', { name: 'Open navigation' })).toHaveAttribute('aria-expanded', 'false');
  const task = page.getByRole('button', { name: 'Render board', exact: true });
  await task.focus(); await page.keyboard.press('Enter');
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await expect(task).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/board-mobile.png', fullPage: true });
});

test('expired token and failed API show errors with retry', async ({ page }) => {
  await page.goto('/?token=expired');
  await expect(page.getByRole('alert')).toContainText('token has expired');
  await page.route('**/api/overview?*', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'Temporarily unavailable' }) }));
  await open(page);
  await expect(page.getByRole('alert')).toContainText('Temporarily unavailable');
  await page.unroute('**/api/overview?*');
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'A clear view of your work.' })).toBeVisible();
});

test('concurrent task edit preserves draft and reports conflict', async ({ page, request }) => {
  await open(page, 'board');
  await page.getByRole('button', { name: 'Review board', exact: true }).click();
  await page.getByLabel('Title', { exact: true }).fill('Unsaved browser draft');
  const headers = { Authorization: 'Bearer browser-test-token' };
  const detail = await (await request.get('/api/projects/workspace/tasks/task_board_review', { headers })).json();
  await request.put('/api/projects/workspace/tasks/task_board_review', { headers, data: { title: 'External update', expected_revision: detail.task.revision } });
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('record changed');
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Unsaved browser draft');
});
