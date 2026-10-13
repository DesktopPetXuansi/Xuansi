// 管理操作只作用于本机新建的验收账号、合成图片和未发布版本草稿。
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import path from 'node:path';

async function promoteLocalAccount(project, email) {
  const child = spawn('go', ['run', './cmd/admin', '-email', email], {
    cwd: path.join(project, 'web/backend'), windowsHide: true, stdio: 'ignore',
    env: { ...process.env, DATABASE_URL: 'postgres://xuansi@127.0.0.1:54329/xuansi?sslmode=disable' },
  });
  const code = await new Promise((resolve, reject) => {
    child.on('error', reject);
    child.on('close', resolve);
  });
  assert.equal(code, 0, '本机管理员初始化失败');
}

export async function verifyAdmin({ project, email, page, browser, origin, api, request, image, imageVersion, checked }) {
  await promoteLocalAccount(project, email);
  await page.goto(`${origin}/admin/resources`);
  // 多次验收可产生同名资源，以本次唯一版本定位，避免选中旧数据。
  assert.match(imageVersion, /^[a-f0-9-]{36}$/);
  const publication = page.locator('article').filter({ has: page.locator(`option[value="${imageVersion}"]`) });
  await publication.getByRole('combobox').selectOption(imageVersion);
  await publication.getByRole('button', { name: '发布公开资源' }).click();
  await publication.getByText('公开', { exact: false }).waitFor();
  const anonymous = await browser.newContext();
  try {
    const view = await api(anonymous.request, `/resources/${image.id}`);
    assert.equal(view.visibility, 'PUBLIC');
    const response = await anonymous.request.get(`${origin}/resources/${image.id}`);
    assert.equal(response.status(), 200);
    const published = await api(anonymous.request, `/resources/${image.id}/versions/${imageVersion}/manifest`);
    assert.equal(published.kind, 'IMAGE');
    checked('浏览器管理员发布合成图片，匿名读取公开资源');

    const stable = await api(request, '/client/releases/latest');
    const artifact = stable.artifacts[0];
    await page.goto(`${origin}/admin/releases`);
    const draftVersion = `${stable.version}-qa-${Date.now()}`;
    for (const [field, value] of Object.entries({
      version: draftVersion, sourceCommit: stable.sourceCommit, releaseNotes: '本地验收草稿，不发布',
      downloadUrl: artifact.downloadUrl, sha256: artifact.sha256, bytes: String(artifact.bytes),
    })) await page.locator(`[name=${field}]`).fill(value);
    await page.locator('select[name=channel]').selectOption('BETA');
    await page.getByRole('button', { name: '保存草稿', exact: true }).click();
    await page.getByText('版本草稿已创建，请核对后发布。', { exact: true }).waitFor();
    const draftRow = page.locator('article').filter({ hasText: draftVersion });
    await draftRow.getByRole('button', { name: '编辑草稿' }).click();
    assert.ok(await page.locator('[name=version]').isDisabled());
    await page.locator('[name=releaseNotes]').fill('已编辑的本地验收说明，不发布');
    await page.getByRole('button', { name: '保存草稿', exact: true }).click();
    await page.getByText('版本说明已保存。', { exact: true }).waitFor();
    const releases = await api(request, '/admin/client-releases');
    const draft = releases.find((release) => release.version === draftVersion);
    assert.equal(draft.releaseNotes, '已编辑的本地验收说明，不发布');
    assert.equal(draft.publishedAt, null);
    assert.equal((await anonymous.request.get(`${origin}/api/v1/client/releases/${draft.id}`)).status(), 404);
    const detail = await api(anonymous.request, `/client/releases/${stable.id}`);
    assert.equal(detail.artifacts[0].sha256, artifact.sha256);
    checked('浏览器管理员创建和编辑版本草稿，公开接口隔离草稿');

    for (const [route, title] of Object.entries({ users: '用户管理', resources: '资源发布', releases: '客户端版本', jobs: '后台任务', audit: '审计日志' })) {
      await page.goto(`${origin}/admin/${route}`);
      await page.getByRole('heading', { level: 1, name: title, exact: true }).waitFor();
    }
    const audit = await api(request, '/admin/audit-logs');
    assert.ok(audit.some((entry) => entry.targetId === draft.id && entry.action === 'RELEASE_NOTES_UPDATE'));
    checked('五个管理员页面和版本编辑审计记录');
  } finally {
    await anonymous.close();
  }
}
