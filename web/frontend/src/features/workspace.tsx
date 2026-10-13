"use client";
import { useMe } from "@/components/navigation";
import { Notice } from "@/components/ui";
import Link from "next/link";
import { usePathname } from "next/navigation";
const links = [
  ["/dashboard", "概览"],
  ["/dashboard/resources", "我的资源"],
  ["/dashboard/library", "我的资源库"],
  ["/dashboard/uploads", "上传队列"],
  ["/dashboard/account", "账号设置"],
  ["/dashboard/sessions", "会话与授权"],
];
export function Workspace({
  children,
  admin = false,
}: {
  children: React.ReactNode;
  admin?: boolean;
}) {
  const me = useMe();
  const path = usePathname();
  const items = admin
    ? [
        ["/admin/users", "用户"],
        ["/admin/resources", "资源发布"],
        ["/admin/releases", "客户端版本"],
        ["/admin/jobs", "后台任务"],
        ["/admin/audit", "审计日志"],
      ]
    : links;
  return (
    <div className="container">
      <div className="workspace">
        <aside className="sidebar" aria-label="工作台导航">
          {items.map(([href, label]) => (
            <Link
              href={href}
              key={href}
              aria-current={path === href ? "page" : undefined}
            >
              {label}
            </Link>
          ))}
          {me.data?.role === "ADMIN" && !admin && (
            <Link href="/admin/users">管理后台 ↗</Link>
          )}
          {admin && <Link href="/dashboard">返回工作台</Link>}
        </aside>
        <section>
          {me.isPending ? (
            <Notice>正在检查登录状态…</Notice>
          ) : me.error ? (
            <Notice error={me.error} />
          ) : !me.data ? (
            <Notice>
              请先{" "}
              <Link href={`/login?returnTo=${path}`} className="quiet-link">
                登录
              </Link>{" "}
              后继续。
            </Notice>
          ) : admin && me.data.role !== "ADMIN" ? (
            <Notice>你没有管理后台权限。</Notice>
          ) : (
            children
          )}
        </section>
      </div>
    </div>
  );
}

export * from "./account";
export * from "./library";
export * from "./overview";
export * from "./sessions";
export * from "./upload-queue";
