// 隔离 Chrome 与 Mailpit 验收访客入口；测试密码、令牌只在内存中使用。
import assert from 'node:assert/strict';
import { randomBytes, randomUUID } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const origin = process.env.WEB_URL ?? 'http://localhost:3100';
const mail = process.env.MAILPIT_URL ?? 'http://127.0.0.1:8125';
assert.equal(origin, 'http://localhost:3100', '仅允许本轮隔离测试网站');
assert.equal(mail, 'http://127.0.0.1:8125', '仅允许本轮隔离 Mailpit');
const output = path.join(root, 'data/verification/visitor-entry-2026-10-19');
await mkdir(output, { recursive: true });
const { chromium, expect } = await import(pathToFileURL(path.join(root, 'web/frontend/node_modules/@playwright/test/index.mjs')).href);
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const report = { checks: [], screenshots: [], consoleErrors: [] };
page.on('pageerror', error => report.consoleErrors.push(error.message));
const checked = name => { report.checks.push(name); console.log(`通过：${name}`); };
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const noPrivateMenu = async target => {
  await expect(target.locator('aside[aria-label="个人空间导航"]')).toHaveCount(0);
  await expect(target.locator('aside[aria-label="管理后台导航"]')).toHaveCount(0);
};

async function api(route, method = 'GET', data) {
  const headers = { Origin: origin };
  if (method !== 'GET') {
    const csrf = await (await context.request.get(`${origin}/api/v1/auth/csrf`)).json();
    headers['X-CSRF-Token'] = csrf.data.token;
    headers['Idempotency-Key'] = randomUUID();
  }
  const response = await context.request.fetch(`${origin}/api/v1${route}`, { method, data, headers });
  assert.ok(response.ok(), `${method} ${route.split('?')[0]} HTTP ${response.status()}`);
  return response.status() === 204 ? null : (await response.json()).data;
}

async function register() {
  assert.ok((await fetch(`${mail}/api/v1/messages`)).ok, '隔离 Mailpit 未就绪');
  const user = { email: `visitor-${randomBytes(8).toString('hex')}@example.invalid`, password: randomBytes(18).toString('hex'), displayName: '访客入口验收' };
  await api('/auth/register', 'POST', user);
  let token;
  for (let attempt = 0; attempt < 70 && !token; attempt++) {
    const listing = await (await fetch(`${mail}/api/v1/messages`)).json();
    const message = listing.messages?.find(item => item.To?.some(to => to.Address === user.email));
    if (message) {
      const content = await (await fetch(`${mail}/api/v1/message/${message.ID}`)).json();
      token = content.Text?.match(/\/verify-email\?token=([A-Za-z0-9_-]+)/)?.[1];
    }
    if (!token) await delay(200);
  }
  assert.ok(token, '隔离 worker 未投递本次验证邮件');
  await api('/auth/email-verifications/confirm', 'POST', { token });
  return user;
}

async function login(user, destination) {
  await page.locator('[name=email]').fill(user.email);
  await page.locator('[name=password]').fill(user.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page).toHaveURL(`${origin}${destination}`);
}

async function logout() {
  await page.goto(`${origin}/dashboard/account`);
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await expect(page).toHaveURL(`${origin}/`);
  await expect(page.locator('.nav-account-desktop')).toContainText('登录 / 注册');
  await noPrivateMenu(page);
}

try {
  // 旧服务上先保留真实 RED，避免只在修改后证明脚本能跑。
  if (process.argv.includes('--baseline')) {
    await page.goto(origin);
    const homeLinks = await page.getByRole('navigation', { name: '主导航', exact: true }).getByRole('link', { name: '首页', exact: true }).count();
    await page.goto(`${origin}/dashboard/history`);
    await expect(page.getByText('后继续。', { exact: false })).toBeVisible();
    const anonymousSidebar = await page.locator('aside[aria-label="个人空间导航"]').count();
    report.baseline = { homeLinks, anonymousSidebar, expected: { homeLinks: 1, anonymousSidebar: 0 } };
    assert.equal(homeLinks, 0, '基线已变化，请重新确认运行版本');
    assert.equal(anonymousSidebar, 1, '基线已变化，请重新确认运行版本');
    checked('RED 已复现：首页无显式入口，未登录仍显示个人侧栏');
  } else {
    await page.goto(origin);
    await expect(page.getByRole('navigation', { name: '主导航', exact: true }).getByRole('link', { name: '首页', exact: true })).toBeVisible();
    await noPrivateMenu(page);
    await expect(page.locator('.nav-account-desktop')).toContainText('登录 / 注册');
    checked('匿名首页有明确首页导航，公开内容不显示个人菜单');

    const target = '/dashboard/history?kind=DOWNLOAD&from=visitor';
    await page.goto(`${origin}${target}`);
    await noPrivateMenu(page);
    await expect(page.getByRole('link', { name: '返回首页', exact: true })).toBeVisible();
    const loginLink = page.getByRole('link', { name: '登录后继续', exact: true });
    await expect(loginLink).toBeVisible();
    assert.equal(new URL(await loginLink.getAttribute('href'), origin).searchParams.get('returnTo'), target);
    assert.equal(new URL(await page.getByRole('link', { name: '创建账号', exact: true }).getAttribute('href'), origin).searchParams.get('returnTo'), target);
    for (const width of [320, 390, 1440]) {
      await page.setViewportSize({ width, height: 1000 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, `${width}px 横向溢出`);
      const filename = `anonymous-${width}.png`;
      await page.screenshot({ path: path.join(output, filename), fullPage: true });
      report.screenshots.push(filename);
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await loginLink.click();
    await page.getByRole('link', { name: '创建账号', exact: true }).click();
    assert.equal(new URL(page.url()).searchParams.get('returnTo'), target);
    await page.getByRole('link', { name: '返回登录', exact: true }).click();
    assert.equal(new URL(page.url()).searchParams.get('returnTo'), target);
    checked('访客登录/注册保留原路径与多参数，320/390/1440px 布局无溢出');

    const user = await register();
    await login(user, target);
    await expect(page.locator('aside[aria-label="个人空间导航"]')).toBeVisible();
    checked('真实注册、邮件验证、登录后返回原历史页面');
    await page.goto(`${origin}/admin/users`);
    await expect(page.getByText('你没有管理后台权限。', { exact: true })).toBeVisible();
    await noPrivateMenu(page);
    checked('普通账号访问后台不显示管理菜单');
    await logout();
    checked('退出回公开首页，昵称与个人菜单消失');

    await page.goto(`${origin}/admin/users`);
    await expect(page.getByRole('link', { name: '登录后继续', exact: true })).toBeVisible();
    await noPrivateMenu(page);
    checked('匿名访问后台也不泄露管理侧栏');

    // 挂起 /me 可确定性检查身份未决状态；503 则不能误判成未登录。
    const isolated = await browser.newContext();
    const pendingPage = await isolated.newPage();
    let releaseIdentity;
    const held = new Promise(resolve => { releaseIdentity = resolve; });
    await pendingPage.route('**/api/v1/me', async route => {
      await held;
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'TEMPORARY', message: '身份服务测试暂不可用' } }) });
    });
    try {
      await pendingPage.goto(`${origin}/dashboard/library`);
      await expect(pendingPage.getByText('正在检查登录状态…', { exact: true })).toBeVisible();
      await noPrivateMenu(pendingPage);
      releaseIdentity();
      await expect(pendingPage.getByText('身份服务测试暂不可用', { exact: true })).toBeVisible({ timeout: 20000 });
      await noPrivateMenu(pendingPage);
      await expect(pendingPage.getByRole('link', { name: '登录后继续', exact: true })).toHaveCount(0);
    } finally { releaseIdentity(); await isolated.close(); }
    checked('身份加载和 503 错误不暴露侧栏，错误不伪装成匿名');

    await page.goto(`${origin}/dashboard/library?from=visitor&tab=saved`);
    await page.getByRole('link', { name: '登录后继续', exact: true }).click();
    await login(user, '/dashboard/library?from=visitor&tab=saved');
    await logout();
    checked('收藏页登录返回同样保留原始查询参数');

    for (const malicious of ['//example.invalid/escape', '/\\example.invalid/escape', '/a/..//example.invalid/escape', '/.%2e//example.invalid/escape']) {
      await page.goto(`${origin}/login?returnTo=${encodeURIComponent(malicious)}`);
      await login(user, '/dashboard');
      assert.equal(new URL(page.url()).origin, origin);
      await logout();
    }
    checked('协议相对、反斜杠、普通及编码点段外站 returnTo 均安全回个人首页');

    const authorize = '/authorize?client_id=desktop-ai-pet&redirect_uri=http%3A%2F%2F127.0.0.1%3A45123%2Fcallback&scope=resources%3Aread%20history%3Aread&state=visitor%2Bstate&code_challenge=visitor-check&code_challenge_method=S256';
    await page.goto(`${origin}/login?returnTo=${encodeURIComponent(authorize)}`);
    await login(user, authorize);
    assert.equal(new URL(page.url()).search, new URL(authorize, origin).search);
    checked('OAuth 多参数授权目标经过登录保持完整，不自动授权');
    assert.deepEqual(report.consoleErrors, []);
    checked('真实浏览器无页面脚本错误');
  }
} finally {
  await writeFile(path.join(output, process.argv.includes('--baseline') ? 'baseline.json' : 'report.json'), JSON.stringify(report, null, 2));
  await context.close();
  await browser.close();
}
