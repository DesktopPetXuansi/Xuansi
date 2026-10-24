import { expect, test } from "@playwright/test";
import { adminVisitor, sampleFeedback } from "./admin-feedback-fixtures";
import { publicVisitor } from "./public-fixtures";

const id = "10000000-0000-4000-8000-000000000001";
const initial = {
  id,
  title: "测试问题",
  description: "原始问题正文",
  status: "NEW",
  moderationStatus: "PENDING",
  canReply: true,
  messages: [
    {
      id: "30000000-0000-4000-8000-000000000001",
      authorRole: "ADMIN",
      body: "请补充复现步骤 <script>test</script>",
      createdAt: "2026-10-23T01:00:00Z",
    },
  ],
};

test("管理员直接打开私有对话并回复解决，失败同意图重试", async ({ page }) => {
  await adminVisitor(page);
  const requests: { key: string; body: unknown }[] = [];
  await page.route(
    `**/api/v1/admin/feedback/${id}/messages*`,
    async (route) => {
      if (route.request().method() === "GET")
        return route.fulfill({
          json: { data: initial, meta: { nextCursor: null } },
        });
      requests.push({
        key: route.request().headers()["idempotency-key"],
        body: route.request().postDataJSON(),
      });
      await route.fulfill(
        requests.length === 1
          ? {
              status: 503,
              json: { error: { code: "UNAVAILABLE", message: "暂时中断" } },
            }
          : {
              json: {
                data: {
                  message: {
                    id: "30000000-0000-4000-8000-000000000002",
                    authorRole: "ADMIN",
                    body: "已修复，请重试",
                    createdAt: "2026-10-23T02:00:00Z",
                  },
                  feedbackStatus: "RESOLVED",
                },
              },
            },
      );
    },
  );
  await page.goto("/admin/feedback");
  await page.getByRole("button", { name: "回复用户", exact: true }).click();
  await expect(
    page.getByText(initial.messages[0].body, { exact: true }),
  ).toBeVisible();
  await page.getByLabel("回复内容", { exact: true }).fill("已修复，请重试");
  await page
    .getByRole("button", { name: "回复并标记已解决", exact: true })
    .click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "暂时中断",
  );
  await expect(page.getByLabel("回复内容", { exact: true })).toHaveValue(
    "已修复，请重试",
  );
  await page.getByRole("button", { name: "重试发送", exact: true }).click();
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[0]).toEqual(requests[1]);
  await expect(page.getByText("回复已发送", { exact: false })).toBeVisible();
});

test("用户从原管理链接查看私有回复并补充说明", async ({ page }) => {
  await publicVisitor(page);
  await page.route(`**/api/v1/feedback/${id}/management`, (route) =>
    route.fulfill({
      json: {
        data: {
          id,
          moderationStatus: "PENDING",
          canWithdraw: true,
          githubIssueUrl: "",
        },
      },
    }),
  );
  await page.route(`**/api/v1/feedback/${id}/messages/query`, (route) =>
    route.fulfill({ json: { data: initial, meta: { nextCursor: null } } }),
  );
  await page.route(`**/api/v1/feedback/${id}/messages`, (route) =>
    route.fulfill({
      json: {
        data: {
          message: {
            id: "30000000-0000-4000-8000-000000000003",
            authorRole: "USER",
            body: "重启后仍能复现",
            createdAt: "2026-10-23T03:00:00Z",
          },
          feedbackStatus: "NEW",
        },
      },
    }),
  );
  await page.goto(
    `/feedback/manage#id=${id}&key=${id}&token=${"a".repeat(64)}`,
  );
  await page.getByRole("button", { name: "查看对话", exact: true }).click();
  await expect(
    page.getByText(initial.messages[0].body, { exact: true }),
  ).toBeVisible();
  await page.getByLabel("补充说明", { exact: true }).fill("重启后仍能复现");
  await page.getByRole("button", { name: "发送补充", exact: true }).click();
  await expect(page.getByText("重启后仍能复现", { exact: true })).toBeVisible();
  await expect(page.getByLabel("补充说明", { exact: true })).toBeFocused();
  await expect(page.getByText("补充已发送。", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "刷新对话", exact: true }).click();
  await expect(page.getByLabel("补充说明", { exact: true })).toBeEnabled();
  // 发送后的焦点只恢复一次，后续刷新不能再次抢回输入焦点。
  await expect(page.getByLabel("补充说明", { exact: true })).not.toBeFocused();
});

test("回复保存期间锁定筛选刷新进度及撤回，成功更新状态和焦点", async ({
  page,
}) => {
  await adminVisitor(page);
  let finish: (() => void) | undefined;
  const gate = new Promise<void>((resolve) => {
    finish = resolve;
  });
  await page.route(
    `**/api/v1/admin/feedback/${id}/messages*`,
    async (route) => {
      if (route.request().method() === "GET")
        return route.fulfill({
          json: { data: initial, meta: { nextCursor: null } },
        });
      await gate;
      await route.fulfill({
        json: {
          data: {
            message: {
              ...initial.messages[0],
              id: "30000000-0000-4000-8000-000000000004",
              body: "请重试",
            },
            feedbackStatus: "IN_PROGRESS",
          },
        },
      });
    },
  );
  await page.goto("/admin/feedback");
  await page.getByRole("button", { name: "回复用户", exact: true }).click();
  await page.getByLabel("回复内容", { exact: true }).fill("请重试");
  await page.getByRole("button", { name: "发送回复", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "处理中", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "刷新列表", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "开始处理", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "标记已解决", exact: true }),
  ).toBeDisabled();
  finish?.();
  await expect(page.getByRole("article")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "反馈收件箱", exact: true }),
  ).toBeFocused();
  await expect(
    page.getByRole("button", { name: "处理中", exact: true }),
  ).toBeEnabled();
});

for (const status of ["SPAM", "WITHDRAWN", "WITHDRAWAL_REQUESTED"] as const) {
  test(`对话${status}明确关闭新增消息`, async ({ page }) => {
    await adminVisitor(page);
    await page.route(`**/api/v1/admin/feedback/${id}/messages*`, (route) =>
      route.fulfill({
        json: {
          data: {
            ...initial,
            moderationStatus: status,
            canReply: false,
            messages: [],
          },
          meta: { nextCursor: null },
        },
      }),
    );
    await page.goto("/admin/feedback");
    await page.getByRole("button", { name: "回复用户", exact: true }).click();
    await expect(
      page.getByText(
        /这条反馈已关闭对话，或没有原始管理凭据，暂不能新增消息。|这条反馈已撤回，原文与私有对话已清理。/,
        { exact: true },
      ),
    ).toBeVisible();
    await expect(page.getByLabel("回复内容", { exact: true })).toHaveCount(0);
  });
}

test("旧反馈没有原管理凭据时可查看但不能回复", async ({ page }) => {
  await adminVisitor(page);
  await page.route(`**/api/v1/admin/feedback/${id}/messages*`, (route) =>
    route.fulfill({
      json: {
        data: { ...initial, canReply: false, messages: [] },
        meta: { nextCursor: null },
      },
    }),
  );
  await page.goto("/admin/feedback");
  await page.getByRole("button", { name: "回复用户", exact: true }).click();
  await expect(page.getByText("暂无对话记录。", { exact: true })).toBeVisible();
  await expect(page.getByLabel("回复内容", { exact: true })).toHaveCount(0);
});

test("更早消息按时间追加到前面，正文始终作为纯文本显示", async ({ page }) => {
  await adminVisitor(page);
  await page.route(`**/api/v1/admin/feedback/${id}/messages*`, (route) => {
    const earlier = new URL(route.request().url()).searchParams.get("cursor");
    return route.fulfill({
      json: {
        data: {
          ...initial,
          messages: earlier
            ? [
                {
                  ...initial.messages[0],
                  id: "30000000-0000-4000-8000-000000000005",
                  authorRole: "USER",
                  body: "更早的用户补充 <img src=x onerror=alert(1)>",
                  createdAt: "2026-10-22T00:00:00Z",
                },
              ]
            : initial.messages,
        },
        meta: { nextCursor: earlier ? null : "earlier-cursor" },
      },
    });
  });
  await page.goto("/admin/feedback");
  await page.getByRole("button", { name: "回复用户", exact: true }).click();
  await page.getByRole("button", { name: "加载更早消息", exact: true }).click();
  const messages = page
    .getByRole("region", { name: "私有对话", exact: true })
    .getByRole("listitem");
  await expect(messages).toHaveCount(2);
  await expect(messages.first()).toContainText(
    "更早的用户补充 <img src=x onerror=alert(1)>",
  );
  await expect(messages.last()).toContainText(initial.messages[0].body);
  await expect(
    page
      .getByRole("region", { name: "私有对话", exact: true })
      .locator("img,script"),
  ).toHaveCount(0);
});

for (const status of [401, 403]) {
  test(`管理员对话${status}立即清除收件箱及对话正文`, async ({ page }) => {
    await adminVisitor(page);
    let reads = 0;
    await page.route(`**/api/v1/admin/feedback/${id}/messages*`, (route) => {
      reads++;
      return route.fulfill(
        reads === 1
          ? { json: { data: initial, meta: { nextCursor: null } } }
          : {
              status,
              json: { error: { code: "FORBIDDEN", message: "权限已失效" } },
            },
      );
    });
    await page.goto("/admin/feedback");
    await page.getByRole("button", { name: "回复用户", exact: true }).click();
    await expect(
      page.getByText(initial.messages[0].body, { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "刷新对话", exact: true }).click();
    await expect(page.getByRole("article")).toHaveCount(0);
    await expect(
      page.getByText(initial.messages[0].body, { exact: true }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: "全部", exact: true }).click();
    await expect(page.getByRole("article")).toHaveCount(0);
  });
}

test("用户凭据失效后隐藏旧对话及状态，不再显示补充框", async ({ page }) => {
  await publicVisitor(page);
  let reads = 0;
  await page.route(`**/api/v1/feedback/${id}/messages/query`, (route) => {
    reads++;
    return route.fulfill(
      reads === 1
        ? { json: { data: initial, meta: { nextCursor: null } } }
        : {
            status: 403,
            json: { error: { code: "FORBIDDEN", message: "管理凭据无效" } },
          },
    );
  });
  await page.goto(
    `/feedback/manage#id=${id}&key=${id}&token=${"a".repeat(64)}`,
  );
  await page.getByRole("button", { name: "查看对话", exact: true }).click();
  await expect(
    page.getByText(initial.messages[0].body, { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "刷新对话", exact: true }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "管理凭据无效",
  );
  await expect(
    page.getByText(initial.messages[0].body, { exact: true }),
  ).toHaveCount(0);
  await expect(page.getByLabel("补充说明", { exact: true })).toHaveCount(0);
});

test("用户发送失败可重试同意图，改写须显式创建新消息，手机没有横向溢出", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await publicVisitor(page);
  await page.route(`**/api/v1/feedback/${id}/messages/query`, (route) =>
    route.fulfill({ json: { data: initial, meta: { nextCursor: null } } }),
  );
  const requests: { key: string; body: unknown }[] = [];
  await page.route(`**/api/v1/feedback/${id}/messages`, (route) => {
    requests.push({
      key: route.request().headers()["idempotency-key"],
      body: route.request().postDataJSON(),
    });
    return route.fulfill({
      status: 503,
      json: { error: { code: "UNAVAILABLE", message: "测试发送中断" } },
    });
  });
  await page.goto(
    `/feedback/manage#id=${id}&key=${id}&token=${"a".repeat(64)}`,
  );
  await page.getByRole("button", { name: "查看对话", exact: true }).click();
  await page.getByLabel("补充说明", { exact: true }).fill("补充一次");
  await page.getByRole("button", { name: "发送补充", exact: true }).click();
  await page.getByRole("button", { name: "重试发送", exact: true }).click();
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[0]).toEqual(requests[1]);
  await page.getByRole("button", { name: "改写为新消息", exact: true }).click();
  await expect(page.getByLabel("补充说明", { exact: true })).toBeFocused();
  await page.getByLabel("补充说明", { exact: true }).fill("补充新的说明");
  await page.getByRole("button", { name: "发送补充", exact: true }).click();
  await expect.poll(() => requests.length).toBe(3);
  expect(requests[2].key).not.toBe(requests[0].key);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("用户撤回后立即移除旧私有对话", async ({ page }) => {
  await publicVisitor(page);
  await page.route(`**/api/v1/feedback/${id}/messages/query`, (route) =>
    route.fulfill({ json: { data: initial, meta: { nextCursor: null } } }),
  );
  await page.route(`**/api/v1/feedback/${id}/withdrawal`, (route) =>
    route.fulfill({
      json: {
        data: {
          id,
          moderationStatus: "WITHDRAWN",
          canWithdraw: false,
          githubIssueUrl: "",
        },
      },
    }),
  );
  await page.goto(
    `/feedback/manage#id=${id}&key=${id}&token=${"a".repeat(64)}`,
  );
  await page.getByRole("button", { name: "查看对话", exact: true }).click();
  await expect(
    page.getByText(initial.messages[0].body, { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "撤回反馈", exact: true }).click();
  await expect(
    page.getByText("已撤回，站内正文及联系方式已清理。", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(initial.messages[0].body, { exact: true }),
  ).toHaveCount(0);
  await expect(page.getByLabel("补充说明", { exact: true })).toHaveCount(0);
});

for (const status of [401, 403]) {
  test(`管理员发送${status}清除所有正文并解除保存锁`, async ({ page }) => {
    await adminVisitor(page);
    await page.route(`**/api/v1/admin/feedback/${id}/messages*`, (route) =>
      route.fulfill(
        route.request().method() === "GET"
          ? { json: { data: initial, meta: { nextCursor: null } } }
          : {
              status,
              json: { error: { code: "FORBIDDEN", message: "回复权限失效" } },
            },
      ),
    );
    await page.goto("/admin/feedback");
    await page.getByRole("button", { name: "回复用户", exact: true }).click();
    await page.getByLabel("回复内容", { exact: true }).fill("测试私有回复");
    await page.getByRole("button", { name: "发送回复", exact: true }).click();
    await expect(page.getByRole("article")).toHaveCount(0);
    await expect(
      page.getByText(initial.messages[0].body, { exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "全部", exact: true }),
    ).toBeEnabled();
  });
}

test("更早的状态读取成功不能解除较晚的凭据失效", async ({ page }) => {
  await publicVisitor(page);
  let rejectRead: (() => void) | undefined;
  let finishStatus: (() => void) | undefined;
  const failedRead = new Promise<void>((resolve) => {
    rejectRead = resolve;
  });
  const statusRead = new Promise<void>((resolve) => {
    finishStatus = resolve;
  });
  let reads = 0;
  await page.route(`**/api/v1/feedback/${id}/messages/query`, async (route) => {
    reads++;
    if (reads === 1)
      return route.fulfill({
        json: { data: initial, meta: { nextCursor: null } },
      });
    await failedRead;
    await route.fulfill({
      status: 403,
      json: { error: { code: "FORBIDDEN", message: "凭据已失效" } },
    });
  });
  await page.route(`**/api/v1/feedback/${id}/management`, async (route) => {
    await statusRead;
    await route.fulfill({
      json: {
        data: {
          id,
          moderationStatus: "PENDING",
          canWithdraw: true,
          githubIssueUrl: "",
        },
      },
    });
  });
  await page.goto(
    `/feedback/manage#id=${id}&key=${id}&token=${"a".repeat(64)}`,
  );
  await page.getByRole("button", { name: "查看对话", exact: true }).click();
  await expect(
    page.getByText(initial.messages[0].body, { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "刷新对话", exact: true }).click();
  await page.getByRole("button", { name: "查看最新状态", exact: true }).click();
  rejectRead?.();
  await expect(page.getByRole("main").getByRole("alert")).toContainText(
    "凭据已失效",
  );
  finishStatus?.();
  await expect(
    page.getByRole("button", { name: "查看最新状态", exact: true }),
  ).toBeEnabled();
  await expect(
    page.getByText(initial.messages[0].body, { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "查看对话", exact: true }),
  ).toHaveCount(0);
});

for (const viewer of ["ADMIN", "USER"] as const) {
  for (const moderationStatus of [
    "WITHDRAWN",
    "WITHDRAWAL_REQUESTED",
  ] as const) {
    test(`${viewer}加载更早时收到${moderationStatus}会清除已读私信及草稿`, async ({
      page,
    }) => {
      if (viewer === "ADMIN") await adminVisitor(page);
      else await publicVisitor(page);
      const pattern =
        viewer === "ADMIN"
          ? `**/api/v1/admin/feedback/${id}/messages*`
          : `**/api/v1/feedback/${id}/messages/query`;
      let reads = 0;
      await page.route(pattern, (route) => {
        reads++;
        return route.fulfill({
          json: {
            data:
              reads === 1
                ? initial
                : {
                    ...initial,
                    moderationStatus,
                    canReply: false,
                    messages: [],
                  },
            meta: { nextCursor: reads === 1 ? "older" : null },
          },
        });
      });
      await page.goto(
        viewer === "ADMIN"
          ? "/admin/feedback"
          : `/feedback/manage#id=${id}&key=${id}&token=${"a".repeat(64)}`,
      );
      await page
        .getByRole("button", {
          name: viewer === "ADMIN" ? "回复用户" : "查看对话",
          exact: true,
        })
        .click();
      await expect(
        page.getByText(initial.messages[0].body, { exact: true }),
      ).toBeVisible();
      await page
        .getByLabel(viewer === "ADMIN" ? "回复内容" : "补充说明", {
          exact: true,
        })
        .fill("不应保留的草稿");
      await page
        .getByRole("button", { name: "加载更早消息", exact: true })
        .click();
      await expect(
        page.getByText(initial.messages[0].body, { exact: true }),
      ).toHaveCount(0);
      await expect(
        page.getByText(
          /这条反馈已关闭对话，或没有原始管理凭据，暂不能新增消息。|这条反馈已撤回，原文与私有对话已清理。/,
          { exact: true },
        ),
      ).toBeVisible();
      await expect(
        page.getByRole("button", { name: "重试发送", exact: true }),
      ).toHaveCount(0);
    });
  }
}

for (const readAction of ["刷新对话", "加载更早消息"] as const) {
  test(`已确认撤回后${readAction}清除后台各筛选旧原文和联系方式`, async ({
    page,
  }) => {
    const item = sampleFeedback({
      title: "需要清除的原始标题",
      description: "需要清除的原始正文",
      contact: "withdrawn-test@example.invalid",
      diagnostics: {
        appVersion: "withdrawn-test-version",
        system: "test-system",
        architecture: "test-arch",
        pythonVersion: "test-python",
        qtVersion: "test-qt",
      },
    });
    await adminVisitor(page, { items: [item] });
    let reads = 0;
    await page.route(`**/api/v1/admin/feedback/${id}/messages*`, (route) => {
      reads++;
      return route.fulfill({
        json: {
          data:
            reads === 1
              ? { ...initial, title: item.title, description: item.description }
              : {
                  ...initial,
                  title: "",
                  description: "",
                  moderationStatus: "WITHDRAWN",
                  canReply: false,
                  messages: [],
                },
          meta: { nextCursor: reads === 1 ? "older" : null },
        },
      });
    });
    await page.goto("/admin/feedback");
    await page.getByRole("button", { name: "全部", exact: true }).click();
    await expect(page.getByRole("article")).toHaveCount(1);
    await page.getByRole("button", { name: "待处理", exact: true }).click();
    await page.getByRole("button", { name: "回复用户", exact: true }).click();
    await expect(
      page.getByText(initial.messages[0].body, { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: readAction, exact: true }).click();
    await expect(
      page.getByRole("heading", { name: item.title, exact: true }),
    ).toHaveCount(0);
    await expect(page.getByText(item.description, { exact: true })).toHaveCount(
      0,
    );
    await expect(page.getByText(item.contact, { exact: true })).toHaveCount(0);
    await expect(
      page.getByText("withdrawn-test-version", { exact: true }),
    ).toHaveCount(0);
    await page.route(/\/api\/v1\/admin\/feedback(?:\?.*)?$/, (route) =>
      route.fulfill({
        status: 503,
        json: {
          error: { code: "UNAVAILABLE", message: "阻止重新读取，检查缓存清理" },
        },
      }),
    );
    await page.getByRole("button", { name: "全部", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "已撤回的反馈", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: item.title, exact: true }),
    ).toHaveCount(0);
    await expect(page.getByText(item.contact, { exact: true })).toHaveCount(0);
  });
}

test("撤回待清理只清私信，后台仍保留初始问题和联系信息供清理", async ({
  page,
}) => {
  const item = sampleFeedback();
  await adminVisitor(page, { items: [item] });
  await page.route(`**/api/v1/admin/feedback/${id}/messages*`, (route) =>
    route.fulfill({
      json: {
        data: {
          ...initial,
          moderationStatus: "WITHDRAWAL_REQUESTED",
          canReply: false,
          messages: [],
        },
        meta: { nextCursor: null },
      },
    }),
  );
  await page.goto("/admin/feedback");
  await page.getByRole("button", { name: "回复用户", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: item.title, exact: true }),
  ).toBeVisible();
  await expect(page.getByText(item.contact, { exact: true })).toBeVisible();
  await expect(page.getByLabel("回复内容", { exact: true })).toHaveCount(0);
});

test("对话已确认撤回后，迟到的完整进度响应不能恢复原文或联系方式", async ({
  page,
}) => {
  const item = sampleFeedback({
    title: "交错测试原始标题",
    description: "交错测试原始正文",
    contact: "delayed-patch@example.invalid",
  });
  await adminVisitor(page, { items: [item] });
  let finishConversation: (() => void) | undefined;
  let finishPatch: (() => void) | undefined;
  const conversationGate = new Promise<void>((resolve) => {
    finishConversation = resolve;
  });
  const patchGate = new Promise<void>((resolve) => {
    finishPatch = resolve;
  });
  await page.route(
    `**/api/v1/admin/feedback/${id}/messages*`,
    async (route) => {
      await conversationGate;
      await route.fulfill({
        json: {
          data: {
            ...initial,
            title: "",
            description: "",
            moderationStatus: "WITHDRAWN",
            canReply: false,
            messages: [],
          },
          meta: { nextCursor: null },
        },
      });
    },
  );
  let patchReceived = false;
  await page.route(`**/api/v1/admin/feedback/${id}`, async (route) => {
    patchReceived = true;
    await patchGate;
    await route.fulfill({
      json: {
        data: {
          ...item,
          status: "IN_PROGRESS",
          updatedAt: "2026-10-23T05:00:00Z",
        },
      },
    });
  });
  await page.goto("/admin/feedback");
  await page.getByRole("button", { name: "全部", exact: true }).click();
  await page.getByRole("button", { name: "回复用户", exact: true }).click();
  await page.getByRole("button", { name: "开始处理", exact: true }).click();
  await expect.poll(() => patchReceived).toBe(true);
  finishConversation?.();
  await expect(
    page.getByRole("heading", { name: "已撤回的反馈", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(item.contact, { exact: true })).toHaveCount(0);
  finishPatch?.();
  await expect(
    page.getByText("已标记为处理中。", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "已撤回的反馈", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: item.title, exact: true }),
  ).toHaveCount(0);
  await expect(page.getByText(item.description, { exact: true })).toHaveCount(
    0,
  );
  await expect(page.getByText(item.contact, { exact: true })).toHaveCount(0);
  await expect(
    page.getByText("这条反馈已撤回，原文与私有对话已清理。", { exact: true }),
  ).toBeVisible();
});
