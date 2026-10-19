// 真实 Chrome + Go + worker + 隔离 Mailpit，使用随机测试账号，不读取用户凭据。
import assert from 'node:assert/strict';
import { randomBytes, randomUUID } from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const origin = process.env.WEB_URL ?? 'http://localhost:3100';
const mail = process.env.MAILPIT_URL ?? 'http://127.0.0.1:8125';
for (const address of [origin, mail]) assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(new URL(address).hostname));
// 本轮启动器明确使用独立数据库及1125邮件捕获；非默认端口在现有API中标为SMTP。
assert.equal(origin, 'http://localhost:3100');
assert.ok((await fetch(`${mail}/api/v1/messages`)).ok, '独立 Mailpit 未就绪');
const output = path.join(root, 'data/verification/personal-space-2026-10-19/browser');
await mkdir(output, { recursive: true });
const { chromium, expect } = await import(pathToFileURL(path.join(root, 'web/frontend/node_modules/@playwright/test/index.mjs')).href);
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const report = { checks: [], screenshots: [], consoleErrors: [] };
page.on('pageerror', error => report.consoleErrors.push(error.message));
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const checked = name => { report.checks.push(name); console.log(`通过：${name}`); };

async function api(route, method = 'GET', data) {
  const headers = { Origin: origin };
  if (method !== 'GET') {
    const csrf = await (await context.request.get(`${origin}/api/v1/auth/csrf`)).json();
    headers['X-CSRF-Token'] = csrf.data.token;
    headers['Idempotency-Key'] = randomUUID();
  }
  const response = await context.request.fetch(`${origin}/api/v1${route}`, { method, data, headers });
  assert.ok(response.ok(), `${method} ${route.split('?')[0]} 返回 HTTP ${response.status()}`);
  return response.status() === 204 ? null : (await response.json()).data;
}

async function register(displayName) {
  const email = `personal-${randomBytes(8).toString('hex')}@example.invalid`;
  const password = randomBytes(18).toString('hex');
  await api('/auth/register', 'POST', { email, password, displayName });
  let token;
  for (let attempt = 0; attempt < 70 && !token; attempt++) {
    const listing = await (await fetch(`${mail}/api/v1/messages`)).json();
    const message = listing.messages?.find(item => item.To?.some(to => to.Address === email));
    if (message) {
      const content = await (await fetch(`${mail}/api/v1/message/${message.ID}`)).json();
      token = content.Text?.match(/\/verify-email\?token=([A-Za-z0-9_-]+)/)?.[1];
    }
    if (!token) await delay(200);
  }
  assert.ok(token, '隔离 worker 未投递本次验证邮件');
  await api('/auth/email-verifications/confirm', 'POST', { token });
  return { email, password, displayName };
}

async function login(user) {
  await page.goto(`${origin}/login`);
  await page.locator('[name=email]').fill(user.email);
  await page.locator('[name=password]').fill(user.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.waitForURL('**/dashboard');
  await expect(page.locator('.nav-account-desktop')).toContainText(user.displayName);
  await expect(page.getByRole('heading', { name: '我的桌宠', exact: true })).toBeVisible();
}

async function nativeSync() {
  const child = spawn(path.join(root, '.venv/Scripts/python.exe'), [path.join(root, 'web/scripts/verify-client-history.py')], {
    cwd: root, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'], env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  });
  child.stdin.end(JSON.stringify({ origin }));
  let buffer = '', consent, result;
  child.stderr.on('data', () => {});
  child.stdout.on('data', part => {
    buffer += part.toString();
    const lines = buffer.split(/\r?\n/); buffer = lines.pop();
    for (const line of lines) {
      if (line.startsWith('__QA_AUTHORIZE__')) {
        consent = (async () => {
          await page.goto(line.slice('__QA_AUTHORIZE__'.length));
          await expect(page.getByRole('button', { name: '允许同步形象历史', exact: true })).toBeVisible();
          await expect(page.getByText('历史同步与删除：', { exact: false })).toBeVisible();
          await page.getByRole('button', { name: '允许同步形象历史', exact: true }).click();
        })();
        consent.catch(() => child.kill());
      } else if (line.startsWith('__QA_RESULT__')) result = JSON.parse(line.slice('__QA_RESULT__'.length));
    }
  });
  const timeout = setTimeout(() => child.kill(), 75000);
  try {
    const code = await new Promise((resolve, reject) => { child.on('error', reject); child.on('close', resolve); });
    await consent;
    assert.equal(code, 0, '客户端 PKCE/历史同步未完成');
    assert.equal(result?.synced, 1);
    return result;
  } finally { clearTimeout(timeout); if (child.exitCode === null) child.kill(); }
}

try {
  await page.goto(`${origin}/dashboard/history`);
  await expect(page.getByRole('link', { name: '登录后继续', exact: true })).toBeVisible();
  await expect(page.getByLabel('个人空间导航', { exact: true })).toHaveCount(0);
  checked('未登录可访问公共内容，个人历史显示登录入口');
  const userA = await register('形象历史验收甲');
  const userB = await register('形象历史验收乙');
  await login(userA);
  await expect(page.getByText('还没有同步的形象。', { exact: true })).toBeVisible();
  await page.screenshot({ path: path.join(output, 'empty-1440.png'), fullPage: true });
  checked('登录立即显示昵称、我的桌宠与真实空状态');

  const sync = await nativeSync();
  checked('真实客户端 PKCE 同意、同步去重、默认不补传、账号隔离与关闭同步');
  for (let i = 0; i < 25; i++) {
    await api(`/me/history/${randomUUID()}`, 'PUT', { kind: 'APPEARANCE', appearanceKind: 'DEFAULT',
      resourceId: null, resourceVersionId: null, name: `历史验收-${String(i).padStart(2, '0')}`,
      occurredAt: new Date(Date.now() - (i + 1) * 60000).toISOString(), deviceLabel: '隔离测试设备' });
  }
  await page.goto(`${origin}/dashboard`);
  await expect(page.locator('.companion-name')).toHaveText('同步验收形象');
  await expect(page.getByRole('heading', { name: '最近同步的形象' })).toBeVisible();
  for (const width of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect(page.locator('.companion-name')).toBeVisible();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, `个人空间在${width}px横向溢出`);
    const file = `companion-${width}.png`; await page.screenshot({ path: path.join(output, file), fullPage: true });
    report.screenshots.push(file);
  }
  checked('我的桌宠显示实际同步结果，320/390/768/1440px无横向溢出');
  await page.goto(`${origin}/dashboard/history`);
  await expect(page.locator('.history-row')).toHaveCount(20);
  await page.getByRole('button', { name: '加载更多', exact: true }).click();
  await expect(page.locator('.history-row')).toHaveCount(26);
  await page.getByRole('button', { name: '删除 同步验收形象 的记录', exact: true }).click();
  await expect(page.locator('.history-row')).toHaveCount(25);
  assert.ok(!(await api('/me/history')).some(item => item.id === sync.id));
  checked('真实历史稳定分页及单条删除');

  // 用合成PNG验证成功下载，避免真实模型、文件或屏幕进入测试。
  const png = spawnSync(path.join(root, '.venv/Scripts/python.exe'), ['-c', "from PIL import Image;import io,sys;b=io.BytesIO();Image.new('RGBA',(8,8),(50,110,60,255)).save(b,format='PNG');sys.stdout.buffer.write(b.getvalue())"], { windowsHide: true });
  assert.equal(png.status, 0);
  const resource = await api('/resources', 'POST', { kind: 'IMAGE', name: '历史联调图片', author: '隔离验收', license: 'CC0' });
  const created = await api(`/resources/${resource.id}/versions`, 'POST', { version: '1.0.0', filename: 'history.png', expectedBytes: png.stdout.length });
  const csrf = await api('/auth/csrf');
  const uploaded = await context.request.put(new URL(created.upload.url, origin).href, { headers: { ...created.upload.headers, Origin: origin, 'X-CSRF-Token': csrf.token }, data: png.stdout });
  assert.ok(uploaded.ok());
  await api(`/uploads/${created.upload.id}/completion`, 'POST', {});
  let ready = false;
  for (let attempt = 0; attempt < 60; attempt++) {
    const state = await api(`/uploads/${created.upload.id}`);
    if (state.status === 'READY') { ready = true; break; }
    assert.notEqual(state.status, 'FAILED', '测试图片校验失败'); await delay(200);
  }
  assert.ok(ready);
  const authorization = await api(`/resources/${resource.id}/versions/${created.version.id}/download-authorizations`, 'POST', {});
  assert.equal((await api('/me/history?kind=DOWNLOAD')).length, 0);
  const download = await context.request.get(authorization.url); assert.ok(download.ok()); await download.body();
  await api(`/me/library/${resource.id}`, 'PUT', { pinnedVersionId: created.version.id });
  await page.goto(`${origin}/dashboard/history`);
  await page.getByRole('button', { name: '下载记录', exact: true }).click();
  await expect(page.locator('.history-row')).toHaveCount(1);
  await page.getByRole('link', { name: '查看 / 重新获取' }).click();
  await expect(page.locator(`[id="version-${created.version.id}"]`)).toBeVisible();
  checked('完整文件传输才记下载，重新获取定位到原版本');
  await page.goto(`${origin}/dashboard/library`);
  await expect(page.getByRole('heading', { name: '收藏', exact: true })).toBeVisible();
  await expect(page.getByText('历史联调图片', { exact: true })).toBeVisible();
  checked('收藏保持独立并展示真实账号资源');
  await page.goto(`${origin}/dashboard/history`);
  await page.getByRole('button', { name: '清空形象使用记录', exact: true }).click();
  await page.getByRole('button', { name: '确认清空', exact: true }).click();
  await expect(page.locator('.history-row')).toHaveCount(0);
  assert.equal((await api('/me/history?kind=DOWNLOAD')).length, 1);
  await api(`/resources/${resource.id}`, 'PATCH', { status: 'HIDDEN' });
  await page.getByRole('button', { name: '下载记录', exact: true }).click();
  await expect(page.getByText('资源已失效或当前不可访问，记录仍保留。', { exact: true })).toBeVisible();
  checked('按类别清空、保留下载和收藏、失效资源不伪造恢复');

  await page.goto(`${origin}/dashboard/account`);
  await page.getByRole('button', { name: '退出登录', exact: true }).click();
  await expect(page.locator('.nav-account-desktop')).toContainText('登录 / 注册');
  await login(userB);
  await expect(page.getByText('还没有同步的形象。', { exact: true })).toBeVisible();
  await page.goto(`${origin}/dashboard/library`);
  await expect(page.getByText('还没有收藏。', { exact: false })).toBeVisible();
  assert.equal(await page.getByText('历史联调图片', { exact: true }).count(), 0);
  checked('退出/切换账号即时更新身份，无上个账号历史或收藏缓存');
  assert.deepEqual(report.consoleErrors, []);
  checked('真实浏览器无页面脚本错误');
} finally {
  await writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  await context.close(); await browser.close();
}
