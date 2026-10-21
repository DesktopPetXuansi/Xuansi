// 独立 Chrome 与合成路由：不读取用户会话，不访问真实反馈库。
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const origin = process.env.WEB_URL ?? 'http://localhost:3100';
assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(new URL(origin).hostname));
const output = path.join(root, 'data/verification/feedback-center-2026-10-19/browser');
await mkdir(output, { recursive: true });
const { chromium, expect } = await import(pathToFileURL(path.join(root, 'web/frontend/node_modules/@playwright/test/index.mjs')).href);
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const checks = [], errors = [];
const checked = text => { checks.push(text); console.log(`通过：${text}`); };
const feedback = (id, status = 'NEW') => ({ id, category: 'BUG', title: `合成反馈-${id}`, description: '第一行：换形象后没有反应。\n第二行：重新打开后正常。',
  contact: '', diagnostics: null, status, moderationStatus: 'PENDING', publicConsent: false, githubIssueUrl: '', createdAt: '2026-10-19T10:00:00Z', updatedAt: '2026-10-19T10:00:00Z' });

async function fixture(role = 'ADMIN') {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const state = { mode: 'list', listCalls: 0, patches: 0, patchFail: false, patchGate: undefined, listGate: undefined, queries: [] };
  await context.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url());
    const reply = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
    if (url.pathname === '/api/v1/me') return role === 'VISITOR' ? reply({ error: { code: 'UNAUTHORIZED', message: '请先登录' } }, 401)
      : reply({ data: { id: 'synthetic-admin', displayName: '合成管理员', email: 'test@example.invalid', emailVerified: true, role, status: 'ACTIVE' } });
    if (url.pathname === '/api/v1/auth/csrf') return reply({ data: { token: 'synthetic-token' } });
    if (url.pathname === '/api/v1/admin/feedback') {
      state.listCalls++;
      state.queries.push(url.search);
      if (state.listGate) await state.listGate;
      if (state.mode === 'error' || (state.mode === 'page-error' && url.searchParams.has('cursor'))) return reply({ error: { code: 'INTERNAL', message: '合成加载失败，请重试。' } }, 500);
      if (state.mode === 'forbidden') return reply({ error: { code: 'FORBIDDEN', message: '无权读取反馈。' } }, 403);
      if (state.mode === 'empty') return reply({ data: [], meta: { nextCursor: null } });
      if (url.searchParams.has('cursor')) return reply({ data: [feedback('2')], meta: { nextCursor: null } });
      const status = url.searchParams.get('status') ?? 'NEW';
      const item = feedback('1', status);
      item.description += '\n' + 'a'.repeat(200);
      return reply({ data: [item], meta: { nextCursor: status === 'NEW' ? 'opaque-synthetic-cursor' : null } });
    }
    if (url.pathname === '/api/v1/admin/feedback/1' && route.request().method() === 'PATCH') {
      state.patches++;
      if (state.patchGate) await state.patchGate;
      if (state.patchFail) return reply({ error: { code: 'INTERNAL', message: '合成保存失败，请重试。' } }, 500);
      return reply({ data: { ...feedback('1', route.request().postDataJSON().status), contact: 'tester@example.invalid',
        diagnostics: { appVersion: '0.8.0', system: 'Windows', architecture: 'AMD64', pythonVersion: '3.12', qtVersion: '6.11' } } });
    }
    // 未知接口也被隔离，不允许意外落到本地真实服务。
    return reply({ error: { code: 'NOT_FOUND', message: '合成接口未配置' } }, 404);
  });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  return { context, page, state };
}

try {
  for (const role of ['VISITOR', 'USER']) {
    const { context, page, state } = await fixture(role);
    await page.goto(`${origin}/admin/feedback`);
    await expect(page.getByRole('heading', { name: role === 'VISITOR' ? '登录后，继续你的陪伴' : '你没有管理后台权限。', exact: true })).toBeVisible();
    await expect(page.getByLabel('管理后台导航')).toHaveCount(0);
    await expect(page.getByLabel('反馈收件箱')).toHaveCount(0);
    assert.equal(state.listCalls, 0);
    await context.close();
  }
  checked('访客与普通用户不渲染管理员导航、收件内容，也不请求反馈');

  const { context, page, state } = await fixture();
  state.mode = 'empty';
  let releaseList;
  state.listGate = new Promise(resolve => { releaseList = resolve; });
  await page.goto(`${origin}/admin/feedback`);
  await expect(page.getByText('正在加载反馈…', { exact: true })).toBeVisible();
  releaseList();
  await expect(page.getByText('这个状态下暂时没有反馈。')).toBeVisible();
  await expect(page.getByRole('link', { name: '反馈中心', exact: true })).toHaveAttribute('aria-current', 'page');
  checked('管理员独立入口、默认待处理筛选、加载与空状态');

  state.mode = 'error';
  await page.reload();
  await expect(page.locator('.notice[role="alert"]')).toContainText('合成加载失败');
  state.mode = 'list';
  await page.getByRole('button', { name: '重新加载', exact: true }).click();
  await expect(page.getByRole('heading', { name: '合成反馈-1' })).toBeVisible();
  checked('列表错误明确显示且可重试');

  const item = page.getByRole('article', { name: '合成反馈-1' });
  await item.locator('summary').click();
  await expect(item.getByText('未填写', { exact: true })).toBeVisible();
  await expect(item.getByText('未附带', { exact: true })).toBeVisible();
  await expect(item.getByText('第一行：换形象后没有反应。', { exact: false })).toBeVisible();
  state.patchFail = true;
  await item.getByRole('button', { name: '标记为处理中', exact: true }).click();
  await expect(item.getByRole('alert')).toContainText('合成保存失败');
  await expect(item.getByText('待处理', { exact: true })).toBeVisible();
  checked('详情按字段展示，未填写如实提示，状态失败保留正文与原状态');

  state.patchFail = false;
  let release;
  state.patchGate = new Promise(resolve => { release = resolve; });
  const beforePatches = state.patches;
  await item.getByRole('button', { name: '标记为处理中', exact: true }).click();
  await expect(item.getByRole('button', { name: '标记为处理中', exact: true })).toBeDisabled();
  release();
  await expect(page.getByText('已标记为处理中。', { exact: true })).toBeVisible();
  assert.equal(state.patches, beforePatches + 1);
  await expect(item).toHaveCount(0);
  checked('保存中禁止重复提交，服务端确认后移出旧状态列表');

  await page.getByLabel('处理状态', { exact: true }).selectOption('ALL');
  const allItem = page.getByRole('article', { name: '合成反馈-1' });
  await allItem.locator('summary').click();
  await allItem.getByRole('button', { name: '标记为已解决', exact: true }).click();
  await expect(allItem.getByText('tester@example.invalid', { exact: true })).toBeVisible();
  await expect(allItem.getByText('Windows', { exact: true })).toBeVisible();
  await expect(allItem.getByText('已解决', { exact: true })).toBeVisible();
  checked('全部筛选保留已更新条目，联系和诊断信息按独立字段展示');

  await page.getByLabel('处理状态', { exact: true }).selectOption('NEW');
  state.mode = 'page-error';
  await page.getByRole('button', { name: '加载下一页', exact: true }).click();
  await expect(page.locator('.notice[role="alert"]')).toContainText('合成加载失败');
  await expect(page.getByRole('heading', { name: '合成反馈-1' })).toBeVisible();
  state.mode = 'list';
  await page.getByRole('button', { name: '重新加载', exact: true }).click();
  await expect(page.getByRole('heading', { name: '合成反馈-2' })).toBeVisible();
  assert.ok(state.queries.some(value => value.includes('cursor=opaque-synthetic-cursor')));
  checked('不透明游标分页，下一页失败保留原页，重试成功追加');

  await page.getByRole('article', { name: '合成反馈-1' }).locator('summary').click();
  for (const width of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect(page.getByRole('heading', { name: '反馈中心', exact: true })).toBeVisible();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, `${width}px横向溢出`);
    await page.screenshot({ path: path.join(output, `feedback-${width}.png`), fullPage: true });
  }
  checked('320/390/768/1440px内容与长文本无横向溢出');
  await context.close();

  const denied = await fixture();
  denied.state.mode = 'forbidden';
  await denied.page.goto(`${origin}/admin/feedback`);
  await expect(denied.page.locator('.notice[role="alert"]')).toContainText('无权读取反馈');
  await expect(denied.page.getByRole('article')).toHaveCount(0);
  await denied.context.close();
  checked('服务端拒绝时只显示错误，不伪造收件内容');
  assert.deepEqual(errors, []);
  await writeFile(path.join(output, 'report.json'), JSON.stringify({ checks, pageErrors: errors }, null, 2));
  console.log(`反馈中心验收通过：${checks.length}组，全部使用合成数据。`);
} finally { await browser.close(); }
