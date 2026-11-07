"use client";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Field } from "@/components/ui";
import { Button } from "@/components/ui/button";
import { useState } from "react";
import styles from "./admin-users.module.css";

export type UserFilters = { search: string; role: string; status: string };
// Radix 保留空字符串用于清除选择，内部标识只在控件边界使用。
const allOptions = "__all__";

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
      data-assembly="panel"
      onSubmit={(event) => {
        event.preventDefault();
        if (!disabled) onApply({ ...value, search: search.trim() });
      }}
    >
      <Field label="搜索用户">
        <Input
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
        <Select
          disabled={disabled}
          value={value.role || allOptions}
          onValueChange={(selected) =>
            onApply({
              ...value,
              role: selected === allOptions ? "" : selected,
              search: search.trim(),
            })
          }
        >
          <SelectTrigger className="w-full" aria-label="角色">
            <SelectValue />
          </SelectTrigger>
          <SelectContent position="popper">
            <SelectItem value={allOptions}>全部角色</SelectItem>
            <SelectItem value="USER">普通用户</SelectItem>
            <SelectItem value="ADMIN">管理员</SelectItem>
          </SelectContent>
        </Select>
      </Field>
      <Field label="账号状态">
        <Select
          disabled={disabled}
          value={value.status || allOptions}
          onValueChange={(selected) =>
            onApply({
              ...value,
              status: selected === allOptions ? "" : selected,
              search: search.trim(),
            })
          }
        >
          <SelectTrigger className="w-full" aria-label="账号状态">
            <SelectValue />
          </SelectTrigger>
          <SelectContent position="popper">
            <SelectItem value={allOptions}>全部状态</SelectItem>
            <SelectItem value="ACTIVE">正常</SelectItem>
            <SelectItem value="DISABLED">已停用</SelectItem>
          </SelectContent>
        </Select>
      </Field>
      <Button type="submit" disabled={disabled}>
        搜索
      </Button>
      {!!(value.search || value.role || value.status) && (
        <Button
          type="button"
          variant="outline"
          disabled={disabled}
          onClick={() => onApply({ search: "", role: "", status: "" })}
        >
          清除筛选
        </Button>
      )}
    </form>
  );
}
