export const metadata = {
  title: "验证邮箱",
  robots: { index: false, follow: false },
};
import { AuthPage } from "@/features/auth";
import { Suspense } from "react";
export default function Page() {
  return (
    <Suspense fallback={<p>正在加载账号页面…</p>}>
      <AuthPage mode="verify-email" />
    </Suspense>
  );
}
