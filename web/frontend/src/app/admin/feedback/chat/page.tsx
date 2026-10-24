import { Suspense } from "react";
import { Notice } from "@/components/ui";
import { FeedbackChat } from "@/features/feedback/chat/chat-workspace";

export const metadata = { title: "反馈对话" };

export default function Page() {
  return (
    <Suspense fallback={<Notice>正在准备反馈对话…</Notice>}>
      <FeedbackChat admin />
    </Suspense>
  );
}
