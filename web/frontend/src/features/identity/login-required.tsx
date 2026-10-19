"use client";

import { Heading } from "@/components/ui";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { authHref } from "./return-path";

export function LoginRequired() {
  const path = usePathname();
  const search = useSearchParams().toString();
  const destination = `${path}${search ? `?${search}` : ""}`;

  return (
    <div className="container">
      <div className="narrow">
        <Heading eyebrow="YOUR ACCOUNT / 你的账号" title="登录后，继续你的陪伴">
          收藏、使用历史与作品管理需要登录。你也可以先回到首页，认识玄司、浏览资源或下载客户端。
        </Heading>
        <div className="actions">
          <Link className="button-link" href={authHref("/login", destination)}>
            登录后继续
          </Link>
          <Link className="button-link secondary" href={authHref("/register", destination)}>
            创建账号
          </Link>
          <Link className="quiet-link" href="/">返回首页</Link>
        </div>
      </div>
    </div>
  );
}
