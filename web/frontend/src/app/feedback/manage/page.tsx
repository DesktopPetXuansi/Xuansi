import { Heading } from "@/components/ui";
import { FeedbackManagementPanel } from "@/features/feedback/feedback-management";

export const metadata = {
  title: "管理反馈 · 玄司",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

// 页面不读取服务端查询参数，管理权限仅在浏览器 fragment 或本机存储恢复。
export default function ManageFeedbackPage() {
  return (
    <div className="container">
      <Heading title="管理我的反馈">
        无需登录。管理链接相当于这条反馈的钥匙，请妥善保管。
      </Heading>
      <FeedbackManagementPanel />
    </div>
  );
}
