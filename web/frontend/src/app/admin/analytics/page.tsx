import { AdminAnalytics } from "@/features/admin-analytics";

export const metadata = { title: "访问统计" };

// 权限布局与查询组件共用现有管理员会话边界。
export default function Page() {
  return <AdminAnalytics />;
}
