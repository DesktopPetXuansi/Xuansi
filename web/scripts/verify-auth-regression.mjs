// 密码边界、表单与后端规则一致、本地邮件可发现；测试只写本机临时验收账号。
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const { chromium, expect } = await import(pathToFileURL(path.join(root, 'frontend/node_modules/@playwright/test/index.mjs')).href);
const origin = process.env.WEB_URL ?? 'http://localhost:3000';
assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(new URL(origin).hostname));
// 提前拒绝真实 SMTP，避免回归测试把随机账号邮件投递到外网。
const authConfigResponse = await fetch(`${origin}/api/v1/auth/config`);
assert.ok(authConfigResponse.ok, '无法读取邮件验收配置');
const { data: authConfig } = await authConfigResponse.json();
assert.equal(authConfig.email.mode, 'LOCAL_MAILBOX', '浏览器验收需要 Mailpit 配置；当前使用真实 SMTP，已停止，未创建验收账号或发送邮件');
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const context = await browser.newContext();
const page = await context.newPage();
const errors = [];
page.on('pageerror', (error) => errors.push(error.message));
let registrations = 0;
let passwordUpdates = 0;
page.on('request', (request) => {
  if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/v1/auth/register') registrations++;
  if (request.method() === 'PUT' && new URL(request.url()).pathname === '/api/v1/me/password') passwordUpdates++;
});
try {
  await page.goto(`${origin}/register`);
  await expect(page.getByText('12 至 128 个字符。', { exact: true })).toBeVisible({ timeout: 5000 });
  const email = `auth-regression-${Date.now()}@example.invalid`;
  await page.locator('[name=email]').fill(email);
  await page.locator('[name=displayName]').fill('密码规则回归');
  for (const password of ['a'.repeat(10), 'a'.repeat(11), '字'.repeat(11), '🐱'.repeat(11)]) {
    await page.locator('[name=password]').fill(password);
    await page.getByRole('button', { name: '创建账号', exact: true }).click();
    await expect(page.getByText('密码至少 12 个字符。', { exact: true })).toBeVisible();
    assert.equal(registrations, 0, '短密码被提交到服务端');
  }
  console.log('通过：注册提示和ASCII/中文/Emoji短密码校验一致');
  await expect(page.getByRole('link', { name: '打开本地收件箱', exact: true })).toHaveCount(0);
  const password = randomBytes(6).toString('hex');
  await page.locator('[name=password]').fill(password);
  await page.getByRole('button', { name: '创建账号', exact: true }).click();
  await expect(page.getByText('账号已创建', { exact: false })).toBeVisible();
  const mailbox = page.getByRole('link', { name: '打开本地收件箱', exact: true });
  await expect(mailbox).toHaveAttribute('href', 'http://127.0.0.1:8025/');
  await expect(page.getByText('验证邮件会进入本地收件箱，不会发送到真实邮箱。', { exact: true })).toBeVisible();
  assert.equal(registrations, 1);
  console.log('通过：12字符密码实际注册成功，页面明确显示本地收件入口');

  // 只读取本次测试自己收到的邮件，邮件正文和一次性链接不会打印。
  let confirmation;
  for (let attempt = 0; attempt < 30; attempt++) {
    const listing = await (await context.request.get('http://127.0.0.1:8025/api/v1/messages')).json();
    const item = listing.messages?.find((message) => message.To?.some((recipient) => recipient.Address === email));
    if (item) {
      const message = await (await context.request.get(`http://127.0.0.1:8025/api/v1/message/${item.ID}`)).json();
      confirmation = message.Text?.match(/https?:\/\/[^\s<>]+\/verify-email\?token=[A-Za-z0-9_-]+/)?.[0];
      if (confirmation) break;
    }
    await page.waitForTimeout(300);
  }
  assert.ok(confirmation, '本地收件箱没有收到本次验证邮件');
  assert.equal(new URL(confirmation).origin, origin);
  await page.goto(confirmation);
  await page.getByRole('button', { name: '确认验证邮箱' }).click();
  await expect(page.getByText('邮箱验证完成', { exact: false })).toBeVisible();
  console.log('通过：真实worker投递邮件，验证链接可完成邮箱验证');

  await page.goto(`${origin}/login`);
  await page.locator('[name=email]').fill(email);
  await page.locator('[name=password]').fill(password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.waitForURL('**/dashboard');
  await page.goto(`${origin}/dashboard/account`);
  await expect(page.getByText('12 至 128 个字符。', { exact: true })).toBeVisible();
  await page.locator('[name=currentPassword]').fill(password);
  await page.locator('[name=password]').fill('a'.repeat(11));
  await page.getByRole('button', { name: '更新密码', exact: true }).click();
  await expect(page.getByText('密码至少 12 个字符。', { exact: true })).toBeVisible();
  assert.equal(passwordUpdates, 0, '账号设置提交了不符合规则的新密码');
  console.log('通过：账号设置与注册复用相同密码规则');
  // 退出测试账号，避免后续登录失败断言受已有会话影响。
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await page.waitForURL(`${origin}/`);

  await page.goto(`${origin}/reset-password?token=regression-not-a-real-token`);
  await expect(page.getByText('12 至 128 个字符。', { exact: true })).toBeVisible();
  await page.locator('[name=password]').fill('a'.repeat(11));
  await page.getByRole('button', { name: '更新密码', exact: true }).click();
  await expect(page.getByText('密码至少 12 个字符。', { exact: true })).toBeVisible();
  console.log('通过：密码恢复复用相同规则');

  // 登录只能验证非空；新密码规则不能阻止已有短密码账号发起登录。
  await page.goto(`${origin}/login`);
  await page.locator('[name=email]').fill(email);
  await page.locator('[name=password]').fill('old');
  const attempted = page.waitForRequest((request) => request.method() === 'POST' && new URL(request.url()).pathname === '/api/v1/auth/login');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await attempted;
  await expect(page.getByText('邮箱或密码不正确', { exact: true })).toBeVisible();
  // 模拟实际SMTP配置和不同密码门槛，证明文案没有固定在本地测试规则。
  await page.route('**/api/v1/auth/config', (route) => route.fulfill({
    json: { data: { password: { minLength: 14, maxLength: 128 }, email: { mode: 'SMTP', inboxUrl: null } } },
  }));
  await page.goto(`${origin}/register`);
  await expect(page.getByText('14 至 128 个字符。', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '打开本地收件箱', exact: true })).toHaveCount(0);
  await page.locator('[name=email]').fill(email);
  await page.locator('[name=displayName]').fill('配置规则回归');
  await page.locator('[name=password]').fill('a'.repeat(13));
  await page.getByRole('button', { name: '创建账号', exact: true }).click();
  await expect(page.getByText('密码至少 14 个字符。', { exact: true })).toBeVisible();
  assert.equal(registrations, 1);
  assert.deepEqual(errors, []);
  console.log('通过：登录兼容、服务端规则动态生效、SMTP模式隐藏开发入口，浏览器无未捕获异常');
} finally {
  await context.close();
  await browser.close();
}
