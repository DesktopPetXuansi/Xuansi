// 真实浏览器、PostgreSQL、邮件、worker与客户端闭环；测试秘密仅驻留内存/子进程stdin。
import assert from 'node:assert/strict';
import { randomBytes, randomUUID, createHash } from 'node:crypto';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { verifyAdmin } from './platform-admin-checks.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const project = path.dirname(root);
const { chromium } = await import(pathToFileURL(path.join(root, 'frontend/node_modules/@playwright/test/index.mjs')).href);
const origin = process.env.WEB_URL ?? 'http://localhost:3000';
const mail = process.env.MAIL_URL ?? 'http://127.0.0.1:8025';
// 验收会写入账号和私有资源，只允许本机服务。
for (const address of [origin, mail]) {
  assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(new URL(address).hostname), '集成验收仅允许回环开发服务');
}
const fixture = path.join(root, '.runtime/fixtures');
await mkdir(path.join(root, '.runtime/screenshots'), { recursive: true });
const completionKeys = new Map();
const report = { checks: [], versions: [], browserErrors: [] };
const email = `qa-${Date.now()}@example.invalid`;
const password = `Local-${randomBytes(24).toString('hex')}`;
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
page.on('pageerror', (error) => report.browserErrors.push(error.message));

// 只记录断言名，不输出令牌、邮件正文、请求体或会话Cookie。
function checked(label) { report.checks.push(label); console.log(`通过：${label}`); }
const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
async function api(request, route, method = 'GET', payload) {
  const headers = {};
  if (method !== 'GET') {
    const response = await request.get(`${origin}/api/v1/auth/csrf`);
    const body = await response.json();
    headers['X-CSRF-Token'] = body.data.token;
    headers.Origin = origin;
    if (route.endsWith('/completion')) {
      if (!completionKeys.has(route)) completionKeys.set(route, randomUUID());
      headers['Idempotency-Key'] = completionKeys.get(route);
    }
  }
  const response = await request.fetch(`${origin}/api/v1${route}`, { method, headers, data: payload });
  if (!response.ok()) {
    const body = await response.json().catch(() => ({}));
    throw new Error(`接口未通过：${route} ${response.status()} ${body.error?.code ?? ''}`);
  }
  return response.status() === 204 ? null : (await response.json()).data;
}
async function verificationLink(targetEmail, purpose = 'verify-email') {
  for (let attempt = 0; attempt < 40; attempt++) {
    const listing = await (await fetch(`${mail}/api/v1/messages`)).json();
    for (const item of listing.messages ?? []) {
      if (!(item.To ?? []).some((recipient) => recipient.Address === targetEmail)) continue;
      const message = await (await fetch(`${mail}/api/v1/message/${item.ID}`)).json();
      const pattern = new RegExp(`https?:\\/\\/[^\\s"<>]+\\/${purpose}\\?token=[A-Za-z0-9_-]+`);
      const match = `${message.Text ?? ''} ${message.HTML ?? ''}`.match(pattern);
      if (match) return match[0];
    }
    await delay(500);
  }
  throw new Error('开发邮件服务未收到验证链接');
}
async function upload(resource, filename, targetModelVersionId) {
  const bytes = await readFile(path.join(fixture, filename));
  const created = await api(context.request, `/resources/${resource.id}/versions`, 'POST', {
    version: '1.0.0', filename, expectedBytes: bytes.length, targetModelVersionId,
    entrypoint: resource.kind === 'MODEL' ? 'xuansi.model3.json' : undefined,
  });
  const csrf = await api(context.request, '/auth/csrf');
  const put = await context.request.put(new URL(created.upload.url, origin).href, {
    headers: { ...created.upload.headers, 'X-CSRF-Token': csrf.token, Origin: origin }, data: bytes,
  });
  assert.ok(put.ok(), '上传原始文件失败');
  await api(context.request, `/uploads/${created.upload.id}/completion`, 'POST', {});
  // 重新完成同一个意图必须返回同一上传，不应创建重复版本。
  const repeated = await api(context.request, `/uploads/${created.upload.id}/completion`, 'POST', {});
  assert.equal(repeated.id, created.upload.id);
  for (let attempt = 0; attempt < 60; attempt++) {
    const state = await api(context.request, `/uploads/${created.upload.id}`);
    if (state.status === 'FAILED') throw new Error(`资源校验失败：${resource.kind} ${state.errorCode}`);
    if (state.status === 'READY') {
      await api(context.request, `/resources/${resource.id}`, 'PATCH', { currentVersionId: created.version.id });
      await api(context.request, `/me/library/${resource.id}`, 'PUT', { pinnedVersionId: created.version.id });
      const manifest = await api(context.request, `/resources/${resource.id}/versions/${created.version.id}/manifest`);
      assert.equal(manifest.resourceVersionId, created.version.id);
      const authorization = await api(context.request, `/resources/${resource.id}/versions/${created.version.id}/download-authorizations`, 'POST', {});
      const downloaded = await context.request.get(new URL(authorization.url, origin).href);
      assert.ok(downloaded.ok());
      const content = await downloaded.body();
      assert.equal(content.length, authorization.bytes);
      assert.equal(createHash('sha256').update(content).digest('hex'), authorization.sha256);
      const version = { resourceId: resource.id, resourceVersionId: created.version.id, kind: resource.kind };
      report.versions.push(version);
      checked(`${resource.kind}：上传、幂等完成、worker、清单和真实下载摘要`);
      return version;
    }
    await delay(500);
  }
  throw new Error('资源校验超时');
}
async function runChild(executable, args, data) {
  const child = spawn(executable, args, { cwd: project, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'], env: { ...process.env, PYTHONIOENCODING: 'utf-8' } });
  child.stdin.end(JSON.stringify(data));
  let output = '';
  let buffer = '';
  let authorization;
  // 由真实 Python 客户端创建随机回环监听与 PKCE；浏览器代替系统浏览器操作。
  // 授权 URL 只用于 IPC，不写入输出或报告。
  child.stdout.on('data', (part) => {
    buffer += part.toString();
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop();
    for (const line of lines) {
      if (line.startsWith('__QA_AUTHORIZE__')) {
        authorization = (async () => {
          await page.goto(line.slice('__QA_AUTHORIZE__'.length));
          await page.getByRole('button', { name: '允许读取资源' }).click();
          await page.getByText('授权处理完成，请返回桌宠。', { exact: true }).waitFor();
        })();
        authorization.catch(() => child.kill());
      } else if (line.startsWith('客户端验收：') || line.startsWith('客户端验收失败：')) {
        output += `${line}\n`;
      }
    }
  });
  child.stderr.on('data', (part) => {
    output += part.toString().split(/\r?\n/).filter((line) => line.startsWith('客户端验收失败：')).join('\n');
  });
  const timeout = setTimeout(() => child.kill(), 120000);
  const code = await new Promise((resolve, reject) => { child.on('error', reject); child.on('close', resolve); });
  clearTimeout(timeout);
  if (authorization) await authorization.catch(() => { throw new Error('浏览器客户端授权流程失败'); });
  assert.ok(authorization, '客户端未发起系统浏览器授权');
  if (code !== 0) throw new Error('原生客户端验收失败，请检查 SDK 与测试资源');
  console.log(output.split(/\r?\n/).filter((line) => line.startsWith('客户端验收：')).join('\n'));
}

try {
  await page.goto(`${origin}/register`);
  await page.locator('input[name=email]').fill(email);
  await page.locator('input[name=password]').fill(password);
  await page.locator('input[name=displayName]').fill('本地验收账号');
  await page.getByRole('button', { name: '创建账号' }).click();
  await page.getByText('账号已创建', { exact: false }).waitFor({ timeout: 20000 });
  checked('浏览器注册（真实 PostgreSQL）');
  await page.goto(await verificationLink(email));
  await page.getByRole('button', { name: '确认验证邮箱' }).click();
  await page.getByText('邮箱验证完成', { exact: false }).waitFor();
  checked('真实 SMTP 邮件与一次性邮箱验证');
  await page.goto(`${origin}/login`);
  await page.locator('input[name=email]').fill(email);
  await page.locator('input[name=password]').fill(password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.waitForURL('**/dashboard');
  checked('浏览器登录和工作台');

  await page.goto(`${origin}/dashboard/resources/new`);
  await page.getByLabel('资源名称', { exact: true }).fill('验收专用图片');
  await page.locator('select[name=kind]').selectOption('IMAGE');
  await page.getByLabel('作者', { exact: true }).fill('开发验收');
  await page.getByLabel('使用许可', { exact: false }).fill('CC0（本机生成验收图片）');
  await page.getByRole('button', { name: '保存资料' }).click();
  await page.waitForURL(/\/dashboard\/resources\/[a-f0-9-]+$/);
  const imageId = new URL(page.url()).pathname.split('/').at(-1);
  const image = await api(context.request, `/resources/${imageId}`);
  assert.equal(image.visibility, 'PRIVATE');
  checked('浏览器创建个人私有资源');
  await page.getByLabel('版本号', { exact: true }).fill('1.0.0');
  await page.locator('input[name=file]').setInputFiles(path.join(fixture, 'plain.png'));
  await page.getByRole('button', { name: '上传并校验' }).click();
  await page.getByText('文件校验完成', { exact: false }).waitFor({ timeout: 45000 });
  checked('浏览器真实文件上传与后台状态轮询');
  await page.reload();
  await page.locator('input[name=name]').fill('验收专用图片（已编辑）');
  await page.getByRole('button', { name: '保存资料' }).click();
  await page.getByText('资源资料已保存。', { exact: true }).waitFor();
  assert.equal((await api(context.request, `/resources/${imageId}`)).name, '验收专用图片（已编辑）');
  checked('浏览器编辑资源资料并持久保存');
  const imageVersions = await api(context.request, `/resources/${imageId}/versions`);
  await api(context.request, `/me/library/${imageId}`, 'PUT', { pinnedVersionId: imageVersions[0].id });
  report.versions.push({ resourceId: imageId, resourceVersionId: imageVersions[0].id, kind: 'IMAGE' });
  await page.screenshot({ path: path.join(root, '.runtime/screenshots/resource-editor.png'), fullPage: true });

  const second = await browser.newContext();
  const secondEmail = `other-${Date.now()}@example.invalid`;
  await api(second.request, '/auth/register', 'POST', { email: secondEmail, password, displayName: '第二验收用户' });
  await api(second.request, '/auth/login', 'POST', { email: secondEmail, password });
  const denied = await second.request.get(`${origin}/api/v1/resources/${image.id}`);
  assert.ok([403, 404].includes(denied.status()), '跨用户读取私有资源未被拒绝');
  await second.close();
  checked('两个用户的私有资源隔离');

  const create = (kind) => api(context.request, '/resources', 'POST', {
    kind, name: `验收专用${kind}`, description: '本机真实资源链路测试', author: '开发验收',
    license: '仅本地验收，不公开分发', source: '', tags: ['本地验收'],
  });
  const model = await upload(await create('MODEL'), 'model.zip');
  await upload(await create('MOTION'), 'test.motion3.json', model.resourceVersionId);
  await upload(await create('EXPRESSION'), 'test.exp3.json', model.resourceVersionId);
  await upload(await create('ANIMATION'), 'plain.gif');
  await runChild(path.join(project, '.venv/Scripts/python.exe'), ['web/scripts/verify-client-api.py'], { origin, versions: report.versions });
  checked('真实 Python PKCE、随机回环端口、浏览器显式同意与 Go 令牌兑换');
  checked('真实客户端 API 下载、安装、SDK动作表情与离线恢复');
  checked('客户端授权撤销立即阻止新访问');
  await verifyAdmin({ project, email, page, browser, origin, api, request: context.request,
    image, imageVersion: imageVersions[0].id, checked });
  await page.goto(`${origin}/forgot-password`);
  await page.locator('input[name=email]').fill(email);
  await page.getByRole('button', { name: '发送邮件' }).click();
  await page.getByText('如邮箱符合条件', { exact: false }).waitFor();
  const newPassword = `Reset-${randomBytes(24).toString('hex')}`;
  await page.goto(await verificationLink(email, 'reset-password'));
  await page.locator('input[name=password]').fill(newPassword);
  await page.getByRole('button', { name: '更新密码' }).click();
  await page.getByText('密码已更新', { exact: false }).waitFor();
  assert.equal((await context.request.get(`${origin}/api/v1/me`)).status(), 401);
  await page.goto(`${origin}/login`);
  await page.locator('input[name=email]').fill(email);
  await page.locator('input[name=password]').fill(newPassword);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.waitForURL('**/dashboard');
  checked('浏览器密码恢复、旧会话失效与新密码登录');
  assert.deepEqual(report.browserErrors, []);
  checked('完整工作台流程无未捕获浏览器异常');
} finally {
  await mkdir(path.join(root, '.runtime'), { recursive: true });
  await writeFile(path.join(root, '.runtime/integration-report.json'), JSON.stringify(report, null, 2));
  await context.close();
  await browser.close();
}
