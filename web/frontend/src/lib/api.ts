import { z } from "zod";
const errorSchema = z.object({
  error: z.object({ message: z.string(), code: z.string() }),
  requestId: z.string().optional(),
});
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code = "",
  ) {
    super(message);
  }
}
// 私有数据永不进入浏览器/SSR公共缓存，CSRF令牌仅保留在当前请求。
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
  includeMeta = false,
): Promise<T> {
  const headers: Record<string, string> = {};
  if (method !== "GET") {
    const csrf = await api<{ token: string }>("/auth/csrf");
    headers["X-CSRF-Token"] = csrf.token;
    headers["Content-Type"] = "application/json";
    headers["Idempotency-Key"] = crypto.randomUUID();
  }
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method,
      headers,
      credentials: "include",
      cache: "no-store",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("暂时无法连接服务，请稍后重试。", 0);
  }
  if (response.status === 204) return undefined as T;
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const parsed = errorSchema.safeParse(payload);
    throw new ApiError(
      parsed.success
        ? parsed.data.error.message
        : "服务暂时不可用，请稍后重试。",
      response.status,
      parsed.success ? parsed.data.error.code : "",
    );
  }
  const envelope = z
    .object({
      data: z.unknown(),
      meta: z.object({ nextCursor: z.string().optional() }).optional(),
    })
    .safeParse(payload);
  if (!envelope.success) throw new ApiError("服务返回了无法识别的数据。", 502);
  return (includeMeta ? envelope.data : envelope.data.data) as T;
}
export function apiPage<T>(path: string) {
  return api<{ data: T[]; meta?: { nextCursor?: string } }>(
    path,
    "GET",
    undefined,
    true,
  );
}
export function message(error: unknown) {
  return error instanceof Error ? error.message : "操作失败，请重试。";
}
// 下载地址只允许网站同源路径或HTTP(S)，阻止外部数据产生脚本导航。
export function safeUrl(value: string) {
  try {
    const url = new URL(
      value,
      typeof window === "undefined"
        ? "http://localhost:3000"
        : window.location.origin,
    );
    return ["http:", "https:"].includes(url.protocol) ? url.href : "#";
  } catch {
    return "#";
  }
}
