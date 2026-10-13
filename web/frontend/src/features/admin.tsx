"use client";
import { Heading } from "@/components/ui";
import { Records } from "./admin-records";
import { ReleaseAdmin } from "./admin-releases";
import { AdminResources } from "./admin-resources";
import { Users } from "./admin-users";
const titles: Record<string, string> = {
  users: "用户管理",
  resources: "资源发布",
  releases: "客户端版本",
  jobs: "后台任务",
  audit: "审计日志",
};
export function AdminPage({ section }: { section: string }) {
  const endpoint =
    section === "releases"
      ? "client-releases"
      : section === "audit"
        ? "audit-logs"
        : section;
  return (
    <>
      <Heading eyebrow="ADMINISTRATION / 管理" title={titles[section]}>
        仅管理员可访问。所有操作由服务端鉴权并记录。
      </Heading>
      {section === "users" ? (
        <Users />
      ) : section === "resources" ? (
        <AdminResources />
      ) : section === "releases" ? (
        <ReleaseAdmin />
      ) : (
        <Records endpoint={endpoint} />
      )}
    </>
  );
}
