// 密码边界、表单与后端规则一致、本地邮件可发现；测试只写本机临时验收账号。
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const { chromium, expect } = await import(pathToFileURL(path.join(root, 'frontend/node_modules/@playwright/test/index.mjs')).href);
const origin = process.env.WEB_URL ?? 'http://localhost:3123';
const mail = process.env.MAILPIT_URL ?? 'http://127.0.0.1:8126';
assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(new URL(origin).hostname));
// 只允许本轮固定隔离清单中的 loopback Mailpit，不能将 SMTP 模式当作放行条件。
const services = JSON.parse(await readFile(path.join(root, '../data/verification/inline-registration-2026-10-21/services.json'), 'utf8'));
assert.equal(origin, 'http://localhost:3123');
assert.equal(mail, 'http://127.0.0.1:8126');
assert.equal(services.webUrl, origin);
assert.equal(services.mailpitUrl, mail);
assert.equal(services.smtpHost, '127.0.0.1');
assert.equal(services.smtpPort, 1926);
assert.match(services.database, /^xuansi_test_inline_registration_browser_/);
const authConfigResponse = await fetch(`${origin}/api/v1/auth/config`);
assert.ok(authConfigResponse.ok, '无法读取邮件验收配置');
const { data: authConfig } = await authConfigResponse.json();
assert.equal(authConfig.email.mode, 'SMTP', '本轮非默认端口隔离 SMTP 配置发生变化，已停止');
assert.ok((await fetch(`${mail}/api/v1/messages`)).ok, '本轮隔离收件箱未就绪');
const output = path.join(root, '../data/verification/inline-registration-2026-10-21/auth-regression');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const context = await browser.newContext();
const page = await context.newPage();
const errors = [];
page.on('pageerror', (error) => errors.push(error.message));
let registrations = 0;
let passwordUpdates = 0;
const emails = [];
const report = { emails, consoleErrors: errors };
page.on('request', (request) => {
  if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/v1/auth/registrations') registrations++;
  if (request.method() === 'PUT' && new URL(request.url()).pathname === '/api/v1/me/password') passwordUpdates++;
});
try {
  // 只改变显示配置，真实邮件仍由已核验的隔离 Mailpit 接收。
  await page.route('**/api/v1/auth/config', route => route.fulfill({ json: { data: {
    ...authConfig, email: { mode: 'LOCAL_MAILBOX', inboxUrl: `${mail}/` },
  } } }));
  await page.goto(`${origin}/register`);
  await expect(page.getByText('12 至 128 个字符。', { exact: true })).toBeVisible({ timeout: 5000 });
  const email = `auth-regression-${Date.now()}@example.invalid`;
  emails.push(email);
  await page.locator('[name=email]').fill(email);
  await expect(page.locator('[name=displayName]')).toHaveCount(0);
  for (const password of ['a'.repeat(10), 'a'.repeat(11), '字'.repeat(11), '🐱'.repeat(11)]) {
    await page.locator('[name=password]').fill(password);
    await page.getByRole('button', { name: '注册并登录', exact: true }).click();
    await expect(page.getByText('密码至少 12 个字符。', { exact: true })).toBeVisible();
    assert.equal(registrations, 0, '短密码被提交到服务端');
  }
  console.log('通过：注册提示和ASCII/中文/Emoji短密码校验一致');
  await expect(page.getByRole('link', { name: '打开本地收件箱', exact: true })).toHaveCount(0);
  const password = randomBytes(6).toString('hex');
  await page.locator('[name=password]').fill(password);
  await page.getByRole('button', { name: '获取验证码', exact: true }).click();
  await expect(page.locator('form').getByRole('status')).toContainText(email);
  assert.equal(new URL(page.url()).pathname, '/register', '取码离开了注册页');
  assert.ok(await page.locator('[name=password]').inputValue() === password, '取码丢失密码输入');
  await expect(page.getByRole('button', { name: /秒后重发/ })).toBeDisabled();
  const mailbox = page.getByRole('link', { name: '打开本地收件箱', exact: true });
  await expect(mailbox).toHaveAttribute('href', `${mail}/`);
  await expect(page.getByText('验证邮件会进入本地收件箱，不会发送到真实邮箱。', { exact: true })).toBeVisible();
  assert.equal(registrations, 0, '取码不能提前注册');
  console.log('通过：原页取码、密码保留、重发冷却和本地收件入口');

  // 只读取本次测试自己收到的邮件，邮件正文和一次性链接不会打印。
  let code;
  for (let attempt = 0; attempt < 30; attempt++) {
    const listing = await (await context.request.get(`${mail}/api/v1/messages`)).json();
    const item = listing.messages?.find((message) => message.To?.some((recipient) => recipient.Address === email));
    if (item) {
      const message = await (await context.request.get(`${mail}/api/v1/message/${item.ID}`)).json();
      code = message.Text?.match(/你的注册验证码是：([0-9]{6})/)?.[1];
      if (code) break;
    }
    await page.waitForTimeout(300);
  }
  assert.ok(code, '本地收件箱没有收到本次验证码邮件');
  await page.locator('[name=code]').fill(code);
  await page.getByRole('button', { name: '注册并登录', exact: true }).click();
  await page.waitForURL('**/dashboard');
  assert.equal(registrations, 1);
  const me = await (await context.request.get(`${origin}/api/v1/me`)).json();
  assert.equal(me.data.emailVerified, true);
  assert.equal(me.data.displayName, '新朋友');
  console.log('通过：12字符密码和真实邮件验证码原页注册，自动进入已验证会话');
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
  await page.locator('[name=password]').fill('a'.repeat(13));
  await page.getByRole('button', { name: '注册并登录', exact: true }).click();
  await expect(page.getByText('密码至少 14 个字符。', { exact: true })).toBeVisible();
  assert.equal(registrations, 1);
  assert.deepEqual(errors, []);
  report.passed = true;
  console.log('通过：登录兼容、服务端规则动态生效、SMTP模式隐藏开发入口，浏览器无未捕获异常');
} catch (error) {
  report.failure = error instanceof Error ? error.message.split('Call log:')[0] : '浏览器检查失败';
  console.error(report.failure);
  process.exitCode = 1;
} finally {
  await writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  await context.close();
  await browser.close();
}
