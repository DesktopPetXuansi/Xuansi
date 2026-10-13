import { Footer, Navigation } from "@/components/navigation";
import { Providers } from "@/components/providers";
import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  metadataBase: new URL(process.env.SITE_URL ?? "http://localhost:3000"),
  title: {
    default: "玄司 Xuansi · 你的本地桌面伙伴",
    template: "%s · 玄司 Xuansi",
  },
  description:
    "玄司是运行在 Windows 桌面的 AI 伙伴。了解本地聊天、语音与屏幕观察，下载客户端，管理你的 Live2D 模型、动作和表情。",
  openGraph: {
    title: "玄司 Xuansi",
    description: "把陪伴，留在你的桌面。",
    images: ["/brand/front.png"],
  },
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>
        <Providers>
          <a className="skip-link" href="#main">
            跳到正文
          </a>
          <Navigation />
          <main id="main">{children}</main>
          <Footer />
        </Providers>
      </body>
    </html>
  );
}
