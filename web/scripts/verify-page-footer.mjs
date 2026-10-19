// 只浏览本机公开页面，验证页脚的真实几何位置；不创建账号或发送邮件。
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const origin = process.env.WEB_URL ?? 'http://localhost:3100';
assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(new URL(origin).hostname));
const output = path.join(root, 'data/verification/page-footer-2026-10-19');
await mkdir(output, { recursive: true });
const { chromium, expect } = await import(pathToFileURL(path.join(root, 'web/frontend/node_modules/@playwright/test/index.mjs')).href);
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const context = await browser.newContext();
const page = await context.newPage();
const report = { passed: false, layouts: [], checks: [], errors: [] };
const baseline = process.argv.includes('--baseline');
page.on('pageerror', error => report.errors.push(error.message));

async function measure(route, name) {
  const layout = await page.evaluate(() => {
    const rect = selector => {
      const r = document.querySelector(selector).getBoundingClientRect();
      return { top: r.top + scrollY, bottom: r.bottom + scrollY, left: r.left, width: r.width };
    };
    return { viewport: { width: innerWidth, height: innerHeight },
      documentHeight: document.documentElement.scrollHeight,
      footer: rect('.site-footer'), main: rect('#main'),
      overflow: document.documentElement.scrollWidth > innerWidth + 1 };
  });
  report.layouts.push({ route, name, ...layout });
  if (baseline) await page.screenshot({ path: path.join(output, 'before-login-full.png'), fullPage: true });
  assert.ok(Math.abs(layout.footer.bottom - Math.max(layout.viewport.height, layout.documentHeight)) <= 1,
    `${name}: 页脚未落在整页底部`);
  assert.ok(layout.footer.top >= layout.main.bottom - 1, `${name}: 页脚覆盖正文`);
  assert.ok(Math.abs(layout.footer.width - Math.min(layout.viewport.width, 1200)) <= 1,
    `${name}: 页脚宽度异常`);
  assert.equal(layout.overflow, false, `${name}: 整页横向溢出`);
  report.checks.push(name);
  console.log(`通过：${name}`);
}

try {
  const cases = baseline ? [{ width: 1440, height: 1200, route: '/login', name: '高窗口登录页' }] : [
    { width: 1440, height: 1200, route: '/login', name: '高窗口登录页' },
    { width: 1440, height: 1200, route: '/forgot-password', name: '短表单页' },
    { width: 1440, height: 1200, route: '/dashboard', name: '访客登录引导' },
    { width: 1440, height: 1200, route: '/resources', name: '资源列表页' },
    { width: 768, height: 1200, route: '/login', name: '平板登录页' },
    { width: 390, height: 1200, route: '/login', name: '手机高窗口登录页' },
    { width: 320, height: 1400, route: '/forgot-password', name: '窄屏短表单页' },
    { width: 1440, height: 700, route: '/login', name: '低窗口登录页' },
    { width: 390, height: 700, route: '/login', name: '手机自然滚动登录页' },
    { width: 1440, height: 900, route: '/', name: '桌面长首页' },
    { width: 390, height: 900, route: '/', name: '手机长首页' },
    { width: 1440, height: 900, route: '/docs', name: '文档内容页' },
  ];
  for (const item of cases) {
    await page.setViewportSize({ width: item.width, height: item.height });
    const response = await page.goto(`${origin}${item.route}`, { waitUntil: 'networkidle' });
    assert.equal(response?.status(), 200);
    await measure(item.route, item.name);
    if (item.route === '/login' && item.height === 1200 && [1440, 390].includes(item.width)) {
      await page.screenshot({ path: path.join(output, `login-full-${item.width}.png`), fullPage: true });
    }
  }
  // 错误反馈和手机菜单展开会改变正文/页头高度，页脚仍应自然排在后面。
  await page.setViewportSize({ width: 390, height: 1400 });
  await page.goto(`${origin}/login`, { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.locator('[name=email]')).toHaveAttribute('aria-invalid', 'true');
  await measure('/login', '表单错误反馈展开');
  await page.getByRole('button', { name: '展开主导航', exact: true }).click();
  await measure('/login', '手机导航展开');
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
  await measure('/login', '滚动后页脚不覆盖正文');
  assert.deepEqual(report.errors, []);
  report.passed = true;
} catch (error) {
  report.failure = error instanceof Error ? error.message : String(error);
  console.error(report.failure);
  process.exitCode = 1;
} finally {
  await writeFile(path.join(output, baseline ? 'red.json' : 'report.json'), JSON.stringify(report, null, 2));
  await context.close();
  await browser.close();
}
