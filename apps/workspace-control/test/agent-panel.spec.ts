import { test, expect, type Page, type Route } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const openPanel = async (page: Page) => {
  await page.goto('/?token=browser-test-token');
  await expect(page.getByRole('status').filter({ hasText: 'Loading workspace' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Agent', exact: true }).click();
  await expect(page.getByRole('complementary', { name: 'Agent panel' })).toBeVisible();
};

test('the panel degrades when no agent host answers this origin', async ({ page }) => {
  await openPanel(page);
  await expect(page.getByRole('heading', { name: 'The agent host is not running' })).toBeVisible();
  await expect(page.getByText('ws web --agent')).toBeVisible();
  await expect(page.getByRole('tab')).toHaveCount(0);
});

test('chat, approvals, sessions, and config run against the agent host', async ({ page }) => {
  let pending = [{ id: 'a1', project: 'workspace', headSha: 'abcdef1234567890', action: 'deploy', inputHash: '1111111122222222', policyHash: '3333333344444444', requestedAt: new Date().toISOString(), expiresAt: new Date(Date.now() + 60_000).toISOString() }];
  let session: Record<string, unknown> | null = null;

  await page.route('**/api/agent/**', (route: Route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/agent/', '');
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === 'providers') return json({ providers: [{ id: 'anthropic', name: 'Anthropic', models: ['claude-sonnet-4-20250514'], locality: 'remote' }], defaultProvider: 'anthropic', defaultModel: 'claude-sonnet-4-20250514' });
    if (path === 'projects') return json({ projects: [{ key: 'workspace', client: 'framework', folder: '.', allowedEndpoints: null }] });
    if (path === 'workspace') return json({ root: '/tmp/workspace', projects: '', tree: '' });
    if (path === 'config') return route.request().method() === 'POST' ? json({ ok: true }) : json({ defaultProvider: 'anthropic', defaultModel: 'claude-sonnet-4-20250514', providers: { anthropic: { apiKey: 'sk-ant-12...' } } });
    if (path === 'chat') return route.fulfill({ status: 200, contentType: 'text/plain', body: '0:"Hello"\n0:" from the agent"\nd:\n' });
    if (path === 'approvals') return json({ pending });
    if (path === 'approvals/decide') { pending = []; return json({ ok: true }); }
    if (path === 'coding-sessions/workspace') return json({ session });
    if (path === 'coding-sessions/workspace/start') { session = { id: 's1', project: 'workspace', worktree: '/tmp/wt', branch: 'agent/workspace/s1', startedAt: new Date().toISOString() }; return json({ session }); }
    if (path === 'coding-sessions/workspace/stop') { session = null; return json({ stopped: true }); }
    return json({ error: 'unknown agent route' });
  });

  await openPanel(page);
  await expect(page.getByRole('tab', { name: 'Chat' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByText('anthropic/claude-sonnet-4-20250514')).toBeVisible();
  await page.getByLabel('Project this chat works with').selectOption('workspace');

  await page.getByLabel('Message the agent').fill('List the workspace projects');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(page.getByText('Hello from the agent')).toBeVisible();

  await page.getByRole('tab', { name: /Approvals/ }).click();
  await expect(page.getByText('deploy')).toBeVisible();
  await page.getByRole('button', { name: 'Approve' }).click();
  await expect(page.getByText('No approvals are waiting.')).toBeVisible();

  await page.getByRole('tab', { name: 'Sessions' }).click();
  await page.getByRole('button', { name: 'Start session' }).click();
  await expect(page.getByText('agent/workspace/s1')).toBeVisible();
  await page.getByRole('button', { name: 'Stop session' }).click();
  await expect(page.getByRole('button', { name: 'Start session' })).toBeVisible();

  await page.getByRole('tab', { name: 'Config' }).click();
  await page.getByRole('button', { name: 'Save configuration' }).click();
  await expect(page.getByText('Saved. New keys are stored')).toBeVisible();

  const results = await new AxeBuilder({ page }).include('#agent-panel').withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(results.violations).toEqual([]);
  await page.screenshot({ path: 'test-results/agent-panel.png', fullPage: true });
});
