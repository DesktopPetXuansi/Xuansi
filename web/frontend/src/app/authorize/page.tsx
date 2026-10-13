export const metadata = {
  title: "客户端授权",
  robots: { index: false, follow: false },
};
import { Authorize } from "@/features/authorize";
import { Suspense } from "react";
export default function Page() {
  return (
    <Suspense fallback={<p>正在加载授权页面…</p>}>
      <Authorize />
    </Suspense>
  );
}
