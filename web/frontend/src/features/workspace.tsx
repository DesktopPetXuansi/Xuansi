"use client";
import { useMe } from "@/components/navigation";
import { Notice } from "@/components/ui";
import Link from "next/link";
import { usePathname } from "next/navigation";
const groups = [
  { title: "我的桌宠", links: [["/dashboard", "我的桌宠"], ["/dashboard/history", "使用历史"], ["/dashboard/library", "收藏"]] },
  { title: "上传管理", links: [["/dashboard/resources", "我的作品"], ["/dashboard/uploads", "上传队列"]] },
  { title: "账号", links: [["/dashboard/account", "账号设置"], ["/dashboard/sessions", "会话与授权"]] },
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
    : [];
  return (
    <div className="container">
      <div className="workspace">
        <aside className="sidebar" aria-label={admin ? "管理后台导航" : "个人空间导航"}>
          {(admin ? [{ title: "管理后台", links: items }] : groups).map(group => <div className="sidebar-group" key={group.title}>
            <p className="sidebar-label">{group.title}</p>
            {group.links.map(([href, label]) => <Link href={href} key={href} aria-current={path === href || (href === "/dashboard/resources" && path.startsWith(href + "/")) ? "page" : undefined}>{label}</Link>)}
          </div>)}
          {me.data?.role === "ADMIN" && !admin && (
            <Link href="/admin/users">管理后台 ↗</Link>
          )}
          {admin && <Link href="/dashboard">返回我的桌宠</Link>}
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
