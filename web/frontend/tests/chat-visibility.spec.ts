import { expect, test } from "@playwright/test";
import { accountChat, threadId } from "./account-feedback-fixtures";

test("非反馈编号的地址参数不发起聊天读取或打开其他会话", async ({ page }) => {
  const { path, state } = await accountChat(page);
  await page.goto(`${path}?id=${encodeURIComponent("../../other/private")}`);
  await expect(
    page.getByText("这条反馈不存在或已无法查看，请从列表选择其他会话。", {
      exact: true,
    }),
  ).toBeVisible();
  expect(state.messageRequests).toBe(0);
  await expect(page.getByLabel("消息内容", { exact: true })).toHaveCount(0);
});

test("聊天末尾离开页面视口时不标已读，真正滚到消息后才确认", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 360 });
  const { path, state } = await accountChat(page);
  await page.goto(`${path}?id=${threadId}`);
  const lastMessage = page
    .getByRole("log", { name: "聊天记录" })
    .getByText("开发者的私有答复", { exact: true });
  await expect(lastMessage).toBeAttached();
  // 消息在内部滚动容器底部，整个容器仍在页面视口外。
  await expect
    .poll(() =>
      lastMessage.evaluate(
        (element) => element.getBoundingClientRect().top > innerHeight,
      ),
    )
    .toBe(true);
  await expect.poll(() => state.reads.length).toBe(0);
  await lastMessage.evaluate((element) =>
    element.scrollIntoView({ block: "center" }),
  );
  await expect.poll(() => state.reads.length).toBeGreaterThan(0);
});
