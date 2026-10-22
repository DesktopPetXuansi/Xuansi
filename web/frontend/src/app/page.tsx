import { HomeSections } from "@/features/home-sections";
import { PublicFeedback } from "@/features/feedback/public-feedback";
import { ProductPreview } from "@/features/product-preview";
import { HomeClosing } from "@/features/home-closing";
import { clientRelease } from "@/lib/client-release";
import { publicPageMetadata } from "@/lib/site-metadata";
import { ArrowDown, Download } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import "./home.css";

export const metadata = {
  ...publicPageMetadata(
    "你的桌面 AI 伙伴",
    "玄司是个人开发者维护的开源 Windows 桌面伙伴。查看真实客户端界面，了解聊天、记忆和换形象；选择本机模型或在线 API，无需注册即可下载体验。",
    "/",
  ),
  // 根路由页面不会继承同层 layout 的标题模板，明确保留品牌名称。
  title: { absolute: "玄司 Xuansi · 你的桌面 AI 伙伴" },
};

// 首页保持服务端渲染，复用真实品牌素材，不添加持续动画和额外请求。
export default function Home() {
  return (
    <>
      {/* 发行事实由同一配置提供，结构化数据不包含评分或未经核实的用户数字。 */}
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify({
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            name: "玄司 Xuansi",
            applicationCategory: "LifestyleApplication",
            operatingSystem: "Windows 10 1809 或更新版本，x64",
            softwareVersion: clientRelease.version,
            datePublished: clientRelease.publishedAt,
            downloadUrl: clientRelease.downloadUrl,
            url: "https://xuansi.kukude.top/",
            description:
              "可选择本机模型或在线 AI 的 Windows 桌面伙伴，支持文字交流、记忆和自定义形象。",
          }).replace(/</g, "\\u003c"),
        }}
      />
      <section className="hero" aria-labelledby="home-title">
        <div className="hero-copy">
          <p className="eyebrow">玄司 · WINDOWS 桌面伙伴</p>
          <h1 id="home-title">
            把陪伴，
            <br />
            留在你的<em>桌面。</em>
          </h1>
          <p className="hero-description">
            <span>能聊天、记事，也能换成你喜欢的样子。</span>
            <span>选择本机模型，或连接自己的在线 AI 服务。</span>
            <span>忙起来，就让玄司安静地陪着你。</span>
          </p>
          <div className="actions hero-actions">
            <Link className="button-link" href="/download">
              <Download size={17} aria-hidden />
              下载 Windows 客户端
            </Link>
            <a href="#product-preview" className="quiet-link">
              看看实际界面 <ArrowDown size={16} aria-hidden />
            </a>
          </div>
          <p className="hero-access">无需注册即可下载和本地使用</p>
          <p className="hero-note">
            <span className="hero-version">v{clientRelease.version}</span>
            <span>Windows 10 1809 及以上 · 64 位</span>
          </p>
          <p className="hero-requirements">
            首次安装需联网。在线聊天需自备服务商 API 密钥，费用由服务商收取。
          </p>
          <p className="hero-project">
            个人开发者维护 <span aria-hidden>·</span>{" "}
            <a
              href="https://github.com/DesktopPetXuansi/Xuansi"
              target="_blank"
              rel="noreferrer"
            >
              查看开源项目 ↗
            </a>
          </p>
        </div>
        <figure className="hero-art">
          <div className="art-portrait">
            <Image
              src="/brand/front.png"
              alt="玄司角色：黑金服饰与长发的桌面伙伴"
              fill
              preload
              sizes="(max-width: 640px) calc(100vw - 104px), (max-width: 900px) 40vw, 480px"
            />
          </div>
          <span className="art-label" aria-hidden>
            玄司 / YOUR DESKTOP COMPANION
          </span>
          <figcaption className="art-bottom">
            在场，而不打扰。
            <span>XUANSI</span>
          </figcaption>
        </figure>
      </section>
      <ProductPreview />
      <HomeSections />
      <HomeClosing />
      <PublicFeedback />
    </>
  );
}
