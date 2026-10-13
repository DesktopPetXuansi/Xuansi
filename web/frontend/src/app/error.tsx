"use client";
import { Button, Heading, Notice } from "@/components/ui";
import { useEffect } from "react";
export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("页面渲染失败", { digest: error.digest });
  }, [error]);
  return (
    <div className="container">
      <Heading title="页面暂时无法显示" />
      <Notice error={new Error("请重试。如果问题持续，请联系管理员。")} />
      <Button onClick={reset}>重新加载</Button>
    </div>
  );
}
