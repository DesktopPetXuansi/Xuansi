"use client";
import { Button, Notice } from "@/components/ui";
import { api, apiPage } from "@/lib/api";
import type { User } from "@/lib/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { UserFilterForm, type UserFilters } from "./admin-user-filters";
import { UserTable } from "./admin-user-table";
import { useMe } from "./identity/session";
import styles from "./admin-users.module.css";

const emptyFilters: UserFilters = { search: "", role: "", status: "" };

// 只读取当前页；查询按管理员身份隔离，搜索和分页不落入浏览器持久存储。
export function Users() {
  const cache = useQueryClient();
  const me = useMe();
  const identity = me.data?.id ?? "";
  const [filters, setFilters] = useState(emptyFilters);
  const [pages, setPages] = useState([""]);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const cursor = pages.at(-1) ?? "";
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(filters))
    if (value) params.set(name, value);
  if (cursor) params.set("cursor", cursor);
  const query = useQuery({
    queryKey: ["admin-users", identity, filters, cursor],
    enabled: me.data?.role === "ADMIN",
    queryFn: ({ signal }) =>
      apiPage<User>(`/admin/users?${params}`, { signal }),
  });
  const change = useMutation({
    mutationFn: (user: User) =>
      api(`/admin/users/${user.id}`, "PATCH", {
        status: user.status === "ACTIVE" ? "DISABLED" : "ACTIVE",
      }),
    onSuccess: async (_result, user) => {
      setConfirming(null);
      setNotice(
        user.status === "ACTIVE"
          ? "账号已停用，现有登录和客户端授权已撤销。"
          : "账号已恢复，可以重新登录。",
      );
      setPages([""]);
      await cache.invalidateQueries({ queryKey: ["admin-users", identity] });
      console.info("[用户管理] 账号状态已更新");
    },
  });
  function apply(value: UserFilters) {
    setFilters(value);
    setPages([""]);
    setConfirming(null);
    setNotice("");
    change.reset();
    console.debug("[用户管理] 已更新筛选条件");
  }
  if (me.isPending) return <Notice>正在确认管理员身份…</Notice>;
  if (me.error) return <Notice error={me.error} />;
  if (me.data?.role !== "ADMIN")
    return <Notice>需要管理员账号才能查看用户列表。</Notice>;
  const total = query.data?.meta?.total;
  const next = query.data?.meta?.nextCursor;
  return (
    <>
      <p className={styles.description}>
        全站注册账号，不包含访客或未注册的客户端使用者。
      </p>
      <UserFilterForm
        key={`${filters.search}:${filters.role}:${filters.status}`}
        value={filters}
        disabled={change.isPending}
        onApply={apply}
      />
      {change.error && <Notice error={change.error} />}
      {notice && <Notice>{notice}</Notice>}
      <div className={styles.summary}>
        <p className={styles.count} role="status">
          {total === undefined
            ? query.isPending
              ? "正在统计账号…"
              : `本页${query.data?.data.length ?? 0}个账号`
            : `共${total}个账号`}
        </p>
        <span className={styles.hint}>按注册时间从新到旧 · 每页20个</span>
        <Button
          className="secondary"
          disabled={query.isFetching || change.isPending}
          onClick={() => void query.refetch()}
        >
          刷新列表
        </Button>
      </div>
      {query.isPending ? (
        <Notice>正在加载用户…</Notice>
      ) : query.error ? (
        <>
          <Notice error={query.error} />
          <Button className="secondary" onClick={() => void query.refetch()}>
            重试读取用户
          </Button>
        </>
      ) : query.data?.data.length ? (
        <UserTable
          users={query.data.data}
          currentId={identity}
          confirming={confirming}
          busy={change.isPending}
          onConfirm={setConfirming}
          onChange={(user) => change.mutate(user)}
        />
      ) : (
        <section className={styles.empty}>
          <h2>没有符合条件的账号</h2>
          <p>请调整昵称、邮箱、角色或状态后重新查询。</p>
          {!!cursor && (
            <Button className="secondary" onClick={() => setPages([""])}>
              返回第一页
            </Button>
          )}
        </section>
      )}
      <nav className={styles.pagination} aria-label="用户分页">
        <span>第{pages.length}页</span>
        {pages.length > 1 && (
          <Button
            className="secondary"
            disabled={query.isFetching || change.isPending}
            onClick={() => setPages([""])}
          >
            返回第一页
          </Button>
        )}
        <Button
          className="secondary"
          disabled={pages.length < 2 || query.isFetching || change.isPending}
          onClick={() => {
            setPages((values) => values.slice(0, -1));
            setConfirming(null);
          }}
        >
          上一页
        </Button>
        <Button
          className="secondary"
          disabled={!next || query.isFetching || change.isPending}
          onClick={() => {
            if (next) setPages((values) => [...values, next]);
            setConfirming(null);
          }}
        >
          下一页
        </Button>
      </nav>
    </>
  );
}
