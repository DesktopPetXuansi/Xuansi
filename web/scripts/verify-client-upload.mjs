// 真实 Qt/浏览器上传；隔离 API 必须使用 Mailpit，不写用户 Windows 凭据。
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const origin = process.env.WEB_URL ?? 'http://localhost:3000';
const apiOrigin = process.env.UPLOAD_CHECK_API ?? 'http://localhost:8081';
const mail = process.env.MAIL_URL ?? 'http://127.0.0.1:8025';
for (const address of [origin, apiOrigin, mail]) {
    assert.ok(['localhost', '127.0.0.1', '[::1]'].includes(new URL(address).hostname), '上传验收只允许本机服务');
}
const config = await (await fetch(`${apiOrigin}/api/v1/auth/config`)).json();
assert.equal(config.data.email.mode, 'LOCAL_MAILBOX', '上传验收需要隔离的 Mailpit API，拒绝真实 SMTP');
const { chromium, expect } = await import(pathToFileURL(path.join(root, 'web/frontend/node_modules/@playwright/test/index.mjs')).href);
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const context = await browser.newContext();
const page = await context.newPage();
const errors = [];
page.on('pageerror', (error) => errors.push(error.message));

// 前端保留主服务，只有这个独立浏览器上下文把 API/同意请求代理至隔离 Go API。
for (const pattern of ['**/api/v1/**', '**/oauth/authorize']) {
    await context.route(pattern, async (route) => {
        const url = new URL(route.request().url());
        if (url.origin !== origin) return route.continue();
        const response = await route.fetch({ url: `${apiOrigin}${url.pathname}${url.search}` });
        await route.fulfill({ response });
    });
}
async function api(route, method, data) {
    const csrf = await (await context.request.get(`${apiOrigin}/api/v1/auth/csrf`)).json();
    const response = await context.request.fetch(`${apiOrigin}/api/v1${route}`, {
        method, data, headers: { Origin: origin, 'X-CSRF-Token': csrf.data.token },
    });
    assert.ok(response.ok(), `隔离接口失败：${route} HTTP ${response.status()}`);
}
let child;
try {
    const email = `client-upload-${Date.now()}@example.invalid`;
    const password = randomBytes(20).toString('hex');
    const author = '客户端上传验收';
    await api('/auth/register', 'POST', { email, password, displayName: author });
    let verification;
    for (let attempt = 0; attempt < 40 && !verification; attempt++) {
        const listing = await (await fetch(`${mail}/api/v1/messages`)).json();
        const message = listing.messages?.find((item) => item.To?.some((to) => to.Address === email));
        if (message) {
            const content = await (await fetch(`${mail}/api/v1/message/${message.ID}`)).json();
            verification = content.Text?.match(/\/verify-email\?token=([A-Za-z0-9_-]+)/)?.[1];
        }
        if (!verification) await new Promise((resolve) => setTimeout(resolve, 250));
    }
    assert.ok(verification, '隔离 worker 未投递本次测试的验证链接');
    await api('/auth/email-verifications/confirm', 'POST', { token: verification });
    await api('/auth/login', 'POST', { email, password });
    await page.goto(`${origin}/authorize?scope=resources%3Aread`);
    await expect(page.getByRole('button', { name: '允许读取资源', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '允许上传模型', exact: true })).toHaveCount(0);
    console.log('通过：原只读授权页面保留读取文案');
    child = spawn(path.join(root, '.venv/Scripts/python.exe'), [path.join(root, 'web/scripts/verify-client-upload.py')], {
        cwd: root, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'],
        env: { ...process.env, PYTHONIOENCODING: 'utf-8', QT_QPA_PLATFORM: 'offscreen' },
    });
    child.stdin.end(JSON.stringify({ origin: apiOrigin, websiteOrigin: origin, author }));
    let buffer = '', authorization, safeError = '';
    child.stdout.on('data', (part) => {
        buffer += part.toString();
        const lines = buffer.split(/\r?\n/);
        buffer = lines.pop();
        for (const line of lines) {
            if (line.startsWith('__QA_AUTHORIZE__')) {
                authorization = (async () => {
                    await page.goto(line.slice('__QA_AUTHORIZE__'.length));
                    await expect(page.getByRole('button', { name: '允许上传模型', exact: true })).toBeVisible();
                    await page.getByRole('button', { name: '允许上传模型', exact: true }).click();
                    await page.getByText('授权处理完成，请返回桌宠。', { exact: true }).waitFor();
                })();
                authorization.catch(() => child.kill());
            } else if (line.startsWith('客户端上传验收：')) console.log(line);
        }
    });
    child.stderr.on('data', (part) => {
        safeError += part.toString().split(/\r?\n/).filter((line) => line.startsWith('客户端上传验收失败：')).join('');
    });
    const timeout = setTimeout(() => child.kill(), 120000);
    const code = await new Promise((resolve, reject) => { child.on('error', reject); child.on('close', resolve); });
    clearTimeout(timeout);
    if (authorization) await authorization;
    assert.ok(authorization, 'Qt 客户端没有发起显式上传授权');
    assert.equal(code, 0, safeError || 'Qt 上传验收未完成');
    assert.deepEqual(errors, []);
    console.log('通过：真实 Qt/浏览器/Go/PostgreSQL/worker 上传闭环，浏览器无未捕获异常');
} finally {
    if (child && child.exitCode === null) child.kill();
    await context.close();
    await browser.close();
}
