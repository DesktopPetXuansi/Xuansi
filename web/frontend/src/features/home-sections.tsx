import { ArrowUpRight, Images, Layers3, Moon, Monitor } from "lucide-react";
import Link from "next/link";
import { AiModes } from "@/features/ai-modes";

const moments = [
  {
    icon: Monitor,
    label: "01 / 观察",
    title: "一起看看你的屏幕。",
    description:
      "开启看屏幕后，玄司能结合画面回应。使用在线 AI 时，截图会发送给你选择的服务商；开启前请确认屏幕内容。",
  },
  {
    icon: Moon,
    label: "02 / 安静陪伴",
    title: "专注的时候，就让她休息。",
    description:
      "随时让桌宠休眠，再按需要唤醒。朗读、连续对话与看屏幕分别设置，按自己的节奏使用。",
  },
];

const resourceKinds = [
  { icon: Images, title: "图片和动图", description: "用喜欢的画面陪伴你" },
  { icon: Layers3, title: "Live2D 形象", description: "会动的角色" },
];

const firstSteps = [
  {
    title: "安装客户端",
    description: "下载 Windows 安装包，按向导选择安装位置和需要的组件。",
    href: "/download",
    link: "前往下载",
  },
  {
    title: "选择 AI 聊天方式",
    description:
      "在线方式填写自己的 API 密钥；本机方式先按向导检查设备并下载模型。",
    href: "/docs/chat",
    link: "了解两种方式",
  },
  {
    title: "点击桌宠，开始聊天",
    description: "打开对话页，输入第一句话。语音和更换形象可以之后再设置。",
    href: "/docs/getting-started",
    link: "查看开始步骤",
  },
];

// 说明区保持服务端渲染，与导航交互分离，避免增加首页客户端脚本。
export function HomeSections() {
  return (
    <div className="container">
      <section className="home-section" aria-labelledby="everyday-title">
        <header className="section-top">
          <p className="eyebrow">她能做什么</p>
          <h2 id="everyday-title">想聊就聊，想安静也可以。</h2>
          <p className="muted">从一句闲聊开始，按你的节奏慢慢熟悉。</p>
          <Link className="quiet-link" href="/features">
            查看全部功能 <ArrowUpRight size={16} aria-hidden />
          </Link>
        </header>
        <div className="feature-list">
          {moments.map(({ icon: Icon, label, title, description }) => (
            <article key={label}>
              <div className="feature-icon" aria-hidden>
                <Icon size={22} strokeWidth={1.5} />
              </div>
              <div>
                <span className="feature-number">{label}</span>
                <h3>{title}</h3>
                <p>{description}</p>
              </div>
            </article>
          ))}
        </div>
      </section>
      <AiModes />
      <section className="library-promo" aria-labelledby="library-title">
        <div>
          <p className="eyebrow">桌宠长什么样，由你来选</p>
          <h2 id="library-title">
            今天，想和谁一起？
            <br />
            换个形象，继续陪伴。
          </h2>
          <p className="library-description">
            安装后可以直接使用玄司。想换个样子，就去挑选形象，或把自己的图片、动图导入客户端的“更换形象”。
          </p>
          <Link className="button-link secondary" href="/resources">
            挑选形象 <ArrowUpRight size={16} aria-hidden />
          </Link>
        </div>
        <div className="library-types">
          {resourceKinds.map(({ icon: Icon, title, description }) => (
            <div className="library-kind" key={title}>
              <Icon size={20} strokeWidth={1.5} aria-hidden />
              <strong>{title}</strong>
              <span>{description}</span>
            </div>
          ))}
          <p className="legal-note">
            网页负责挑选，实际更换在客户端完成。
            <Link className="quiet-link" href="/docs/appearance">
              查看换形象步骤 →
            </Link>
          </p>
        </div>
      </section>
      <section className="start-section" aria-labelledby="start-title">
        <header className="section-top">
          <p className="eyebrow">第一次使用</p>
          <h2 id="start-title">从下载到第一句聊天。</h2>
          <p className="muted">下载和阅读帮助无需注册网站账号。</p>
        </header>
        <ol className="start-steps">
          {firstSteps.map((step, index) => (
            <li key={step.title}>
              <span className="step-index" aria-hidden>
                0{index + 1}
              </span>
              <h3>{step.title}</h3>
              <p>{step.description}</p>
              <Link className="quiet-link" href={step.href}>
                {step.link} <ArrowUpRight size={16} aria-hidden />
              </Link>
            </li>
          ))}
        </ol>
        <p className="start-help">
          卡在哪一步了？
          <Link className="quiet-link" href="/docs">
            到使用帮助找答案 →
          </Link>
        </p>
      </section>
    </div>
  );
}
