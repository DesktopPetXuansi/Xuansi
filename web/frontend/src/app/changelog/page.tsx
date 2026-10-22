import { publicPageMetadata } from "@/lib/site-metadata";
export const metadata = publicPageMetadata(
  "更新日志",
  "查看玄司当前正式版的真实更新摘要、官方 GitHub 发行历史及资源平台收录记录。",
  "/changelog",
);
import { Releases } from "@/features/releases";
export default function Page() {
  return <Releases history />;
}
