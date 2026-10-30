(() => {
  "use strict";

  // 公开页面白名单避免将账号、反馈管理链接和私有资源标识交给统计服务。
  const publicPaths = new Set([
    "/", "/features", "/download", "/changelog", "/faq", "/resources",
    "/docs", "/docs/getting-started", "/docs/appearance", "/docs/chat",
    "/docs/account", "/docs/troubleshooting", "/licenses", "/privacy", "/terms",
  ]);
  let websiteId;

  // 只发送匿名浏览量及约定的安装包点击；重建载荷以排除身份和任意自定义数据。
  window.xuansiAnalyticsBeforeSend = (type, payload) => {
    if (type !== "event" || !websiteId || !payload ||
        !publicPaths.has(window.location.pathname) || typeof payload.url !== "string") return false;
    let page;
    try {
      page = new URL(payload.url, window.location.origin);
    } catch {
      return false;
    }
    if (page.origin !== window.location.origin || !publicPaths.has(page.pathname)) return false;
    const clean = {
      website: websiteId,
      url: page.pathname,
      hostname: window.location.hostname,
      ...(typeof payload.language === "string" && /^[a-z-]{1,35}$/i.test(payload.language)
        ? { language: payload.language } : {}),
      ...(typeof payload.screen === "string" && /^\d{1,5}x\d{1,5}$/.test(payload.screen)
        ? { screen: payload.screen } : {}),
      referrer: "",
    };
    if (payload.name !== undefined) {
      if (payload.name !== "installer_download") return false;
      const version = payload.data?.version;
      if (typeof version !== "string" || !/^\d{1,4}\.\d{1,4}\.\d{1,4}$/.test(version)) return false;
      clean.name = "installer_download";
      clean.data = { version, platform: "windows-x64" };
    }
    return clean;
  };

  async function load() {
    // 配置来自公共接口，既不读取用户会话，也不等待统计服务才能显示页面。
    const response = await fetch("/api/v1/analytics/config", {
      credentials: "omit",
      cache: "no-store",
      referrerPolicy: "no-referrer",
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) throw new Error("analytics configuration unavailable");
    const config = (await response.json())?.data;
    if (!config?.enabled) return;
    if (typeof config.websiteId !== "string" ||
        !/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(config.websiteId) ||
        typeof config.scriptUrl !== "string") throw new Error("invalid analytics configuration");
    const source = new URL(config.scriptUrl);
    const localHttp = source.protocol === "http:" &&
      ["localhost", "127.0.0.1", "[::1]"].includes(source.hostname);
    // 同源采集请求可能携带完整 Referer，统计服务必须使用独立来源。
    if (source.origin === window.location.origin ||
        (source.protocol !== "https:" && !localHttp) || source.username || source.password ||
        source.search || source.hash || source.pathname !== "/script.js") {
      throw new Error("invalid analytics script origin");
    }
    websiteId = config.websiteId;
    const script = document.createElement("script");
    script.src = source.href;
    script.async = true;
    script.referrerPolicy = "no-referrer";
    script.setAttribute("data-website-id", websiteId);
    script.setAttribute("data-domains", window.location.hostname);
    script.setAttribute("data-before-send", "xuansiAnalyticsBeforeSend");
    script.setAttribute("data-exclude-search", "true");
    script.setAttribute("data-exclude-hash", "true");
    script.setAttribute("data-do-not-track", "true");
    script.onerror = () => console.warn("[网站统计] 统计脚本未加载，页面与下载仍可使用。");
    document.head.appendChild(script);
  }

  void load().catch(() => console.warn("[网站统计] 统计配置暂不可用，页面与下载仍可使用。"));
})();
