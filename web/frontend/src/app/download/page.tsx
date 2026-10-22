import { publicPageMetadata } from "@/lib/site-metadata";
export const metadata = publicPageMetadata(
  "客户端下载",
  "下载玄司 Windows 正式版，无需注册。查看系统要求、安装包大小、未签名说明和 SHA-256 校验步骤。",
  "/download",
);
import { Releases } from "@/features/releases";
export default function Page() {
  return <Releases />;
}
