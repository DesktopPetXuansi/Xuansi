import { ArrowUpRight, Cpu, Globe } from "lucide-react";
import Link from "next/link";
import styles from "./ai-modes.module.css";

const modes = [
  {
    title: "在线 AI",
    icon: Globe,
    subtitle: "连接你自己的服务商",
    facts: [
      ["准备", "需要网络、自己的 API 密钥和服务额度；不要求 NVIDIA 显卡。"],
      [
        "费用",
        "由服务商按用量收费，测试也可能产生费用。网站账号不提供调用额度。",
      ],
      [
        "数据",
        "对话和必要上下文直达你配置的端点；图片、自动观察与记忆按各自提供方式和授权处理。",
      ],
    ],
  },
  {
    title: "本机 AI",
    icon: Cpu,
    subtitle: "让模型在自己的电脑运行",
    facts: [
      [
        "准备",
        "先检测设备并下载模型。标准 9B 模型与视觉组件约 6.60 GB，语音等文件另计。",
      ],
      [
        "费用",
        "本机推理不产生在线服务商的调用费，仍需设备资源、存储空间与首次下载。",
      ],
      [
        "数据",
        "本机推理留在本机，配置完成后可离线聊天；下载、更新和网站功能仍可能联网。",
      ],
    ],
  },
] as const;

// 首页和下载页共用同一份运行条件，避免费用和隐私说明再次分叉。
export function AiModes() {
  return (
    <section
      id="ai-modes"
      className={styles.section}
      aria-labelledby="ai-modes-title"
    >
      <header>
        <p className="eyebrow">选择适合你的聊天方式</p>
        <h2 id="ai-modes-title">AI 在哪里运行，由你选择。</h2>
        <p className={styles.intro}>
          形象决定陪伴的样子，AI 决定如何回应。两种方式都不需要网站账号。
        </p>
      </header>
      <div className={styles.modes}>
        {modes.map(({ title, icon: Icon, subtitle, facts }) => (
          <article key={title}>
            <div className={styles.title}>
              <Icon size={23} aria-hidden />
              <h3>{title}</h3>
            </div>
            <p className={styles.subtitle}>{subtitle}</p>
            <dl>
              {facts.map(([label, text]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{text}</dd>
                </div>
              ))}
            </dl>
          </article>
        ))}
      </div>
      <p className={styles.note}>
        本机硬件要求因模型而异，请以客户端设备检测为准；CPU 与实验 4B
        方案仍有限制。语音和视觉能力取决于模型及所装组件。
      </p>
      <p className={styles.note}>
        自动观察截图与在线记忆读取分别授权、默认关闭。单次附图和对话中的按需截图是独立操作，使用前请检查屏幕内容。
      </p>
      <div className="actions">
        <Link className="quiet-link" href="/docs/chat">
          跟着教程配置 <ArrowUpRight size={16} aria-hidden />
        </Link>
        <Link className="quiet-link" href="/privacy">
          完整数据与隐私说明 →
        </Link>
      </div>
    </section>
  );
}
