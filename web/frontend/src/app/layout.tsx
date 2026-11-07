import { Footer, Navigation } from "@/components/navigation";
import { AssemblyMotion } from "@/components/assembly/assembly-motion";
import { Providers } from "@/components/providers";
import type { Metadata } from "next";
import Script from "next/script";
import "./globals.css";
import "./sketch.css";

// 在首次绘制前标记待组装组件；客户端迟迟未启动时自动恢复正文。
const assemblyBootstrap = `(() => {
  if (!window.matchMedia || window.matchMedia('(prefers-reduced-motion: reduce)').matches ||
      !('IntersectionObserver' in window) || !('animate' in Element.prototype)) return;
  const root = document.documentElement;
  root.setAttribute('data-assembly-pending', '');
  window.setTimeout(() => {
    if (!root.hasAttribute('data-assembly-active')) root.removeAttribute('data-assembly-pending');
  }, 4000);
})();`;
export const metadata: Metadata = {
  metadataBase: new URL(process.env.SITE_URL ?? "https://xuansi.kukude.top"),
  title: {
    default: "玄司 Xuansi · 你的桌面 AI 伙伴",
    template: "%s · 玄司 Xuansi",
  },
  description:
    "玄司是运行在 Windows 桌面的 AI 伙伴。选择本机或在线聊天，用图片、动图或 Live2D 更换形象。从下载到第一次对话，跟着使用帮助开始。",
  // 小尺寸图标复用玄司品牌素材，减少每次访问的图标下载量。
  icons: {
    icon: { url: "/brand/favicon.png", sizes: "48x48", type: "image/png" },
  },
  openGraph: {
    title: "玄司 Xuansi",
    description: "把陪伴，留在你的桌面。",
    type: "website",
    locale: "zh_CN",
    siteName: "玄司 Xuansi",
    images: [
      {
        url: "/brand/share.png",
        width: 1200,
        height: 630,
        alt: "玄司 Xuansi · 把陪伴，留在你的桌面。",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "玄司 Xuansi · 你的桌面 AI 伙伴",
    description: "把陪伴，留在你的桌面。",
    images: ["/brand/share.png"],
  },
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: assemblyBootstrap }} />
      </head>
      <body>
        <Providers>
          <a className="skip-link" href="#main">
            跳到正文
          </a>
          <Navigation />
          <main id="main">{children}</main>
          <Footer />
          <AssemblyMotion />
        </Providers>
        <Script src="/analytics-loader.js" strategy="afterInteractive" />
      </body>
    </html>
  );
}
