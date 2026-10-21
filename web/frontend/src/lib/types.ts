import type { components } from "../../../contracts/generated/api";
// 公共实体直接引用OpenAPI生成类型，避免网站与Go协议漂移。
export type User = components["schemas"]["User"];
export type AuthConfig = components["schemas"]["AuthConfig"];
export type Resource = components["schemas"]["Resource"];
export type Version = components["schemas"]["ResourceVersion"];
export type Upload = components["schemas"]["Upload"];
export type Release = components["schemas"]["Release"];
export type Feedback = components["schemas"]["Feedback"];
export type FeedbackInput = components["schemas"]["FeedbackInput"];
export type FeedbackReceipt = components["schemas"]["FeedbackReceipt"];
export type FeedbackManagement = components["schemas"]["FeedbackManagement"];
export type FeedbackModerationInput =
  components["schemas"]["FeedbackModerationInput"];
export type FeedbackDiagnostics = components["schemas"]["FeedbackDiagnostics"];
export interface Session {
  id: string;
  createdAt: string;
  lastSeenAt: string;
  isCurrent?: boolean;
  deviceLabel?: string;
}
export const kinds: Record<string, string> = {
  MODEL: "Live2D 模型",
  MOTION: "动作",
  EXPRESSION: "表情",
  IMAGE: "静态形象",
  ANIMATION: "透明动图",
};
export const statuses: Record<string, string> = {
  PENDING: "等待校验",
  VALIDATING: "正在校验",
  READY: "校验完成",
  FAILED: "校验失败",
  CREATED: "等待上传",
  UPLOADED: "已上传",
  ACTIVE: "正常",
  HIDDEN: "已隐藏",
  DISABLED: "已停用",
  PRIVATE: "私有",
  PUBLIC: "公开",
  CANCELLED: "已取消",
  EXPIRED: "已过期",
  COMPATIBLE: "兼容",
  UNTESTED: "待客户端试载",
  INCOMPATIBLE: "不兼容",
};
export function bytes(value = 0) {
  return value < 1048576
    ? `${(value / 1024).toFixed(1)} KB`
    : `${(value / 1048576).toFixed(1)} MB`;
}
