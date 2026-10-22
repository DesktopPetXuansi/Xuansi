import { publicPageMetadata } from "@/lib/site-metadata";
export const metadata = publicPageMetadata(
  "隐私说明",
  "了解个人开发者维护的玄司如何处理本机数据、在线 AI 请求、网站账号与反馈信息，以及可用的隐私选项。",
  "/privacy",
);
import { ContentPage } from "@/features/content";
export default function Page() {
  return <ContentPage slug="privacy" />;
}
