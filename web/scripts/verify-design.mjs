// 独立 Chrome 验证导航和筛选；不创建账号、不写入资源、不发送邮件。
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const { chromium, expect } = createRequire(path.join(root, 'frontend/package.json'))('@playwright/test');
const origin = process.env.WEB_URL ?? 'http://localhost:3000';
const output = path.join(root, '.runtime/screenshots/design-2026-10-16');
await mkdir(output, { recursive: true });
const browser = await chromium.launch(process.env.CHROME_PATH
  ? { executablePath: process.env.CHROME_PATH, headless: true }
  : { channel: 'chrome', headless: true });
const report = { passed: false, responsive: [], interactions: [], contrast: [], errors: [], network: [], warnings: [] };

try {
  const context = await browser.newContext({ viewport: { width: 320, height: 1000 }, reducedMotion: 'reduce' });
  const page = await context.newPage();
  page.on('pageerror', error => report.errors.push(error.message));
  page.on('console', entry => {
    if (entry.type() === 'warning') report.warnings.push(entry.text());
  });
  page.on('response', response => {
    const pathname = new URL(response.url()).pathname;
    // 未登录的 /me 按现有协议返回 401，是预期权限状态。
    if (response.status() >= 400 && !(pathname === '/api/v1/me' && response.status() === 401)) {
      report.network.push({ pathname, status: response.status() });
    }
  });
  await page.goto(origin, { waitUntil: 'networkidle' });

  // 先证明手机导航能由键盘展开、关闭、恢复焦点和完成跳转。
  const menu = page.locator('button[aria-controls="primary-navigation"]');
  await expect(menu).toBeVisible();
  await expect(page.getByRole('navigation', { name: '主导航' })).toBeHidden();
  await page.getByRole('link', { name: '玄司首页', exact: true }).focus();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: '登录 / 注册', exact: true })).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(menu).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(menu).toHaveAttribute('aria-expanded', 'true');
  await page.keyboard.press('Tab');
  await expect(page.getByRole('navigation', { name: '主导航' }).getByRole('link', { name: '产品', exact: true })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(menu).toBeFocused();
  await expect(menu).toHaveAttribute('aria-expanded', 'false');
  await menu.click();
  await page.getByRole('navigation', { name: '主导航' }).getByRole('link', { name: '文档', exact: true }).click();
  await expect(page).toHaveURL(`${origin}/docs`);
  await expect(page.getByRole('button', { name: '展开主导航' })).toHaveAttribute('aria-expanded', 'false');
  await page.getByRole('button', { name: '展开主导航' }).click();
  await expect(page.getByRole('navigation', { name: '主导航' }).getByRole('link', { name: '文档', exact: true })).toHaveAttribute('aria-current', 'page');
  // 账号链接没有菜单关闭处理器，独立验证跨路由重建能收起展开状态。
  await page.getByRole('link', { name: '登录 / 注册', exact: true }).click();
  await expect(page).toHaveURL(`${origin}/login`);
  await expect(menu).toHaveAttribute('aria-expanded', 'false');
  report.interactions.push('移动导航：键盘展开、Tab、Escape/焦点恢复、路由关闭、当前页');

  // 下列路由使用真实本地服务，只做浏览和截图。
  for (const width of [320, 390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const route of ['/', '/features', '/resources', '/download', '/login', '/docs']) {
      const response = await page.goto(`${origin}${route}`, { waitUntil: 'networkidle' });
      assert.equal(response?.status(), 200, `页面状态异常：${route}/${width}`);
      await expect(page.locator('h1')).toHaveCount(1);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, `整页溢出：${route}/${width}`);
      if (route === '/') {
        assert.equal(await page.locator('.hero img').evaluate(image => image.complete && image.naturalWidth > 0), true, '首页角色未加载');
        await page.screenshot({ path: path.join(output, `after-home-${width}.png`), fullPage: true });
      }
      if (['/resources', '/download', '/login'].includes(route) && [320, 1440].includes(width)) {
        await page.screenshot({ path: path.join(output, `after-${route.slice(1)}-${width}.png`), fullPage: true });
      }
      report.responsive.push({ route, width, status: response.status(), overflow: false });
    }
  }
  await page.getByRole('link', { name: '玄司首页', exact: true }).click();
  await page.getByRole('link', { name: '探索资源库' }).click();
  await expect(page).toHaveURL(`${origin}/resources`);
  await page.getByRole('link', { name: '玄司首页', exact: true }).click();
  await expect(page.locator('.hero')).toBeVisible();
  report.interactions.push('首页 → 资源库 → 首页的客户端跳转');

  // 检查最终计算样式中的文字配色，覆盖容易漏掉的浅绿区块背景。
  const colorPairs = await page.evaluate(() => {
    const css = getComputedStyle(document.documentElement);
    return [['辅助文字/页面', '--muted', '--paper'], ['辅助文字/浅绿', '--muted', '--green-soft'], ['主按钮', '--white', '--green']]
      .map(([label, foreground, background]) => ({ label, foreground: css.getPropertyValue(foreground).trim(), background: css.getPropertyValue(background).trim() }));
  });
  function luminance(hex) {
    const value = Number.parseInt(hex.slice(1), 16);
    const channels = [value >> 16 & 255, value >> 8 & 255, value & 255].map(channel => {
      const s = channel / 255;
      return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    });
    return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  }
  report.contrast = colorPairs.map(({ label, foreground, background }) => {
    const values = [luminance(foreground), luminance(background)];
    const ratio = (Math.max(...values) + 0.05) / (Math.min(...values) + 0.05);
    assert.ok(ratio >= 4.5, `文字对比度不足：${label}/${ratio}`);
    return { label, ratio: Number(ratio.toFixed(2)) };
  });

  // 替身只覆盖 GET 查询，检查空态、Enter 提交与游标，不修改真实数据。
  const queries = [];
  await page.route('**/api/v1/resources?**', async route => {
    const query = new URL(route.request().url()).searchParams;
    queries.push(Object.fromEntries(query));
    await route.fulfill({ json: { data: [], meta: { nextCursor: query.get('cursor') ? undefined : 'design-next' } } });
  });
  await page.goto(`${origin}/resources`, { waitUntil: 'networkidle' });
  await expect(page.getByRole('status').filter({ hasText: '暂时没有符合条件的资源' })).toBeVisible();
  await page.getByLabel('搜索资源').fill('玄司');
  await page.getByLabel('资源类型').selectOption('MODEL');
  await page.getByLabel('标签', { exact: true }).fill('本地');
  await page.getByLabel('标签', { exact: true }).press('Enter');
  await expect.poll(() => queries.at(-1)).toEqual({ search: '玄司', kind: 'MODEL', tag: '本地', cursor: '' });
  await page.getByRole('button', { name: '下一页' }).click();
  await expect.poll(() => queries.at(-1)?.cursor).toBe('design-next');
  assert.equal(queries.at(-1).search, '玄司');
  assert.equal(queries.at(-1).kind, 'MODEL');
  assert.equal(queries.at(-1).tag, '本地');
  await page.getByRole('button', { name: '返回首页' }).click();
  // 首批结果可能仍在 Query 缓存中；用用户可见的翻页状态验证返回。
  await expect(page.getByRole('button', { name: '返回首页' })).toBeHidden();
  await expect(page.getByRole('button', { name: '下一页' })).toBeVisible();
  report.interactions.push('资源筛选：空态、Enter、搜索/类型/标签、翻页保留条件、回到首批');

  await context.close();

  // 工作台只使用合成会话与空列表检查布局，不接触真实账号或提交接口。
  const workspace = await browser.newContext({ reducedMotion: 'reduce' });
  const workspacePage = await workspace.newPage();
  workspacePage.on('pageerror', error => report.errors.push(error.message));
  await workspacePage.route('**/api/v1/me', route => route.fulfill({ json: { data: {
    id: 'design-user', displayName: '视觉验收', email: 'visual@example.invalid',
    role: 'USER', status: 'ACTIVE', emailVerified: true,
  } } }));
  await workspacePage.route('**/api/v1/me/resources?**', route => route.fulfill({ json: { data: [] } }));
  for (const width of [320, 768, 1024]) {
    await workspacePage.setViewportSize({ width, height: 1000 });
    await workspacePage.goto(`${origin}/dashboard/resources`, { waitUntil: 'networkidle' });
    await expect(workspacePage.getByRole('heading', { name: '我的资源', exact: true })).toBeVisible();
    const input = await workspacePage.getByLabel('搜索资源').boundingBox();
    assert.ok(input && input.width >= 120, `工作台筛选字段过窄：${width}`);
    assert.equal(await workspacePage.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, `工作台溢出：${width}`);
    await workspacePage.screenshot({ path: path.join(output, `after-workspace-${width}.png`), fullPage: true });
    report.responsive.push({ route: '/dashboard/resources', width, source: '合成会话与空列表', overflow: false });
  }
  await workspace.close();
  report.interactions.push('合成会话：工作台导航、320/768/1024px 筛选布局');
  assert.deepEqual(report.errors, [], '浏览器出现未捕获异常');
  assert.deepEqual(report.network, [], '页面出现非预期请求错误');
  assert.deepEqual(report.warnings, [], '浏览器出现警告');
  report.passed = true;
  console.log(`视觉与交互检查通过：${report.responsive.length} 个页面/尺寸组合，${report.interactions.length} 组交互。`);
} finally {
  await writeFile(path.join(output, 'verification.json'), JSON.stringify(report, null, 2));
  await browser.close();
}
