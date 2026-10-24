import { z } from "zod";

// 只持久保存独立管理权限，不将反馈正文和联系方式写入浏览器存储。
const credentialsSchema = z.object({
  id: z.string().uuid().optional(),
  managementToken: z.string().regex(/^[a-f0-9]{64}$/),
  idempotencyKey: z.string().uuid(),
});
export type FeedbackCredentials = z.infer<typeof credentialsSchema>;
const storageKey = "xuansi-feedback-management";
export function createCredentials(): FeedbackCredentials {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  // 服务端以幂等编号作为反馈 ID，响应丢失也能用预保存的权限恢复管理。
  const id = crypto.randomUUID();
  return {
    id,
    managementToken: Array.from(bytes, (value) =>
      value.toString(16).padStart(2, "0"),
    ).join(""),
    idempotencyKey: id,
  };
}
export function saveCredentials(value: FeedbackCredentials) {
  try {
    const saved = readSavedCredentials();
    localStorage.setItem(
      storageKey,
      JSON.stringify([
        ...saved.filter((item) => item.idempotencyKey !== value.idempotencyKey),
        value,
      ]),
    );
    return true;
  } catch {
    console.warn("[公众反馈] 浏览器未能保存管理凭据");
    return false;
  }
}
export function readSavedCredentials() {
  const raw: unknown = JSON.parse(localStorage.getItem(storageKey) ?? "[]");
  const list = z.array(credentialsSchema).safeParse(raw);
  if (list.success) return list.data;
  const single = credentialsSchema.safeParse(raw);
  return single.success ? [single.data] : [];
}
// 只清除用户已主动关联的这条旧凭据，不影响同一浏览器的其他旧反馈。
export function forgetCredentials(key: string) {
  try {
    const remaining = readSavedCredentials().filter(
      (item) => item.idempotencyKey !== key,
    );
    if (remaining.length)
      localStorage.setItem(storageKey, JSON.stringify(remaining));
    else localStorage.removeItem(storageKey);
  } catch {
    console.warn("[公众反馈] 旧凭据本机清理未完成，服务器已撤销原权限");
  }
}
export function restoreCredentials() {
  const fragment = new URLSearchParams(window.location.hash.slice(1));
  const fromLink = credentialsSchema.safeParse({
    id: fragment.get("id") ?? undefined,
    managementToken: fragment.get("token"),
    idempotencyKey: fragment.get("key"),
  });
  if (fromLink.success) return fromLink.data;
  // 显式管理链接无效时禁止回退其他记录，避免用户误撤回本机另一条反馈。
  if (["id", "token", "key"].some((key) => fragment.has(key))) return undefined;
  try {
    return readSavedCredentials().at(-1);
  } catch {
    console.warn("[公众反馈] 浏览器管理凭据不可用");
    return undefined;
  }
}
export function managementLink(value: FeedbackCredentials) {
  const fragment = new URLSearchParams({
    token: value.managementToken,
    key: value.idempotencyKey,
  });
  if (value.id) fragment.set("id", value.id);
  return `${window.location.origin}/feedback/manage#${fragment}`;
}
