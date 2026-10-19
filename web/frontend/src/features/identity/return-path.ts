// 只解析站内返回地址，不发出请求；URL 会同时识别浏览器对反斜杠的归一化。
const localOrigin = "https://xuansi.invalid";

export function returnPath(value: string | null) {
  if (!value?.startsWith("/") || value.startsWith("//")) return "/dashboard";
  try {
    const url = new URL(value, localOrigin);
    // 点段归一化也可能把 /a/..//host 变成协议相对地址，返回前再次拒绝。
    return url.origin === localOrigin && !url.pathname.startsWith("//")
      ? `${url.pathname}${url.search}${url.hash}`
      : "/dashboard";
  } catch {
    return "/dashboard";
  }
}

export function authHref(path: "/login" | "/register" | "/forgot-password" | "/verify-email", destination: string) {
  return `${path}?${new URLSearchParams({ returnTo: returnPath(destination) })}`;
}
