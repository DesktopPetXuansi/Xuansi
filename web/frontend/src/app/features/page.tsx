import { publicPageMetadata } from "@/lib/site-metadata";
export const metadata = publicPageMetadata(
  "产品功能",
  "了解玄司的桌面陪伴、AI 聊天、语音与形象更换功能，查看当前版本支持的能力及使用条件。",
  "/features",
);
import { ContentPage } from "@/features/content";
export default function Page() {
  return <ContentPage slug="features" />;
}
