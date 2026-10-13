export const metadata = { title: "官方资源库" };
import { ResourceList } from "@/features/resources";
export default function Page() {
  return (
    <div className="container">
      <ResourceList />
    </div>
  );
}
