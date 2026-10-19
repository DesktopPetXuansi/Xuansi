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
  { href: "/features", label: "产品" },
  { href: "/resources", label: "资源库" },
  { href: "/docs", label: "文档" },
  { href: "/download", label: "下载" },
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
            aria-current={
              pathname === href || (href !== "/" && pathname.startsWith(`${href}/`))
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
      {user ? <><span className="nav-nickname">{user.displayName || "朋友"}</span><span>我的桌宠</span></> : "登录 / 注册"}
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
