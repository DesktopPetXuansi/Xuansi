export const metadata = {
  title: "重设密码",
  robots: { index: false, follow: false },
};
import { AuthPage } from "@/features/auth";
import { Suspense } from "react";
export default function Page() {
  return (
    <Suspense fallback={<p>正在加载账号页面…</p>}>
      <AuthPage mode="reset-password" />
    </Suspense>
  );
}
