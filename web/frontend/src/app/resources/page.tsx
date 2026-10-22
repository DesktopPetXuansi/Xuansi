import { publicPageMetadata } from "@/lib/site-metadata";
export const metadata = publicPageMetadata(
  "挑选桌宠形象",
  "浏览玄司形象资源，了解图片、透明动图与 Live2D 资源的兼容性，再选择适合自己的桌面伙伴。",
  "/resources",
);
import { ResourceList } from "@/features/resources";
export default function Page() {
  return (
    <div className="container">
      <ResourceList />
    </div>
  );
}
