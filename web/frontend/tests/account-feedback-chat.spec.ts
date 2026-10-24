import { expect, test } from "@playwright/test";
import {
  accountChat,
  chatConversation,
  chatMessage,
  chatThread,
  messageId,
  otherThreadId,
  threadId,
} from "./account-feedback-fixtures";

for (const admin of [false, true]) {
  const side = admin ? "管理员" : "账号用户";
  test(`${side}看到真实昵称、原始问题和私有回复`, async ({ page }) => {
    const { path } = await accountChat(page, admin);
    await page.goto(path);
    await page.getByRole("button", { name: /账号测试问题/ }).click();
    const conversation = page.getByRole("region", {
      name: "反馈会话",
      exact: true,
    });
    await expect(
      conversation
        .getByText(admin ? "星河测试者" : "提交时昵称", { exact: true })
        .first(),
    ).toBeVisible();
    await expect(
      conversation.getByText("最初的问题正文", { exact: true }),
    ).toBeVisible();
    await expect(
      conversation.getByText("开发者的私有答复", { exact: true }),
    ).toBeVisible();
    await expect(
      conversation.getByText("玄司开发者", { exact: true }).first(),
    ).toBeVisible();
    await expect(conversation).not.toContainText("admin-test@example.invalid");
  });

  test(`${side}失败重试沿用正文与幂等编号，明确改写生成新编号`, async ({
    page,
  }) => {
    const { path, prefix } = await accountChat(page, admin);
    const requests: { key: string; body: Record<string, unknown> }[] = [];
    await page.route(
      `**/api/v1${prefix}/${threadId}/messages`,
      async (route) => {
        if (route.request().method() !== "POST") return route.fallback();
        requests.push({
          key: route.request().headers()["idempotency-key"],
          body: route.request().postDataJSON() as Record<string, unknown>,
        });
        return route.fulfill({
          status: 503,
          json: { error: { code: "UNAVAILABLE", message: "测试发送中断" } },
        });
      },
    );
    await page.goto(path);
    await page.getByRole("button", { name: /账号测试问题/ }).click();
    const input = page.getByLabel("消息内容", { exact: true });
    await input.fill("第一次发送的正文");
    await page.getByRole("button", { name: "发送消息", exact: true }).click();
    await expect(page.getByText("测试发送中断", { exact: true })).toBeVisible();
    await expect(input).toHaveValue("第一次发送的正文");
    await expect(input).toBeDisabled();
    await page.getByRole("button", { name: "重试发送", exact: true }).click();
    await expect.poll(() => requests.length).toBe(2);
    expect(requests[0]).toEqual(requests[1]);
    await page
      .getByRole("button", { name: "改写为新消息", exact: true })
      .click();
    await input.fill("明确改写后的正文");
    await page.getByRole("button", { name: "发送消息", exact: true }).click();
    await expect.poll(() => requests.length).toBe(3);
    expect(requests[2].key).not.toBe(requests[0].key);
    expect(requests[2].body.body).toBe("明确改写后的正文");
  });

  for (const status of [401, 403]) {
    test(`${side}读取${status}清除所有会话私人正文`, async ({ page }) => {
      const { path, state } = await accountChat(page, admin);
      state.threads.push(chatThread(otherThreadId, "第二个私有问题"));
      await page.goto(path);
      await page.getByRole("button", { name: /账号测试问题/ }).click();
      await expect(
        page.getByText("开发者的私有答复", { exact: true }).last(),
      ).toBeVisible();
      await page
        .getByLabel("消息内容", { exact: true })
        .fill("未发出的私人草稿");
      state.messageStatus = status;
      await page.getByRole("button", { name: "刷新会话", exact: true }).click();
      await expect(
        page.getByText("会话权限已失效，请重新登录后查看。", { exact: false }),
      ).toBeVisible();
      await expect(
        page.getByText("开发者的私有答复", { exact: true }),
      ).toHaveCount(0);
      await expect(
        page.getByText("最初的问题正文", { exact: true }),
      ).toHaveCount(0);
      await expect(page.getByLabel("消息内容", { exact: true })).toHaveCount(0);
      await expect(
        page.getByRole("button", { name: /第二个私有问题/ }),
      ).toHaveCount(0);
    });
  }

  test(`${side}404只关闭失效会话，其他会话仍能查看`, async ({ page }) => {
    const { path, state } = await accountChat(page, admin);
    state.threads.push(chatThread(otherThreadId, "第二个私有问题"));
    await page.goto(`${path}?id=${threadId}`);
    await expect(page.getByLabel("消息内容", { exact: true })).toBeVisible();
    state.messageStatus = 404;
    await page.getByRole("button", { name: "刷新会话", exact: true }).click();
    await expect(page.getByRole("log", { name: "聊天记录" })).toHaveCount(0);
    state.messageStatus = 200;
    await page.getByRole("button", { name: /第二个私有问题/ }).click();
    await expect(page.getByLabel("消息内容", { exact: true })).toBeVisible();
  });

  for (const width of [320, 390, 768, 1440]) {
    test(`${side}${width}px长昵称长URL聊天布局不横溢，手机可返回列表`, async ({
      page,
    }) => {
      const { path, state } = await accountChat(page, admin);
      state.threads[0].participant.displayName =
        "很长的账号昵称用于检查手机聊天布局";
      state.conversation.participant.displayName =
        state.threads[0].participant.displayName;
      state.conversation.messages[0].body = `https://example.invalid/${"longpath".repeat(90)}`;
      await page.setViewportSize({ width, height: 844 });
      await page.goto(path);
      await page.getByRole("button", { name: /账号测试问题/ }).click();
      await expect(page.getByLabel("消息内容", { exact: true })).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      if (width <= 640) {
        await page
          .getByRole("button", { name: "返回会话列表", exact: true })
          .click();
        await expect(
          page.getByRole("button", { name: /账号测试问题/ }),
        ).toBeVisible();
        await expect(
          page.getByLabel("消息内容", { exact: true }),
        ).not.toBeVisible();
      }
    });
  }
}

test("列表自动同步新消息，仅已展示的消息发送已读水位", async ({ page }) => {
  const { path, state } = await accountChat(page);
  await page.goto(`${path}?id=${threadId}`);
  await expect(
    page.getByText("开发者的私有答复", { exact: true }).last(),
  ).toBeVisible();
  await page
    .getByRole("log")
    .getByText("开发者的私有答复", { exact: true })
    .evaluate((element) => element.scrollIntoView({ block: "center" }));
  await expect
    .poll(() => state.reads.some((read) => read.messageId === messageId))
    .toBe(true);
  const nextId = "30000000-0000-4000-8000-000000000002";
  expect(state.reads.some((read) => read.messageId === nextId)).toBe(false);
  state.conversation.messages.push(chatMessage("刚刚到达的新回复", nextId));
  state.threads[0].lastMessage = chatMessage("刚刚到达的新回复", nextId);
  state.threads[0].updatedAt = "2026-10-24T02:00:00Z";
  await expect(
    page.getByText("刚刚到达的新回复", { exact: true }).last(),
  ).toBeVisible({ timeout: 15000 });
  // 新回复可以已渲染但仍在页面视口外，只有真正滚到消息才确认已读。
  await page
    .getByRole("log")
    .getByText("刚刚到达的新回复", { exact: true })
    .evaluate((element) => element.scrollIntoView({ block: "center" }));
  await expect
    .poll(() => state.reads.some((read) => read.messageId === nextId))
    .toBe(true);
});

test("已读请求失败不能清除可重试的私有聊天", async ({ page }) => {
  const { path, state } = await accountChat(page);
  state.readStatus = 503;
  await page.goto(`${path}?id=${threadId}`);
  await expect(
    page.getByText("开发者的私有答复", { exact: true }).last(),
  ).toBeVisible();
  await expect(page.getByLabel("消息内容", { exact: true })).toBeEnabled();
});

test("账号请求失败不显示其他人会话或降级为访客发送", async ({ page }) => {
  const { path } = await accountChat(page);
  await page.route("**/api/v1/me/feedback?*", (route) =>
    route.fulfill({
      status: 503,
      json: { error: { code: "UNAVAILABLE", message: "我的反馈读取失败" } },
    }),
  );
  await page.goto(path);
  await expect(
    page.getByText("我的反馈读取失败", { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("消息内容", { exact: true })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "提交反馈", exact: true }),
  ).toHaveCount(0);
});

test("隐藏标签页暂停读取，恢复可见立即同步新回复", async ({ page }) => {
  await page.clock.install();
  const { path, state } = await accountChat(page);
  await page.goto(`${path}?id=${threadId}`);
  await expect(page.getByLabel("消息内容", { exact: true })).toBeVisible();
  await page
    .getByRole("log")
    .getByText("开发者的私有答复", { exact: true })
    .evaluate((element) => element.scrollIntoView({ block: "center" }));
  await expect.poll(() => state.reads.length).toBeGreaterThan(0);
  // 用可控制的浏览器可见性事件替代窗口管理器，避免 CI 中失焦标签页不稳定。
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => true,
    });
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "hidden",
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  const reads = state.messageRequests;
  const nextId = "30000000-0000-4000-8000-000000000003";
  state.threads[0].lastMessage = chatMessage("恢复后出现的回复", nextId);
  state.conversation.messages.push(chatMessage("恢复后出现的回复", nextId));
  await page.clock.fastForward(6000);
  expect(state.messageRequests).toBe(reads);
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => false,
    });
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "visible",
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(
    page.getByText("恢复后出现的回复", { exact: true }).last(),
  ).toBeVisible();
});

test("发送期间暂停会话读取，迟到读取不能覆盖已发送消息", async ({ page }) => {
  await page.clock.install();
  const { path, prefix, state } = await accountChat(page);
  let finish: (() => void) | undefined;
  const gate = new Promise<void>((resolve) => {
    finish = resolve;
  });
  await page.route(`**/api/v1${prefix}/${threadId}/messages`, async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    await gate;
    const message = {
      ...chatMessage("发送中的消息", "30000000-0000-4000-8000-000000000004"),
      authorRole: "USER",
      authorName: "星河测试者",
    };
    state.conversation.messages.push(message);
    return route.fulfill({
      json: { data: { message, feedbackStatus: "NEW" } },
    });
  });
  await page.goto(`${path}?id=${threadId}`);
  await page.getByLabel("消息内容", { exact: true }).fill("发送中的消息");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await expect(page.getByLabel("消息内容", { exact: true })).toBeDisabled();
  const reads = state.messageRequests;
  await page.clock.fastForward(6000);
  expect(state.messageRequests).toBe(reads);
  finish?.();
  await expect(page.getByText("消息已发送。", { exact: true })).toBeVisible();
  await expect(
    page
      .getByRole("log", { name: "聊天记录" })
      .getByText("发送中的消息", { exact: true }),
  ).toBeVisible();
});

test("登录用户提交绑定账号并通过个人会话入口继续沟通", async ({ page }) => {
  const { state } = await accountChat(page);
  let submittedId = "";
  const requests: Record<string, unknown>[] = [];
  await page.route(/\/api\/v1\/me\/feedback$/, async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    requests.push(route.request().postDataJSON() as Record<string, unknown>);
    submittedId = route.request().headers()["idempotency-key"];
    state.threads[0].id = submittedId;
    state.conversation.id = submittedId;
    return route.fulfill({
      status: 201,
      json: {
        data: {
          id: submittedId,
          status: "NEW",
          createdAt: "2026-10-24T00:00:00Z",
        },
      },
    });
  });
  await page.goto("/#feedback");
  const section = page.locator("#feedback");
  await section
    .getByRole("textbox", { name: "问题或建议", exact: true })
    .fill("登录后提交的问题可以继续聊天。");
  await section.getByRole("button", { name: "提交反馈", exact: true }).click();
  // click只确认事件已触发，须等实际POST处理后再读取回执编号作为预期地址。
  await expect.poll(() => requests.length).toBe(1);
  await expect(
    section.getByRole("link", { name: /打开反馈会话/ }),
  ).toHaveAttribute("href", `/dashboard/feedback?id=${submittedId}`);
  expect(requests[0]).not.toHaveProperty("managementToken");
  expect(requests[0]).not.toHaveProperty("userId");
  await section.getByRole("link", { name: /打开反馈会话/ }).click();
  await expect(page.getByLabel("消息内容", { exact: true })).toBeVisible();
});

test("账号提交遇到会话失效不能悄悄转换为访客重发", async ({ page }) => {
  await accountChat(page);
  let guestSubmissions = 0;
  await page.route(/\/api\/v1\/me\/feedback$/, (route) =>
    route.fulfill({
      status: 401,
      json: { error: { code: "UNAUTHORIZED", message: "会话已失效" } },
    }),
  );
  await page.route(/\/api\/v1\/feedback$/, (route) => {
    guestSubmissions++;
    return route.fulfill({
      status: 503,
      json: { error: { code: "UNAVAILABLE", message: "不应访客提交" } },
    });
  });
  await page.goto("/#feedback");
  const section = page.locator("#feedback");
  await section
    .getByRole("textbox", { name: "问题或建议", exact: true })
    .fill("属于账号的私人问题");
  await section.getByRole("button", { name: "提交反馈", exact: true }).click();
  await expect(section.getByRole("alert")).toBeVisible();
  expect(guestSubmissions).toBe(0);
  await expect(
    section.getByRole("heading", { name: "反馈已收到", exact: true }),
  ).toHaveCount(0);
});

test("未打开的会话保留未读，不擅自标记已读", async ({ page }) => {
  const { path, state } = await accountChat(page);
  await page.goto(path);
  await expect(page.getByLabel("1 条未读消息", { exact: true })).toBeVisible();
  expect(state.reads).toHaveLength(0);
  expect(state.messageRequests).toBe(0);
});

test("发送取消正在进行的读取，迟到旧正文不能覆盖新回执", async ({ page }) => {
  const { path, prefix } = await accountChat(page);
  await page.goto(`${path}?id=${threadId}`);
  await expect(page.getByLabel("消息内容", { exact: true })).toBeVisible();
  let started = false;
  let finish: (() => void) | undefined;
  const gate = new Promise<void>((resolve) => {
    finish = resolve;
  });
  await page.route(
    `**/api/v1${prefix}/${threadId}/messages*`,
    async (route) => {
      if (route.request().method() === "GET") {
        started = true;
        await gate;
        return route.fulfill({
          json: {
            data: { ...chatConversation(), description: "迟到的旧正文" },
            meta: { nextCursor: null },
          },
        });
      }
      return route.fulfill({
        status: 201,
        json: {
          data: {
            message: {
              ...chatMessage("新消息必须保留"),
              id: "30000000-0000-4000-8000-000000000009",
              authorRole: "USER",
            },
            feedbackStatus: "NEW",
          },
        },
      });
    },
  );
  await page.getByRole("button", { name: "刷新会话", exact: true }).click();
  await expect.poll(() => started).toBe(true);
  await page.getByLabel("消息内容", { exact: true }).fill("新消息必须保留");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await expect(page.getByText("消息已发送。", { exact: true })).toBeVisible();
  finish?.();
  await expect(
    page
      .getByRole("log", { name: "聊天记录" })
      .getByText("新消息必须保留", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("迟到的旧正文", { exact: true })).toHaveCount(0);
});

test("账号没有反馈时显示空状态和提交入口", async ({ page }) => {
  const { path, state } = await accountChat(page);
  state.threads = [];
  await page.goto(path);
  await expect(page.getByText(/还没有反馈会话/)).toBeVisible();
  await expect(
    page.getByRole("link", { name: /提交新的反馈/ }),
  ).toHaveAttribute("href", "/#feedback");
});

test("管理员收到访客一次性反馈仅收件，不冒充账号聊天", async ({ page }) => {
  const { path, state } = await accountChat(page, true);
  state.threads[0].participant = { kind: "GUEST", displayName: "访客" };
  state.threads[0].canReply = false;
  state.conversation.participant = { kind: "GUEST", displayName: "访客" };
  state.conversation.canReply = false;
  await page.goto(`${path}?id=${threadId}`);
  await expect(page.getByText(/访客单次反馈：仅收件/)).toBeVisible();
  await expect(page.getByLabel("消息内容", { exact: true })).toHaveCount(0);
});

test("持旧链接显式关联账号后进入个人会话，旧管理凭据不再可用", async ({
  page,
}) => {
  await accountChat(page);
  const token = "a".repeat(64);
  let claimed = false;
  const claims: Record<string, unknown>[] = [];
  await page.route(`**/api/v1/feedback/${threadId}/management`, (route) =>
    route.fulfill(
      claimed
        ? {
            status: 403,
            json: { error: { code: "FORBIDDEN", message: "原管理凭据已失效" } },
          }
        : {
            json: {
              data: {
                id: threadId,
                moderationStatus: "PENDING",
                canWithdraw: true,
                githubIssueUrl: "",
              },
            },
          },
    ),
  );
  await page.route(`**/api/v1/me/feedback/${threadId}/claim`, async (route) => {
    claims.push(route.request().postDataJSON() as Record<string, unknown>);
    claimed = true;
    return route.fulfill({ json: { data: chatThread() } });
  });
  const link = `/feedback/manage#id=${threadId}&key=${threadId}&token=${token}`;
  await page.goto(link);
  await expect(page.getByText(/关联后，原管理链接将失效/)).toBeVisible();
  await page
    .getByRole("button", { name: "关联到我的账号", exact: true })
    .click();
  await expect(page).toHaveURL(
    new RegExp(`/dashboard/feedback\\?id=${threadId}$`),
  );
  await expect(page.getByLabel("消息内容", { exact: true })).toBeVisible();
  expect(claims).toEqual([{ managementToken: token }]);
  await page.goto(link);
  await page.getByRole("button", { name: "查看最新状态", exact: true }).click();
  await expect(
    page.getByText("原管理凭据已失效", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "查看对话", exact: true }),
  ).toHaveCount(0);
});

for (const moderationStatus of ["WITHDRAWN", "WITHDRAWAL_REQUESTED"]) {
  test(`账号撤回${moderationStatus}立即清理聊天正文及列表摘要`, async ({
    page,
  }) => {
    const { path, state } = await accountChat(page);
    await page.route(
      `**/api/v1/me/feedback/${threadId}/withdrawal`,
      (route) => {
        state.conversation = {
          ...state.conversation,
          description: "",
          messages: [],
          moderationStatus,
          canReply: false,
        };
        state.threads[0] = {
          ...state.threads[0],
          preview: "",
          lastMessage: null,
          unreadCount: 0,
          moderationStatus,
          canReply: false,
        };
        return route.fulfill({
          json: {
            data: {
              id: threadId,
              moderationStatus,
              canWithdraw: false,
              githubIssueUrl: "",
            },
          },
        });
      },
    );
    await page.goto(`${path}?id=${threadId}`);
    await expect(page.getByRole("log", { name: "聊天记录" })).toContainText(
      "开发者的私有答复",
    );
    await page
      .getByRole("button", { name: "撤回这条反馈", exact: true })
      .click();
    await page.getByRole("button", { name: "确认撤回", exact: true }).click();
    await expect(
      page.getByText(
        moderationStatus === "WITHDRAWN"
          ? "反馈已撤回，问题内容和私有对话已清理。"
          : "撤回申请已提交，私有对话已清理；已公开的原问题仍需管理员处理。",
        { exact: true },
      ),
    ).toBeVisible();
    await expect(
      page.getByText("开发者的私有答复", { exact: true }),
    ).toHaveCount(0);
    await expect(page.getByText("最初的问题正文", { exact: true })).toHaveCount(
      0,
    );
    await expect(page.getByLabel("消息内容", { exact: true })).toHaveCount(0);
  });
}

test("账号撤回失败保留会话和未发送草稿", async ({ page }) => {
  const { path } = await accountChat(page);
  await page.route(`**/api/v1/me/feedback/${threadId}/withdrawal`, (route) =>
    route.fulfill({
      status: 503,
      json: { error: { code: "UNAVAILABLE", message: "撤回暂时中断" } },
    }),
  );
  await page.goto(`${path}?id=${threadId}`);
  await page.getByLabel("消息内容", { exact: true }).fill("尚未发送的草稿");
  await page.getByRole("button", { name: "撤回这条反馈", exact: true }).click();
  await page.getByRole("button", { name: "确认撤回", exact: true }).click();
  await expect(page.getByText("撤回暂时中断", { exact: true })).toBeVisible();
  await expect(page.getByRole("log", { name: "聊天记录" })).toContainText(
    "开发者的私有答复",
  );
  await expect(page.getByLabel("消息内容", { exact: true })).toHaveValue(
    "尚未发送的草稿",
  );
});
