import { HomeSections } from "@/features/home-sections";
import { ArrowUpRight, Download } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import "./home.css";

const principles = [
  {
    title: "运行在你的设备",
    description: "本地模型推理，保留自己的数据边界。",
  },
  {
    title: "按你的节奏陪伴",
    description: "聊天、语音、观察与休眠，由你开启。",
  },
  { title: "让形象属于你", description: "管理模型、动作、表情与透明动图。" },
];

// 首页保持服务端渲染，复用真实品牌素材，不添加持续动画和额外请求。
export default function Home() {
  return (
    <>
      <section className="hero" aria-labelledby="home-title">
        <div className="hero-copy">
          <p className="eyebrow">MEET XUANSI / 遇见玄司</p>
          <h1 id="home-title">
            把陪伴，
            <br />
            留在你的<em>桌面。</em>
          </h1>
          <p className="hero-description">
            <span>她会听你说话，也会看看你正在忙什么。</span>
            <span>一个住在电脑里的 AI 伙伴，让日常多一点回应。</span>
            <span>推理在本地运行，陪伴由你决定。</span>
          </p>
          <div className="actions hero-actions">
            <Link className="button-link" href="/download">
              <Download size={17} aria-hidden />
              下载 Windows 客户端
            </Link>
            <Link href="/features" className="quiet-link">
              认识玄司 <ArrowUpRight size={16} aria-hidden />
            </Link>
          </div>
          <p className="hero-note">
            <span className="hero-version">v0.6.0</span>
            <span>Windows 11 x64 · NVIDIA / CUDA 12.4</span>
          </p>
          <p className="hero-requirements">
            首次安装需要联网，安装路径需要 D 盘。
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
    </>
  );
}
