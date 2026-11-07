import { createAssemblyFrame } from "./assembly-frame";

// 仅让实际出现的标题、面板和 shadcn 控件参与组装，不改写 React 管理的文字或表单。
const targets = [
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "p",
  "article",
  "li",
  "dt",
  "dd",
  "th",
  "td",
  "blockquote",
  "figcaption",
  "pre",
  "label",
  "button",
  'input:not([type="hidden"])',
  "textarea",
  "select",
  '[role="alert"]',
  '[role="status"]',
  'a:not([data-slot="button"]):not(:is(p, li, dt, dd, figcaption) *)',
  ':is(span, strong, small, em, b):not(:empty):not(:has(*)):not(:is(p, h1, h2, h3, h4, h5, h6, a, button, label, li, dt, dd, th, td, figcaption, pre, [role="button"]) *)',
  'img:not([alt=""]):not([aria-hidden="true"]):not(:is(a, button) *)',
  ".page-heading",
  ".field",
  ".panel",
  "[data-assembly]",
  '[data-slot="card"]',
  '[data-slot="card-title"]',
  '[data-slot="card-description"]',
  '[data-slot="button"]',
  '[data-slot="input"]',
  '[data-slot="textarea"]',
  '[data-slot="checkbox"]',
  '[data-slot="select-trigger"]',
  '[data-slot="tabs-list"]',
  '[data-slot="tabs-trigger"]',
  '[data-slot="progress"]',
  '[data-slot="accordion-trigger"]',
  '[data-slot="collapsible-trigger"]',
].join(",");

type Running = {
  target: HTMLElement;
  frame: ReturnType<typeof createAssemblyFrame>;
  animations: Animation[];
};

export function startAssembly(roots: HTMLElement[], layer: HTMLElement) {
  const registered = new WeakSet<Element>();
  const queue: HTMLElement[] = [];
  const running = new Set<Running>();
  let stopped = false;
  let updateRequest = 0;
  let pumpTimer = 0;

  function show(target: HTMLElement) {
    target.setAttribute("data-assembly-ready", "");
  }

  // 先开始绘制容器，再依次组装内部标题和控件。
  function waitingAncestor(target: HTMLElement) {
    let parent = target.parentElement?.closest(targets);
    while (parent) {
      const ancestor = parent;
      if (!roots.some((root) => root.contains(ancestor))) break;
      if (
        ancestor instanceof HTMLElement &&
        !ancestor.hasAttribute("data-assembly-ready")
      )
        return ancestor;
      parent = ancestor.parentElement?.closest(targets);
    }
    return null;
  }

  function finish(item: Running) {
    if (!running.delete(item)) return;
    item.frame.element.remove();
    pump();
  }

  // 选框从上边向下展开，随后组件和文字才逐步显现。
  function play(target: HTMLElement) {
    const box = target.getBoundingClientRect();
    if (
      !target.isConnected ||
      box.width < 2 ||
      box.height < 2 ||
      box.bottom < 0 ||
      box.top > innerHeight ||
      typeof target.animate !== "function" ||
      target.contains(document.activeElement)
    ) {
      show(target);
      return false;
    }

    const frame = createAssemblyFrame(target, layer);
    const frameAnimation = frame.element.animate(
      [
        {
          transform: "scaleY(0.02)",
          opacity: 0,
          easing: "cubic-bezier(0.22, 1, 0.36, 1)",
        },
        { transform: "scaleY(1)", opacity: 1, offset: 0.4 },
        { transform: "scaleY(1)", opacity: 1, offset: 0.75 },
        { transform: "scaleY(1)", opacity: 0 },
      ],
      { duration: 480, easing: "linear", fill: "backwards" },
    );
    const heading = target.matches("h1, h2");
    const count = heading
      ? Math.max(6, Math.min(24, (target.textContent ?? "").length))
      : 6;
    show(target);
    const reveal = target.animate(
      heading
        ? [{ clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0 0 0)" }]
        : [{ opacity: 0 }, { opacity: 1 }],
      {
        duration: 240,
        delay: 200,
        fill: "backwards",
        easing: heading ? `steps(${count}, end)` : "ease-out",
      },
    );
    const item = { target, frame, animations: [frameAnimation, reveal] };
    running.add(item);
    void Promise.allSettled(
      item.animations.map((animation) => animation.finished),
    ).then(() => finish(item));
    return true;
  }

  // 每次成批读取位置，优先处理最上方一行，再按从左到右排列。
  function nextTarget() {
    const positions = queue.map((target) => ({
      target,
      box: target.getBoundingClientRect(),
    }));
    const top = Math.min(...positions.map(({ box }) => box.top));
    const row = positions.filter(({ box }) => box.top <= top + 24);
    row.sort((a, b) => a.box.left - b.box.left || a.box.top - b.box.top);
    return row[0]?.target;
  }

  function schedulePump() {
    if (stopped || pumpTimer || running.size >= 6 || !queue.length) return;
    pumpTimer = window.setTimeout(() => {
      pumpTimer = 0;
      pump();
    }, 50);
  }

  function pump() {
    if (stopped || pumpTimer || running.size >= 6) return;
    while (queue.length) {
      let target = nextTarget();
      if (!target) return;
      let ancestor = waitingAncestor(target);
      while (ancestor) {
        if (queue.includes(ancestor)) target = ancestor;
        else {
          // 父容器若不在可视队列中，立即显示，避免子组件永久等待。
          show(ancestor);
          intersection.unobserve(ancestor);
        }
        ancestor = waitingAncestor(target);
      }
      queue.splice(queue.indexOf(target), 1);
      if (!play(target)) continue;
      schedulePump();
      return;
    }
  }

  const intersection = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (
          !entry.isIntersecting ||
          !(entry.target instanceof HTMLElement) ||
          entry.target.hasAttribute("data-assembly-ready")
        )
          continue;
        intersection.unobserve(entry.target);
        queue.push(entry.target);
      }
      pump();
    },
    { threshold: 0.05 },
  );

  function register(element: Element) {
    if (
      !(element instanceof HTMLElement) ||
      registered.has(element) ||
      element.hasAttribute("data-assembly-ready")
    )
      return;
    // 导航只绘制整体，切换页面时新建的链接和菜单项直接显示。
    if (element.closest(".site-header") && !element.matches(".nav-inner"))
      return;
    registered.add(element);
    intersection.observe(element);
  }
  function scan(element: Element) {
    if (element.matches(targets)) register(element);
    element.querySelectorAll(targets).forEach(register);
  }

  // 异步内容只在进入页面时注册，后续表单输入不会触发重新扫描。
  const changes = new MutationObserver((records) => {
    for (const record of records) {
      for (const node of record.addedNodes)
        if (node instanceof Element) scan(node);
    }
  });
  for (const root of roots) {
    scan(root);
    changes.observe(root, { childList: true, subtree: true });
  }

  function updateFrames() {
    if (!running.size || updateRequest) return;
    // 同一帧先批量读取位置，再更新选框，避免滚动时反复触发布局。
    updateRequest = requestAnimationFrame(() => {
      updateRequest = 0;
      const boxes = Array.from(running, (item) => ({
        item,
        box: item.target.getBoundingClientRect(),
      }));
      for (const { item, box } of boxes) item.frame.update(box);
    });
  }
  function releaseFrames() {
    if (updateRequest) cancelAnimationFrame(updateRequest);
    updateRequest = 0;
    if (pumpTimer) clearTimeout(pumpTimer);
    pumpTimer = 0;
    for (const target of queue) show(target);
    queue.length = 0;
    for (const item of running) {
      for (const animation of item.animations) animation.cancel();
      item.frame.element.remove();
    }
    running.clear();
  }
  function onVisibilityChange() {
    if (document.hidden) releaseFrames();
  }

  // 操作时只释放当前控件及其容器，其他内容继续按顺序绘制。
  function releaseInteraction(event: Event) {
    if (!(event.target instanceof Element)) return;
    const element = event.target;
    if (element === document.body || element === document.documentElement)
      return;
    const control = element.closest(
      "a, button, input, textarea, select, label, [role='button']",
    );
    const related = (target: HTMLElement) =>
      target.contains(element) || Boolean(control?.contains(target));
    for (let index = queue.length - 1; index >= 0; index -= 1) {
      const target = queue[index];
      if (!related(target)) continue;
      show(target);
      queue.splice(index, 1);
    }
    for (const item of running) {
      if (!related(item.target)) continue;
      for (const animation of item.animations) animation.cancel();
      item.frame.element.remove();
      running.delete(item);
    }
    let ancestor = element.closest(targets);
    while (ancestor && roots.some((root) => root.contains(ancestor))) {
      if (ancestor instanceof HTMLElement) {
        show(ancestor);
        registered.add(ancestor);
        intersection.unobserve(ancestor);
      }
      ancestor = ancestor.parentElement?.closest(targets) ?? null;
    }
    pump();
  }

  // 用户开始操作时让出视觉焦点；覆盖层始终不可点击。
  window.addEventListener("scroll", updateFrames, { passive: true });
  window.addEventListener("resize", updateFrames);
  window.addEventListener("pointerdown", releaseInteraction, { passive: true });
  window.addEventListener("keydown", releaseInteraction);
  window.addEventListener("focusin", releaseInteraction);
  document.addEventListener("visibilitychange", onVisibilityChange);
  console.debug("[页面组装] 已启用分段呈现");

  return () => {
    stopped = true;
    intersection.disconnect();
    changes.disconnect();
    window.removeEventListener("scroll", updateFrames);
    window.removeEventListener("resize", updateFrames);
    window.removeEventListener("pointerdown", releaseInteraction);
    window.removeEventListener("keydown", releaseInteraction);
    window.removeEventListener("focusin", releaseInteraction);
    document.removeEventListener("visibilitychange", onVisibilityChange);
    releaseFrames();
  };
}
