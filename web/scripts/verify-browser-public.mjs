// 使用独立浏览器配置验证本地官网，不连接用户日常浏览器会话。
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const { chromium } = await import(pathToFileURL(path.join(root, 'frontend/node_modules/@playwright/test/index.mjs')).href);
const origin = process.env.WEB_URL ?? 'http://localhost:3000';
const screenshots = path.join(root, '.runtime/screenshots');
await mkdir(screenshots, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const pages = ['/', '/features', '/download', '/docs', '/faq', '/privacy', '/licenses'];
const failures = [];
try {
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: 1000 }, reducedMotion: 'reduce' });
    const page = await context.newPage();
    page.on('pageerror', (error) => failures.push(error.message));
    for (const route of pages) {
      const response = await page.goto(`${origin}${route}`, { waitUntil: 'networkidle' });
      assert.equal(response?.status(), 200, `页面未成功加载：${route}`);
      assert.equal(await page.locator('h1').count(), 1, `页面标题不唯一：${route}`);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
      assert.equal(overflow, false, `页面横向溢出：${route}/${width}`);
      assert.ok((await page.title()).includes('玄司'), `页面缺少产品标题：${route}`);
      if (route === '/') await page.screenshot({ path: path.join(screenshots, `homepage-${width}.png`), fullPage: true });
      if (route === '/download') await page.screenshot({ path: path.join(screenshots, `download-${width}.png`), fullPage: true });
    }
    await context.close();
  }
  assert.deepEqual(failures, [], '页面出现未捕获异常');
  console.log(`官网浏览器检查通过：${pages.length * 2} 个页面/尺寸组合，包含桌面与移动截图。`);
} finally {
  await browser.close();
}
