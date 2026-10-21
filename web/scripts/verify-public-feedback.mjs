// 独立 Chrome 与完全合成 API：不读取真实会话，不接触后端或生产反馈。
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const origin = process.env.WEB_URL ?? 'http://localhost:3121';
assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(new URL(origin).hostname));
const output = path.join(root, 'data/verification/feedback-moderation-2026-10-21/browser');
await mkdir(output, { recursive: true });
const { chromium, expect } = await import(pathToFileURL(path.join(root, 'web/frontend/node_modules/@playwright/test/index.mjs')).href);
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const checks = [], pageErrors = [];
const checked = text => { checks.push(text); console.log(`通过：${text}`); };
const timestamp = '2026-10-21T04:00:00Z';
const item = (id, moderationStatus = 'PENDING', publicConsent = true) => ({
  id, category: 'OTHER', title: `合成反馈-${id}`, description: '合成正文，仅用于本地浏览器验收。', contact: '', diagnostics: null,
  status: 'NEW', moderationStatus, publicConsent, githubIssueUrl: moderationStatus === 'WITHDRAWAL_REQUESTED' ? 'https://example.invalid/issue/1' : '',
  createdAt: timestamp, updatedAt: timestamp,
});

async function fixture({ admin = false, blockedStorage = false } = {}) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, permissions: ['clipboard-read', 'clipboard-write'] });
  if (blockedStorage) await context.addInitScript(() => {
    Object.defineProperty(window, 'localStorage', { get() { throw new DOMException('Synthetic blocked storage', 'SecurityError'); } });
  });
  const state = { requests: [], managementCalls: 0, responseStatus: 200, badReceipt: false, moderationStatus: 'PENDING', canWithdraw: true, decisions: [], adminItems: [item('approve'), item('spam'), item('private', 'PENDING', false), item('withdraw', 'WITHDRAWAL_REQUESTED')] };
  await context.route('**/api/v1/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const reply = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
    const error = status => reply({ error: { code: status === 409 ? 'DUPLICATE_FEEDBACK' : 'SYNTHETIC_ERROR', message: `合成拒绝 ${status}` } }, status);
    if (url.pathname === '/api/v1/me') return admin ? reply({ data: { id: 'synthetic-admin', displayName: '合成管理员', email: 'test@example.invalid', emailVerified: true, role: 'ADMIN', status: 'ACTIVE' } }) : error(401);
    if (url.pathname === '/api/v1/auth/csrf') return reply({ data: { token: 'synthetic-csrf' } });
    if (url.pathname === '/api/v1/feedback' && request.method() === 'POST') {
      const body = request.postDataJSON();
      const key = request.headers()['idempotency-key'];
      state.requests.push({ key, body });
      if (state.responseStatus !== 200) return error(state.responseStatus);
      return reply({ data: { id: state.badReceipt ? '00000000-0000-4000-8000-000000000000' : key, status: 'NEW', createdAt: timestamp } }, 201);
    }
    const management = url.pathname.match(/^\/api\/v1\/feedback\/([^/]+)\/(management|withdrawal)$/);
    if (management) { state.managementCalls++;
      const credentials = state.requests.find(entry => entry.key === management[1]);
      assert.ok(credentials && request.postDataJSON().managementToken === credentials.body.managementToken, '管理操作必须携带当前反馈专属权限');
      if (management[2] === 'withdrawal') {
        state.moderationStatus = state.canWithdraw ? 'WITHDRAWN' : 'WITHDRAWAL_REQUESTED';
        state.canWithdraw = false;
      }
      return reply({ data: { id: management[1], createdAt: timestamp, status: 'NEW', moderationStatus: state.moderationStatus, githubIssueUrl: '', canWithdraw: state.canWithdraw } });
    }
    if (url.pathname === '/api/v1/admin/feedback') return reply({ data: state.adminItems, meta: { nextCursor: null } });
    const moderation = url.pathname.match(/^\/api\/v1\/admin\/feedback\/([^/]+)\/moderation$/);
    if (moderation) {
      const decision = request.postDataJSON().decision;
      state.decisions.push({ id: moderation[1], decision });
      const found = state.adminItems.find(row => row.id === moderation[1]);
      assert.ok(found);
      found.moderationStatus = decision === 'APPROVE' ? 'APPROVED' : decision === 'SPAM' ? 'SPAM' : 'WITHDRAWN';
      if (decision === 'CONFIRM_WITHDRAWAL') { found.title = ''; found.description = ''; }
      return reply({ data: found });
    }
    // 所有未定义 API 同样被拦截，不允许落到真实服务。
    return error(404);
  });
  const page = await context.newPage();
  page.on('pageerror', error => pageErrors.push(error.message));
  return { context, page, state };
}
const form = page => page.locator('#feedback');
async function fill(page, body = '合成问题：换形象后需要重新打开。') {
  await page.goto(origin);
  await form(page).getByRole('textbox', { name: '问题或建议', exact: true }).fill(body);
}
async function submit(page, retry = false) {
  await form(page).getByRole('button', { name: retry ? '重试这条反馈' : '提交反馈', exact: true }).click();
}

try {
  const layout = await fixture();
  await layout.page.goto(origin);
  await expect(form(layout.page).getByRole('textbox', { name: '问题或建议', exact: true })).toBeVisible();
  await expect(form(layout.page).getByRole('checkbox')).not.toBeChecked();
  for (const width of [320, 390, 768, 1440]) {
    await layout.page.setViewportSize({ width, height: 1000 });
    await form(layout.page).scrollIntoViewIfNeeded();
    assert.equal(await layout.page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, `${width}px首页无横向溢出`);
    await layout.page.screenshot({ path: path.join(output, `home-feedback-${width}.png`), fullPage: true });
  }
  assert.ok(await layout.page.locator('#feedback').evaluate(node => Boolean(node.closest('main') && document.querySelector('footer') && (node.compareDocumentPosition(document.querySelector('footer')) & Node.DOCUMENT_POSITION_FOLLOWING))));
  await layout.context.close();
  checked('首页页脚前直接输入、公开许可默认关闭，320/390/768/1440px无溢出');

  const retry = await fixture();
  await fill(retry.page, '😀'.repeat(90) + '\n合成后续说明');
  retry.state.responseStatus = 500;
  await submit(retry.page);
  await expect(form(retry.page).getByRole('alert')).toContainText('500');
  await expect(form(retry.page).getByRole('textbox', { name: '问题或建议', exact: true })).toHaveValue('😀'.repeat(90) + '\n合成后续说明');
  assert.equal(Array.from(retry.state.requests[0].body.title).length, 80);
  assert.equal(retry.state.requests[0].body.publicConsent, false);
  assert.match(retry.state.requests[0].body.managementToken, /^[a-f0-9]{64}$/);
  retry.state.responseStatus = 200;
  await submit(retry.page, true);
  await expect(form(retry.page).getByText('已收到，反馈正在私有待审核。你可以撤回或保存专属管理链接。')).toBeVisible();
  assert.ok(JSON.stringify(retry.state.requests[0]) === JSON.stringify(retry.state.requests[1]), '5xx重试必须保持相同key/token/body');
  await expect(form(retry.page).getByRole('textbox', { name: '问题或建议', exact: true })).toHaveValue('');
  await retry.page.goto(`${origin}/feedback/manage`);
  await retry.page.reload();
  await retry.page.getByRole('button', { name: '查看最新状态', exact: true }).click();
  await expect(retry.page.getByText('反馈正在私有待审核，尚未公开。', { exact: true })).toBeVisible();
  await retry.page.getByRole('button', { name: '撤回反馈', exact: true }).click();
  await expect(retry.page.getByText('已撤回，站内正文及联系方式已清理。', { exact: true })).toBeVisible();
  await retry.context.close();
  checked('Unicode标题截80字、5xx稳定幂等重试、成功清稿、刷新管理与未公开撤回');

  for (const status of [403, 409, 429]) {
    const rejected = await fixture();
    rejected.state.responseStatus = status;
    await fill(rejected.page);
    await submit(rejected.page);
    await expect(form(rejected.page).getByRole('alert')).toContainText(String(status));
    await expect(form(rejected.page).getByRole('textbox', { name: '问题或建议', exact: true })).toBeEnabled();
    await form(rejected.page).getByRole('textbox', { name: '问题或建议', exact: true }).fill('明确拒绝后可修改草稿');
    await rejected.context.close();
  }
  checked('403/409/429保留草稿且允许继续编辑');

  const invalid = await fixture();
  invalid.state.badReceipt = true;
  await fill(invalid.page, '错误收据不应该清掉此草稿');
  await submit(invalid.page);
  await expect(form(invalid.page).getByRole('alert')).toContainText('收据无法确认');
  await expect(form(invalid.page).getByRole('textbox', { name: '问题或建议', exact: true })).toHaveValue('错误收据不应该清掉此草稿');
  invalid.state.badReceipt = false;
  await submit(invalid.page, true);
  await expect(form(invalid.page).getByRole('textbox', { name: '问题或建议', exact: true })).toHaveValue('');
  assert.ok(invalid.state.requests[0].key === invalid.state.requests[1].key, '非法收据不改变幂等编号');
  invalid.state.moderationStatus = 'APPROVED';
  invalid.state.canWithdraw = false;
  await form(invalid.page).getByRole('button', { name: '查看最新状态', exact: true }).click();
  await form(invalid.page).getByRole('button', { name: '申请撤回公开内容', exact: true }).click();
  await expect(form(invalid.page).getByText(/撤回申请已收到/)).toBeVisible();
  await invalid.context.close();
  checked('错误收据留稿并复用key，已开始公开投递仍可申请撤回');

  const lost = await fixture();
  lost.state.responseStatus = 500;
  await fill(lost.page);
  await submit(lost.page);
  await expect(form(lost.page).getByRole('alert')).toBeVisible();
  await lost.page.goto(`${origin}/feedback/manage`);
  await lost.page.reload();
  await lost.page.getByRole('button', { name: '查看最新状态', exact: true }).click();
  await expect(lost.page.getByText('反馈正在私有待审核，尚未公开。', { exact: true })).toBeVisible();
  const priorManagementCalls = lost.state.managementCalls;
  await lost.page.goto(`${origin}/feedback/manage#id=broken-id&token=invalid`);
  await expect(lost.page.getByText(/管理链接无效或不完整/)).toBeVisible();
  await expect(lost.page.getByRole('button', { name: '查看最新状态', exact: true })).toHaveCount(0);
  await expect(lost.page.getByRole('button', { name: '撤回反馈', exact: true })).toHaveCount(0);
  assert.equal(lost.state.managementCalls, priorManagementCalls, '无效链接不得静默管理本机另一条反馈');
  await lost.context.close();
  checked('本机已有记录时，损坏管理链接不会回退其他记录或请求其管理权限');
  checked('响应未确认后刷新管理页，仍凭发送前保存的ID与权限恢复');

  const blocked = await fixture({ blockedStorage: true });
  await fill(blocked.page);
  await submit(blocked.page);
  await expect(form(blocked.page).getByText(/浏览器无法保存管理凭据/)).toBeVisible();
  const managementLink = await form(blocked.page).getByLabel('专属管理链接（请勿分享，持有者可撤回反馈）').inputValue();
  const url = new URL(managementLink);
  assert.equal(url.search, '');
  assert.ok(url.hash.includes('token='), '管理权限仅在fragment');
  await form(blocked.page).getByRole('button', { name: '复制管理链接', exact: true }).click();
  await expect(form(blocked.page).getByRole('button', { name: '已复制管理链接', exact: true })).toBeVisible();
  await blocked.page.goto(managementLink);
  await blocked.page.getByRole('button', { name: '查看最新状态', exact: true }).click();
  await expect(blocked.page.getByText('反馈正在私有待审核，尚未公开。', { exact: true })).toBeVisible();
  await blocked.context.close();
  checked('禁用localStorage时明确提示，仍可复制fragment链接并恢复管理');

  const admin = await fixture({ admin: true });
  await admin.page.goto(`${origin}/admin/feedback`);
  for (const row of admin.state.adminItems) await admin.page.getByRole('article', { name: row.title, exact: true }).locator('summary').click();
  const privateItem = admin.page.getByRole('article', { name: '合成反馈-private', exact: true });
  await expect(privateItem.getByRole('button', { name: '未授权公开', exact: true })).toBeDisabled();
  await expect(privateItem.getByRole('button', { name: '标记为处理中', exact: true })).toBeEnabled();
  await admin.page.getByRole('article', { name: '合成反馈-approve', exact: true }).getByRole('button', { name: '审核通过并排队公开', exact: true }).click();
  await expect(admin.page.getByRole('article', { name: '合成反馈-approve', exact: true }).getByText(/审核状态：已审核/)).toBeVisible();
  await admin.page.getByRole('article', { name: '合成反馈-spam', exact: true }).getByRole('button', { name: '标记为垃圾反馈', exact: true }).click();
  await expect(admin.page.getByRole('article', { name: '合成反馈-spam', exact: true }).getByText(/审核状态：垃圾反馈/)).toBeVisible();
  const withdrawal = admin.page.getByRole('article', { name: '合成反馈-withdraw', exact: true });
  await expect(withdrawal.getByRole('button', { name: '确认清理并完成撤回', exact: true })).toBeDisabled();
  await withdrawal.getByRole('checkbox').check();
  await withdrawal.getByRole('button', { name: '确认清理并完成撤回', exact: true }).click();
  await expect(admin.page.getByRole('heading', { name: '已撤回的反馈', exact: true })).toBeVisible();
  assert.equal(admin.state.decisions.length, 3);
  for (const width of [320, 390, 768, 1440]) {
    await admin.page.setViewportSize({ width, height: 1000 });
    assert.equal(await admin.page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, `${width}px管理员无横向溢出`);
    await admin.page.screenshot({ path: path.join(output, `moderation-${width}.png`), fullPage: true });
  }
  await admin.context.close();
  checked('管理员审批/垃圾、无许可禁用公开、人工清理确认与空标题占位，四种宽度无溢出');
  assert.deepEqual(pageErrors, []);
  await writeFile(path.join(output, 'report.json'), JSON.stringify({ checks, pageErrors, syntheticOnly: true }, null, 2));
  console.log(`公众反馈验收通过：${checks.length}组，所有API均由合成路由隔离。`);
} catch (failure) { console.error(String(failure.message).replace(/token=[a-f0-9]+/g, "token=[REDACTED]")); process.exitCode = 1; } finally { await browser.close(); }
