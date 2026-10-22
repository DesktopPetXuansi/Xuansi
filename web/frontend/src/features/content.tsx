import { Heading } from "@/components/ui";
import Link from "next/link";
import type { ReactNode } from "react";
import { clientRelease } from "@/lib/client-release";
import { legalContent } from "@/features/legal/content";
// 产品概览与法律说明保留独立目的；操作指南由 help 模块按任务维护。
const content: Record<
  string,
  {
    title: string;
    intro: string;
    sections: { title: string; text: ReactNode }[];
  }
> = {
  features: {
    title: "让桌面，多一点回应。",
    intro:
      "一个住在 Windows 桌面的 AI 伙伴。聊天、换形象、安静陪伴，都按你的节奏来。",
    sections: [
      {
        title: "从一句话开始交流",
        text: "点击角色打开“对话”，输入文字就能交流。可以选本机 AI，也可以使用自备密钥的在线服务。想直接说话或听她朗读，再按需安装语音组件并允许麦克风访问。",
      },
      {
        title: "按需观察屏幕",
        text: "在对话中提供屏幕画面，让她结合正在看的内容回应。使用在线 AI 时，所提供的图片会交给对应服务商；自动观察的截图发送需单独授权，默认关闭。网站账号不保存截图。",
      },
      {
        title: "明确授权的记忆",
        text: "你可以在“记忆”中查看和管理本机保存的事项。允许在线服务读取长期记忆需要单独开启；网站账号不提供聊天或记忆的云同步。",
      },
      {
        title: "用喜欢的形象陪伴",
        text: `在“更换形象”本地导入图片、动图或导出的 Live2D 模型，也可以在线挑选，无需先上传。当前正式版 ${clientRelease.version} 支持选中形象后直接点击“使用这个形象”，自动下载、检查并保存；独立预览可选。旧版 0.7.1 在线挑选需先下载并预览，再点击使用。暂时不想被打扰时，可以让桌宠休眠。`,
      },
    ],
  },
  ...legalContent,
  licenses: {
    title: "授权与致谢",
    intro: "角色与软件依赖各有许可，不混为一个开放授权。",
    sections: [
      {
        title: "玄司角色素材",
        text: "本网站展示仓库现有玄司角色图像。版权及使用限制以 assets/xuansi/LICENSE 和权利人授权为准，不因网站公开而获得再分发许可。",
      },
      {
        title: "Live2D",
        text: (
          <>
            网站仅展示角色图片和客户端截图，不在浏览器运行 Cubism
            Core。客户端使用 Live2D 的 SDK
            与运行组件，接入、分发及所导入模型的使用须遵守
            <a
              href="https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html"
              target="_blank"
              rel="noreferrer"
            >
              Live2D 官方许可
            </a>
            及模型作者的授权；网站提供下载不改变这些限制。
          </>
        ),
      },
      {
        title: "开源软件",
        text: (
          <>
            玄司软件源码按{" "}
            <a
              href="https://github.com/DesktopPetXuansi/Xuansi/blob/main/LICENSE"
              target="_blank"
              rel="noreferrer"
            >
              Apache-2.0
            </a>{" "}
            开源。 网站使用的 React、Next.js、Go、PostgreSQL
            等软件遵循各自许可，完整依赖与锁定版本可在仓库查阅。源码许可不自动覆盖角色素材和用户上传资源。
          </>
        ),
      },
      {
        title: "用户上传",
        text: "每个资源独立保留作者、来源和许可。平台提供下载不改变原作者的权利。",
      },
    ],
  },
};
export function ContentPage({ slug }: { slug: string }) {
  const page = content[slug];
  if (!page) return null;
  return (
    <div className="container">
      <Heading title={page.title}>{page.intro}</Heading>
      <div className="prose">
        {page.sections.map((section) => (
          <section key={section.title}>
            <h2>{section.title}</h2>
            <p>{section.text}</p>
          </section>
        ))}
        {slug === "features" && (
          <div className="actions" style={{ marginTop: 30 }}>
            <Link className="button-link" href="/download">
              下载客户端
            </Link>
            <Link className="quiet-link" href="/docs/getting-started">
              跟着步骤开始使用 →
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
