import { Heading } from "@/components/ui";
import Link from "next/link";
const content: Record<
  string,
  { title: string; intro: string; sections: { title: string; text: string }[] }
> = {
  features: {
    title: "让桌面，多一点回应。",
    intro: "玄司在本地运行。你决定什么时候交流，什么时候让她安静待着。",
    sections: [
      {
        title: "文字与连续语音",
        text: "通过文字聊天，或开启连续语音交流。语音需要安装对应 ASR / TTS 模型，并允许麦克风访问。设备性能会影响响应速度。",
      },
      {
        title: "按需观察屏幕",
        text: "在你开启后读取屏幕截图，结合当前内容回应。推理在设备上进行；网站资源账号不会上传截图。",
      },
      {
        title: "明确授权的记忆",
        text: "长期记忆需要你明确授权，保存在本地。你可以管理这些内容，网站账号只负责资源服务。",
      },
      {
        title: "形象与休眠",
        text: "已有图片和透明动图导入、托盘及休眠能力。网站模型、动作和表情需要客户端接入版；不能把 0.5.6 当作通用 Live2D 资源客户端。",
      },
    ],
  },
  docs: {
    title: "开始使用玄司",
    intro: "先确认设备条件，再完成安装与模型下载。",
    sections: [
      {
        title: "01 / 检查设备",
        text: "当前已验证路线为 Windows 11 x64、NVIDIA 显卡、CUDA 12.4 和 D 盘。首次安装需要联网下载模型与运行依赖。",
      },
      {
        title: "02 / 下载并安装",
        text: "从下载页进入官方 GitHub Release，使用 0.5.6 在线安装器，按安装向导完成首次下载。不要把首次联网安装误认为离线安装包。",
      },
      {
        title: "03 / 开始交流",
        text: "启动玄司后先使用文字聊天，再按需开启麦克风和屏幕观察。模型加载需要一定时间，具体取决于设备。",
      },
      {
        title: "04 / 管理资源",
        text: "验证邮箱后创建资源，上传文件并等待后台校验。动作与表情必须绑定目标模型版本。客户端接入版通过系统浏览器授权，下载后验证摘要与安全路径，再试载应用。",
      },
      {
        title: "遇到问题",
        text: "核对显卡驱动、CUDA、D盘空间和首次联网条件。安装与本地配置细节以仓库 docs 中的现行文档为准。",
      },
    ],
  },
  faq: {
    title: "常见问题",
    intro: "关于设备、数据与模型资源。",
    sections: [
      {
        title: "需要一直联网吗？",
        text: "首次安装需要联网下载模型。现有本地推理可离线使用；网站登录、上传和资源下载需要网络。",
      },
      {
        title: "支持 macOS 或 AMD 显卡吗？",
        text: "当前已验证安装路线只有 Windows 11 x64 与 NVIDIA / CUDA 12.4。其他平台没有作为当前官方下载选项提供。",
      },
      {
        title: "网站账号会同步聊天吗？",
        text: "不会。账号用于资源平台；聊天、截图、录音和长期记忆维持客户端本地数据边界。",
      },
      {
        title: "所有 Live2D 模型都能使用吗？",
        text: "不能保证。包校验只检查格式、路径和完整性，客户端需要试载。动作、表情与参数映射都应按精确模型版本验证。",
      },
      {
        title: "可以公开分享模型吗？",
        text: "首期上传默认私有，公开资源由管理员发布。用户社区分享与商店为后续扩展，还需满足作者许可。",
      },
      {
        title: "能自动更新客户端吗？",
        text: "0.5.6 没有自动更新功能，当前通过官方下载页手动升级。",
      },
    ],
  },
  privacy: {
    title: "隐私说明",
    intro: "把客户端本地数据与网站资源账号区分清楚。",
    sections: [
      {
        title: "客户端数据",
        text: "聊天、截图、录音、长期记忆与本地推理继续保留在客户端既有流程中。网站账号不提供这些数据的云同步。",
      },
      {
        title: "网站账号",
        text: "平台处理邮箱、昵称、密码摘要、会话与授权记录，用于登录、邮箱验证、账号恢复和权限控制。",
      },
      {
        title: "上传资源",
        text: "平台保存资源文件、作者许可、版本、依赖、校验报告及必要审计记录。新资源默认私有。管理员可为服务管理与问题诊断访问受控数据。",
      },
      {
        title: "会话与授权",
        text: "网站使用必要的安全会话 Cookie。客户端通过浏览器显式授权读取资源，你可在工作台撤销会话和授权。",
      },
      {
        title: "上线前信息",
        text: "正式服务的运营主体、联系渠道、数据保存周期与地区需在生产上线前补充。当前文本描述实现的数据边界，不替代正式法律审查。",
      },
    ],
  },
  terms: {
    title: "使用条款",
    intro: "尊重作者许可，管理好自己的账号和资源。",
    sections: [
      {
        title: "资源权利",
        text: "请仅上传你拥有权利或获得授权的模型、动作、表情和图像。填写真实作者、来源及允许的使用范围。",
      },
      {
        title: "资源使用",
        text: "下载许可不等同于商业使用许可或再次分发许可。使用资源前请阅读作者声明。",
      },
      {
        title: "服务管理",
        text: "平台可处理违规内容、停用账号或隐藏资源。首期不提供付费交易与公开社区分享。",
      },
      {
        title: "功能与兼容性",
        text: "校验完成不保证模型运行效果。不同模型的参数、动作、表情和设备要求不同，应通过客户端试载验证。",
      },
      {
        title: "正式服务条款",
        text: "运营主体、争议处理和正式联系渠道在生产上线前补充并审查。",
      },
    ],
  },
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
        text: "Live2D Cubism SDK / Core 的使用与再分发遵循官方许可。首期网站仅展示封面，不加载浏览器 Cubism Core。可导入模型的客户端发行还需核实 Expandable Application 许可。",
      },
      {
        title: "开源软件",
        text: "网站使用 React、Next.js、Go、PostgreSQL 等软件，遵循各自许可。完整依赖与锁定版本可在仓库查阅。",
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
        <div className="actions" style={{ marginTop: 30 }}>
          <Link className="button-link" href="/download">
            下载客户端
          </Link>
          <a
            className="quiet-link"
            href="https://github.com/DesktopPetXuansi/Xuansi/tree/main/docs"
            target="_blank"
            rel="noreferrer"
          >
            项目文档 ↗
          </a>
        </div>
      </div>
    </div>
  );
}
