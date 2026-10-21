import { HomeSections } from "@/features/home-sections";
import { PublicFeedback } from "@/features/feedback/public-feedback";
import { clientRelease } from "@/lib/client-release";
import { ArrowUpRight, Download } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import "./home.css";

const principles = [
  {
    title: "文字、语音都能聊",
    description: "先开始文字聊天，再按需配置语音。",
  },
  {
    title: "按你的节奏陪伴",
    description: "看屏幕、朗读和休眠，由你决定。",
  },
  {
    title: "换成喜欢的形象",
    description: "使用自带角色，也能导入图片、动图或 Live2D。",
  },
];

// 首页保持服务端渲染，复用真实品牌素材，不添加持续动画和额外请求。
export default function Home() {
  return (
    <>
      <section className="hero" aria-labelledby="home-title">
        <div className="hero-copy">
          <p className="eyebrow">玄司 · AI 桌面伙伴</p>
          <h1 id="home-title">
            把陪伴，
            <br />
            留在你的<em>桌面。</em>
          </h1>
          <p className="hero-description">
            <span>一个住在 Windows 桌面上的 AI 伙伴。</span>
            <span>聊聊今天的事，换个喜欢的形象，忙起来就让她安静待着。</span>
            <span>选择在线服务或本机模型后，就能开始聊天。</span>
          </p>
          <div className="actions hero-actions">
            <Link className="button-link" href="/download">
              <Download size={17} aria-hidden />
              下载 Windows 客户端
            </Link>
            <Link href="/resources" className="quiet-link">
              挑选桌宠形象 <ArrowUpRight size={16} aria-hidden />
            </Link>
          </div>
          <p className="hero-note">
            <span className="hero-version">v{clientRelease.version}</span>
            <span>Windows 10 1809 及以上 · 64 位</span>
          </p>
          <p className="hero-requirements">
            首次安装需联网。在线聊天需自备服务商 API 密钥，费用由服务商收取。
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
      <section className="principles" aria-label="陪伴的三个原则">
        <div className="principles-inner">
          {principles.map(({ title, description }, index) => (
            <article key={title}>
              <span aria-hidden>0{index + 1}</span>
              <div>
                <h2>{title}</h2>
                <p>{description}</p>
              </div>
            </article>
          ))}
        </div>
      </section>
      <HomeSections />
      <PublicFeedback />
    </>
  );
}
