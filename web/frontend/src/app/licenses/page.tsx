import { publicPageMetadata } from "@/lib/site-metadata";
export const metadata = publicPageMetadata(
  "授权与致谢",
  "查看玄司使用的开源组件、角色和资源授权说明，了解第三方素材的使用范围与致谢信息。",
  "/licenses",
);
import { ContentPage } from "@/features/content";
export default function Page() {
  return <ContentPage slug="licenses" />;
}
