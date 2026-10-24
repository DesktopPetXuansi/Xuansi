"use client";
import { Button, Field } from "@/components/ui";
import { useState } from "react";
import styles from "./admin-users.module.css";

export type UserFilters = { search: string; role: string; status: string };

// 管理员的邮箱关键词只保留在当前页面内存，不写地址栏或本机存储。
export function UserFilterForm({
  value,
  disabled,
  onApply,
}: {
  value: UserFilters;
  disabled: boolean;
  onApply: (value: UserFilters) => void;
}) {
  const [search, setSearch] = useState(value.search);
  return (
    <form
      className={styles.filters}
      onSubmit={(event) => {
        event.preventDefault();
        if (!disabled) onApply({ ...value, search: search.trim() });
      }}
    >
      <Field label="搜索用户">
        <input
          type="search"
          maxLength={240}
          value={search}
          disabled={disabled}
          placeholder="昵称或邮箱，搜索全部账号"
          onChange={(event) =>
            setSearch(Array.from(event.target.value).slice(0, 120).join(""))
          }
        />
      </Field>
      <Field label="角色">
        <select
          aria-label="角色"
          disabled={disabled}
          value={value.role}
          onChange={(event) =>
            onApply({
              ...value,
              role: event.target.value,
              search: search.trim(),
            })
          }
        >
          <option value="">全部角色</option>
          <option value="USER">普通用户</option>
          <option value="ADMIN">管理员</option>
        </select>
      </Field>
      <Field label="账号状态">
        <select
          aria-label="账号状态"
          disabled={disabled}
          value={value.status}
          onChange={(event) =>
            onApply({
              ...value,
              status: event.target.value,
              search: search.trim(),
            })
          }
        >
          <option value="">全部状态</option>
          <option value="ACTIVE">正常</option>
          <option value="DISABLED">已停用</option>
        </select>
      </Field>
      <Button type="submit" disabled={disabled}>
        搜索
      </Button>
      {!!(value.search || value.role || value.status) && (
        <Button
          type="button"
          className="secondary"
          disabled={disabled}
          onClick={() => onApply({ search: "", role: "", status: "" })}
        >
          清除筛选
        </Button>
      )}
    </form>
  );
}
