import { message } from "@/lib/api";
import type { ReactNode } from "react";
// 兼容既有导入路径，所有按钮使用同一个 shadcn 实现与 variant。
export { Button } from "@/components/ui/button";
export function Notice({
  error,
  children,
}: {
  error?: unknown;
  children?: ReactNode;
}) {
  return (
    <div
      className={error ? "notice error" : "notice"}
      role={error ? "alert" : "status"}
    >
      {error ? message(error) : children}
    </div>
  );
}
export function Heading({
  eyebrow,
  title,
  children,
}: {
  eyebrow?: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <header className="page-heading">
      <p className="eyebrow">{eyebrow ?? "XUANSI / 玄司"}</p>
      <h1>{title}</h1>
      {children && <p className="intro">{children}</p>}
    </header>
  );
}
export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}
