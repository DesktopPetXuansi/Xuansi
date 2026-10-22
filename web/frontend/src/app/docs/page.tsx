import { publicPageMetadata } from "@/lib/site-metadata";
export const metadata = publicPageMetadata(
  "使用帮助",
  "从下载安装到第一次对话，按步骤配置玄司的本机模型或在线 API，学习语音、记忆与形象设置。",
  "/docs",
);
import { HelpCenter } from "@/features/help";
export default function Page() {
  return <HelpCenter />;
}
