"use client";
import { useMe } from "@/components/navigation";
import { Button, Heading, Notice } from "@/components/ui";
import { LoginRequired } from "./identity/login-required";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense } from "react";
const groups = [
  { title: "我的桌宠", links: [["/dashboard", "我的桌宠"], ["/dashboard/history", "使用历史"], ["/dashboard/library", "收藏"]] },
  { title: "上传管理", links: [["/dashboard/resources", "我的作品"], ["/dashboard/uploads", "上传队列"]] },
  { title: "账号", links: [["/dashboard/feedback", "我的反馈"], ["/dashboard/account", "账号设置"], ["/dashboard/sessions", "会话与授权"]] },
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
  // 登录检查先于个人导航和内容，访客、检查中及失败时均不渲染私人工作区。
  if (me.isPending || me.error) {
    return <div className="container"><div className="narrow">
      {me.isPending ? <Notice>正在检查登录状态…</Notice> : <>
        <Notice error={me.error} />
        <Button className="secondary" onClick={() => {
          console.debug("[个人空间] 重试登录状态检查");
          void me.refetch();
        }}>重试检查</Button>
      </>}
      <p><Link href="/" className="quiet-link">返回首页</Link></p>
    </div></div>;
  }
  if (!me.data) {
    return <Suspense fallback={<div className="container"><Notice>正在准备登录入口…</Notice></div>}>
      <LoginRequired />
    </Suspense>;
  }
  if (admin && me.data.role !== "ADMIN") {
    return <div className="container"><div className="narrow">
      <Heading title="你没有管理后台权限。">可以返回个人空间，继续管理自己的桌宠与收藏。</Heading>
      <Link href="/dashboard" className="button-link">返回我的桌宠</Link>
    </div></div>;
  }
  const items = admin
    ? [
        ["/admin/users", "用户"],
        ["/admin/resources", "资源发布"],
        ["/admin/releases", "客户端版本"],
        ["/admin/feedback/chat", "反馈对话"],
        ["/admin/feedback", "收件与审核"],
        ["/admin/jobs", "后台任务"],
        ["/admin/audit", "审计日志"],
      ]
    : [];
  return (
    <div className="container">
      <div className="workspace">
        <aside className="sidebar" aria-label={admin ? "管理后台导航" : "个人空间导航"} data-feedback-chat={!admin && path === "/dashboard/feedback" ? "true" : undefined}>
          {(admin ? [{ title: "管理后台", links: items }] : groups).map(group => <div className="sidebar-group" key={group.title} data-feedback-primary={group.title === "账号" ? "true" : undefined}>
            <p className="sidebar-label">{group.title}</p>
            {group.links.map(([href, label]) => <Link href={href} key={href} aria-current={path === href || (href === "/dashboard/resources" && path.startsWith(href + "/")) ? "page" : undefined}>{label}</Link>)}
          </div>)}
          {me.data?.role === "ADMIN" && !admin && (
            <Link href="/admin/users">管理后台 ↗</Link>
          )}
          {admin && <Link href="/dashboard">返回我的桌宠</Link>}
        </aside>
        <section>{children}</section>
      </div>
    </div>
  );
}

export * from "./account";
export * from "./library";
export * from "./overview";
export * from "./sessions";
export * from "./upload-queue";
