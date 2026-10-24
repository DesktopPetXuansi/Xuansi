import { z } from "zod";
const errorSchema = z.object({
  error: z.object({ message: z.string(), code: z.string() }),
  requestId: z.string().optional(),
});
type RequestOptions = {
  idempotencyKey?: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  expectedAccountId?: string;
};
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
  options?: RequestOptions,
): Promise<T> {
  const headers: Record<string, string> = {};
  // 只作为会话匹配护栏，防止跨标签页切号后旧操作误归属新账号。
  if (options?.expectedAccountId)
    headers["X-Feedback-Account"] = options.expectedAccountId;
  if (method !== "GET") {
    const csrf = await api<{ token: string }>("/auth/csrf");
    headers["X-CSRF-Token"] = csrf.token;
    headers["Content-Type"] = "application/json";
    // 提交结果不确定时允许调用方复用请求编号，避免网络重试产生重复反馈。
    headers["Idempotency-Key"] = options?.idempotencyKey ?? crypto.randomUUID();
  }
  // 只给读取设置时限；写入结果不确定时仍由原有幂等流程恢复。
  const timeout =
    method === "GET"
      ? AbortSignal.timeout(options?.timeoutMs ?? 15000)
      : undefined;
  const signal =
    options?.signal && timeout
      ? AbortSignal.any([options.signal, timeout])
      : (options?.signal ?? timeout);
  let response: Response;
  let payload: unknown;
  try {
    response = await fetch(`/api/v1${path}`, {
      method,
      headers,
      credentials: "include",
      cache: "no-store",
      signal,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (response.status === 204) return undefined as T;
    payload = await response.json().catch((failure: unknown) => {
      if (signal?.aborted) throw failure;
      return null;
    });
  } catch (failure) {
    // 切换筛选或页面的取消交给查询库处理，不显示成网络故障。
    if (options?.signal?.aborted) throw failure;
    if (timeout?.aborted) {
      console.warn("[公开读取] 请求超时，可重试");
      throw new ApiError(
        "读取超时，请检查网络后重新加载。",
        408,
        "REQUEST_TIMEOUT",
      );
    }
    throw new ApiError("暂时无法连接服务，请稍后重试。", 0);
  }
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
      meta: z
        .object({
          nextCursor: z.string().nullable().optional(),
          total: z.number().int().nonnegative().optional(),
        })
        .optional(),
    })
    .safeParse(payload);
  if (!envelope.success) throw new ApiError("服务返回了无法识别的数据。", 502);
  return (includeMeta ? envelope.data : envelope.data.data) as T;
}
export function apiPage<T>(
  path: string,
  options?: Pick<RequestOptions, "signal">,
) {
  return api<{
    data: T[];
    meta?: { nextCursor?: string | null; total?: number };
  }>(path, "GET", undefined, true, options);
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
