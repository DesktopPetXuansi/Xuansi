import { publicPageMetadata } from "@/lib/site-metadata";
export const metadata = publicPageMetadata(
  "使用条款",
  "阅读玄司个人开发者服务的使用条件、AI 内容与资源使用责任、服务限制及问题反馈方式。",
  "/terms",
);
import { ContentPage } from "@/features/content";
export default function Page() {
  return <ContentPage slug="terms" />;
}
