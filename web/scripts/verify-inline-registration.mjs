// 仅连接本地页面；所有 API 均为合成响应，不发送真实邮件或创建真实账号。
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const origin = process.env.WEB_URL ?? 'http://localhost:3122';
assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(new URL(origin).hostname));
const output = path.join(root, 'data/verification/inline-registration-2026-10-21/browser');
await mkdir(output, { recursive: true });
const { chromium, expect } = await import(pathToFileURL(path.join(root, 'web/frontend/node_modules/@playwright/test/index.mjs')).href);
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const checks = [], pageErrors = [];
const checked = text => { checks.push(text); console.log(`通过：${text}`); };
const user = { id: 'synthetic-user', email: 'synthetic@example.invalid', displayName: '新朋友', emailVerified: true, role: 'USER', status: 'ACTIVE' };

async function fixture({ localMailbox = false, cooldown = 60 } = {}) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const state = { sent: [], registrations: [], signedIn: false, rejectCode: true, hold: false, release: undefined, holdRegistration: false, releaseRegistration: undefined, sequence: 0, badReceipt: undefined };
  await context.route('**/api/v1/**', async route => {
    const request = route.request(), pathname = new URL(request.url()).pathname;
    const reply = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
    const error = (code, message, status = 400) => reply({ error: { code, message } }, status);
    if (pathname === '/api/v1/auth/config') return reply({ data: { password: { minLength: 10, maxLength: 128 }, email: { mode: localMailbox ? 'LOCAL_MAILBOX' : 'SMTP', inboxUrl: localMailbox ? 'http://localhost:8025' : '' } } });
    if (pathname === '/api/v1/auth/csrf') return reply({ data: { token: 'synthetic-csrf' } });
    if (pathname === '/api/v1/me') return state.signedIn ? reply({ data: user }) : error('UNAUTHENTICATED', '请登录', 401);
    if (pathname === '/api/v1/auth/registration-codes') {
      assert.equal(request.headers()['x-csrf-token'], 'synthetic-csrf');
      state.sent.push(request.postDataJSON());
      if (state.hold) await new Promise(resolve => { state.release = resolve; });
      if (state.badReceipt !== undefined) return reply({ data: state.badReceipt }, 202);
      return reply({ data: { challengeId: `00000000-0000-4000-8000-${String(++state.sequence).padStart(12, '0')}`, expiresAt: new Date(Date.now() + 600000).toISOString(), resendAt: new Date(Date.now() + cooldown * 1000).toISOString() } }, 202);
    }
    if (pathname === '/api/v1/auth/registrations') {
      assert.equal(request.headers()['x-csrf-token'], 'synthetic-csrf');
      state.registrations.push(request.postDataJSON());
      if (state.holdRegistration) await new Promise(resolve => { state.releaseRegistration = resolve; });
      if (state.rejectCode) return error('REGISTRATION_CODE_INVALID', '验证码无效');
      state.signedIn = true;
      return reply({ data: user }, 201);
    }
    if (pathname === '/api/v1/auth/login') { state.signedIn = true; return reply({ data: user }); }
    if (pathname === '/api/v1/auth/password-resets') return reply({ data: {} }, 202);
    return error('SYNTHETIC_NOT_FOUND', '合成接口未定义', 404);
  });
  const page = await context.newPage();
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.goto(`${origin}/register?returnTo=${encodeURIComponent('/docs?from=registration')}`);
  await expect(page.getByRole('button', { name: '获取验证码', exact: true })).toBeEnabled();
  return { context, page, state };
}

try {
  {
    const { context, page, state } = await fixture();
    await expect(page.getByLabel('昵称', { exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: '获取验证码', exact: true }).click();
    await expect(page.getByText('请输入有效的邮箱地址。')).toBeVisible();
    assert.equal(state.sent.length, 0);
    await page.getByLabel('邮箱', { exact: true }).fill('synthetic@example.invalid');
    await page.getByRole('button', { name: '获取验证码', exact: true }).click();
    await expect(page.getByText(/验证码邮件已排队发送至/)).toBeVisible();
    assert.deepEqual(state.sent, [{ email: 'synthetic@example.invalid' }]);
    await expect(page.getByRole('button', { name: /秒后重发/ })).toBeDisabled();
    checked('取码无需密码、仅发送邮箱、错误就近提示且服务端时间控制重发');
    await page.getByLabel('邮件验证码', { exact: true }).fill('１２３４５６');
    await page.getByLabel('设置密码', { exact: true }).fill('Synthetic-password-42');
    await page.getByRole('button', { name: '注册并登录', exact: true }).click();
    await expect(page.getByText('请输入邮件中的 6 位数字验证码。')).toBeVisible();
    assert.equal(state.registrations.length, 0);
    await page.getByLabel('邮件验证码', { exact: true }).fill('012345');
    await page.getByRole('button', { name: '注册并登录', exact: true }).click();
    await expect(page.getByText('验证码错误或已失效，请检查后重试，或重新获取。')).toBeVisible();
    await expect(page.getByLabel('设置密码', { exact: true })).toHaveValue('Synthetic-password-42');
    await expect(page.getByLabel('邮件验证码', { exact: true })).toHaveValue('012345');
    assert.equal(state.registrations[0].code, '012345');
    checked('仅接受 6 位 ASCII 数字，保留前导零，服务端错码后保留全部输入');
    await page.getByRole('button', { name: '显示密码', exact: true }).click();
    await expect(page.getByLabel('设置密码', { exact: true })).toHaveAttribute('type', 'text');
    await page.getByRole('button', { name: '隐藏密码', exact: true }).click();
    await expect(page.getByLabel('设置密码', { exact: true })).toHaveAttribute('type', 'password');
    for (const width of [320, 390, 768, 1440]) {
      await page.setViewportSize({ width, height: 1100 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);
      await page.screenshot({ path: path.join(output, `register-${width}.png`), fullPage: true });
    }
    checked('密码显隐、自动填充属性和 320/390/768/1440 布局无横向溢出');
    state.rejectCode = false;
    state.holdRegistration = true;
    await page.getByRole('button', { name: '注册并登录', exact: true }).click();
    await expect.poll(() => state.registrations.length).toBe(2);
    await expect(page.getByRole('button', { name: '正在注册并登录…', exact: true })).toBeDisabled();
    await page.locator('main form').evaluate(form => {
      form.requestSubmit();
      form.requestSubmit();
    });
    assert.equal(state.registrations.length, 2);
    state.releaseRegistration();
    await expect(page).toHaveURL(`${origin}/docs?from=registration`);
    await expect(page.locator('.nav-account-desktop')).toContainText('新朋友');
    checked('注册期间防重复提交；成功先同步真实会话查询，再返回 returnTo，导航立即显示账号');
    await context.close();
  }
  {
    const { context, page, state } = await fixture();
    state.hold = true;
    await page.getByLabel('邮箱', { exact: true }).fill('old@example.invalid');
    await page.getByLabel('设置密码', { exact: true }).fill('Synthetic-password-42');
    await page.getByRole('button', { name: '获取验证码', exact: true }).click();
    await expect.poll(() => state.sent.length).toBe(1);
    await expect(page.getByRole('button', { name: '正在发送…', exact: true })).toBeDisabled();
    await page.getByLabel('邮箱', { exact: true }).fill('new@example.invalid');
    state.release();
    await expect(page.getByRole('button', { name: '获取验证码', exact: true })).toBeEnabled();
    await expect(page.getByText(/验证码邮件已排队发送至/)).toHaveCount(0);
    await expect(page.getByLabel('设置密码', { exact: true })).toHaveValue('Synthetic-password-42');
    await page.getByRole('button', { name: '注册并登录', exact: true }).click();
    await expect(page.getByText('请先获取邮箱验证码。')).toBeVisible();
    assert.equal(state.registrations.length, 0);
    state.hold = false;
    await page.getByRole('button', { name: '获取验证码', exact: true }).click();
    await expect(page.getByText(/验证码邮件已排队发送至 new@example.invalid/)).toBeVisible();
    assert.equal(state.sent.length, 2);
    checked('发送期间防重复；编辑邮箱隔离旧响应、旧挑战与提示，密码保留');
    await context.close();
  }
  {
    const { context, page, state } = await fixture();
    await page.getByLabel('邮箱', { exact: true }).fill('synthetic@example.invalid');
    await page.getByLabel('设置密码', { exact: true }).fill('Synthetic-password-42');
    await page.getByLabel('邮件验证码', { exact: true }).fill('012345');
    const valid = { challengeId: '00000000-0000-4000-8000-000000000001', expiresAt: new Date(Date.now() + 600000).toISOString(), resendAt: new Date(Date.now() + 60000).toISOString() };
    const malformed = [null, {}, { ...valid, challengeId: 'invalid-uuid' }, { ...valid, resendAt: 'invalid-date' }, { ...valid, expiresAt: valid.resendAt }];
    for (const receipt of malformed) {
      state.badReceipt = receipt;
      await page.getByRole('button', { name: '获取验证码', exact: true }).click();
      await expect(page.getByText('验证码请求结果无效，请重新获取。')).toBeVisible();
      await expect(page.getByRole('button', { name: '获取验证码', exact: true })).toBeEnabled();
      await expect(page.getByLabel('设置密码', { exact: true })).toHaveValue('Synthetic-password-42');
      await expect(page.getByLabel('邮件验证码', { exact: true })).toHaveValue('012345');
      await expect(page.getByText(/验证码邮件已排队发送至/)).toHaveCount(0);
      await page.getByRole('button', { name: '注册并登录', exact: true }).click();
      await expect(page.getByText('请先获取邮箱验证码。')).toBeVisible();
      assert.equal(state.registrations.length, 0);
    }
    state.badReceipt = undefined;
    await page.getByRole('button', { name: '获取验证码', exact: true }).click();
    await expect(page.getByText(/验证码邮件已排队发送至/)).toBeVisible();
    checked('丢失/坏 UUID/无效 ISO/冲突时间收据被拒绝，保留输入、不锁重发且不提交注册');
    await context.close();
  }
  {
    const { context, page, state } = await fixture({ cooldown: 1, localMailbox: true });
    await page.getByLabel('邮箱', { exact: true }).fill('synthetic@example.invalid');
    await page.getByRole('button', { name: '获取验证码', exact: true }).click();
    await expect(page.getByText(/邮件内含.*6.*位验证码/)).toBeVisible();
    await page.getByLabel('邮件验证码', { exact: true }).fill('000001');
    await expect(page.getByRole('button', { name: '重新获取', exact: true })).toBeEnabled({ timeout: 5000 });
    await page.getByRole('button', { name: '重新获取', exact: true }).click();
    await expect(page.getByLabel('邮件验证码', { exact: true })).toHaveValue('');
    await page.getByLabel('邮件验证码', { exact: true }).fill('000002');
    await page.getByLabel('设置密码', { exact: true }).fill('Synthetic-password-42');
    await page.getByRole('button', { name: '注册并登录', exact: true }).click();
    await expect.poll(() => state.registrations.length).toBe(1);
    assert.equal(state.registrations[0].challengeId, '00000000-0000-4000-8000-000000000002');
    checked('本地收件提示为验证码；重发清旧码并使用最新 challenge 提交');
    await page.goto(`${origin}/login?returnTo=%2Fdocs`);
    await expect(page.getByLabel('密码', { exact: true })).toHaveAttribute('autocomplete', 'current-password');
    await page.getByRole('link', { name: '忘记密码？', exact: true }).click();
    await expect(page.getByRole('heading', { name: '找回密码', exact: true })).toBeVisible();
    await page.getByLabel('邮箱', { exact: true }).fill('synthetic@example.invalid');
    await page.getByRole('button', { name: '发送邮件', exact: true }).click();
    await expect(page.getByText(/如邮箱符合条件，验证邮件会进入下方本地收件箱/)).toBeVisible();
    checked('原登录和找回密码入口、邮件流程继续可用');
    await context.close();
  }
  assert.deepEqual(pageErrors, []);
} finally {
  await browser.close();
  await writeFile(path.join(output, 'report.json'), JSON.stringify({ checks, pageErrors }, null, 2));
}
