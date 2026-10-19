// 仅针对专用本机预览库：真实Qt提交后，以临时合成管理员验证Chrome收件与处理。
import assert from 'node:assert/strict';
import { createHash, randomBytes, randomUUID } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const evidence = path.join(root, 'data/verification/feedback-center-2026-10-19');
const origin = 'http://localhost:3100';
const database = 'personal_space_ui_20261019_a6210f';
const native = JSON.parse(await readFile(path.join(evidence, 'native/report.json'), 'utf8'));
assert.equal(native.passed, true);
const receipt = native.receipt;
assert.match(receipt.id, /^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/);
const psql = path.join(root, 'web/.runtime/tools/postgresql/pgsql/bin/psql.exe');
function sql(statement) {
  const result = spawnSync(psql, ['-X', '-w', '-h', '127.0.0.1', '-p', '54329', '-U', 'xuansi', '-d', database,
    '-v', 'ON_ERROR_STOP=1', '-qAt'], { input: statement, encoding: 'utf8', windowsHide: true, env: { ...process.env, PGPASSWORD: '' } });
  assert.equal(result.status, 0, '专用预览库操作失败');
  return result.stdout.trim();
}
assert.equal(sql(`SELECT title FROM feedback WHERE id='${receipt.id}';`), '合成验收：软件反馈中心');
const admin = randomUUID(), session = randomUUID(), token = randomBytes(32).toString('base64url');
const digest = createHash('sha256').update(token).digest('hex');
const output = path.join(evidence, 'delivery');
await mkdir(output, { recursive: true });
const { chromium, expect } = await import(pathToFileURL(path.join(root, 'web/frontend/node_modules/@playwright/test/index.mjs')).href);
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const errors = [], checks = [];
page.on('pageerror', error => errors.push(error.message));
try {
  // 只创建本轮随机身份与五分钟会话；不登录实际账号、不读取浏览器凭据或投递邮件。
  sql(`BEGIN;
    INSERT INTO users(id,email,password_hash,display_name,role,email_verified,quota_bytes)
      VALUES('${admin}','feedback-${admin}@example.invalid','synthetic-not-a-login','本机反馈验收管理员','ADMIN',true,1048576);
    INSERT INTO web_sessions(id,user_id,token_hash,expires_at) VALUES('${session}','${admin}','${digest}',now()+interval '5 minutes');
    COMMIT;`);
  const denied = await context.request.get(`${origin}/api/v1/admin/feedback`);
  assert.equal(denied.status(), 401);
  checks.push('匿名提交不会授予读取反馈的权限');
  await context.addCookies([{ name: 'xuansi_session', value: token, url: origin, httpOnly: true, sameSite: 'Lax' }]);
  const response = await context.request.get(`${origin}/api/v1/admin/feedback?status=NEW`);
  assert.equal(response.status(), 200);
  const stored = (await response.json()).data.find(item => item.id === receipt.id);
  assert.ok(stored && stored.diagnostics);
  assert.equal(Date.parse(stored.createdAt), Date.parse(receipt.createdAt)); // UTC和带偏移时间表示同一时刻。
  checks.push('客户端收据、真实数据库与管理员API为同一编号和时间');
  await page.goto(`${origin}/admin/feedback`);
  const article = page.getByRole('article', { name: '合成验收：软件反馈中心', exact: true });
  await expect(article).toBeVisible();
  await article.locator('summary').click();
  await expect(article).toContainText(stored.description);
  await expect(article).toContainText(stored.diagnostics.qtVersion);
  await page.screenshot({ path: path.join(output, 'admin-received.png'), fullPage: true });
  checks.push('真实Chrome后台显示软件提交的正文和自愿附带的版本信息');
  await article.getByRole('button', { name: '标记为处理中', exact: true }).click();
  await expect(article).toHaveCount(0);
  await page.getByRole('combobox', { name: '处理状态', exact: true }).selectOption('IN_PROGRESS');
  await expect(article).toBeVisible();
  assert.equal(sql(`SELECT status FROM feedback WHERE id='${receipt.id}';`), 'IN_PROGRESS');
  checks.push('点击处理状态经真实服务持久化，筛选列表同步更新');
  await page.setViewportSize({ width: 390, height: 844 });
  await article.locator('summary').click();
  await expect(article.getByRole('button', { name: '标记为已解决', exact: true })).toBeVisible();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await page.screenshot({ path: path.join(output, 'admin-mobile.png'), fullPage: true });
  assert.deepEqual(errors, []);
  checks.push('390px真实收件内容无水平溢出，无页面异常');
} finally {
  await browser.close();
  // 只清理本轮生成的身份、会话、审计与已确认的合成反馈，不碰其他测试或用户记录。
  sql(`BEGIN; DELETE FROM audit_logs WHERE actor_id='${admin}'; DELETE FROM web_sessions WHERE id='${session}' AND user_id='${admin}';
    DELETE FROM users WHERE id='${admin}' AND email='feedback-${admin}@example.invalid';
    DELETE FROM feedback WHERE id='${receipt.id}' AND title='合成验收：软件反馈中心'; COMMIT;`);
  await writeFile(path.join(output, 'report.json'), JSON.stringify({ passed: checks.length === 5 && errors.length === 0,
    checks, pageErrors: errors, syntheticRecordsCleaned: true }, null, 2));
}
console.log(JSON.stringify({ passed: true, checks, pageErrors: errors, syntheticRecordsCleaned: true }));
