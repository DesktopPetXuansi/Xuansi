import { expect, test } from "@playwright/test";
import { publicVisitor } from "./public-fixtures";

test("页面脚本尚未加载时，待组装组件不会提前出现", async ({ page }) => {
  await publicVisitor(page);
  let releaseChunks = () => {};
  const chunksReady = new Promise<void>((resolve) => {
    releaseChunks = resolve;
  });
  // 暂停客户端代码，检查服务端 HTML 首次绘制时的真实状态。
  await page.route(/\/_next\/static\/.*\.js(?:\?.*)?$/, async (route) => {
    await chunksReady;
    await route.continue().catch(() => {});
  });
  try {
    await page.goto("/resources", { waitUntil: "commit" });
    const title = page.locator("#main h1");
    const portrait = page.getByRole("img", {
      name: "客户端自带的玄司形象",
    });
    await expect(page.locator(".nav-inner")).toHaveCSS("opacity", "0", {
      timeout: 3000,
    });
    await expect(title).toHaveCSS("opacity", "0", { timeout: 3000 });
    await expect(page.locator(".page-heading .intro")).toHaveCSS(
      "opacity",
      "0",
    );
    await expect(portrait.locator("..")).toHaveCSS("opacity", "0");
  } finally {
    releaseChunks();
  }
});

test("普通文字与图文内容会绘制选框，点击空白处不会跳过余下内容", async ({
  page,
}) => {
  await publicVisitor(page);
  await page.addInitScript(() => {
    const animate = Element.prototype.animate;
    Element.prototype.animate = function (...args) {
      const root = document.documentElement;
      if (this.matches(".nav-inner")) root.dataset.headerStarted = "true";
      if (this.matches(".hero-kicker")) root.dataset.kickerStarted = "true";
      if (this.matches(".hero-description"))
        root.dataset.descriptionStarted = "true";
      if (this.matches(".hero-access")) root.dataset.accessStarted = "true";
      if (this.matches(".library-kind strong"))
        root.dataset.inlineStarted = "true";
      return animate.apply(this, args);
    };
  });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.dataset.headerStarted),
    )
    .toBe("true");
  await page.mouse.click(5, 150);
  await expect
    .poll(() =>
      page.evaluate(() => {
        const data = document.documentElement.dataset;
        return [
          data.kickerStarted,
          data.descriptionStarted,
          data.accessStarted,
        ];
      }),
    )
    .toEqual(["true", "true", "true"]);
  await page.locator(".library-kind strong").first().scrollIntoViewIfNeeded();
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.dataset.inlineStarted),
    )
    .toBe("true");
});

test("选框按从上到下、同一行从左到右的顺序快速绘制", async ({ page }) => {
  await publicVisitor(page);
  await page.addInitScript(() => {
    const animate = Element.prototype.animate;
    Element.prototype.animate = function (...args) {
      const animation = animate.apply(this, args);
      if (
        this instanceof HTMLElement &&
        this.classList.contains("assembly-frame") &&
        this.style.width === "149px"
      ) {
        const root = document.documentElement;
        const point = `${this.style.top},${this.style.left}`;
        root.dataset.frameOrder = [root.dataset.frameOrder, point]
          .filter(Boolean)
          .join("|");
        if (!root.dataset.frameProbeReady) {
          animation.pause();
          animation.currentTime = 80;
          root.dataset.frameProbeReady = "true";
        }
      }
      return animation;
    };
  });
  await page.goto("/docs", { waitUntil: "domcontentloaded" });
  await expect
    .poll(() =>
      page.evaluate(() =>
        document.documentElement.hasAttribute("data-assembly-active"),
      ),
    )
    .toBe(true);
  await page.mouse.click(10, 10);
  await page.evaluate(() => {
    const host = document.createElement("div");
    // 故意逆序插入节点，校验的是屏幕位置而非 DOM 顺序。
    for (const [top, left] of [
      [310, 20],
      [160, 250],
      [160, 20],
    ]) {
      const item = document.createElement("div");
      item.setAttribute("data-assembly", "panel");
      Object.assign(item.style, {
        position: "fixed",
        top: `${top}px`,
        left: `${left}px`,
        width: "149px",
        height: "72px",
      });
      host.append(item);
    }
    document.querySelector("#main")?.append(host);
  });
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.dataset.frameOrder),
    )
    .toBe("160px,20px|160px,250px|310px,20px");
  const frame = page.locator('.assembly-frame[style*="149px"]').first();
  const motion = await frame.evaluate((element) => {
    const transform = new DOMMatrixReadOnly(
      getComputedStyle(element).transform,
    );
    const duration = element
      .getAnimations()[0]
      .effect?.getComputedTiming().duration;
    return { scaleX: transform.m11, scaleY: transform.m22, duration };
  });
  expect(motion.scaleX).toBeCloseTo(1);
  expect(motion.scaleY).toBeLessThan(1);
  expect(motion.duration).toBeLessThanOrEqual(600);
});

test("选框绘制完成前，标题与组件保持隐藏", async ({ page }) => {
  await publicVisitor(page);
  await page.addInitScript(() => {
    const animate = Element.prototype.animate;
    Element.prototype.animate = function (...args) {
      const animation = animate.apply(this, args);
      const title = this.matches("#main h1");
      const portrait =
        this.matches("[data-assembly]") &&
        this.querySelector('img[alt="客户端自带的玄司形象"]');
      if (title || portrait) {
        animation.pause();
        animation.currentTime = 100;
        const frame = document.querySelector(".assembly-frame:last-child");
        const frameAnimation = frame?.getAnimations()[0];
        frameAnimation?.pause();
        if (frameAnimation) frameAnimation.currentTime = 100;
        if (title) document.documentElement.dataset.titleProbeReady = "true";
        if (portrait)
          document.documentElement.dataset.portraitProbeReady = "true";
      }
      return animation;
    };
  });
  await page.goto("/resources", { waitUntil: "domcontentloaded" });
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.dataset.titleProbeReady),
    )
    .toBe("true");
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.dataset.portraitProbeReady),
    )
    .toBe("true");
  const title = page.locator("#main h1");
  const portrait = page
    .getByRole("img", { name: "客户端自带的玄司形象" })
    .locator("..");
  // 将两段动画停在同一时间点，验证选框尚未画完时标题完全不可见。
  await expect(title).toHaveCSS("clip-path", /100%/);
  await expect(portrait).toHaveCSS("opacity", "0");
  await title.evaluate((element) => {
    const animation = element.getAnimations()[0];
    animation.currentTime = 350;
  });
  await portrait.evaluate((element) => {
    const animation = element.getAnimations()[0];
    animation.currentTime = 350;
  });
  await expect(title).not.toHaveCSS("clip-path", /100%/);
  await expect(portrait).not.toHaveCSS("opacity", "0");
});

test("客户端脚本加载失败时正文会自动恢复", async ({ page }) => {
  await publicVisitor(page);
  await page.route(/\/_next\/static\/.*\.js(?:\?.*)?$/, (route) =>
    route.abort(),
  );
  await page.goto("/resources", { waitUntil: "domcontentloaded" });
  const title = page.locator("#main h1");
  await expect(title).toHaveCSS("opacity", "0");
  await expect(title).toHaveCSS("opacity", "1", { timeout: 7000 });
});

test("站内切换页面后，新标题仍会先绘制选框", async ({ page }) => {
  await publicVisitor(page);
  await page.addInitScript(() => {
    const animate = Element.prototype.animate;
    Element.prototype.animate = function (...args) {
      const animation = animate.apply(this, args);
      if (this.matches("#main h1")) {
        document.documentElement.dataset.lastAnimatedHeading =
          this.textContent ?? "";
      }
      return animation;
    };
  });
  await page.goto("/resources");
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.dataset.lastAnimatedHeading),
    )
    .toContain("选一个喜欢的桌面伙伴");
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("link", { name: "使用帮助" })
    .click();
  await expect(page).toHaveURL(/\/docs$/, { timeout: 30000 });
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.dataset.lastAnimatedHeading),
    )
    .toContain("你想先做什么");
});

test("导航栏只在首次进入时绘制，切换页面后保持稳定", async ({ page }) => {
  await publicVisitor(page);
  await page.addInitScript(() => {
    const animate = Element.prototype.animate;
    Element.prototype.animate = function (...args) {
      const root = document.documentElement;
      if (this.closest(".site-header")) {
        const key = root.dataset.navSwitched ? "navAfter" : "navBefore";
        root.dataset[key] = String(Number(root.dataset[key] ?? 0) + 1);
      }
      if (this.matches("#main h1"))
        root.dataset.lastAnimatedHeading = this.textContent ?? "";
      return animate.apply(this, args);
    };
    document.addEventListener(
      "click",
      (event) => {
        if (
          event.target instanceof Element &&
          event.target.closest('.site-header a[href="/resources"]')
        )
          document.documentElement.dataset.navSwitched = "true";
      },
      true,
    );
  });
  await page.goto("/docs", { waitUntil: "domcontentloaded" });
  await expect
    .poll(() =>
      page.evaluate(() => Number(document.documentElement.dataset.navBefore)),
    )
    .toBeGreaterThan(0);
  await expect(page.locator(".nav-inner")).toHaveCSS("opacity", "1");
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("link", { name: "挑选形象" })
    .click();
  await expect(page).toHaveURL(/\/resources$/, { timeout: 30000 });
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.dataset.lastAnimatedHeading),
    )
    .toContain("选一个喜欢的桌面伙伴");
  await expect(
    page.getByRole("navigation", { name: "主导航" }).getByRole("link", {
      name: "挑选形象",
    }),
  ).toHaveCSS("opacity", "1");
  expect(
    await page.evaluate(() =>
      Number(document.documentElement.dataset.navAfter ?? 0),
    ),
  ).toBe(0);
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("link", { name: "使用帮助" })
    .click();
  await expect(page).toHaveURL(/\/docs$/, { timeout: 30000 });
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.dataset.lastAnimatedHeading),
    )
    .toContain("你想先做什么");
  expect(
    await page.evaluate(() =>
      Number(document.documentElement.dataset.navAfter ?? 0),
    ),
  ).toBe(0);
});

test("手机菜单展开时导航项直接显示", async ({ page }) => {
  await publicVisitor(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => {
    const animate = Element.prototype.animate;
    Element.prototype.animate = function (...args) {
      const root = document.documentElement;
      if (root.dataset.menuOpened && this.closest(".site-header"))
        root.dataset.menuAnimations = String(
          Number(root.dataset.menuAnimations ?? 0) + 1,
        );
      return animate.apply(this, args);
    };
    document.addEventListener(
      "click",
      (event) => {
        if (
          event.target instanceof Element &&
          event.target.closest(".site-header .nav-toggle")
        )
          document.documentElement.dataset.menuOpened = "true";
      },
      true,
    );
  });
  await page.goto("/docs", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".nav-inner")).toHaveCSS("opacity", "1");
  await page.getByRole("button", { name: "展开主导航" }).click();
  const link = page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("link", { name: "挑选形象" });
  await expect(link).toBeVisible();
  await expect(link).toHaveCSS("opacity", "1");
  expect(
    await page.evaluate(() =>
      Number(document.documentElement.dataset.menuAnimations ?? 0),
    ),
  ).toBe(0);
});

test("组装动效不显示指针，也不阻挡真实链接", async ({ page }) => {
  await publicVisitor(page);
  // 只记录装饰框是否出现，浏览器不读取或写入真实账号数据。
  await page.addInitScript(() => {
    new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (
            node instanceof HTMLElement &&
            node.classList.contains("assembly-frame")
          ) {
            document.documentElement.dataset.assemblySeen = "true";
          }
        }
      }
    }).observe(document, { childList: true, subtree: true });
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.dataset.assemblySeen),
    )
    .toBe("true");
  const layer = page.locator(".assembly-layer");
  await expect(layer).toHaveAttribute("aria-hidden", "true");
  await expect(layer).toHaveCSS("pointer-events", "none");
  await expect(layer.locator("svg, .pointer")).toHaveCount(0);
  await page
    .getByRole("link", { name: "下载 Windows 客户端", exact: true })
    .click();
  await expect(page).toHaveURL(/\/download$/, { timeout: 30000 });
});

test("减少动态效果时页面直接完整显示", async ({ page }) => {
  await publicVisitor(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/docs");
  await page.waitForLoadState("networkidle");
  await expect(
    page.getByRole("heading", { name: "你想先做什么？" }),
  ).toBeVisible();
  await expect(page.locator(".assembly-layer")).toBeHidden();
  await expect(page.locator(".assembly-frame")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "查看新手步骤" })).toBeVisible();
});

test("组装期间输入框仍可编辑，装饰层不复制输入内容", async ({ page }) => {
  await publicVisitor(page);
  await page.goto("/login");
  const email = page.getByLabel("邮箱", { exact: true });
  await email.click();
  await email.fill("assembly-test@example.invalid");
  await expect(email).toHaveValue("assembly-test@example.invalid");
  await expect(page.locator(".assembly-layer")).not.toContainText(
    "assembly-test@example.invalid",
  );
});

test.describe("脚本不可用", () => {
  test.use({ javaScriptEnabled: false });
  test("帮助内容仍然可读并保留导航", async ({ page }) => {
    await publicVisitor(page);
    await page.goto("/docs");
    await expect(
      page.getByRole("heading", { name: "你想先做什么？" }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "查看新手步骤" }),
    ).toHaveAttribute("href", "/docs/getting-started");
    await expect(page.locator(".assembly-frame")).toHaveCount(0);
  });
});
