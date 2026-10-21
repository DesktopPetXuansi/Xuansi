// 真实首页 → 隔离 API/PostgreSQL → 管理员审核；仅使用合成数据，不启动投递 worker。
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const origin = process.env.WEB_URL ?? 'http://localhost:3121';
const database = 'xuansi_test_feedback_browser_20261021';
assert.ok(['localhost', '127.0.0.1'].includes(new URL(origin).hostname));
const psql = path.join(root, 'web/.runtime/tools/postgresql/pgsql/bin/psql.exe');
const output = path.join(root, 'data/verification/feedback-moderation-2026-10-21/delivery');
await mkdir(output, { recursive: true });
const { chromium, expect } = await import(pathToFileURL(path.join(root, 'web/frontend/node_modules/@playwright/test/index.mjs')).href);

// 固定回环地址及本轮独立测试库，拒绝从真实 .env 发现数据库目标。
function sql(query) {
  return execFileSync(psql, ['-h', '127.0.0.1', '-p', '54341', '-U', 'xuansi_feedback_test',
    '-d', database, '-X', '-A', '-t', '-v', 'ON_ERROR_STOP=1', '-c', query], { encoding: 'utf8' }).trim();
}
function checkedID(value) {
  assert.match(value, /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/);
  return value;
}
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const checks = [], errors = [], feedbackIDs = [];
let adminID;
let adminEmail;
const record = value => { checks.push(value); console.log(`通过：${value}`); };

try {
  const visitor = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  // 新建隔离浏览器上下文，所有访问限定本轮本机网站。
  await visitor.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
  const page = await visitor.newPage();
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`${origin}/#feedback`);
  const section = page.locator('#feedback');
  const description = section.getByLabel('问题或建议', { exact: true });
  const consent = section.getByRole('checkbox');
  await expect(consent).not.toBeChecked();
  const suffix = Date.now().toString(36);

  async function submit(text, publicly = false) {
    await description.fill(text);
    await section.getByLabel(/联系方式（选填）/).fill('synthetic-delivery@example.invalid');
    await consent.setChecked(publicly);
    const received = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/feedback' && response.request().method() === 'POST');
    await section.getByRole('button', { name: '提交反馈', exact: true }).click();
    const response = await received;
    assert.equal(response.status(), 201);
    const { data } = await response.json();
    checkedID(data.id);
    feedbackIDs.push(data.id);
    await expect(section.getByText('已收到，反馈正在私有待审核。你可以撤回或保存专属管理链接。', { exact: true })).toBeVisible();
    const link = await section.getByLabel('专属管理链接（请勿分享，持有者可撤回反馈）', { exact: true }).inputValue();
    assert.equal(new URL(link).search, '');
    return { id: data.id, link };
  }

  const privateFeedback = await submit(`合成联调：私有反馈 ${suffix}`);
  assert.equal(sql(`SELECT moderation_status FROM feedback WHERE id='${privateFeedback.id}'`), 'PENDING');
  assert.equal(sql("SELECT count(*) FROM jobs WHERE kind='FEEDBACK_GITHUB'"), '0');
  assert.equal(sql(`SELECT length(management_token_hash) FROM feedback WHERE id='${privateFeedback.id}'`), '64');
  record('真实首页匿名提交保存到 PostgreSQL，未授权内容保持私有且无投递任务');

  // 刷新并通过本浏览器预保存的独立凭据恢复，验证服务端真正擦除敏感字段。
  const manage = await visitor.newPage();
  manage.on('pageerror', error => errors.push(error.message));
  await manage.goto(`${origin}/feedback/manage`);
  await manage.reload();
  await manage.getByRole('button', { name: '查看最新状态', exact: true }).click();
  await expect(manage.getByText('反馈正在私有待审核，尚未公开。', { exact: true })).toBeVisible();
  await manage.getByRole('button', { name: '撤回反馈', exact: true }).click();
  await expect(manage.getByText('已撤回，站内正文及联系方式已清理。', { exact: true })).toBeVisible();
  assert.equal(sql(`SELECT moderation_status||':'||(title='')::int||':'||(description='')::int||':'||(contact='')::int||':'||(diagnostics IS NULL)::int FROM feedback WHERE id='${privateFeedback.id}'`), 'WITHDRAWN:1:1:1:1');
  record('刷新后恢复管理权限，匿名撤回确实清理数据库正文、联系与诊断');

  const published = await submit(`合成联调：审核后公开 ${suffix}`, true);
  const admin = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  async function mutation(route, data) {
    const csrf = await (await admin.request.get(`${origin}/api/v1/auth/csrf`)).json();
    return admin.request.post(`${origin}/api/v1${route}`, { data, headers: { Origin: origin, 'X-CSRF-Token': csrf.data.token } });
  }
  const email = `feedback-${suffix}@example.invalid`;
  adminEmail = email;
  const password = 'synthetic-feedback-validation-only-2026';
  const registration = await mutation('/auth/register', { email, password, displayName: '合成反馈验收管理员' });
  assert.equal(registration.status(), 201);
  adminID = checkedID((await registration.json()).data.id);
  sql(`UPDATE users SET role='ADMIN',email_verified=true WHERE id='${adminID}'`);
  assert.equal((await mutation('/auth/login', { email, password })).status(), 200);
  const adminPage = await admin.newPage();
  adminPage.on('pageerror', error => errors.push(error.message));
  await adminPage.goto(`${origin}/admin/feedback`);
  const item = adminPage.getByRole('article', { name: `合成联调：审核后公开 ${suffix}`, exact: true });
  await item.locator('summary').click();
  await item.getByRole('button', { name: '审核通过并排队公开', exact: true }).click();
  await expect(item.getByText(/审核状态：已审核/)).toBeVisible();
  assert.equal(sql(`SELECT moderation_status FROM feedback WHERE id='${published.id}'`), 'APPROVED');
  assert.equal(sql("SELECT count(*) FROM jobs WHERE kind='FEEDBACK_GITHUB'"), '1');
  record('真实管理员界面批准后才生成唯一 GitHub 投递任务');

  // 本验收不启动 worker，不向真实 GitHub 建单；排队期间仍应能完整撤回。
  await manage.goto(published.link);
  await manage.getByRole('button', { name: '撤回反馈', exact: true }).click();
  await expect(manage.getByText('已撤回，站内正文及联系方式已清理。', { exact: true })).toBeVisible();
  assert.equal(sql(`SELECT moderation_status FROM feedback WHERE id='${published.id}'`), 'WITHDRAWN');
  record('已审核但尚未出网的反馈仍可凭匿名管理链接完整撤回');
  await page.reload();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('#feedback').scrollIntoViewIfNeeded();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await page.screenshot({ path: path.join(output, 'real-home-feedback-390.png'), fullPage: true });
  await adminPage.screenshot({ path: path.join(output, 'real-admin-feedback.png'), fullPage: true });
  assert.deepEqual(errors, []);
  record('真实联调页面无脚本异常，390px 无横向溢出');
} finally {
  await browser.close();
  // 只清理本脚本创建的合成记录，保留库中其他测试及用户数据。
  for (const id of feedbackIDs) {
    sql(`DELETE FROM jobs WHERE kind='FEEDBACK_GITHUB' AND payload->>'feedbackId'='${checkedID(id)}'`);
    sql(`DELETE FROM feedback WHERE id='${id}'`);
  }
  if (adminID) {
    sql(`DELETE FROM jobs WHERE kind='MAIL' AND payload->>'to'='${adminEmail}'`);
    sql(`DELETE FROM audit_logs WHERE actor_id='${checkedID(adminID)}'`);
    sql(`DELETE FROM web_sessions WHERE user_id='${adminID}'`);
    sql(`DELETE FROM account_tokens WHERE user_id='${adminID}'`);
    sql(`DELETE FROM users WHERE id='${adminID}'`);
  }
}
await writeFile(path.join(output, 'report.json'), JSON.stringify({ origin, database, checks, pageErrors: errors, externalGitHubWrites: 0, cleanupCompleted: true }, null, 2));
