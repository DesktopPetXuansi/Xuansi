"use client";
import { api,ApiError } from "@/lib/api";
import type { User } from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
import Image from "next/image";
import Link from "next/link";
export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api<User>("/me");
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
  });
}
export function Navigation() {
  const me = useMe();
  return (
    <header className="site-header">
      <div className="nav-inner">
        <Link href="/" className="brand" aria-label="玄司首页">
          <Image src="/brand/icon.png" width={38} height={38} alt="" />
          <span>
            玄司<span className="brand-en">XUANSI</span>
          </span>
        </Link>
        <nav aria-label="主导航">
          <Link href="/features">产品</Link>
          <Link href="/resources">资源库</Link>
          <Link href="/docs">文档</Link>
          <Link href="/download">下载</Link>
        </nav>
        <Link className="nav-account" href={me.data ? "/dashboard" : "/login"}>
          {me.data ? "工作台 ↗" : "登录 / 注册"}
        </Link>
      </div>
    </header>
  );
}
export function Footer() {
  return (
    <footer className="site-footer">
      <div>
        <Link className="brand" href="/">
          玄司 <span className="brand-en">XUANSI</span>
        </Link>
        <p>一个在你桌面上，认真陪伴的伙伴。</p>
        <small>本地推理 · 你的设备 · 你的选择</small>
      </div>
      <nav aria-label="页脚导航">
        <Link href="/faq">常见问题</Link>
        <Link href="/privacy">隐私说明</Link>
        <Link href="/terms">使用条款</Link>
        <Link href="/licenses">授权与致谢</Link>
        <a
          href="https://github.com/DesktopPetXuansi/Xuansi"
          target="_blank"
          rel="noreferrer"
        >
          GitHub ↗
        </a>
      </nav>
    </footer>
  );
}
