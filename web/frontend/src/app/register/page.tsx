export const metadata = {
  title: "注册",
  robots: { index: false, follow: false },
};
import { RegistrationPage } from "@/features/identity/registration";
import { Suspense } from "react";
export default function Page() {
  return (
    <Suspense fallback={<p>正在加载账号页面…</p>}>
      <RegistrationPage />
    </Suspense>
  );
}
