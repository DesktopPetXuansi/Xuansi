"use client";
import { Button, Notice } from "@/components/ui";
import { api } from "@/lib/api";
import { type User, statuses } from "@/lib/types";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
export function Users() {
  const cache = useQueryClient();
  const query = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => api<User[]>("/admin/users"),
  });
  const [error, setError] = useState<unknown>();
  async function change(user: User) {
    try {
      await api(`/admin/users/${user.id}`, "PATCH", {
        status: user.status === "ACTIVE" ? "DISABLED" : "ACTIVE",
      });
      await cache.invalidateQueries({ queryKey: ["admin-users"] });
    } catch (cause) {
      setError(cause);
    }
  }
  return (
    <>
      {query.isPending && <Notice>正在加载用户…</Notice>}
      {query.error && <Notice error={query.error} />}{" "}
      {error !== undefined && <Notice error={error} />}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>用户</th>
              <th>角色 / 验证</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {query.data?.map((user) => (
              <tr key={user.id}>
                <td>
                  {user.displayName}
                  <br />
                  {user.email}
                </td>
                <td>
                  {user.role} / {user.emailVerified ? "已验证" : "待验证"}
                </td>
                <td>{statuses[user.status]}</td>
                <td>
                  <Button className="secondary" onClick={() => change(user)}>
                    {user.status === "ACTIVE" ? "停用" : "恢复"}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
