"use client";
import { useMe } from "@/features/identity/session";
export { useMe } from "@/features/identity/session";
import type { User } from "@/lib/types";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowUpRight, Menu, UserRound, X } from "lucide-react";
import { useRef, useState, type KeyboardEvent } from "react";

const links = [
  { href: "/", label: "首页" },
  { href: "/resources", label: "挑选形象" },
  { href: "/docs", label: "使用帮助" },
  { href: "/download", label: "下载客户端" },
];

function PrimaryNavigation({ pathname }: { pathname: string }) {
  const [open, setOpen] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);

  function closeMenu(event: KeyboardEvent<HTMLElement>) {
    if (event.key !== "Escape" || !open) return;
    setOpen(false);
    toggle.current?.focus();
    console.debug("[主导航] Escape 关闭菜单并恢复焦点");
  }

  return (
    <>
      <button
        ref={toggle}
        type="button"
        className="nav-toggle"
        aria-label={open ? "收起主导航" : "展开主导航"}
        aria-expanded={open}
        aria-controls="primary-navigation"
        onKeyDown={closeMenu}
        onClick={() => {
          setOpen(!open);
          console.debug("[主导航]", open ? "收起" : "展开");
        }}
      >
        {open ? <X size={20} aria-hidden /> : <Menu size={20} aria-hidden />}
      </button>
      <nav
        id="primary-navigation"
        className="primary-navigation"
        aria-label="主导航"
        data-expanded={open}
        onKeyDown={closeMenu}
      >
        {links.map(({ href, label }) => (
          <Link
            key={href}
            href={href}
            className={href === "/download" ? "nav-download" : undefined}
            aria-current={
              pathname === href ||
              (href !== "/" && pathname.startsWith(`${href}/`)) ||
              (href === "/docs" && pathname === "/faq")
                ? "page"
                : undefined
            }
            onClick={() => setOpen(false)}
          >
            {label}
          </Link>
        ))}
      </nav>
    </>
  );
}
export function Navigation() {
  const me = useMe();
  const pathname = usePathname();
  return (
    <header className="site-header">
      <div className="nav-inner">
        <Link href="/" className="brand" aria-label="玄司首页">
          <Image src="/brand/icon.png" width={38} height={38} alt="" />
          <span>
            玄司<span className="brand-en">XUANSI</span>
          </span>
        </Link>
        {/* 两个断点入口交替显示，让视觉顺序与键盘顺序始终一致。 */}
        <AccountLink user={me.data} mobile />
        {/* 路由切换时重建菜单状态，不用 effect 同步用户操作。 */}
        <PrimaryNavigation key={pathname} pathname={pathname} />
        <AccountLink user={me.data} />
      </div>
    </header>
  );
}
function AccountLink({
  user,
  mobile = false,
}: {
  user?: User | null;
  mobile?: boolean;
}) {
  return (
    <Link
      className={`nav-account nav-account-${mobile ? "mobile" : "desktop"}`}
      href={user ? "/dashboard" : "/login"}
    >
      <UserRound size={15} aria-hidden />
      {user ? (
        <>
          <span className="nav-nickname">{user.displayName || "朋友"}</span>
          <span>我的桌宠</span>
        </>
      ) : (
        "登录 / 注册"
      )}
      <ArrowUpRight size={14} aria-hidden />
    </Link>
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
        <small>形象、聊天方式与分享，由你选择。</small>
      </div>
      {/* 低频入口按用途分组，问答归入帮助，项目资料不占主导航。 */}
      <div className="footer-groups">
        <nav aria-label="开始使用">
          <h2>开始使用</h2>
          <Link href="/download">下载客户端</Link>
          <Link href="/docs">使用帮助</Link>
          <Link href="/docs/appearance">如何换形象</Link>
        </nav>
        <nav aria-label="项目与反馈">
          <h2>项目与反馈</h2>
          <Link href="/changelog">更新记录</Link>
          <Link href="/#feedback">问题反馈</Link>
          <a
            href="https://github.com/DesktopPetXuansi/Xuansi"
            target="_blank"
            rel="noreferrer"
          >
            GitHub 源码 ↗
          </a>
        </nav>
        <nav aria-label="条款与许可">
          <h2>条款与许可</h2>
          <Link href="/privacy">隐私说明</Link>
          <Link href="/terms">使用条款</Link>
          <Link href="/licenses">授权与致谢</Link>
        </nav>
      </div>
    </footer>
  );
}
