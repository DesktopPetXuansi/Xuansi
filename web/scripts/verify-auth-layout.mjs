// 真实浏览器验收：只用隔离本机服务、随机测试账号和合成密码，不读取用户会话。
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const origin = process.env.WEB_URL ?? 'http://localhost:3100';
const mail = process.env.MAILPIT_URL ?? 'http://127.0.0.1:8125';
assert.equal(origin, 'http://localhost:3100');
assert.equal(mail, 'http://127.0.0.1:8125');
// 非默认SMTP端口的本机Mailpit会被服务报告为SMTP；核对本轮隔离启动清单而不放宽旧脚本守卫。
const services = JSON.parse(await readFile(path.join(root, 'data/verification/personal-space-2026-10-19/services.json'), 'utf8'));
assert.equal(services.web_url, origin);
assert.equal(services.mailbox_url, mail);
assert.equal(services.smtp_port, 1125);
assert.match(services.database, /^personal_space_ui_/);
assert.ok((await fetch(`${mail}/api/v1/messages`)).ok, '隔离本机收件箱未就绪');
const config = (await (await fetch(`${origin}/api/v1/auth/config`)).json()).data;
const output = path.join(root, 'data/verification/auth-layout-2026-10-19');
await mkdir(output, { recursive: true });
const { chromium, expect } = await import(pathToFileURL(path.join(root, 'web/frontend/node_modules/@playwright/test/index.mjs')).href);
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const report = { checks: [], screenshots: [], layouts: [], consoleErrors: [] };
const counts = { login: 0, register: 0, reset: 0 };
page.on('pageerror', error => report.consoleErrors.push(error.message));
page.on('request', request => {
  if (request.method() !== 'POST') return;
  const endpoint = new URL(request.url()).pathname;
  if (endpoint === '/api/v1/auth/login') counts.login++;
  if (endpoint === '/api/v1/auth/register') counts.register++;
  if (endpoint === '/api/v1/auth/password-resets/confirm') counts.reset++;
});
const checked = name => { report.checks.push(name); console.log(`通过：${name}`); };
const submit = () => page.locator('button[type=submit]');
const field = name => page.locator(`[name="${name}"]`);

async function invalid(name, message) {
  await expect(field(name)).toHaveAttribute('aria-invalid', 'true');
  const describedBy = await field(name).getAttribute('aria-describedby');
  assert.ok(describedBy, `${name} 缺少错误说明关联`);
  const ids = describedBy.split(/\s+/);
  let associated = false;
  for (const id of ids) {
    const explanation = page.locator(`[id="${id}"]`);
    if ((await explanation.textContent())?.includes(message)) associated = true;
  }
  assert.ok(associated, `${name} 的错误说明没有关联到字段`);
  await expect(page.getByText(message, { exact: true })).toBeVisible();
}

async function noMailHelp() {
  await expect(page.getByRole('link', { name: '打开本地收件箱', exact: true })).toHaveCount(0);
  await expect(page.getByRole('link', { name: '重新发送验证邮件', exact: true })).toHaveCount(0);
}

async function emailLink(email, purpose = 'verify-email') {
  // 仅打开本轮合成地址自己的邮件，不输出正文、密码或一次性链接。
  for (let attempt = 0; attempt < 70; attempt++) {
    const listing = await (await fetch(`${mail}/api/v1/messages`)).json();
    const messages = listing.messages?.filter(item => item.To?.some(recipient => recipient.Address === email)) ?? [];
    for (const message of messages) {
      const content = await (await fetch(`${mail}/api/v1/message/${message.ID}`)).json();
      const expression = new RegExp(`https?:\\/\\/[^\\s<>]+\\/${purpose}\\?token=[A-Za-z0-9_-]+`);
      const link = content.Text?.match(expression)?.[0];
      if (link) {
        assert.equal(new URL(link).origin, origin);
        return link;
      }
    }
    await page.waitForTimeout(200);
  }
  assert.fail('隔离worker没有投递本轮操作邮件');
}

try {
  for (const width of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto(`${origin}/login`);
    await expect(submit()).toBeEnabled();
    await noMailHelp();
    const inputBox = await field('email').boundingBox();
    const buttonBox = await submit().boundingBox();
    assert.ok(inputBox && buttonBox);
    assert.ok(Math.abs(inputBox.width - buttonBox.width) <= 2, `${width}px 登录按钮未与输入框同宽`);
    assert.ok(Math.abs(inputBox.x - buttonBox.x) <= 2, `${width}px 登录按钮未与输入框对齐`);
    const sizes = await page.evaluate(() => ({ content: document.documentElement.scrollWidth, viewport: window.innerWidth }));
    assert.ok(sizes.content <= sizes.viewport, `${width}px 出现横向溢出`);
    for (const item of await page.locator('.panel').getByRole('link').all()) {
      const bounds = await item.boundingBox();
      if (bounds) assert.ok(bounds.height >= 44, '表单辅助链接触摸区域小于44px');
    }
    const filename = `login-${width}.png`;
    await page.screenshot({ path: path.join(output, filename), fullPage: true });
    report.screenshots.push(filename);
    report.layouts.push({ width, inputWidth: inputBox.width, buttonWidth: buttonBox.width, overflow: sizes.content - sizes.viewport });
    checked(`${width}px 按钮对齐全宽、无横向溢出，空表单截图`);
  }

  const synthetic = 'synthetic-Password-Not-A-User';
  await field('password').fill(synthetic);
  const show = page.getByRole('button', { name: '显示密码', exact: true });
  await expect(show).toHaveAttribute('type', 'button');
  await expect(show).toHaveAttribute('aria-controls', await field('password').getAttribute('id'));
  await expect(show).toHaveAttribute('aria-pressed', 'false');
  await show.click();
  await expect(field('password')).toHaveAttribute('type', 'text');
  const hide = page.getByRole('button', { name: '隐藏密码', exact: true });
  await expect(hide).toHaveAttribute('aria-pressed', 'true');
  await hide.focus();
  await page.keyboard.press('Space');
  await expect(field('password')).toHaveAttribute('type', 'password');
  assert.ok(await field('password').inputValue() === synthetic, '显示切换丢失了合成输入值');
  assert.equal(counts.login, 0, '切换密码意外提交了表单');
  checked('密码显示/隐藏支持鼠标和键盘，值保留，状态可访问且不提交');

  await field('password').fill('');
  await submit().click();
  await invalid('email', '请输入有效的邮箱地址。');
  await invalid('password', '请输入密码。');
  await field('email').fill('not-an-email');
  await field('password').fill('old');
  await submit().click();
  await invalid('email', '请输入有效的邮箱地址。');
  assert.equal(counts.login, 0);
  await field('email').fill(`auth-error-${randomBytes(6).toString('hex')}@example.invalid`);
  await submit().click();
  await expect(page.locator('form').getByRole('alert')).toContainText('邮箱或密码不正确');
  assert.equal(counts.login, 1, '登录对旧短密码添加了注册门槛');
  checked('登录空值、邮箱错误关联字段，错误凭据由服务端提示，兼容旧短密码');

  const destination = '/dashboard/history';
  await page.goto(`${origin}/login?returnTo=${encodeURIComponent(destination)}`);
  await page.getByRole('link', { name: '创建账号', exact: true }).click();
  await page.waitForURL(url => url.pathname === '/register');
  assert.equal(new URL(page.url()).searchParams.get('returnTo'), destination);
  await noMailHelp();
  const email = `auth-layout-${randomBytes(8).toString('hex')}@example.invalid`;
  const password = randomBytes(18).toString('hex');
  await field('email').fill(email);
  await field('displayName').fill('登录布局验收');
  for (const value of ['a', '字'.repeat(config.password.minLength - 1), '🐱'.repeat(config.password.minLength - 1)]) {
    await field('password').fill(value);
    await submit().click();
    await invalid('password', `密码至少 ${config.password.minLength} 个字符。`);
  }
  assert.equal(counts.register, 0);
  checked('注册保留原目标，未提交前无邮件帮助，字符/中文/Emoji规则与服务端一致');
  await field('password').fill(password);
  await submit().click();
  await expect(page.getByText('账号已创建', { exact: false })).toBeVisible();
  assert.equal(counts.register, 1);
  await expect(page.getByRole('link', { name: '重新发送验证邮件', exact: true })).toBeVisible();
  const returnLogin = page.getByRole('link', { name: '返回登录', exact: true });
  const loginHref = await returnLogin.getAttribute('href');
  assert.equal(new URL(loginHref, origin).searchParams.get('returnTo'), destination);
  await page.goto(await emailLink(email));
  await page.getByRole('button', { name: '确认验证邮箱', exact: true }).click();
  await expect(page.getByText('邮箱验证完成', { exact: false })).toBeVisible();
  await page.goto(new URL(loginHref, origin).href);
  await field('email').fill(email);
  await field('password').fill(password);
  await submit().click();
  await page.waitForURL(`${origin}${destination}`);
  await expect(page.getByLabel('个人空间导航', { exact: true })).toBeVisible();
  await page.goto(`${origin}/dashboard/account`);
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await page.waitForURL(`${origin}/`);
  checked('真实UI注册→本轮邮件→验证→登录返回目标→退出首页完整闭环');

  await page.goto(`${origin}/reset-password?token=auth-layout-not-a-real-token`);
  await field('password').fill('a'.repeat(config.password.minLength - 1));
  await submit().click();
  await invalid('password', `密码至少 ${config.password.minLength} 个字符。`);
  assert.equal(counts.reset, 0);
  await expect(page.getByRole('button', { name: '显示密码', exact: true })).toBeVisible();
  checked('重设密码复用服务端规则与可访问密码控件，不提交无效密码');

  await page.goto(`${origin}/forgot-password?returnTo=${encodeURIComponent(destination)}`);
  await field('email').fill(email);
  await submit().click();
  await expect(page.getByText('如邮箱符合条件', { exact: false })).toBeVisible();
  const resetLink = new URL(await emailLink(email, 'reset-password'));
  // 验证重置页接收原站内目标时继续保留；邮件token始终来自本轮真实worker。
  resetLink.searchParams.set('returnTo', destination);
  await page.goto(resetLink.href);
  const replacement = randomBytes(18).toString('hex');
  await field('password').fill(replacement);
  await submit().click();
  await expect(page.getByText('密码已更新，请使用新密码登录。', { exact: true })).toBeVisible();
  await expect(page.locator('form')).toHaveCount(0);
  const resetLogin = page.getByRole('link', { name: '返回登录', exact: true });
  assert.equal(new URL(await resetLogin.getAttribute('href'), origin).searchParams.get('returnTo'), destination);
  await resetLogin.click();
  await field('email').fill(email);
  await field('password').fill(replacement);
  await submit().click();
  await page.waitForURL(`${origin}${destination}`);
  await page.goto(`${origin}/dashboard/account`);
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await page.waitForURL(`${origin}/`);
  checked('真实找回邮件→重置成功隐藏表单→返回原目标→新密码登录闭环');

  // 仅隔离当前context的显示配置；真实投递仍由1125端口Mailpit捕获。
  await page.route('**/api/v1/auth/config', route => route.fulfill({ json: {
    data: { password: config.password, email: { mode: 'LOCAL_MAILBOX', inboxUrl: `${mail}/` } },
  } }));
  await page.goto(`${origin}/login`);
  await noMailHelp();
  await page.goto(`${origin}/forgot-password`);
  await noMailHelp();
  await field('email').fill(email);
  await submit().click();
  await expect(page.getByRole('link', { name: '打开本地收件箱', exact: true })).toHaveAttribute('href', `${mail}/`);
  await page.goto(`${origin}/verify-email`);
  await expect(page.getByRole('link', { name: '打开本地收件箱', exact: true })).toBeVisible();
  checked('本地收件箱按需出现：默认登录/找回无帮助，邮件发送后及验证页显示');
  await page.goto(`${origin}/register`);
  await noMailHelp();
  await field('email').fill(`auth-layout-mail-${randomBytes(8).toString('hex')}@example.invalid`);
  await field('displayName').fill('按需邮件帮助验收');
  await field('password').fill(randomBytes(18).toString('hex'));
  await submit().click();
  await expect(page.getByText('账号已创建', { exact: false })).toBeVisible();
  await expect(page.locator('form')).toHaveCount(0);
  await expect(page.getByRole('link', { name: '打开本地收件箱', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '重新发送验证邮件', exact: true })).toBeVisible();
  checked('本地邮箱模式注册成功后才显示邮件帮助，已完成表单不重复提交');
  assert.deepEqual(report.consoleErrors, []);
  checked('浏览器无未捕获异常');
} catch (error) {
  // Playwright的完整异常含字段快照；只保存简短错误，避免合成密码进入日志/报告。
  report.failure = error instanceof Error ? error.message.split('Call log:')[0] : '浏览器检查失败';
  console.error(report.failure);
  process.exitCode = 1;
} finally {
  await writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  await context.close();
  await browser.close();
}
