import {
  ArrowUpRight,
  Film,
  Images,
  Layers3,
  MemoryStick,
  MessagesSquare,
  Monitor,
} from "lucide-react";
import Link from "next/link";

const moments = [
  {
    icon: MessagesSquare,
    label: "01 / 对话",
    title: "想到什么，就聊什么。",
    description:
      "文字交流与连续语音，在工作间隙分享想法。语音功能需要相应模型与设备支持。",
  },
  {
    icon: Monitor,
    label: "02 / 观察",
    title: "一起看看你的屏幕。",
    description:
      "在你开启后，玄司可以观察屏幕内容并回应。截图参与本地推理，是否开启由你掌握。",
  },
  {
    icon: MemoryStick,
    label: "03 / 记忆",
    title: "记住你愿意留下的事。",
    description:
      "明确授权的长期记忆，保存在本地。你可以检查与管理，而不是默认上传聊天记录。",
  },
];

const resourceKinds = [
  { icon: Layers3, title: "Live2D 模型", description: "完整导出包" },
  { icon: Film, title: "动作 / 表情", description: "绑定模型版本" },
  { icon: Images, title: "图片 / 透明动图", description: "你的桌面形象" },
];

// 说明区保持服务端渲染，与导航交互分离，避免增加首页客户端脚本。
export function HomeSections() {
  return (
    <div className="container">
      <section className="home-section" aria-labelledby="everyday-title">
        <header className="section-top">
          <p className="eyebrow">SMALL MOMENTS / 日常之间</p>
          <h2 id="everyday-title">不只是桌面上的一个身影。</h2>
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
      <section className="library-promo" aria-labelledby="library-title">
        <div>
          <p className="eyebrow">YOUR CHARACTERS / 你的形象</p>
          <h2 id="library-title">
            一个资源库，
            <br />
            管理每一种陪伴的可能。
          </h2>
          <p className="library-description">
            为模型保留作者和许可，为动作标注精确依赖。上传默认私有，通过校验后再交给接入版客户端试载。
          </p>
          <Link className="button-link secondary" href="/resources">
            探索资源库 <ArrowUpRight size={16} aria-hidden />
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
            资源平台需要客户端接入版。0.5.6 仍使用原有本地导入流程。
          </p>
        </div>
      </section>
    </div>
  );
}
