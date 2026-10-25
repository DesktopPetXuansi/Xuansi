// 独立 Chrome 验证新手路径；合成资源仅在浏览器拦截层提供，不写账号或资源库。
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const origin = process.env.WEB_URL ?? 'http://localhost:3100';
assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(new URL(origin).hostname), '仅允许本机测试');
const output = path.join(root, 'data/verification/public-site-2026-10-25-release-0.9.0');
await mkdir(output, { recursive: true });
const { chromium, expect } = await import(pathToFileURL(path.join(root, 'web/frontend/node_modules/@playwright/test/index.mjs')).href);
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
const page = await context.newPage();
const report = { passed: false, checks: [], errors: [], fixtures: '资源边界场景在浏览器内合成；截图来自本机真实空库页面' };
page.on('pageerror', error => report.errors.push(error.message));
const pass = name => { report.checks.push(name); console.log(`通过：${name}`); };

try {
  await page.goto(origin, { waitUntil: 'networkidle' });
  const navigation = page.getByRole('navigation', { name: '主导航', exact: true });
  assert.deepEqual(await navigation.locator('a').allTextContents(), ['首页', '挑选形象', '使用帮助', '下载客户端']);
  await page.locator('.hero').getByRole('link', { name: '下载 Windows 客户端' }).click();
  await expect(page).toHaveURL(`${origin}/download`);
  const download = page.locator('main').getByRole('link', { name: '下载 Windows 安装包', exact: true });
  await expect(download).toHaveAttribute('href', 'https://github.com/DesktopPetXuansi/Xuansi/releases/download/v0.9.0/Xuansi-0.9.0-windows-x64-setup.exe');
  await expect(page.locator('main')).not.toContainText('0.5.6');
  await expect(page.locator('main')).toContainText('不要求 D 盘');
  await expect(page.locator('main')).toContainText('Windows 10 1809');
  await expect(page.getByText('安装包来自项目官方 GitHub', { exact: false })).toBeHidden();
  await page.getByText('安装包校验与来源', { exact: true }).click();
  await expect(page.getByRole('link', { name: '查看 SHA256SUMS 校验文件' })).toBeVisible();
  pass('首页到单一正式版下载，系统条件与按需校验');

  // 下载页不依赖平台历史 API；平台离线仍能读官方入口和安装说明。
  const releaseRequests = [];
  await page.route('**/api/v1/client/releases?**', route => {
    releaseRequests.push(route.request().url());
    return route.fulfill({ status: 503, json: { error: { code: 'test', message: '合成平台离线' } } });
  });
  await page.reload({ waitUntil: 'networkidle' });
  assert.equal(releaseRequests.length, 0);
  await expect(download).toBeVisible();
  await page.unroute('**/api/v1/client/releases?**');
  pass('平台历史离线不阻塞官方下载');

  const topics = [
    ['getting-started', '第一次使用玄司'],
    ['appearance', '换一个桌宠形象'],
    ['chat', '让玄司开始聊天'],
    ['account', '登录后能做什么'],
    ['troubleshooting', '遇到问题怎么办'],
  ];
  for (const [slug, title] of topics) {
    await page.goto(`${origin}/docs`, { waitUntil: 'networkidle' });
    await page.locator('main').locator(`a[href="/docs/${slug}"]`).first().click();
    await expect(page).toHaveURL(`${origin}/docs/${slug}`);
    await expect(page.getByRole('heading', { level: 1, name: title, exact: true })).toBeVisible();
    await expect(page.locator('main article > ol > li')).toHaveCount(4);
    await expect(navigation.getByRole('link', { name: '使用帮助', exact: true })).toHaveAttribute('aria-current', 'page');
    const stepLink = page.getByRole('navigation', { name: '本页步骤' }).locator('a').last();
    await stepLink.click();
    assert.equal(new URL(page.url()).hash, '#step-4');
    await page.locator('main').getByRole('link', { name: '返回使用帮助' }).click();
    await expect(page.getByRole('heading', { level: 1, name: '你想先做什么？' })).toBeVisible();
  }
  const unknown = await page.goto(`${origin}/docs/does-not-exist`, { waitUntil: 'networkidle' });
  assert.equal(unknown.status(), 404);
  pass('五类帮助可从中心进入、步骤目录可跳转、未知主题404');

  await page.goto(`${origin}/faq`, { waitUntil: 'networkidle' });
  const question = page.locator('main summary').filter({ hasText: '下载了形象' });
  await question.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('link', { name: '按步骤更换形象', exact: true })).toBeVisible();
  await page.getByRole('link', { name: '按步骤更换形象', exact: true }).click();
  await expect(page).toHaveURL(`${origin}/docs/appearance`);
  pass('常见问题可由键盘展开并直接进入操作指南');

  await page.goto(`${origin}/resources`, { waitUntil: 'networkidle' });
  await page.getByRole('link', { name: '怎么更换形象' }).click();
  await expect(page).toHaveURL(`${origin}/docs/appearance`);
  await expect(page.locator('main')).toContainText('本地导入无需账号，也不用先上传');
  await expect(page.locator('main')).toContainText('网站的下载按钮会保存文件，不会直接更换桌宠');
  await expect(page.locator('main')).toContainText('使用这个形象');
  pass('形象库到本地导入、预览与实际使用的完整说明');

  // 不创建公开测试资源：只对这些 UUID 的 GET 和下载请求提供浏览器替身。
  const resourceId = 'f0ee0000-0000-4000-8000-000000000001';
  const base = `${origin}/api/v1/resources/${resourceId}`;
  const fixture = { id: resourceId, name: '合成验收形象', description: '仅浏览器内的验证数据', kind: 'MODEL', visibility: 'PUBLIC', author: '测试作者', license: '测试许可', tags: [], coverUrl: '/brand/front.png' };
  const version = (id, compatibilityStatus, validationStatus = 'READY') => ({ id, version: id, compatibilityStatus, validationStatus, entrypoint: 'test.model3.json', packageBytes: 1024, packageSha256: 'fixture-digest', dependencies: [] });
  let versions = [version('blocked', 'INCOMPATIBLE'), version('available', 'UNTESTED'), version('other', 'COMPATIBLE')];
  await page.route(base, route => route.fulfill({ json: { data: fixture } }));
  await page.route(`${base}/versions`, route => route.fulfill({ json: { data: versions } }));
  await page.goto(`${origin}/resources/${resourceId}`, { waitUntil: 'networkidle' });
  await expect(page.locator('#version-available')).toBeVisible();
  await expect(page.locator('#version-blocked')).toBeHidden();
  await expect(page.locator('#version-other')).toBeHidden();
  await expect(page.locator('#version-available')).toContainText('仍需在客户端预览确认');
  await expect(page.locator('#version-available code').first()).toBeHidden();
  await expect(page.getByRole('link', { name: '登录后收藏', exact: true })).toHaveAttribute('href', `/login?returnTo=${encodeURIComponent(`/resources/${resourceId}`)}`);
  pass('公开详情优先可用版本，隐藏专业字段，未试载风险与收藏登录回程保留');

  let authorizedVersion = '';
  await page.route('**/api/v1/auth/csrf', route => route.fulfill({ json: { data: { token: 'synthetic-browser-token' } } }));
  await page.route(`${base}/versions/*/download-authorizations`, route => {
    assert.equal(route.request().method(), 'POST');
    authorizedVersion = new URL(route.request().url()).pathname.split('/').at(-2);
    return route.fulfill({ json: { data: { url: '/__ux-fixture-download' } } });
  });
  await page.route(`${origin}/__ux-fixture-download`, route => route.fulfill({
    contentType: 'application/octet-stream', headers: { 'Content-Disposition': 'attachment; filename="ux-fixture.txt"' }, body: 'synthetic download only',
  }));
  const downloaded = page.waitForEvent('download');
  await page.getByRole('button', { name: '下载资源包', exact: false }).click();
  assert.equal((await downloaded).suggestedFilename(), 'ux-fixture.txt');
  assert.equal(authorizedVersion, 'available');
  pass('匿名下载选中实际可用版本，未产生登录门槛或写入真实资源');

  versions = [version('blocked', 'INCOMPATIBLE')];
  await page.reload({ waitUntil: 'networkidle' });
  await expect(page.locator('#version-blocked')).toBeVisible();
  await expect(page.locator('#version-blocked')).toContainText('此版本标记为不兼容');
  await expect(page.getByRole('button', { name: '仍要下载文件', exact: false })).toBeVisible();
  versions = [version('failed', 'UNTESTED', 'FAILED')];
  await page.reload({ waitUntil: 'networkidle' });
  await expect(page.getByRole('button', { name: '下载资源包', exact: false })).toHaveCount(0);
  versions = [];
  await page.reload({ waitUntil: 'networkidle' });
  await expect(page.getByRole('status')).toContainText('作者还没有上传可用版本');
  pass('不兼容、校验失败和无版本均如实呈现');

  // 创作者只使用合成身份，PATCH 被截获，证明管理版本没有因公开折叠而丢失。
  await page.route('**/api/v1/me', route => route.fulfill({ json: { data: {
    id: 'synthetic-owner', displayName: '验收作者', email: 'ux@example.invalid',
    role: 'USER', status: 'ACTIVE', emailVerified: true,
  } } }));
  await page.route('**/api/v1/me/resources?**', route => route.fulfill({ json: { data: [] } }));
  await page.goto(`${origin}/dashboard/resources`, { waitUntil: 'networkidle' });
  await page.getByLabel('搜索名称').fill('没有匹配结果');
  await page.getByLabel('搜索名称').press('Enter');
  await expect(page.getByRole('heading', { name: '没有找到符合条件的资源', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '还没有上传资源', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '清除筛选', exact: true }).click();
  await expect(page.getByLabel('搜索名称')).toHaveValue('');
  await expect(page.getByRole('heading', { name: '还没有上传资源', exact: true })).toBeVisible();
  pass('个人列表区分未匹配与未上传，清除筛选恢复输入和结果');

  versions = [version('failed', 'UNTESTED', 'FAILED'), version('available', 'UNTESTED'), version('other', 'COMPATIBLE')];
  let selectedVersion = '';
  await page.unroute(base);
  await page.route(base, route => {
    if (route.request().method() === 'PATCH') selectedVersion = route.request().postDataJSON().currentVersionId;
    return route.fulfill({ json: { data: { ...fixture, currentVersionId: selectedVersion, ownerId: 'synthetic-owner', status: 'ACTIVE' } } });
  });
  await page.goto(`${origin}/dashboard/resources/${resourceId}`, { waitUntil: 'networkidle' });
  await expect(page.locator('#version-available')).toBeVisible();
  await expect(page.locator('#version-other')).toBeVisible();
  await expect(page.locator('#version-failed').getByRole('button', { name: '设为当前版本' })).toHaveCount(0);
  await page.locator('#version-other').getByRole('button', { name: '设为当前版本' }).click();
  await expect.poll(() => selectedVersion).toBe('other');
  pass('管理模式保留完整版本与设为当前操作，失败版本不可选择');

  // 最终展示只截真实本机公开页面，清除全部资源替身。
  await context.unrouteAll({ behavior: 'wait' });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const [name, route] of [['home', '/'], ['resources', '/resources'], ['help', '/docs'], ['appearance-help', '/docs/appearance'], ['download', '/download']]) {
      await page.goto(`${origin}${route}`, { waitUntil: 'networkidle' });
      await page.screenshot({ path: path.join(output, `${name}-${width}.png`), fullPage: true });
    }
  }
  assert.deepEqual(report.errors, []);
  report.passed = true;
} catch (error) {
  report.failure = error instanceof Error ? error.message : String(error);
  console.error(report.failure);
  process.exitCode = 1;
} finally {
  await writeFile(path.join(output, 'journey-report.json'), JSON.stringify(report, null, 2));
  await context.close();
  await browser.close();
}
