import { publicPageMetadata } from "@/lib/site-metadata";
export const metadata = publicPageMetadata(
  "常见问题",
  "查找玄司下载、账号、硬件、本机模型、在线 API 费用及隐私相关问题的说明。",
  "/faq",
);
import { HelpQuestions } from "@/features/help";
export default function Page() {
  return <HelpQuestions />;
}
