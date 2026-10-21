import { Heading } from "@/components/ui";
import Link from "next/link";
// 产品概览与法律说明保留独立目的；操作指南由 help 模块按任务维护。
const content: Record<
  string,
  { title: string; intro: string; sections: { title: string; text: string }[] }
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
        text: "在“更换形象”本地导入图片、动图或导出的 Live2D 模型，也可以在线挑选，无需先上传。尚未发布的新版支持选中形象后直接点击“使用这个形象”，自动下载、检查并保存；独立预览可选。公开 0.7.1 在线挑选仍需先下载并预览，再点击使用。暂时不想被打扰时，可以让桌宠休眠。",
      },
    ],
  },
  privacy: {
    title: "隐私说明",
    intro: "分别说明本机数据、网站账号，以及你选择的在线 AI 服务。",
    sections: [
      {
        title: "客户端数据",
        text: "网站不保存或同步客户端的聊天内容、屏幕截图、录音、长期记忆和 AI 密钥。长期记忆与 AI 配置历史保存在本机；密钥由 Windows 凭据管理器保存，普通配置保存凭据引用。",
      },
      {
        title: "在线 AI 服务",
        text: "选择在线 AI 时，对话文字、必要历史和工具结果会交给所选服务商。明确附图或对话中按需提供的截图也会发送；自动观察截图与长期记忆读取分别授权、默认关闭。开启记忆读取后，可能分批发送本地记忆的候选内容，并不限于最终命中片段。数据处理和调用费用由相应服务商的规则决定。",
      },
      {
        title: "网站账号",
        text: "平台处理邮箱、昵称、密码摘要、会话与授权记录，用于登录、邮箱验证、账号恢复和权限控制；同时保存账号的收藏和登录后的下载记录。支持历史同步的新版客户端只有在主动开启并授权后才上传形象使用记录，公开 0.7.1 暂未包含该能力。形象记录不代表桌宠的实时状态。",
      },
      {
        title: "上传资源",
        text: "平台保存资源文件、作者许可、版本、依赖、校验报告及必要审计记录。新资源默认私有。管理员可为服务管理与问题诊断访问受控数据。",
      },
      {
        title: "主动提交的反馈",
        text: "在首页或软件反馈中心主动提交后，网站将反馈正文、可选联系方式和处理状态保存到数据库。新反馈先私有保存；只有获得你的公开许可并经管理员审核，正文和主动附带的版本信息才会同步到 GitHub，联系方式始终不公开。网页提交后可凭本浏览器保存的权限或专属管理链接撤回；公开投递开始后需申请管理员清理，已被他人保存的内容无法保证删除。版本与系统信息默认不附带，只有主动勾选才发送固定五项版本信息。反馈不会自动附带聊天、AI 密钥、截图、录音、完整日志或用户目录，请勿填写密码等敏感信息。",
      },
      {
        title: "会话与授权",
        text: "网站使用必要的会话 Cookie。客户端通过浏览器明确申请相应权限，你可在“我的桌宠 → 账号”中管理和撤销会话与客户端授权。退出账号会清除当前网页的个人查询缓存。",
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
